import tempfile
import unittest
from pathlib import Path

from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher


class MatchLogArchiveTests(unittest.TestCase):
    def test_archive_rebuilds_accuracy_from_one_match_only(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("match-1", ("blue", "red"))
            archive.record_throws(1, [
                {"time": 100.0, "side": "blue", "punch": "jab"},
                {"time": 99.0, "side": "blue", "punch": "hook"},
            ])
            archive.record_damage(1, [{
                "time": 100.0,
                "attacker_side": "blue",
                "receiver_side": "red",
                "punch": "jab",
                "damage": 20.0,
                "damage_type": "Hit",
            }])

            watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
            watcher._match_archive = archive
            watcher._scorecard_rounds = {}
            rounds = watcher._report_scorecard_rounds()

            self.assertEqual(rounds[1]["thrown"]["blue"], 2)
            self.assertEqual(rounds[1]["landed"]["blue"], 1)
            self.assertLessEqual(rounds[1]["landed"]["blue"], rounds[1]["thrown"]["blue"])

    def test_final_official_scores_refresh_when_source_settles(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("match-1", ("blue", "red"))
            scores = Path(root) / "scores.csv"
            winner = Path(root) / "winner.txt"
            scores.write_text("round,blue_score,red_score\n1,10,9\n", encoding="utf-8")
            winner.write_text("blue", encoding="utf-8")

            archive.snapshot_scores(1, str(scores), final=True)
            archive.snapshot_winner(str(winner))
            scores.write_text("round,blue_score,red_score\n1,10,6\n", encoding="utf-8")
            archive.snapshot_scores(1, str(scores), final=True)

            self.assertIn("10,6", Path(archive.final_scores_path()).read_text(encoding="utf-8"))
            self.assertEqual(Path(archive.final_winner_path()).read_text(encoding="utf-8"), "blue")

    def test_round_and_final_vitals_are_kept_separate(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("match-1", ("blue", "red"))
            round_vitals = {"blue": {"hp_ratio": 0.58}, "red": {"hp_ratio": 0.63}}
            final_vitals = {"blue": {"hp_ratio": 0.51}, "red": {"hp_ratio": 0.60}}

            archive.snapshot_vitals(3, round_vitals)
            archive.snapshot_vitals(3, final_vitals, final=True)

            self.assertEqual(archive.load_vitals(3), round_vitals)
            self.assertEqual(archive.load_vitals(3, final=True), final_vitals)
