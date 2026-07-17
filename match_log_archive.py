from __future__ import annotations

"""Small per-match log archive used by reports and post-match analysis."""

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


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
        self._score_hashes: Dict[str, str] = {}

    def start(self, session_id: str, pair: Iterable[str]) -> str:
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
        self._score_hashes.clear()
        self._write_manifest(pair)
        return self.session_dir

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

    def record_damage(self, round_no: int, events: Iterable[dict]) -> None:
        self._append_records("damage_events.jsonl", round_no, events, self._seen_damage, "damage")

    def record_throws(self, round_no: int, events: Iterable[dict]) -> None:
        self._append_records("punches_thrown.jsonl", round_no, events, self._seen_throws, "throw")

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
        self._write_manifest((), update_only=True)

    def snapshot_vitals(self, round_no: int, values: Dict[str, Any], *, final: bool = False) -> None:
        if not self.active() or not values:
            return
        name = "vitals_final.json" if final else f"vitals_round_{max(1, int(round_no or 1)):02d}.json"
        target = Path(self.session_dir) / name
        try:
            target.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
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

    def round_records(self) -> Dict[int, Dict[str, List[dict]]]:
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

    def final_scores_path(self) -> str:
        """Return the frozen official end-of-match score file when present."""
        path = Path(self.session_dir) / "scores_final.csv"
        return str(path) if path.is_file() else ""

    def snapshot_winner(self, source_path: str) -> None:
        if not self.active() or not source_path or not os.path.isfile(source_path):
            return
        try:
            (Path(self.session_dir) / "winner_final.txt").write_bytes(Path(source_path).read_bytes())
        except OSError:
            return

    def final_winner_path(self) -> str:
        path = Path(self.session_dir) / "winner_final.txt"
        return str(path) if path.is_file() else ""

    def _append_records(self, filename: str, round_no: int, events: Iterable[dict], seen: set[str], kind: str) -> None:
        if not self.active():
            return
        records = []
        for event in events or []:
            data = dict(event or {})
            key = self._event_key(data, kind)
            if not key or key in seen:
                continue
            seen.add(key)
            records.append({"round": max(1, int(round_no or 1)), "event": data})
        if not records:
            return
        path = Path(self.session_dir) / filename
        try:
            with path.open("a", encoding="utf-8") as handle:
                for item in records:
                    handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            return

    @staticmethod
    def _event_key(event: Dict[str, Any], kind: str) -> str:
        try:
            raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            raw = repr(event)
        return f"{kind}:{hashlib.sha1(raw.encode('utf-8', 'ignore')).hexdigest()}"

    def _write_manifest(self, pair: Iterable[str], *, update_only: bool = False) -> None:
        if not self.active():
            return
        payload = {
            "session_id": self.session_id,
            "pair": list(pair or []),
            "updated_at": time.time(),
            "purpose": "Per-match report source. scores.csv is authoritative for official score, damage and knockdowns.",
            "update_only": bool(update_only),
        }
        try:
            (Path(self.session_dir) / "manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
