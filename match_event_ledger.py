from __future__ import annotations

"""Transactional per-match event ledger.

The game's SpectatorLog files are rolling snapshots, not a durable event
source.  This ledger stores each normalized event once, keeps the raw fact and
the central-engine verdict separate, and can rebuild the existing JSONL-facing
report projection after an application restart.
"""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DERIVED_FIELDS = {
    "_central_event",
    "event_id",
    "seen_at",
    "effect_kind",
    "is_counter",
    "event_primary",
    "event_tags",
    "combo_hits",
    "combo_damage",
    "counter_reason",
    "official_counter",
    "inferred_counter",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def raw_event(event: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(event or {})
    result = {key: value for key, value in source.items() if key not in DERIVED_FIELDS}
    # Older builds encoded an inferred whiff/graze counter by overwriting the
    # game's multiplier with 1.01. Undo only that synthetic sentinel while
    # importing legacy JSONL; genuine official multipliers remain untouched.
    inferred_reason = str(source.get("counter_reason") or "").lower().strip()
    if inferred_reason in ("whiff", "graze", "light_trade") and "counter_mult" in result:
        try:
            if float(result.get("counter_mult", 1.0) or 1.0) <= 1.011:
                result["counter_mult"] = 1.0
        except (TypeError, ValueError):
            result["counter_mult"] = 1.0
    # ``is_counter`` is also exposed as a live derived field. Recover the
    # immutable game verdict from counter_mult before persisting the raw fact.
    if "counter_mult" in result:
        try:
            result["is_counter"] = float(result.get("counter_mult", 1.0) or 1.0) > 1.0001
        except (TypeError, ValueError):
            result["is_counter"] = False
    return result


def classified_event(event: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(event or {})
    central = dict(data.get("_central_event") or {})
    if central:
        return central
    result = {
        key: data.get(key)
        for key in (
            "event_primary",
            "event_tags",
            "combo_hits",
            "combo_damage",
            "counter_reason",
            "official_counter",
            "inferred_counter",
        )
        if key in data
    }
    if "is_counter" in data and (
        data.get("counter_reason") or data.get("official_counter") or data.get("inferred_counter")
    ):
        result["counter"] = bool(data.get("is_counter"))
    return result


def stable_event_id(round_no: int, kind: str, event: Dict[str, Any]) -> str:
    """Return an ID based only on immutable game facts.

    Derived fields are deliberately excluded so enriching an already archived
    hit updates its verdict instead of creating a duplicate event.
    """

    data = raw_event(event)
    if kind == "damage":
        fields = (
            "time", "attacker_side", "receiver_side", "damage", "counter_mult",
            "hand", "screen_x", "screen_y", "world_x", "world_y", "world_z",
            "punch", "damage_type", "weak_point", "raw_line",
        )
    else:
        fields = ("time", "side", "hand", "punch", "raw_line")
    identity = {"round": max(1, int(round_no or 1)), "kind": str(kind)}
    identity.update({key: data.get(key) for key in fields if key in data})
    digest = hashlib.sha1(_json(identity).encode("utf-8", "ignore")).hexdigest()
    return f"{kind}:{digest}"


class MatchEventLedger:
    SCHEMA_VERSION = 1

    def __init__(self, path: str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._wal_initialized = False
        with self._lock:
            self._connect()
            self._create_schema()
            self._disconnect()

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            if not self._wal_initialized:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._wal_initialized = True
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA foreign_keys=ON")
        return self._db

    def _disconnect(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                round_no INTEGER NOT NULL,
                kind TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                classified_json TEXT,
                ruleset_version TEXT NOT NULL DEFAULT '',
                first_seen_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_round_kind_seq
                ON events(round_no, kind, sequence_no);
            CREATE TABLE IF NOT EXISTS official_snapshots (
                snapshot_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                round_no INTEGER NOT NULL,
                digest TEXT NOT NULL,
                payload BLOB NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vitals (
                scope TEXT NOT NULL,
                round_no INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(scope, round_no)
            );
            CREATE TABLE IF NOT EXISTS audits (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase TEXT NOT NULL,
                ok INTEGER NOT NULL,
                details_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consumer_checkpoints (
                consumer TEXT PRIMARY KEY,
                sequence_no INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        self._db.execute(
            """
            INSERT INTO metadata(key,value_json,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at
            """,
            ("schema_version", _json(self.SCHEMA_VERSION), time.time()),
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                if self._db is not None:
                    self._db.commit()
            except sqlite3.Error:
                pass
            self._disconnect()

    def set_metadata(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            db = self._connect()
            try:
                db.execute(
                    """
                    INSERT INTO metadata(key,value_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at
                    """,
                    (str(key), _json(value), now),
                )
                db.commit()
            finally:
                self._disconnect()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        with self._lock:
            db = self._connect()
            try:
                row = db.execute("SELECT value_json FROM metadata WHERE key=?", (str(key),)).fetchone()
            finally:
                self._disconnect()
        if row is None:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except (TypeError, ValueError):
            return default

    def _next_sequence(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(sequence_no),0)+1 AS value FROM events").fetchone()
        return int(row["value"] if row else 1)

    def upsert_events(
        self,
        round_no: int,
        kind: str,
        events: Iterable[dict],
        *,
        ruleset_version: str = "",
    ) -> List[str]:
        archived_round = max(1, int(round_no or 1))
        now = time.time()
        ids: List[str] = []
        with self._lock:
            db = self._connect()
            sequence = self._next_sequence()
            db.execute("BEGIN IMMEDIATE")
            try:
                for item in events or []:
                    data = dict(item or {})
                    event_id = stable_event_id(archived_round, kind, data)
                    raw = raw_event(data)
                    verdict = classified_event(data)
                    existing = db.execute(
                        "SELECT classified_json,ruleset_version FROM events WHERE event_id=?",
                        (event_id,),
                    ).fetchone()
                    if existing is None:
                        db.execute(
                            """
                            INSERT INTO events(
                                event_id,round_no,kind,sequence_no,raw_json,classified_json,
                                ruleset_version,first_seen_at,updated_at
                            ) VALUES(?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                event_id, archived_round, str(kind), sequence, _json(raw),
                                _json(verdict) if verdict else None,
                                str(ruleset_version or "") if verdict else "",
                                now, now,
                            ),
                        )
                        sequence += 1
                    else:
                        classified_json = _json(verdict) if verdict else existing["classified_json"]
                        version = str(ruleset_version or "") if verdict else str(existing["ruleset_version"] or "")
                        db.execute(
                            """
                            UPDATE events SET raw_json=?,classified_json=?,ruleset_version=?,updated_at=?
                            WHERE event_id=?
                            """,
                            (_json(raw), classified_json, version, now, event_id),
                        )
                    ids.append(event_id)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                self._disconnect()
        return ids

    def records(self) -> Dict[int, Dict[str, List[dict]]]:
        result: Dict[int, Dict[str, List[dict]]] = {}
        with self._lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT round_no,kind,raw_json,classified_json,event_id FROM events ORDER BY sequence_no"
                ).fetchall()
            finally:
                self._disconnect()
        for row in rows:
            try:
                event = dict(json.loads(str(row["raw_json"])))
                verdict = json.loads(str(row["classified_json"])) if row["classified_json"] else {}
            except (TypeError, ValueError):
                continue
            if isinstance(verdict, dict) and verdict:
                event["_central_event"] = dict(verdict)
                event["event_id"] = str(verdict.get("event_id") or row["event_id"])
                event["event_primary"] = str(verdict.get("primary") or verdict.get("event_primary") or "hit")
                event["event_tags"] = list(verdict.get("tags") or verdict.get("event_tags") or [])
                event["combo_hits"] = int(verdict.get("combo_hits", 0) or 0)
                event["combo_damage"] = float(verdict.get("combo_damage", 0.0) or 0.0)
                event["is_counter"] = bool(verdict.get("counter", event.get("is_counter", False)))
                event["counter_reason"] = str(verdict.get("counter_reason") or "")
                event["official_counter"] = bool(verdict.get("official_counter", False))
                event["inferred_counter"] = bool(verdict.get("inferred_counter", False))
            round_no = max(1, int(row["round_no"] or 1))
            bucket = result.setdefault(round_no, {"events": [], "throws": []})
            bucket["events" if str(row["kind"]) == "damage" else "throws"].append(event)
        return result

    def classification_counts(self, ruleset_version: str) -> Dict[str, int]:
        with self._lock:
            db = self._connect()
            try:
                total = int(db.execute("SELECT COUNT(*) FROM events WHERE kind='damage'").fetchone()[0])
                classified = int(
                    db.execute(
                        """
                        SELECT COUNT(*) FROM events
                        WHERE kind='damage' AND classified_json IS NOT NULL AND ruleset_version=?
                        """,
                        (str(ruleset_version or ""),),
                    ).fetchone()[0]
                )
            finally:
                self._disconnect()
        return {"total": total, "classified": classified}

    def snapshot_official(self, key: str, kind: str, round_no: int, payload: bytes) -> None:
        digest = hashlib.sha1(payload).hexdigest()
        with self._lock:
            db = self._connect()
            try:
                db.execute(
                    """
                    INSERT INTO official_snapshots(snapshot_key,kind,round_no,digest,payload,updated_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(snapshot_key) DO UPDATE SET
                        digest=excluded.digest,payload=excluded.payload,updated_at=excluded.updated_at
                    """,
                    (str(key), str(kind), int(round_no or 0), digest, sqlite3.Binary(payload), time.time()),
                )
                db.commit()
            finally:
                self._disconnect()

    def snapshot_vitals(self, scope: str, round_no: int, values: Dict[str, Any]) -> None:
        with self._lock:
            db = self._connect()
            try:
                db.execute(
                    """
                    INSERT INTO vitals(scope,round_no,payload_json,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(scope,round_no) DO UPDATE SET
                        payload_json=excluded.payload_json,updated_at=excluded.updated_at
                    """,
                    (str(scope), int(round_no or 0), _json(values), time.time()),
                )
                db.commit()
            finally:
                self._disconnect()

    def audit(self, phase: str, ok: bool, details: Dict[str, Any]) -> None:
        with self._lock:
            db = self._connect()
            try:
                db.execute(
                    "INSERT INTO audits(phase,ok,details_json,created_at) VALUES(?,?,?,?)",
                    (str(phase), 1 if ok else 0, _json(details), time.time()),
                )
                db.commit()
            finally:
                self._disconnect()

    def integrity(self) -> Dict[str, Any]:
        with self._lock:
            db = self._connect()
            try:
                result = str(db.execute("PRAGMA integrity_check").fetchone()[0])
                rows = db.execute(
                    "SELECT kind,COUNT(*) AS count FROM events GROUP BY kind"
                ).fetchall()
            finally:
                self._disconnect()
        return {
            "ok": result.lower() == "ok",
            "integrity": result,
            "counts": {str(row["kind"]): int(row["count"]) for row in rows},
        }

    def official_counts(self) -> Dict[str, int]:
        with self._lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT kind,COUNT(*) AS count FROM official_snapshots GROUP BY kind"
                ).fetchall()
            finally:
                self._disconnect()
        return {str(row["kind"]): int(row["count"]) for row in rows}
