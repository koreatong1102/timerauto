from __future__ import annotations

"""Byte-exact SpectatorLog blackbox recorder.

Purpose
-------
The live SpectatorLog folder is not an append-only log. Many files are one-line
state files that are overwritten, and a few files such as lobby.txt appear and
then disappear. This recorder preserves those changes for later format analysis.

Important rule: raw snapshots are copied byte-for-byte. Timestamps, event names,
and all metadata are written only to events.jsonl / manifest.json, never into the
copied raw log files.
"""

import json
import logging
import os
import shutil
import time
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from app_paths import normalize_app_path


_TEXT_SUFFIXES = {".txt", ".csv", ".json", ".jsonl", ".log", ".ini", ".cfg"}
_HIGH_FREQ_BASENAMES = {
    "camera.txt",
    "camera_input.txt",
    "head_position.txt",
    "glove_left_position.txt",
    "glove_right_position.txt",
    "round_time.txt",
    "punishment_mid.txt",
    "punishment_long_raw.txt",
    "punishment_long_weighted.txt",
}
_ALWAYS_SNAPSHOT_BASENAMES = {
    "lobby.txt",
    "damage_events.txt",
    "punches_thrown.txt",
    "scores.csv",
    "winner.txt",
    "round_state.txt",
    "round_number.txt",
    "round_total.txt",
    "name.txt",
    "cosmetics.txt",
    "accessibility.txt",
    "portrait.png",
}


def _utc_like_local_iso() -> str:
    """Millisecond local timestamp for metadata only."""
    return datetime.now().isoformat(timespec="milliseconds")


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    try:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "y")
        return bool(value)
    except Exception:
        return bool(default)


class SpectatorLogBlackboxRecorder:
    """Poll-based full-folder recorder for SpectatorLog.

    It records every discovered file path, every observed create/delete, and
    sampled/meaningful modifications. Raw file contents are written exactly as
    bytes copied from SpectatorLog; timing metadata is kept separately.
    """

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self._root = ""
        self._session_dir = ""
        self._events_path = ""
        self._manifest_path = ""
        self._state: Dict[str, Dict[str, Any]] = {}
        self._sampled_at: Dict[str, float] = {}
        self._snapshot_counts: Dict[str, int] = {}
        self._content_hashes: Dict[str, str] = {}
        self._session_id = ""
        self._last_poll_at = 0.0
        self._closed = True

    def is_enabled(self) -> bool:
        return _safe_bool(getattr(self.cfg, "spectatorlog_blackbox_enabled", False), False)

    def poll(self, root: str) -> Optional[str]:
        if not self.is_enabled():
            self.close()
            return None
        root = os.path.abspath(str(root or ""))
        if not root or not os.path.isdir(root):
            self.close()
            return None
        if self._root != root or not self._session_dir:
            self.close()
            self._start_session(root)
        if not self._session_dir:
            return None
        now = time.time()
        min_poll = max(0.02, min(2.0, _safe_int(getattr(self.cfg, "spectatorlog_blackbox_poll_ms", 100), 100) / 1000.0))
        if now - float(self._last_poll_at or 0.0) < min_poll:
            return self._session_dir
        self._last_poll_at = now
        try:
            current = self._scan_files(root)
            self._process_deletes(current)
            self._process_creates_and_modifies(root, current, now)
            self._write_manifest(update_only=True)
        except Exception:
            logging.exception("SPECTATORLOG_BLACKBOX_POLL_FAIL")
        return self._session_dir

    def close(self) -> None:
        if not self._session_dir or self._closed:
            self._reset_session_vars(keep_state=False)
            return
        try:
            self._append_event({"event": "session_end"})
            self._write_manifest(update_only=False)
            if _safe_bool(getattr(self.cfg, "spectatorlog_blackbox_zip_on_close", False), False):
                self._zip_session()
        except Exception:
            logging.exception("SPECTATORLOG_BLACKBOX_CLOSE_FAIL")
        finally:
            self._reset_session_vars(keep_state=False)

    def session_dir(self) -> str:
        return self._session_dir

    def _reset_session_vars(self, *, keep_state: bool) -> None:
        self._root = ""
        self._session_dir = ""
        self._events_path = ""
        self._manifest_path = ""
        self._session_id = ""
        self._last_poll_at = 0.0
        self._closed = True
        if not keep_state:
            self._state = {}
            self._sampled_at = {}
            self._snapshot_counts = {}
            self._content_hashes = {}

    def _start_session(self, root: str) -> None:
        base_dir = self._archive_base_dir(root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
        self._session_dir = os.path.join(base_dir, self._session_id)
        self._root = root
        self._events_path = os.path.join(self._session_dir, "events.jsonl")
        self._manifest_path = os.path.join(self._session_dir, "manifest.json")
        os.makedirs(os.path.join(self._session_dir, "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self._session_dir, "deleted_last_snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self._session_dir, "latest_snapshot"), exist_ok=True)
        self._state = {}
        self._sampled_at = {}
        self._snapshot_counts = {}
        self._content_hashes = {}
        self._closed = False
        self._write_manifest(update_only=False)
        self._append_event({
            "event": "session_start",
            "root": root,
            "mode": self._mode(),
            "raw_rule": "Raw snapshot files are byte-exact copies; metadata is stored only in events.jsonl.",
        })
        logging.info("SPECTATORLOG_BLACKBOX_START root=%s session=%s", root, self._session_dir)

    def _archive_base_dir(self, root: str) -> str:
        configured = str(getattr(self.cfg, "spectatorlog_blackbox_dir", "") or "").strip()
        if not configured:
            configured = "SpectatorLogArchive"
        if not os.path.isabs(configured):
            # Keep archives outside the live SpectatorLog tree by default so the
            # recorder does not record its own output.  Do not use the process
            # working directory: portable EXEs launched from a shortcut often
            # inherit C:\\Windows\\System32, which is not writable.
            configured = normalize_app_path(configured)
        os.makedirs(configured, exist_ok=True)
        return configured

    def _mode(self) -> str:
        mode = str(getattr(self.cfg, "spectatorlog_blackbox_mode", "smart") or "smart").strip().lower()
        if mode not in ("light", "smart", "full"):
            mode = "smart"
        return mode

    def _write_manifest(self, *, update_only: bool) -> None:
        if not self._manifest_path:
            return
        high_ms = _safe_int(getattr(self.cfg, "spectatorlog_blackbox_sample_ms", 250), 250)
        data = {
            "session_id": self._session_id,
            "root": self._root,
            "created_or_updated_at": _utc_like_local_iso(),
            "mode": self._mode(),
            "raw_snapshot_rule": "No timestamps or metadata are inserted into raw snapshot files.",
            "metadata_file": "events.jsonl",
            "sample_ms_for_high_frequency_files": high_ms,
            "known_high_frequency_basenames": sorted(_HIGH_FREQ_BASENAMES),
            "known_always_snapshot_basenames": sorted(_ALWAYS_SNAPSHOT_BASENAMES),
            "tracked_files_currently_seen": len([1 for s in self._state.values() if not s.get("deleted")]),
            "tracked_paths_total": len(self._state),
            "snapshot_count_total": sum(int(v or 0) for v in self._snapshot_counts.values()),
            "update_only": bool(update_only),
        }
        tmp = self._manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._manifest_path)

    def _append_event(self, data: Dict[str, Any]) -> None:
        if not self._events_path:
            return
        os.makedirs(os.path.dirname(self._events_path), exist_ok=True)
        ev = dict(data or {})
        ev.setdefault("time", _utc_like_local_iso())
        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _scan_files(self, root: str) -> Dict[str, Tuple[int, int, int]]:
        current: Dict[str, Tuple[int, int, int]] = {}
        archive_abs = os.path.abspath(self._archive_base_dir(root))
        for dirpath, dirnames, filenames in os.walk(root):
            abs_dir = os.path.abspath(dirpath)
            # Guard if the user intentionally places the archive below SpectatorLog.
            if abs_dir == archive_abs or abs_dir.startswith(archive_abs + os.sep):
                dirnames[:] = []
                continue
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path)
                    rel = os.path.relpath(path, root).replace(os.sep, "/")
                    current[rel] = (int(st.st_mtime_ns), int(st.st_size), int(getattr(st, "st_ctime_ns", 0)))
                except FileNotFoundError:
                    continue
                except Exception:
                    logging.debug("SPECTATORLOG_BLACKBOX_STAT_FAIL path=%s", path, exc_info=True)
        return current

    def _process_deletes(self, current: Dict[str, Tuple[int, int, int]]) -> None:
        current_paths: Set[str] = set(current.keys())
        for rel in list(self._state.keys()):
            st = self._state.get(rel) or {}
            if st.get("deleted"):
                continue
            if rel not in current_paths:
                st["deleted"] = True
                self._state[rel] = st
                self._append_event({
                    "event": "delete",
                    "path": rel,
                    "last_snapshot": st.get("last_snapshot", ""),
                    "last_size": st.get("size", 0),
                })
                self._copy_last_snapshot_to_deleted(rel, st.get("last_snapshot", ""))

    def _process_creates_and_modifies(self, root: str, current: Dict[str, Tuple[int, int, int]], now: float) -> None:
        for rel, sig in sorted(current.items()):
            prev = self._state.get(rel)
            path = os.path.join(root, *rel.split("/"))
            if not prev or prev.get("deleted"):
                event = "create"
                snapshot = self._maybe_snapshot(path, rel, event, now, force=True)
                self._state[rel] = {"sig": sig, "size": sig[1], "last_snapshot": snapshot or "", "deleted": False}
                self._append_event({"event": event, "path": rel, "size": sig[1], "snapshot": snapshot or ""})
                self._update_latest_snapshot(path, rel)
                continue
            if tuple(prev.get("sig") or ()) != tuple(sig):
                event = "modify"
                snapshot = self._maybe_snapshot(path, rel, event, now, force=False)
                same_content = snapshot == "__same_content__"
                if same_content:
                    snapshot = ""
                prev.update({"sig": sig, "size": sig[1], "deleted": False})
                if snapshot:
                    prev["last_snapshot"] = snapshot
                    self._update_latest_snapshot(path, rel)
                self._state[rel] = prev
                # Record all non-high-frequency modifications. For high-frequency files,
                # record only sampled snapshots to avoid an events.jsonl flood.
                if (not same_content) and (snapshot or not self._is_high_frequency(rel)):
                    self._append_event({"event": event if not self._is_high_frequency(rel) else "sample", "path": rel, "size": sig[1], "snapshot": snapshot or ""})

    def _is_high_frequency(self, rel: str) -> bool:
        base = os.path.basename(rel).lower()
        if base in _HIGH_FREQ_BASENAMES:
            return True
        # Position files from newer builds should also be treated as high frequency.
        return base.endswith("_position.txt") or base.endswith("position.txt")

    def _is_always_snapshot(self, rel: str) -> bool:
        base = os.path.basename(rel).lower()
        return base in _ALWAYS_SNAPSHOT_BASENAMES

    def _maybe_snapshot(self, path: str, rel: str, event: str, now: float, *, force: bool) -> str:
        mode = self._mode()
        if mode == "light" and event == "modify" and not self._is_always_snapshot(rel):
            return ""
        if mode != "full" and self._is_high_frequency(rel) and not force:
            sample_ms = max(50, min(5000, _safe_int(getattr(self.cfg, "spectatorlog_blackbox_sample_ms", 250), 250)))
            last = float(self._sampled_at.get(rel, 0.0) or 0.0)
            if now - last < sample_ms / 1000.0:
                return ""
        max_mb = max(1, min(1024, _safe_int(getattr(self.cfg, "spectatorlog_blackbox_max_snapshot_mb", 64), 64)))
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        if size > max_mb * 1024 * 1024:
            self._append_event({"event": "snapshot_skipped_size", "path": rel, "size": size, "max_mb": max_mb})
            return ""
        try:
            data = self._read_bytes_stable(path)
            if data is None:
                return ""
            digest = hashlib.sha1(data).hexdigest()
            prev_digest = str((self._content_hashes or {}).get(rel) or "")
            if event == "modify" and mode != "full" and prev_digest and prev_digest == digest:
                # The game can rewrite one-line state files without changing
                # content.  Do not waste raw snapshots for identical bytes;
                # metadata still records that a filesystem modify happened.
                self._append_event({"event": "same_content_modify", "path": rel, "size": size, "sha1": digest})
                return "__same_content__"
            snap_rel = self._snapshot_relpath(rel)
            snap_abs = os.path.join(self._session_dir, snap_rel)
            os.makedirs(os.path.dirname(snap_abs), exist_ok=True)
            with open(snap_abs, "wb") as f:
                f.write(data)
            self._content_hashes[rel] = digest
            if self._is_high_frequency(rel):
                self._sampled_at[rel] = now
            return snap_rel.replace(os.sep, "/")
        except Exception:
            logging.debug("SPECTATORLOG_BLACKBOX_SNAPSHOT_FAIL path=%s", path, exc_info=True)
            return ""

    def _read_bytes_stable(self, path: str) -> Optional[bytes]:
        last_data: Optional[bytes] = None
        for _ in range(3):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                if last_data is not None and data == last_data:
                    return data
                last_data = data
                time.sleep(0.01)
            except FileNotFoundError:
                return None
            except PermissionError:
                time.sleep(0.02)
            except Exception:
                time.sleep(0.01)
        return last_data

    def _snapshot_relpath(self, rel: str) -> str:
        count = int(self._snapshot_counts.get(rel, 0) or 0) + 1
        self._snapshot_counts[rel] = count
        suffix = Path(rel).suffix
        if not suffix:
            suffix = ".bin"
        # Store under a directory named by the original relative path, so the raw
        # file itself can remain byte-exact with a simple numbered filename.
        return os.path.join("snapshots", *rel.split("/"), f"{count:06d}{suffix}")

    def _update_latest_snapshot(self, path: str, rel: str) -> None:
        try:
            data = self._read_bytes_stable(path)
            if data is None:
                return
            dest = os.path.join(self._session_dir, "latest_snapshot", *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
        except Exception:
            logging.debug("SPECTATORLOG_BLACKBOX_LATEST_FAIL path=%s", path, exc_info=True)

    def _copy_last_snapshot_to_deleted(self, rel: str, snap_rel: str) -> None:
        if not snap_rel:
            return
        try:
            src = os.path.join(self._session_dir, *snap_rel.split("/"))
            if not os.path.isfile(src):
                return
            suffix = Path(rel).suffix or ".bin"
            dest = os.path.join(self._session_dir, "deleted_last_snapshots", *rel.split("/"))
            # If rel already has a filename, append .last before original suffix by
            # making the destination exact-ish but not a raw reusable log path.
            dest = dest + ".last" + suffix
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
        except Exception:
            logging.debug("SPECTATORLOG_BLACKBOX_DELETE_COPY_FAIL rel=%s", rel, exc_info=True)

    def _zip_session(self) -> None:
        try:
            if not self._session_dir or not os.path.isdir(self._session_dir):
                return
            base_name = self._session_dir.rstrip(os.sep)
            shutil.make_archive(base_name, "zip", root_dir=os.path.dirname(self._session_dir), base_dir=os.path.basename(self._session_dir))
        except Exception:
            logging.exception("SPECTATORLOG_BLACKBOX_ZIP_FAIL")


__all__ = ["SpectatorLogBlackboxRecorder"]
