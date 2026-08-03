import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from event_engine import FightEventEngine
from match_event_ledger import MatchEventLedger
from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher


class MatchEventLedgerTests(unittest.TestCase):
    def test_raw_and_classified_upserts_are_one_event(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = MatchEventLedger(str(Path(root) / "match.db"))
            raw = {
                "time": 100.0,
                "attacker_side": "blue",
                "receiver_side": "red",
                "damage": 31.0,
                "counter_mult": 1.0,
            }
            enriched = dict(raw)
            enriched["_central_event"] = {
                "event_id": "live-1",
                "primary": "hit",
                "tags": ["hit", "counter", "counter_graze"],
                "combo_hits": 1,
                "combo_damage": 31.0,
                "counter": True,
                "counter_reason": "graze",
                "official_counter": False,
                "inferred_counter": True,
            }
            ledger.upsert_events(1, "damage", [raw])
            ledger.upsert_events(1, "damage", [enriched], ruleset_version="rules-a")

            records = ledger.records()
            status = ledger.classification_counts("rules-a")

            self.assertEqual(len(records[1]["events"]), 1)
            self.assertTrue(records[1]["events"][0]["is_counter"])
            self.assertEqual(records[1]["events"][0]["counter_reason"], "graze")
            self.assertEqual(status, {"total": 1, "classified": 1})

    def test_legacy_jsonl_is_imported_when_ledger_is_created(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("legacy-import", ("blue", "red"))
            session = Path(archive.session_dir)
            archive.record_damage(2, [{
                "time": 42.0,
                "attacker_side": "red",
                "receiver_side": "blue",
                "damage": 22.0,
            }])
            archive.close()
            (session / "match_archive.db").unlink()

            resumed = MatchLogArchive(root)
            self.assertTrue(resumed.resume_latest(("blue", "red"), max_age_sec=60))
            records = resumed.round_records()

            self.assertEqual(len(records[2]["events"]), 1)
            self.assertEqual(records[2]["events"][0]["damage"], 22.0)

    def test_official_files_and_integrity_are_snapshotted(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("official", ("blue", "red"))
            scores = Path(root) / "scores.csv"
            winner = Path(root) / "winner.txt"
            scores.write_text("round,blue_score,red_score\n1,10,9\n", encoding="utf-8")
            winner.write_text("blue", encoding="utf-8")

            archive.snapshot_scores(1, str(scores), final=True)
            archive.snapshot_winner(str(winner))

            self.assertTrue(archive.integrity()["ok"])
            self.assertTrue(Path(archive.final_scores_path()).is_file())
            self.assertTrue(Path(archive.final_winner_path()).is_file())

    def test_archive_rebuild_persists_whiff_counter_and_combo(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("rebuild", ("blue", "red"))
            archive.record_throws(1, [{"time": 100.0, "side": "red", "punch": "jab"}])
            archive.record_damage(1, [
                {"time": 99.5, "attacker_side": "blue", "receiver_side": "red", "damage": 31.0},
                {"time": 99.0, "attacker_side": "blue", "receiver_side": "red", "damage": 25.0},
            ])
            cfg = SimpleNamespace(
                event_counter_window_sec=0.7,
                event_counter_graze_max_damage=15.0,
                event_counter_response_min_damage=30.0,
                event_combo_min_damage=15.0,
                event_combo_window_sec=0.8,
                event_combo_break_damage=20.0,
                event_heavy_damage=50.0,
                event_signature_damage=60.0,
                event_counter_min_damage=40.0,
                event_combo_emphasis_hits=5,
            )
            watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
            watcher.cfg = cfg
            watcher._event_engine = FightEventEngine(cfg)
            watcher._match_archive = archive

            status = watcher._rebuild_archive_classifications()
            events = archive.round_records()[1]["events"]

            self.assertEqual(status, {"total": 2, "classified": 2})
            self.assertEqual(events[0]["counter_reason"], "whiff")
            self.assertTrue(events[0]["is_counter"])
            self.assertEqual(events[1]["combo_hits"], 2)
            self.assertTrue(archive.reconcile()["ok"])
