import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing

from event_engine import FightEventEngine
from match_event_ledger import MatchEventLedger, raw_event, stable_event_id
from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher


def hit(mult=1.01, *, round_prefix=True):
    parts = ["14.23", "31.23", str(mult), "red", "right", ".4", ".4", "0", "0", "0", "Cross", "Hit", "Head"]
    if round_prefix:
        parts.insert(0, "2")
    return {"time": 14.23, "damage": 31.23, "attacker_side": "blue", "receiver_side": "red",
            "counter_mult": mult, "hand": "right", "punch": "Cross", "damage_type": "Hit",
            "raw_line": "\t".join(parts)}


def seed_old_database(path):
    ledger = MatchEventLedger(str(path))
    ledger.close()
    original = hit()
    lowered = dict(original, counter_mult=1.0, is_counter=False)
    later = dict(hit(), time=5.0, raw_line=hit()["raw_line"].replace("14.23", "5.0"))
    entries = [("old-lowered-id", 2, lowered), (stable_event_id(2, "damage", original), 2, raw_event(original)),
               (stable_event_id(2, "damage", later), 2, raw_event(later)), (stable_event_id(3, "damage", original), 3, raw_event(original))]
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM metadata WHERE key='raw_fact_revision'")
        for sequence, (event_id, round_no, event) in enumerate(entries, 1):
            db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)", (event_id, round_no, "damage", sequence,
                       json.dumps(event, sort_keys=True, separators=(",", ":")),
                       json.dumps({"counter": True, "combo_hits": 2, "combo_damage": 62.46}), "old-rules", 100.0, 100.0))
        db.execute("INSERT INTO official_snapshots VALUES('final','scores',0,'original',?,100)", (b"official score bytes",))
        db.execute("INSERT INTO vitals VALUES('final',0,?,100)", ('{"blue":{"staminaPct":42}}',))
    return original


class RawFactIdentityTests(unittest.TestCase):
    def test_inference_never_turns_a_genuine_101_into_100(self):
        for prefix in (True, False):
            original = hit(round_prefix=prefix)
            for reason in ("whiff", "graze", "light_trade", ""):
                enriched = dict(original, counter_reason=reason, is_counter=True, combo_hits=2, combo_damage=62.46)
                self.assertEqual(1.01, raw_event(enriched)["counter_mult"])
                self.assertEqual(stable_event_id(2, "damage", original), stable_event_id(2, "damage", enriched))

    def test_source_line_repairs_both_legacy_sentinel_and_incorrect_lowering(self):
        self.assertEqual(1.0, raw_event(dict(hit(1.0), counter_mult=1.01, counter_reason="whiff"))["counter_mult"])
        self.assertEqual(1.01, raw_event(dict(hit(), counter_mult=1.0))["counter_mult"])

    def test_no_source_evidence_means_no_guessed_multiplier_change(self):
        event = dict(hit(), counter_reason="whiff")
        event.pop("raw_line")
        self.assertEqual(1.01, raw_event(event)["counter_mult"])
        self.assertEqual(1.01, raw_event(dict(event, raw_line="malformed"))["counter_mult"])

    def test_raw_then_classified_then_raw_still_has_one_row(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = MatchEventLedger(str(Path(directory) / "match.db"))
            original = hit()
            enriched = dict(original, counter_reason="whiff", _central_event={"counter": True, "combo_hits": 1, "combo_damage": 31.23})
            first_id = ledger.upsert_events(2, "damage", [original])
            self.assertEqual(first_id, ledger.upsert_events(2, "damage", [enriched], ruleset_version="current"))
            ledger.upsert_events(2, "damage", [original])
            self.assertEqual({"total": 1, "classified": 1}, ledger.classification_counts("current"))
            self.assertEqual(1.01, ledger.records()[2]["events"][0]["counter_mult"])
            ledger.close()

    def test_real_hits_in_different_rounds_or_different_source_rows_are_not_merged(self):
        original = hit()
        other = dict(original, hand="left", raw_line=original["raw_line"].replace("right", "left"))
        self.assertNotEqual(stable_event_id(2, "damage", original), stable_event_id(2, "damage", other))
        self.assertNotEqual(stable_event_id(2, "damage", original), stable_event_id(3, "damage", original))


class ExistingLedgerRepairTests(unittest.TestCase):
    def test_migration_is_backed_up_idempotent_and_preserves_official_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "match.db"
            original = seed_old_database(path)
            ledger = MatchEventLedger(str(path))
            self.assertEqual(3, ledger.integrity()["counts"]["damage"])
            records = ledger.records()
            self.assertEqual(2, len(records[2]["events"]))
            self.assertNotIn("_central_event", records[2]["events"][0])
            self.assertNotIn("_central_event", records[2]["events"][1])
            self.assertEqual(1.01, records[2]["events"][0]["counter_mult"])
            self.assertIn("_central_event", records[3]["events"][0])  # Unaffected round kept.
            ledger.close()
            backups = list(Path(directory).glob("*.before_raw_fact_v2_*.db"))
            self.assertEqual(1, len(backups))
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertEqual(4, db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(b"official score bytes", db.execute("SELECT payload FROM official_snapshots").fetchone()[0])
                self.assertEqual('{"blue":{"staminaPct":42}}', db.execute("SELECT payload_json FROM vitals").fetchone()[0])
                details = json.loads(db.execute("SELECT details_json FROM audits WHERE phase='raw_fact_identity_repair'").fetchone()[0])
                self.assertEqual(1, details["duplicates_removed"])
                self.assertEqual([2], details["rounds"])
            again = MatchEventLedger(str(path))
            again.upsert_events(2, "damage", [original])
            self.assertEqual(3, again.integrity()["counts"]["damage"])
            again.close()
            self.assertEqual(backups, list(Path(directory).glob("*.before_raw_fact_v2_*.db")))

    def test_rebuild_finishes_once_and_does_not_invent_62_damage_combo(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = MatchLogArchive(directory)
            archive.start("rebuild-101", ("BLUE", "RED"))
            archive.close()
            path = Path(archive.session_dir) / "match_archive.db"
            seed_old_database(path)
            archive._open_ledger(import_legacy=True)
            cfg = SimpleNamespace()
            watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
            watcher.cfg = cfg
            watcher._event_engine = FightEventEngine(cfg)
            watcher._match_archive = archive
            try:
                for _ in range(28):
                    self.assertEqual({"total": 3, "classified": 3}, watcher._rebuild_archive_classifications())
                event = archive.round_records()[2]["events"][0]
                self.assertEqual(1, event["combo_hits"])
                self.assertEqual(31.23, event["combo_damage"])
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(1, db.execute("SELECT COUNT(*) FROM audits WHERE phase='classification_rebuild'").fetchone()[0])
            finally:
                archive.close()

    def test_legacy_jsonl_duplicates_cannot_recreate_the_extra_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = MatchLogArchive(directory)
            archive.start("legacy-101", ("BLUE", "RED"))
            archive.close()
            path = Path(archive.session_dir)
            original = hit()
            bad = dict(original, counter_mult=1.0, counter_reason="whiff")
            (path / "damage_events.jsonl").write_text("\n".join(json.dumps({"round": 2, "event": ev}) for ev in (bad, original)), encoding="utf-8")
            archive._open_ledger(import_legacy=True)
            self.assertEqual(1, archive.integrity()["counts"]["damage"])
            self.assertEqual(1.01, archive.round_records()[2]["events"][0]["counter_mult"])
            self.assertTrue(archive.reconcile()["ok"])
            archive.close()
