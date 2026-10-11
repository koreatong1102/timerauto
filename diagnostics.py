# diagnostics.py
# -*- coding: utf-8 -*-
"""Lightweight app-flow recorder and diagnostic ZIP exporter.

This module intentionally has no Qt imports and no dependency on the rest of the
app.  It is safe to import from timerauto.py, spectator_log_watcher.py and
browser_overlay.py.
"""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import hashlib
import sqlite3
import shutil
import subprocess
import uuid
import threading
import time
import traceback
import zipfile
from collections import deque
from contextlib import closing, contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_SECRET_KEY_RE = re.compile(r"(token|secret|password|passwd|api[_-]?key|auth|cookie)", re.I)
_USER_PATH_RE = re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/]+", re.I)
_HOME_PATH_RE = re.compile(r"/home/[^/]+")
_SECRET_TEXT_RE = re.compile(r'(?<![A-Za-z0-9_])((?:password|passwd|token|secret|api[_-]?key|authorization|cookie)["\x27]?\s*[=:]\s*)("[^"]*"|\x27[^\x27]*\x27|[^\s,;}]+)', re.I)
_CRITICAL_PREFIXES = ("app_", "error", "incident", "diagnostic", "obs_", "replay_", "potm_", "report_", "commentary_", "lobby_", "latency_", "spectator_watcher")


def _is_secret_key(key: str) -> bool:
    # Replay instance IDs are correlation evidence, not authentication tokens.
    if re.sub(r"[^a-z]", "", str(key).lower()).endswith("replaytoken"):
        return False
    return bool(_SECRET_KEY_RE.search(str(key)))


def _tail_text(path: str, lines: int = 100, max_bytes: int = 512 * 1024) -> str:
    try:
        if not path or not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8-sig", errors="replace")
        if lines and lines > 0:
            parts = text.splitlines()
            if len(parts) > int(lines):
                text = "\n".join(parts[-int(lines):])
        return text
    except Exception as exc:
        return f"<read failed: {exc}>"


def _mask_string(value: str) -> str:
    s = str(value)
    s = _USER_PATH_RE.sub(r"\1<USER>", s)
    s = _HOME_PATH_RE.sub("/home/<USER>", s)
    return _redact_credentials(s)


def _redact_credentials(s: str) -> str:
    s = _SECRET_TEXT_RE.sub(lambda m: m.group(1) + (m.group(2)[0] + "<redacted>" + m.group(2)[0] if m.group(2).startswith(('"', "'")) else "<redacted>"), s)
    return re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer <redacted>", s)


def _evidence_json(value: Any, mask: bool = True) -> Any:
    """Do not drop late config/overlay fields. Bounds apply to total bytes instead."""
    if isinstance(value, dict):
        return {str(k): "<redacted>" if _is_secret_key(str(k)) else _evidence_json(v, mask) for k, v in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_evidence_json(v, mask) for v in value]
    if isinstance(value, str):
        return _mask_string(value) if mask else _redact_credentials(value)
    return _safe_json(value, mask_sensitive=mask, max_depth=16, max_list=10000)


@contextmanager
def _atomic_zip(path):
    temporary = path + ".tmp"
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            yield zf
        os.replace(temporary, path)
    finally:
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


class DiagnosticExportJob:
    def __init__(self, recorder, kwargs):
        self.done = threading.Event()
        self.path = ""
        self.error = ""
        def run():
            try:
                self.path = recorder.export_zip(**kwargs)
            except Exception as exc:
                self.error = str(exc)
            finally:
                self.done.set()
        threading.Thread(target=run, name="DiagnosticZipExport", daemon=True).start()


def _safe_json(value: Any, *, mask_sensitive: bool = False, max_depth: int = 5, max_list: int = 40) -> Any:
    """Convert arbitrary app values into JSON-safe, compact values."""
    if max_depth <= 0:
        return "<max_depth>"
    try:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            s = _mask_string(value) if mask_sensitive else value
            return s if len(s) <= 2000 else s[:2000] + "...<truncated>"
        if isinstance(value, bytes):
            return f"<bytes {len(value)}>"
        # Avoid serializing images / numpy arrays / Qt objects.
        cls_name = type(value).__name__
        mod_name = getattr(type(value), "__module__", "")
        if cls_name in ("ndarray", "QImage", "QPixmap") or "numpy" in mod_name or "PyQt" in mod_name:
            shape = getattr(value, "shape", None)
            if shape is not None:
                return f"<{cls_name} shape={tuple(shape)}>"
            return f"<{cls_name}>"
        if is_dataclass(value):
            return _safe_json(asdict(value), mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list)
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in list(value.items())[:max_list]:
                key = str(k)
                if mask_sensitive and _is_secret_key(key):
                    out[key] = "<redacted>"
                else:
                    out[key] = _safe_json(v, mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list)
            if len(value) > max_list:
                out["<truncated>"] = len(value) - max_list
            return out
        if isinstance(value, (list, tuple, set, deque)):
            seq = list(value)
            out = [_safe_json(v, mask_sensitive=mask_sensitive, max_depth=max_depth - 1, max_list=max_list) for v in seq[:max_list]]
            if len(seq) > max_list:
                out.append(f"<truncated {len(seq) - max_list}>")
            return out
        return repr(value)[:2000]
    except Exception as exc:
        return f"<safe_json failed: {exc}>"


class DiagnosticRecorder:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._disk_lock = threading.Lock()
        self.enabled = True
        self.mask_sensitive_default = True
        self.raw_sample_lines = 100
        self.events: deque[dict] = deque(maxlen=5000)
        self.incidents: deque[dict] = deque(maxlen=200)
        self.errors: deque[dict] = deque(maxlen=400)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.start_time = time.time()
        self.start_monotonic = time.monotonic()
        self.critical_events: deque[dict] = deque(maxlen=5000)
        self.trace_seconds = 600.0
        self.dropped_events = 0
        self._incident_windows: deque[dict] = deque(maxlen=5)
        self._store_dir = ""
        self._write_queue = queue.Queue(maxsize=1000)
        self._writer = None
        self._writer_stop = threading.Event()
        self.persistence_error = ""
        self.persistence_dropped = 0
        self.store_max_bytes = 4 * 1024 * 1024

    def set_options(self, *, enabled: Optional[bool] = None, max_events: Optional[int] = None,
                    raw_sample_lines: Optional[int] = None, mask_sensitive: Optional[bool] = None,
                    trace_seconds: Optional[float] = None) -> None:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if trace_seconds is not None:
                self.trace_seconds = max(120.0, min(7200.0, float(trace_seconds)))
            if raw_sample_lines is not None:
                try:
                    self.raw_sample_lines = max(10, min(2000, int(raw_sample_lines)))
                except Exception:
                    pass
            if mask_sensitive is not None:
                self.mask_sensitive_default = bool(mask_sensitive)
            if max_events is not None:
                try:
                    n = max(300, min(50000, int(max_events)))
                    old = list(self.events)[-n:]
                    self.events = deque(old, maxlen=n)
                except Exception:
                    pass

    def configure_storage(self, folder: str) -> None:
        """Only explicit app startup enables disk persistence; imports/tests do not."""
        folder = os.path.abspath(folder)
        with self._lock:
            if self._writer is not None:
                return
            try:
                os.makedirs(folder, exist_ok=True)
                self._store_dir = folder
                self._writer = threading.Thread(target=self._write_loop, name="DiagnosticBlackbox", daemon=True)
                self._writer.start()
            except Exception as exc:
                self.persistence_error = str(exc)

    def _write_loop(self) -> None:
        path = os.path.join(self._store_dir, "critical.jsonl")
        while not self._writer_stop.is_set() or not self._write_queue.empty():
            try:
                item = self._write_queue.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                batch = [item]
                while len(batch) < 100:
                    try:
                        batch.append(self._write_queue.get_nowait())
                    except queue.Empty:
                        break
                with self._disk_lock:
                    for row in batch:
                        encoded = (json.dumps(_evidence_json(row, True), ensure_ascii=False) + "\n").encode("utf-8")
                        if len(encoded) > self.store_max_bytes:
                            self.persistence_dropped += 1
                            continue
                        if os.path.isfile(path) and os.path.getsize(path) + len(encoded) > self.store_max_bytes:
                            os.replace(path, path + ".previous")
                        with open(path, "ab") as stream:
                            stream.write(encoded)
            except Exception as exc:
                self.persistence_error = str(exc)
            finally:
                for _ in batch:
                    self._write_queue.task_done()

    def close(self) -> None:
        self._writer_stop.set()
        if self._writer:
            self._writer.join(timeout=2)

    def _append(self, item: dict, *, critical: bool = False) -> None:
        with self._lock:
            if len(self.events) == self.events.maxlen:
                self.dropped_events += 1
            self.events.append(item)
            while self.events and item["mono"] - self.events[0].get("mono", item["mono"]) > self.trace_seconds:
                self.events.popleft()
                self.dropped_events += 1
            if critical:
                self.critical_events.append(item)
            for window in self._incident_windows:
                if item["mono"] <= window["until_monotonic"] and len(window["after"]) < 3000:
                    window["after"].append(item)
                    critical = True
            if critical and self._store_dir and not self._writer_stop.is_set():
                try:
                    self._write_queue.put_nowait(item)
                except queue.Full:
                    self.persistence_dropped += 1

    def record(self, event_type: str, **payload: Any) -> None:
        if not self.enabled:
            return
        try:
            now = time.time()
            item = {
                "t": round(now, 3),
                "dt": round(time.monotonic() - self.start_monotonic, 3),
                "mono": time.monotonic(),
                "session_id": self.session_id,
                "type": str(event_type or "event"),
                "payload": _safe_json(payload, mask_sensitive=False, max_depth=10, max_list=180),
            }
            critical = str(event_type).startswith(_CRITICAL_PREFIXES) or event_type == "browser_overlay_beacon" or (
                event_type == "browser_overlay_event" and payload.get("kind") in ("round_report", "potm_intro", "potm_flash", "potm_report_transition"))
            self._append(item, critical=critical)
        except Exception:
            # Diagnostics must never break the app.
            pass

    def error(self, event_type: str, exc: BaseException | None = None, **payload: Any) -> None:
        try:
            item = {
                "t": round(time.time(), 3),
                "type": str(event_type or "error"),
                "payload": _safe_json(payload, mask_sensitive=False, max_depth=4, max_list=60),
                "traceback": traceback.format_exc() if exc is None else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            }
            with self._lock:
                self.errors.append(item)
                if self.enabled:
                    self._append({"t": item["t"], "mono": time.monotonic(), "session_id": self.session_id, "dt": round(time.monotonic() - self.start_monotonic, 3), "type": "error", "payload": item}, critical=True)
        except Exception:
            pass

    def mark_incident(self, note: str = "") -> dict:
        item = {
            "t": round(time.time(), 3),
            "dt": round(time.monotonic() - self.start_monotonic, 3),
            "note": str(note or "사용자 문제 발생 표시"),
        }
        with self._lock:
            self.incidents.append(item)
            now = time.monotonic()
            before = [ev for ev in self.events if ev.get("mono", 0) >= now - 120][-3000:]
            self._incident_windows.append({"incident": dict(item), "until_monotonic": now + 30,
                "requested_before_sec": 120, "before_span_sec": now - before[0]["mono"] if before else 0,
                "before": before, "after": []})
            self.record("incident_mark", **item)
            if self._store_dir:
                try:
                    self._write_queue.put_nowait({"type": "incident_window_before", "session_id": self.session_id, "t": item["t"], "payload": _evidence_json(self._incident_windows[-1], True)})
                except queue.Full:
                    self.persistence_dropped += 1
        return item

    def snapshot(self, *, mask_sensitive: bool = False) -> dict:
        with self._lock:
            events, critical, errors, incidents = list(self.events), list(self.critical_events), list(self.errors), list(self.incidents)
            windows = [{**window, "post_window_complete": time.monotonic() >= window["until_monotonic"],
                        "post_count_limited": len(window["after"]) >= 3000,
                        "before": list(window["before"]), "after": list(window["after"])} for window in self._incident_windows]
            result = {
                "session_id": self.session_id,
                "enabled": bool(self.enabled),
                "start_time": self.start_time,
                "now": time.time(),
                "event_count": len(self.events),
                "incident_count": len(self.incidents),
                "error_count": len(self.errors),
                "dropped_events": self.dropped_events,
                "persistence_error": self.persistence_error,
                "persistence_dropped": self.persistence_dropped,
            }
        # Conversion is potentially expensive. Never hold the live recorder lock
        # while formatting an export on the background thread.
        result.update(events=_evidence_json(events, mask_sensitive), critical_events=_evidence_json(critical, mask_sensitive),
                      incident_windows=_evidence_json(windows, mask_sensitive), incidents=_evidence_json(incidents, mask_sensitive),
                      errors=_evidence_json(errors, mask_sensitive))
        return result

    def summary(self, *, mask_sensitive: bool = False, tail: int = 8) -> dict:
        """Compact diagnostics state for app_state/current-state text.

        Full event lists are still exported as recent_trace.jsonl. Putting the full
        nested trace inside app_state made the clipboard summary unreadable and
        produced <max_depth> noise.
        """
        with self._lock:
            ev_tail = list(self.events)[-max(0, int(tail or 0)):]
            inc_tail = list(self.incidents)[-3:]
            err_tail = list(self.errors)[-3:]
            return {
                "session_id": self.session_id,
                "enabled": bool(self.enabled),
                "start_time": self.start_time,
                "now": time.time(),
                "event_count": len(self.events),
                "incident_count": len(self.incidents),
                "error_count": len(self.errors),
                "events_tail": _safe_json(ev_tail, mask_sensitive=mask_sensitive, max_depth=6, max_list=40),
                "incidents_tail": _safe_json(inc_tail, mask_sensitive=mask_sensitive, max_depth=5, max_list=10),
                "errors_tail": _safe_json(err_tail, mask_sensitive=mask_sensitive, max_depth=5, max_list=10),
            }

    def current_state_text(self, app_state: Optional[dict] = None) -> str:
        app_state = app_state or {}
        with self._lock:
            last = list(self.events)[-8:]
            incident = list(self.incidents)[-1:] or []
            err_count = len(self.errors)
        lines = []
        lines.append("RFC Diagnostic State")
        lines.append(f"session={self.session_id}")
        lines.append(f"events={len(self.events)} errors={err_count} incidents={len(self.incidents)}")
        if app_state:
            try:
                compact_state = dict(app_state or {})
                if isinstance(compact_state.get("diagnostics"), dict) and "events" in compact_state.get("diagnostics", {}):
                    compact_state["diagnostics"] = self.summary(mask_sensitive=True, tail=3)
                lines.append("app_state=" + json.dumps(_safe_json(compact_state, mask_sensitive=True, max_depth=6, max_list=60), ensure_ascii=False))
            except Exception:
                lines.append("app_state=<failed>")
        if incident:
            lines.append("last_incident=" + json.dumps(incident[-1], ensure_ascii=False))
        lines.append("recent_events:")
        for ev in last:
            lines.append(json.dumps(_safe_json(ev, mask_sensitive=True, max_depth=4, max_list=20), ensure_ascii=False))
        return "\n".join(lines)

    def export_zip(self, output_dir: str, *, app_state: Optional[dict] = None, cfg_snapshot: Optional[Any] = None,
                   spectator_root: str = "", overlay_snapshot: Optional[dict] = None,
                   mask_sensitive: Optional[bool] = None, raw_sample_lines: Optional[int] = None,
                   context: Optional[dict] = None, app_base: str = "", obs_provider=None) -> str:
        mask = self.mask_sensitive_default if mask_sensitive is None else bool(mask_sensitive)
        lines = self.raw_sample_lines if raw_sample_lines is None else int(raw_sample_lines or self.raw_sample_lines)
        os.makedirs(output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.abspath(os.path.join(output_dir, f"RFC_Diagnostic_{stamp}_{uuid.uuid4().hex[:6]}.zip"))
        self.record("diagnostic_export_started")
        snap = self.snapshot(mask_sensitive=mask)
        app_state_safe = _evidence_json(app_state or {}, mask)
        # Credentials are always excluded, even when the user opts to retain paths.
        cfg_safe = _evidence_json(cfg_snapshot or {}, mask)
        overlay_safe = _evidence_json(overlay_snapshot or {}, mask)
        format_detected = self._detect_spectator_format(spectator_root)
        context = dict(context or {})
        if obs_provider is not None:
            try:
                context.setdefault("runtime", {}).setdefault("obs", {})["live_query"] = obs_provider.diagnostic_snapshot(timeout=2.0)
            except Exception as exc:
                context.setdefault("runtime", {}).setdefault("obs", {})["live_query"] = {"status": "failed", "error": str(exc)}
        manifest = []
        with _atomic_zip(zip_path) as zf:
            zf.writestr("README.txt", self._readme())
            zf.writestr("diagnostic_meta.json", json.dumps({
                "created_at": stamp,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "session_id": self.session_id,
                "mask_sensitive": mask,
                "credentials_always_redacted": True,
                "schema_version": 2,
                "trace_seconds": self.trace_seconds,
                "dropped_events": self.dropped_events,
                "persistence_dropped": self.persistence_dropped,
                "persistence_error": self.persistence_error,
            }, ensure_ascii=False, indent=2))
            zf.writestr("app_state.json", json.dumps(app_state_safe, ensure_ascii=False, indent=2))
            zf.writestr("settings_snapshot.json", json.dumps(cfg_safe, ensure_ascii=False, indent=2))
            zf.writestr("recent_trace.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in snap.get("events", [])))
            zf.writestr("recent_errors.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in snap.get("errors", [])))
            zf.writestr("incidents.json", json.dumps(snap.get("incidents", []), ensure_ascii=False, indent=2))
            zf.writestr("incident_windows.json", json.dumps(snap.get("incident_windows", []), ensure_ascii=False, indent=2))
            zf.writestr("critical_trace.jsonl", "\n".join(json.dumps(ev, ensure_ascii=False) for ev in snap.get("critical_events", [])))
            zf.writestr("runtime_evidence.json", json.dumps(_evidence_json(context.get("runtime", {}), mask), ensure_ascii=False, indent=2))
            zf.writestr("overlay_snapshot.json", json.dumps(overlay_safe, ensure_ascii=False, indent=2))
            zf.writestr("spectator_format_detected.json", json.dumps(format_detected, ensure_ascii=False, indent=2))
            if spectator_root and os.path.isdir(spectator_root):
                for rel in self._raw_sample_files():
                    path = os.path.join(spectator_root, *rel.split("/"))
                    text = _tail_text(path, lines=0 if rel in ("format.txt", "lobby.txt") else lines)
                    manifest.append({"entry": "raw_log_samples/" + rel.replace("/", "__"), "status": "sample" if text else "missing", "line_limit": lines, "byte_limit": 524288})
                    if text:
                        text = _mask_string(text) if mask else _redact_credentials(text)
                        zf.writestr("raw_log_samples/" + rel.replace("/", "__"), text)
            # Include the app's own latest log files if present.
            for candidate in self._app_log_candidates(app_base or os.getcwd()):
                if os.path.isfile(candidate):
                    text = _tail_text(candidate, lines=0, max_bytes=2 * 1024 * 1024)
                    text = _mask_string(text) if mask else _redact_credentials(text)
                    zf.writestr("app_logs/" + os.path.basename(candidate), text)
                    manifest.append({"entry": "app_logs/" + os.path.basename(candidate), "status": "tail" if os.path.getsize(candidate) > 2*1024*1024 else "complete", "byte_limit": 2*1024*1024})
            if self._store_dir:
                with self._disk_lock:
                    for name in ("critical.jsonl.previous", "critical.jsonl"):
                        path = os.path.join(self._store_dir, name)
                        if os.path.isfile(path):
                            text = _tail_text(path, lines=0, max_bytes=5*1024*1024)
                            zf.writestr("blackbox/" + name, _mask_string(text) if mask else text)
                manifest.append({"entry": "blackbox/", "status": "bounded", "pending_write_count": self._write_queue.qsize(), "byte_limit_per_file": self.store_max_bytes})
            self._export_match_evidence(zf, context.get("match_dirs", []), manifest, mask)
            try:
                from diagnostic_replay import replay_diagnostic_zip
                reproduction = replay_diagnostic_zip(zf)
            except Exception as exc:
                reproduction = {"matches": [], "status": "failed", "error": str(exc)}
            zf.writestr("reproduction_check.json", json.dumps(_evidence_json(reproduction, mask), ensure_ascii=False, indent=2))
            paths = list(context.get("media_paths", []))
            for event in reversed(snap.get("critical_events", [])):
                if event.get("type") in ("replay_video_requested", "potm_file_attached", "obs_replay_file_received"):
                    path = event.get("payload", {}).get("path")
                    if path:
                        paths.append(path)
                if len(set(paths)) >= 4:
                    break
            media = [self._media_info(path, context.get("ffprobe_path", "")) for path in list(dict.fromkeys(paths))[:4] if path]
            zf.writestr("media_metadata.json", json.dumps(_evidence_json(media, mask), ensure_ascii=False, indent=2))
            zf.writestr("build_fingerprints.json", json.dumps(self._build_fingerprints(app_base or os.getcwd()), indent=2))
            zf.writestr("evidence_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            findings = self._findings(context, media, reproduction)
            zf.writestr("findings.json", json.dumps(_evidence_json(findings, mask), ensure_ascii=False, indent=2))
            summary = self._analysis_summary(app_state_safe, cfg_safe, context, snap, manifest, media)
            summary += "\n\n[자동 점검 항목]\n" + "\n".join(f"{item['certainty']}: {item['message']} (근거: {item['evidence']})" for item in findings)
            zf.writestr("진단요약.txt", summary)
        self.record("diagnostic_zip_exported", path=zip_path)
        return zip_path

    def start_export(self, **kwargs) -> DiagnosticExportJob:
        return DiagnosticExportJob(self, kwargs)

    @staticmethod
    def _build_fingerprints(base: str) -> dict:
        result = {}
        for name in ("diagnostics.py", "timerauto.py", "event_engine.py", "spectator_log_watcher.py", "match_analytics.py", "browser_overlay.py", "obs_integration.py"):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                with open(path, "rb") as stream:
                    result[name] = hashlib.sha256(stream.read()).hexdigest()
        # Frozen builds may not contain sources; the executable identifies that build.
        if not result:
            import sys
            digest = hashlib.sha256()
            with open(sys.executable, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b""):
                    digest.update(chunk)
            result["executable"] = {"name": os.path.basename(sys.executable), "size": os.path.getsize(sys.executable), "sha256": digest.hexdigest()}
        from importlib.metadata import version, PackageNotFoundError
        result["dependencies"] = {}
        for name in ("PyQt6", "PyQt6-Qt6", "numpy", "opencv-python", "aiohttp", "edge-tts", "mss"):
            try:
                result["dependencies"][name] = version(name)
            except PackageNotFoundError:
                result["dependencies"][name] = "unavailable (not necessarily absent in frozen build)"
        return result

    @staticmethod
    def _media_info(path: str, probe_path: str = "") -> dict:
        result = {"path": path, "exists": os.path.isfile(path), "probe_status": "unavailable"}
        if not result["exists"]:
            return result
        result.update(size_bytes=os.path.getsize(path), mtime=os.path.getmtime(path))
        probe = probe_path if probe_path and os.path.isfile(probe_path) else shutil.which("ffprobe")
        if not probe:
            return result
        try:
            proc = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,sample_rate,channels", "-of", "json", path], capture_output=True, timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if proc.returncode or len(proc.stdout) > 256000:
                result["probe_status"] = "failed"
            else:
                result["metadata"] = json.loads(proc.stdout)
                result["probe_status"] = "ok"
        except Exception as exc:
            result.update(probe_status="failed", error=str(exc))
        return result

    @staticmethod
    def _export_match_evidence(zf, folders, manifest, mask):
        """Copy only allowlisted evidence, never videos/portraits/entire archives."""
        budget = 16 * 1024 * 1024
        for index, folder in enumerate(list(dict.fromkeys(folders))[:2]):
            root = Path(folder)
            prefix = f"match_evidence/{index}/"
            manifest.append({"entry": prefix, "source": _mask_string(str(root)) if mask else str(root), "status": "present" if root.is_dir() else "missing"})
            if not root.is_dir():
                continue
            try:
                files = [p for p in root.iterdir() if p.name in ("manifest.json", "potm_candidate.json", "scores_final.csv", "winner_final.txt", "vitals_final.json", "vitals_live.json", "damage_events.jsonl", "punches_thrown.jsonl") or re.fullmatch(r"(?:scores_round_\d+\.csv|vitals_round_\d+\.json)", p.name)]
            except OSError as exc:
                manifest.append({"entry": prefix, "status": "read_failed", "error": _mask_string(str(exc))})
                continue
            for path in sorted(files):
                entry = prefix + path.name
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    before = path.stat()
                    size = before.st_size
                except OSError as exc:
                    manifest.append({"entry": entry, "status": "read_failed", "error": _mask_string(str(exc))})
                    continue
                limit = min(budget, 4*1024*1024)
                if limit <= 0:
                    manifest.append({"entry": entry, "status": "omitted_budget"})
                    continue
                content = _tail_text(str(path), lines=0, max_bytes=limit)
                if size > limit:  # Do not export a partial JSON/CSV as complete evidence.
                    manifest.append({"entry": entry, "status": "omitted_size", "size": size})
                    continue
                try:
                    after = path.stat()
                    stable = (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)
                except OSError:
                    stable = False
                if not stable or content.startswith("<read failed:"):
                    manifest.append({"entry": entry, "status": "read_failed", "error": "changed during read or unreadable"})
                    continue
                zf.writestr(entry, _mask_string(content) if mask else _redact_credentials(content))
                budget -= size
                manifest.append({"entry": entry, "status": "complete", "size": size, "mtime_ns": before.st_mtime_ns,
                                 "captured_at": time.time(), "sha256_utf8": hashlib.sha256(content.encode("utf-8")).hexdigest()})
            db = root / "match_archive.db"
            if db.is_file() and not db.is_symlink():
                try:
                    # One read transaction includes WAL data. Never copy a live DB without WAL.
                    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
                        conn.execute("BEGIN")
                        conn.row_factory = sqlite3.Row
                        for table in ("metadata", "events", "official_snapshots", "vitals", "audits", "consumer_checkpoints"):
                            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                                continue
                            rows = conn.execute(f'SELECT * FROM "{table}"').fetchmany(20001)
                            if len(rows) > 20000:
                                manifest.append({"entry": prefix + table, "status": "omitted_row_limit"})
                                continue
                            materialized = []
                            for row in rows:
                                values = dict(row)
                                # Official snapshots are UTF-8 source files, not opaque bytes.
                                if isinstance(values.get("payload"), bytes):
                                    values["payload"] = values["payload"].decode("utf-8-sig", errors="replace")
                                materialized.append(_evidence_json(values, mask))
                            content = "\n".join(json.dumps(row, ensure_ascii=False) for row in materialized)
                            size = len(content.encode("utf-8"))
                            if size > budget:
                                manifest.append({"entry": prefix + table, "status": "omitted_budget"})
                                continue
                            zf.writestr(prefix + "ledger_" + table + ".jsonl", content)
                            budget -= size
                            manifest.append({"entry": prefix + "ledger_" + table + ".jsonl", "status": "complete", "rows": len(rows)})
                except Exception as exc:
                    manifest.append({"entry": prefix + "ledger", "status": "read_failed", "error": _mask_string(str(exc))})

    @staticmethod
    def _findings(context, media, reproduction):
        findings = []
        def add(certainty, message, evidence):
            findings.append({"certainty": certainty, "message": message, "evidence": evidence})
        runtime = context.get("runtime", {})
        candidate = runtime.get("potm_candidate", {})
        if candidate.get("file_source") and candidate.get("capture_source") and candidate["file_source"] != candidate["capture_source"]:
            add("확정", "후보의 선택 저장 방식과 연결된 영상 방식이 다릅니다.", "runtime_evidence.json:potm_candidate")
        for item in media:
            if not item["exists"]:
                add("확정", "수집 시점에 선택/최근 영상 경로에 파일이 없습니다. 이전 재생 성공 여부는 별도입니다.", "media_metadata.json")
            elif item.get("probe_status") == "ok" and not any(stream.get("codec_type") == "audio" for stream in item.get("metadata", {}).get("streams", [])):
                add("확정", "검사한 영상에 오디오 트랙이 없습니다.", "media_metadata.json")
        query = runtime.get("obs", {}).get("live_query", {})
        if query.get("status") != "complete":
            add("확인 불가", "OBS 실시간 조회가 없거나 완료되지 않았습니다.", "runtime_evidence.json:obs.live_query")
        for name, response in query.get("responses", {}).items():
            if not response.get("ok"):
                add("확인 불가", f"OBS {response.get('request_type', name)} 조회가 실패했습니다. 방송 기능 자체의 실패를 뜻하지는 않습니다.", f"runtime_evidence.json:obs.live_query.responses.{name}")
        for item in reproduction.get("matches", []):
            if item.get("different"):
                add("확정", f"동일 규칙 버전의 저장 판정과 오프라인 재현이 {item['different']}건 다릅니다. 구현/입력 이력 추가 조사가 필요합니다.", "reproduction_check.json")
            if item.get("different_ruleset_or_unclassified"):
                add("확인 필요", "규칙 버전이 다르거나 판정이 없는 사건은 버그 비교에서 제외했습니다.", "reproduction_check.json")
            if item.get("status") == "failed":
                add("확인 불가", "해당 경기의 판정 재현을 완료하지 못했습니다.", "reproduction_check.json")
        if not reproduction.get("matches"):
            add("확인 불가", "재현할 경기 이벤트 원장이 없습니다.", "evidence_manifest.json / match_evidence")
        if reproduction.get("status") == "failed":
            add("확인 불가", "오프라인 재현 실행에 실패했습니다. 나머지 증거는 계속 수집했습니다.", "reproduction_check.json")
        return findings

    @staticmethod
    def _analysis_summary(state, cfg, context, snap, manifest, media):
        runtime = context.get("runtime", {})
        lines = ["RFC 진단 요약 (자동 점검 / 원인 확정 아님)", "", "[확인된 상태]"]
        lines.append(f"앱 버전: {state.get('app_version', '확인 불가')}")
        lines.append(f"최근 기록 {snap['event_count']}건 / 오류 {snap['error_count']}건 / 문제 표시 {snap['incident_count']}건")
        lines.append(f"POTM 설정: {cfg.get('potm_capture_source', '확인 불가')} / KD 설정: {cfg.get('obs_auto_replay_source', '확인 불가')}")
        lines.append("OBS 상태: " + str(runtime.get("obs", {}).get("status", "확인 불가")))
        for entry in media:
            lines.append(f"선택 영상 존재: {entry['exists']} / 메타데이터 확인: {entry['probe_status']}")
        lines += ["", "[확인 필요 / 증거 부족]"]
        if snap.get("dropped_events"):
            lines.append("일반 흐름 기록 일부가 보관 한도/시간을 지나 제외됨. critical_trace와 blackbox도 확인하세요.")
        if snap.get("persistence_error") or snap.get("persistence_dropped"):
            lines.append("중요 기록의 디스크 보관 실패/누락이 있음.")
        if not context.get("match_dirs"):
            lines.append("해당 경기 아카이브 경로를 확보하지 못함.")
        for item in manifest:
            if item["status"] in ("read_failed", "omitted_size", "omitted_budget", "omitted_row_limit"):
                lines.append(f"증거 불완전: {item['entry']} ({item['status']})")
        lines += ["OBS 조회 내용은 수집 시각의 상태이며 문제 발생 시점과 다를 수 있습니다.",
                  "요청 성공은 저장 파일 생성/실제 화면 표시/실제 소리 출력의 성공을 뜻하지 않습니다.",
                  "영상 메타데이터만으로 타이머가 화면에 포함됐는지는 판정할 수 없습니다.",
                  "컴퓨터 성능/인터넷 문제는 이 ZIP만으로 확정하지 않습니다.", "", "[분석 순서]",
                  "1. incident_windows → critical_trace/blackbox에서 사건과 후보 ID를 연결",
                  "2. runtime_evidence/media_metadata에서 설정 방식과 실제 선택 파일 비교",
                  "3. match_evidence의 공식 점수/승자와 리포트·해설 근거 비교",
                  "4. evidence_manifest의 누락/제한을 먼저 확인"]
        return _mask_string("\n".join(lines))

    def _readme(self) -> str:
        return (
            "RFC Diagnostic Package\n"
            "======================\n\n"
            "이 ZIP은 앱 버그/업그레이드 재현을 위해 만든 진단 패키지입니다.\n"
            "중요 파일:\n"
            "- recent_trace.jsonl: 앱 내부 흐름 기록\n"
            "- app_state.json: 현재 앱/타이머/오버레이 상태\n"
            "- settings_snapshot.json: 설정 스냅샷\n"
            "- raw_log_samples/: SpectatorLog 최근 원본 샘플\n"
            "- spectator_format_detected.json: 로그 포맷 감지 결과\n"
            "- 진단요약.txt / evidence_manifest.json: 확인 사항과 누락된 증거\n"
            "- critical_trace.jsonl / blackbox/: 재시작 전후 중요 사건 (용량 제한)\n"
            "- incident_windows.json: 문제 표시 직전 최대 2분 + 이후 최대 30초 (각 3000건 제한)\n"
            "- match_evidence/: 현재/최근 경기의 공식 점수, 승자, 원장과 체력 기록\n"
            "- runtime_evidence.json / media_metadata.json: 실제 선택 파일과 실행 상태\n"
            "영상 원본/인증정보는 기본 포함하지 않습니다. 원본 로그와 아카이브는 변경하지 않습니다.\n"
        )

    def _raw_sample_files(self) -> List[str]:
        return [
            "format.txt",
            "lobby.txt",
            "match/round_state.txt",
            "match/round_time.txt",
            "match/round_number.txt",
            "match/round_total.txt",
            "match/damage_events.txt",
            "match/punches_thrown.txt",
            "match/scores.csv",
            "match/winner.txt",
            "match/camera_input.txt",
            "blue/punishment_mid.txt",
            "blue/punishment_long_raw.txt",
            "blue/punishment_long_weighted.txt",
            "red/punishment_mid.txt",
            "red/punishment_long_raw.txt",
            "red/punishment_long_weighted.txt",
            "blue/name.txt",
            "red/name.txt",
            "blue/accessibility.txt",
            "red/accessibility.txt",
            "blue/cosmetics.txt",
            "red/cosmetics.txt",
            "blue/head_position.txt",
            "red/head_position.txt",
            "blue/glove_left_position.txt",
            "blue/glove_right_position.txt",
            "red/glove_left_position.txt",
            "red/glove_right_position.txt",
        ]

    def _app_log_candidates(self, base: str) -> Iterable[str]:
        for rel in ("timerauto.log", "app.log", "logs/timerauto.log", "logs/app.log", "logs/error.log"):
            yield os.path.join(base, rel)
        logs_dir = os.path.join(base, "logs")
        try:
            dated = [
                os.path.join(logs_dir, name)
                for name in os.listdir(logs_dir)
                if name.lower().startswith("timerauto_") and name.lower().endswith(".log")
            ]
            for path in sorted(dated, key=os.path.getmtime, reverse=True)[:3]:
                yield path
        except Exception:
            return

    def _detect_spectator_format(self, root: str) -> dict:
        info: Dict[str, Any] = {"root_exists": bool(root and os.path.isdir(root)), "root": _mask_string(root or "")}
        if not root or not os.path.isdir(root):
            return info
        dmg = os.path.join(root, "match", "damage_events.txt")
        last = ""
        for line in _tail_text(dmg, lines=20).splitlines():
            if line.strip():
                last = line.strip()
        if last:
            parts = last.split("\t")
            info["damage_events_columns"] = len(parts)
            # Current SpectatorLog layout is: time, damage, multiplier,
            # receiving-corner, hand, ... .  The former index 3 check was the
            # receiver (blue/red), so diagnostics always falsely said no hand
            # column existed.
            info["damage_events_has_hand_column"] = bool(len(parts) >= 12 and str(parts[4]).lower() in ("left", "right"))
            info["damage_events_last_sample"] = _safe_json(parts, mask_sensitive=True, max_depth=2, max_list=20)
        for rel in ("match/punches_thrown.txt", "match/scores.csv", "match/winner.txt", "match/round_total.txt", "match/camera_input.txt"):
            path = os.path.join(root, *rel.split("/"))
            info[rel.replace("/", "_").replace(".", "_")] = os.path.isfile(path)
        return info


diagnostics = DiagnosticRecorder()

__all__ = ["diagnostics", "DiagnosticRecorder"]
