from __future__ import annotations

"""Small per-match log archive used by reports and post-match analysis."""

import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from match_event_ledger import MatchEventLedger, stable_event_id


class MatchLogArchive:
    """Persist only the current match's relevant spectator records.

    The live SpectatorLog files can be truncated while a match is still running.
    This recorder writes each newly observed row once, keeping the report source
    stable without polling/copying large files on every UI tick.
    """

    def __init__(self, base_dir: str = "MatchLogArchive") -> None:
        self.base_dir = str(base_dir or "MatchLogArchive")
        self.session_id = ""
        self.session_dir = ""
        self._seen_damage: set[str] = set()
        self._seen_throws: set[str] = set()
        self._raw_key_rounds: Dict[str, Dict[str, set[int]]] = {
            "damage": {},
            "throw": {},
        }
        self._rolling_kinds: set[str] = set()
        self._score_hashes: Dict[str, str] = {}
        self._pair: List[str] = []
        self._completed = False
        self._ledger: MatchEventLedger | None = None
        self._vitals_lock = threading.RLock()

    def start(self, session_id: str, pair: Iterable[str]) -> str:
        self.close()
        self.session_id = str(session_id or "match")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.session_id)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(self.base_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        self.session_dir = str(base / f"{stamp}_{safe}")
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        # Keep a bounded replay history. The active session is never a prune target.
        self._prune_old_sessions(base, keep=20)
        self._seen_damage.clear()
        self._seen_throws.clear()
        self._raw_key_rounds = {"damage": {}, "throw": {}}
        self._rolling_kinds.clear()
        self._score_hashes.clear()
        self._pair = [str(value or "") for value in list(pair or [])]
        self._completed = False
        self._write_manifest(pair)
        self._open_ledger(import_legacy=True)
        return self.session_dir

    def resume_latest(self, pair: Iterable[str], *, max_age_sec: float = 21600.0) -> str:
        """Attach to the newest unfinished archive for the same live players.

        TimerAuto may be restarted during a broadcast update.  A winner snapshot
        is the completion marker: completed bouts are never candidates, even if
        the same two players immediately have a rematch.
        """
        requested_pair = [str(value or "") for value in list(pair or [])]
        if len(requested_pair) != 2 or not all(requested_pair):
            return ""
        base = Path(self.base_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        try:
            candidates = sorted((path for path in base.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            return ""
        now = time.time()
        for path in candidates:
            try:
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                updated_at = float(manifest.get("updated_at", 0.0) or 0.0)
                archived_pair = [str(value or "") for value in list(manifest.get("pair") or [])]
                completed = bool(manifest.get("completed", False)) or (path / "winner_final.txt").is_file()
            except (OSError, TypeError, ValueError):
                continue
            if completed or archived_pair != requested_pair or now - updated_at > max(60.0, float(max_age_sec or 0.0)):
                continue
            self.session_dir = str(path)
            self.session_id = str(manifest.get("session_id") or path.name)
            self._pair = archived_pair
            self._completed = False
            self._seen_damage = self._load_seen("damage_events.jsonl", "damage")
            self._seen_throws = self._load_seen("punches_thrown.jsonl", "throw")
            self._restore_rolling_state()
            self._open_ledger(import_legacy=True)
            self._write_manifest((), update_only=True)
            return self.session_dir
        return ""

    def _prune_old_sessions(self, base: Path, *, keep: int) -> None:
        """Remove oldest completed match folders while preserving the active one."""
        try:
            current = Path(self.session_dir).resolve()
            sessions = sorted(
                (path for path in base.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            retained = 0
            for path in sessions:
                if path.resolve() == current:
                    retained += 1
                    continue
                retained += 1
                if retained > max(1, int(keep or 20)):
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass

    def active(self) -> bool:
        return bool(self.session_dir)

    def close(self) -> None:
        ledger = self._ledger
        self._ledger = None
        if ledger is not None:
            ledger.close()

    def _open_ledger(self, *, import_legacy: bool) -> None:
        if not self.active():
            return
        self.close()
        self._ledger = MatchEventLedger(str(Path(self.session_dir) / "match_archive.db"))
        self._ledger.set_metadata("session_id", self.session_id)
        self._ledger.set_metadata("pair", list(self._pair or []))
        self._ledger.set_metadata(
            "official_authority",
            {"winner": "winner.txt", "score_damage_knockdowns": "scores.csv"},
        )
        if import_legacy:
            records = self._legacy_round_records()
            for round_no, values in records.items():
                self._ledger.upsert_events(round_no, "damage", values.get("events") or [])
                self._ledger.upsert_events(round_no, "throw", values.get("throws") or [])

    def record_damage(self, round_no: int, events: Iterable[dict], *, ruleset_version: str = "") -> None:
        materialized = self._filter_rolling_snapshot(round_no, events, "damage")
        if self._ledger is not None:
            self._ledger.upsert_events(round_no, "damage", materialized, ruleset_version=ruleset_version)
        self._append_records("damage_events.jsonl", round_no, materialized, self._seen_damage, "damage")

    def record_throws(self, round_no: int, events: Iterable[dict]) -> None:
        materialized = self._filter_rolling_snapshot(round_no, events, "throw")
        if self._ledger is not None:
            self._ledger.upsert_events(round_no, "throw", materialized)
        self._append_records("punches_thrown.jsonl", round_no, materialized, self._seen_throws, "throw")

    def record_classified(self, round_no: int, events: Iterable[dict], *, ruleset_version: str) -> None:
        """Upsert central verdicts without creating duplicate raw events."""
        if self._ledger is None:
            return
        self._ledger.upsert_events(
            round_no,
            "damage",
            [dict(event or {}) for event in events or []],
            ruleset_version=str(ruleset_version or ""),
        )

    def classification_counts(self, ruleset_version: str) -> Dict[str, int]:
        if self._ledger is None:
            return {"total": 0, "classified": 0}
        return self._ledger.classification_counts(str(ruleset_version or ""))

    def audit(self, phase: str, ok: bool, details: Dict[str, Any]) -> None:
        if self._ledger is not None:
            self._ledger.audit(phase, ok, details)

    def integrity(self) -> Dict[str, Any]:
        if self._ledger is None:
            return {"ok": False, "integrity": "ledger unavailable", "counts": {}}
        return self._ledger.integrity()

    def reconcile(self) -> Dict[str, Any]:
        """Compare the SQLite primary ledger with the JSONL recovery mirror."""
        if self._ledger is None:
            return {"ok": False, "missing_in_ledger": 0, "missing_in_jsonl": 0}
        ledger_rows = self._ledger.records()
        legacy_rows = self._legacy_round_records()

        def _ids(rows: Dict[int, Dict[str, List[dict]]]) -> set[str]:
            result: set[str] = set()
            for round_no, values in dict(rows or {}).items():
                for kind, key in (("damage", "events"), ("throw", "throws")):
                    for event in list(dict(values or {}).get(key) or []):
                        result.add(stable_event_id(int(round_no or 1), kind, dict(event or {})))
            return result

        ledger_ids = _ids(ledger_rows)
        legacy_ids = _ids(legacy_rows)
        details = {
            "ok": legacy_ids.issubset(ledger_ids),
            "ledger_events": len(ledger_ids),
            "jsonl_events": len(legacy_ids),
            "missing_in_ledger": len(legacy_ids - ledger_ids),
            # A positive value is allowed briefly because the transactional
            # ledger is committed before its compatibility mirror is appended.
            "missing_in_jsonl": len(ledger_ids - legacy_ids),
        }
        self._ledger.audit("ledger_jsonl_reconcile", bool(details["ok"]), details)
        return details

    def snapshot_scores(self, round_no: int, source_path: str, *, final: bool = False) -> None:
        if not self.active() or not source_path or not os.path.isfile(source_path):
            return
        try:
            raw = Path(source_path).read_bytes()
        except OSError:
            return
        digest = hashlib.sha1(raw).hexdigest()
        key = f"{int(round_no or 0)}:{'final' if final else 'round'}"
        if self._score_hashes.get(key) == digest:
            return
        self._score_hashes[key] = digest
        name = "scores_final.csv" if final else f"scores_round_{max(1, int(round_no or 1)):02d}.csv"
        target = Path(self.session_dir) / name
        try:
            target.write_bytes(raw)
        except OSError:
            return
        if self._ledger is not None:
            self._ledger.snapshot_official(key, "scores", int(round_no or 0), raw)
            if final:
                self._audit_official_sources()
        self._write_manifest((), update_only=True)

    def snapshot_vitals(self, round_no: int, values: Dict[str, Any], *, final: bool = False) -> None:
        if not self.active() or not values:
            return
        name = "vitals_final.json" if final else f"vitals_round_{max(1, int(round_no or 1)):02d}.json"
        target = Path(self.session_dir) / name
        try:
            materialized = {
                side: dict((values or {}).get(side) or {})
                for side in ("blue", "red")
            }
            # TimerAuto owns the movement-derived SP/actual-health value and
            # merges it after the watcher freezes punishment gauges. A late
            # score/result refresh used to overwrite the whole JSON document
            # and silently erase staminaPct. Preserve that independently owned
            # field while still replacing the watcher-owned health values.
            if target.is_file():
                try:
                    previous = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError):
                    previous = {}
                for side in ("blue", "red"):
                    old_side = dict((previous or {}).get(side) or {})
                    if (
                        "staminaPct" in old_side
                        and "staminaPct" not in materialized[side]
                    ):
                        materialized[side]["staminaPct"] = old_side["staminaPct"]
            target.write_text(json.dumps(materialized, ensure_ascii=False, indent=2), encoding="utf-8")
            if self._ledger is not None:
                self._ledger.snapshot_vitals(
                    "final" if final else "round",
                    int(round_no or 0),
                    materialized,
                )
            self._write_manifest((), update_only=True)
        except OSError:
            return

    def load_vitals(self, round_no: int, *, final: bool = False) -> Dict[str, Any]:
        """Read a frozen report gauge snapshot without consulting live files."""
        if not self.active():
            return {}
        name = "vitals_final.json" if final else f"vitals_round_{max(1, int(round_no or 1)):02d}.json"
        try:
            data = json.loads((Path(self.session_dir) / name).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def merge_vitals(self, round_no: int, values: Dict[str, Any], *, final: bool = False) -> None:
        """Merge another report-owned gauge into the frozen archive snapshot.

        Punishment/game-health is captured by the watcher while movement SP is
        owned by TimerAuto.  Keeping both in this one archived document lets a
        rebuilt final report read the exact same values after an app restart.
        """
        if not self.active() or not values:
            return
        current = self.load_vitals(round_no, final=final)
        merged = dict(current or {})
        for side in ("blue", "red"):
            incoming = dict((values or {}).get(side) or {})
            if not incoming:
                continue
            target = dict(merged.get(side) or {})
            target.update(incoming)
            merged[side] = target
        self.snapshot_vitals(round_no, merged, final=final)

    def snapshot_live_vitals(self, round_no: int, values: Dict[str, Any]) -> None:
        """Persist the latest in-progress gauge state for a safe app restart.

        This is separate from the round/final report snapshots: a restart must
        restore the current broadcast gauge without changing a frozen report.
        """
        if not self.active() or not values:
            return
        with self._vitals_lock:
            materialized = {
                side: dict((values or {}).get(side) or {})
                for side in ("blue", "red")
            }
            # The watcher owns punishment/game-health while TimerAuto owns the
            # movement-derived actual-health value.  Either side can update the
            # live snapshot first, so preserve fields omitted by the writer.
            previous = self._load_live_vitals_unlocked()
            previous_values = dict(previous.get("values") or {})
            for side in ("blue", "red"):
                old_side = dict(previous_values.get(side) or {})
                for key, value in old_side.items():
                    materialized[side].setdefault(key, value)
            payload = {
                "round": max(1, int(round_no or 1)),
                "updated_at": time.time(),
                "values": materialized,
            }
            try:
                target = Path(self.session_dir) / "vitals_live.json"
                temp = target.with_suffix(".json.tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temp, target)
                if self._ledger is not None:
                    self._ledger.snapshot_vitals("live", int(round_no or 0), payload)
                self._write_manifest((), update_only=True)
            except OSError:
                return

    def load_live_vitals(self) -> Dict[str, Any]:
        """Return the last in-progress gauge snapshot saved before restart."""
        if not self.active():
            return {}
        with self._vitals_lock:
            return self._load_live_vitals_unlocked()

    def _load_live_vitals_unlocked(self) -> Dict[str, Any]:
        try:
            data = json.loads((Path(self.session_dir) / "vitals_live.json").read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
            return {}
        return data

    def merge_live_vitals(self, round_no: int, values: Dict[str, Any]) -> None:
        """Merge TimerAuto-owned actual health into the restart snapshot."""
        if not self.active() or not values:
            return
        with self._vitals_lock:
            current = self._load_live_vitals_unlocked()
            merged = {
                side: dict(dict(current.get("values") or {}).get(side) or {})
                for side in ("blue", "red")
            }
            for side in ("blue", "red"):
                merged[side].update(dict((values or {}).get(side) or {}))
            self.snapshot_live_vitals(
                max(1, int(round_no or current.get("round") or 1)),
                merged,
            )

    def round_records(self) -> Dict[int, Dict[str, List[dict]]]:
        if self._ledger is not None:
            records = self._ledger.records()
            if records:
                return self._remove_cross_round_snapshot_duplicates(records)
        return self._remove_cross_round_snapshot_duplicates(self._legacy_round_records())

    def _legacy_round_records(self) -> Dict[int, Dict[str, List[dict]]]:
        rows: Dict[int, Dict[str, List[dict]]] = {}
        for filename, key in (("damage_events.jsonl", "events"), ("punches_thrown.jsonl", "throws")):
            path = Path(self.session_dir) / filename
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    item = json.loads(line)
                    round_no = max(1, int(item.get("round", 1) or 1))
                    event = dict(item.get("event") or {})
                except Exception:
                    continue
                rows.setdefault(round_no, {"events": [], "throws": []})[key].append(event)
        return rows

    def _restore_rolling_state(self) -> None:
        """Restore cross-round snapshot knowledge after an application restart."""
        self._raw_key_rounds = {"damage": {}, "throw": {}}
        self._rolling_kinds.clear()
        records = self._legacy_round_records()
        for round_no, values in sorted(records.items()):
            for kind, field in (("damage", "events"), ("throw", "throws")):
                key_rounds = self._raw_key_rounds[kind]
                rows = [dict(item or {}) for item in list(dict(values or {}).get(field) or [])]
                keys = [self._event_key(item, kind) for item in rows]
                overlap = sum(
                    1 for key in set(keys)
                    if key and any(saved_round != int(round_no) for saved_round in key_rounds.get(key, set()))
                )
                if overlap >= 3 and overlap / max(1, len(set(keys))) >= 0.10:
                    self._rolling_kinds.add(kind)
                for key in keys:
                    if key:
                        key_rounds.setdefault(key, set()).add(int(round_no))

    def _filter_rolling_snapshot(self, round_no: int, events: Iterable[dict], kind: str) -> List[dict]:
        """Return only rows belonging to this round when a game file is cumulative.

        SpectatorLog sometimes keeps the previous round at the front of
        punches_thrown.txt/damage_events.txt.  The watcher reads the whole
        snapshot, so assigning every row to the new round inflates accuracy and
        all derived report metrics.  Detect substantial cross-round overlap and
        retain only rows that have not already appeared in an earlier round.
        """
        archived_round = max(1, int(round_no or 1))
        materialized = [dict(event or {}) for event in events or []]
        if not materialized:
            return []
        kind = "throw" if str(kind) == "throw" else "damage"
        key_rounds = self._raw_key_rounds.setdefault(kind, {})
        keyed = [(event, self._event_key(event, kind)) for event in materialized]
        unique_keys = {key for _, key in keyed if key}
        cross_round_keys = {
            key for key in unique_keys
            if any(saved_round != archived_round for saved_round in key_rounds.get(key, set()))
        }
        if (
            kind in self._rolling_kinds
            or (
                len(cross_round_keys) >= 3
                and len(cross_round_keys) / max(1, len(unique_keys)) >= 0.10
            )
        ):
            self._rolling_kinds.add(kind)
            materialized = [
                event for event, key in keyed
                if key not in cross_round_keys
            ]
        for event in materialized:
            key = self._event_key(event, kind)
            if key:
                key_rounds.setdefault(key, set()).add(archived_round)
        return materialized

    def _remove_cross_round_snapshot_duplicates(
        self, records: Dict[int, Dict[str, List[dict]]]
    ) -> Dict[int, Dict[str, List[dict]]]:
        """Repair the report view of archives written by older builds.

        The physical archive stays untouched.  Only a round showing substantial
        exact overlap with earlier rounds is treated as a rolling snapshot, so a
        genuinely identical isolated punch in two rounds remains valid.
        """
        cleaned: Dict[int, Dict[str, List[dict]]] = {
            int(round_no): {
                "events": [dict(item or {}) for item in list(dict(values or {}).get("events") or [])],
                "throws": [dict(item or {}) for item in list(dict(values or {}).get("throws") or [])],
            }
            for round_no, values in dict(records or {}).items()
        }
        for kind, field in (("damage", "events"), ("throw", "throws")):
            seen: set[str] = set()
            rolling = False
            for round_no in sorted(cleaned):
                rows = list(cleaned[round_no][field])
                keys = [self._event_key(row, kind) for row in rows]
                duplicates = {key for key in keys if key and key in seen}
                unique_count = max(1, len({key for key in keys if key}))
                if len(duplicates) >= 3 and len(duplicates) / unique_count >= 0.10:
                    rolling = True
                if rolling and duplicates:
                    cleaned[round_no][field] = [
                        row for row, key in zip(rows, keys)
                        if key not in seen
                    ]
                seen.update(
                    self._event_key(row, kind)
                    for row in cleaned[round_no][field]
                    if self._event_key(row, kind)
                )
        return cleaned

    def final_scores_path(self) -> str:
        """Return the frozen official end-of-match score file when present."""
        path = Path(self.session_dir) / "scores_final.csv"
        return str(path) if path.is_file() else ""

    def snapshot_winner(self, source_path: str) -> None:
        if not self.active() or not source_path or not os.path.isfile(source_path):
            return
        try:
            raw = Path(source_path).read_bytes()
            (Path(self.session_dir) / "winner_final.txt").write_bytes(raw)
            if self._ledger is not None:
                self._ledger.snapshot_official("winner:final", "winner", 0, raw)
                self._ledger.set_metadata("completed", True)
            self._completed = True
            self._write_manifest((), update_only=True)
            self._audit_official_sources()
        except OSError:
            return

    def final_winner_path(self) -> str:
        path = Path(self.session_dir) / "winner_final.txt"
        return str(path) if path.is_file() else ""

    def _audit_official_sources(self) -> None:
        """Record whether both game-authoritative end-state files are frozen."""
        if self._ledger is None:
            return
        counts = self._ledger.official_counts()
        details = {
            "scores_csv": bool((Path(self.session_dir) / "scores_final.csv").is_file()),
            "winner_txt": bool((Path(self.session_dir) / "winner_final.txt").is_file()),
            "official_snapshots": counts,
            "authority": {
                "score_damage_knockdowns": "scores.csv",
                "winner_result": "winner.txt",
            },
        }
        ok = bool(details["scores_csv"] and details["winner_txt"])
        self._ledger.audit("official_sources_frozen", ok, details)

    def _append_records(self, filename: str, round_no: int, events: Iterable[dict], seen: set[str], kind: str) -> None:
        if not self.active():
            return
        archived_round = max(1, int(round_no or 1))
        records = []
        for event in events or []:
            data = dict(event or {})
            # Round clocks reset, so an otherwise identical punch can legally
            # occur again in a later round. Deduplicate within a round only.
            key = f"{archived_round}:{self._event_key(data, kind)}"
            if not key or key in seen:
                continue
            seen.add(key)
            records.append({"round": archived_round, "event": data})
        if not records:
            return
        path = Path(self.session_dir) / filename
        try:
            with path.open("a", encoding="utf-8") as handle:
                for item in records:
                    handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._write_manifest((), update_only=True)
        except OSError:
            return

    def _load_seen(self, filename: str, kind: str) -> set[str]:
        seen: set[str] = set()
        try:
            lines = (Path(self.session_dir) / filename).read_text(encoding="utf-8").splitlines()
        except OSError:
            return seen
        for line in lines:
            try:
                item = json.loads(line)
                archived_round = max(1, int(item.get("round", 1) or 1))
                seen.add(
                    f"{archived_round}:{self._event_key(dict(item.get('event') or {}), kind)}"
                )
            except Exception:
                continue
        return seen

    @staticmethod
    def _event_key(event: Dict[str, Any], kind: str) -> str:
        return stable_event_id(1, kind, event)

    def _write_manifest(self, pair: Iterable[str], *, update_only: bool = False) -> None:
        if not self.active():
            return
        if pair:
            self._pair = [str(value or "") for value in list(pair or [])]
        payload = {
            "session_id": self.session_id,
            "pair": list(self._pair or []),
            "updated_at": time.time(),
            "purpose": "Per-match report source. scores.csv is authoritative for official score, damage and knockdowns.",
            "update_only": bool(update_only),
            "completed": bool(self._completed),
        }
        try:
            (Path(self.session_dir) / "manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
