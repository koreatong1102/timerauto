import tempfile
import unittest
from pathlib import Path

from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher


class MatchLogArchiveTests(unittest.TestCase):
    def test_late_watcher_snapshot_preserves_timer_owned_actual_health(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("vitals-ownership", ("BLUE", "RED"))
            archive.snapshot_vitals(
                3,
                {
                    "blue": {"long": 30.0, "hp_ratio": 0.70},
                    "red": {"long": 40.0, "hp_ratio": 0.60},
                },
                final=True,
            )
            archive.merge_vitals(
                3,
                {
                    "blue": {"staminaPct": 44},
                    "red": {"staminaPct": 57},
                },
                final=True,
            )
            archive.snapshot_vitals(
                3,
                {
                    "blue": {"long": 31.0, "hp_ratio": 0.69},
                    "red": {"long": 42.0, "hp_ratio": 0.58},
                },
                final=True,
            )

            restored = archive.load_vitals(3, final=True)

        self.assertEqual(restored["blue"]["staminaPct"], 44)
        self.assertEqual(restored["red"]["staminaPct"], 57)
        self.assertEqual(restored["blue"]["hp_ratio"], 0.69)
        self.assertEqual(restored["red"]["hp_ratio"], 0.58)

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

    def test_live_vitals_survive_restart_without_overwriting_round_report(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("match-1", ("blue", "red"))
            round_vitals = {"blue": {"hp_ratio": 0.68}, "red": {"hp_ratio": 0.74}}
            live_vitals = {"blue": {"hp_ratio": 0.41, "long": 59.0}, "red": {"hp_ratio": 0.62, "long": 38.0}}
            archive.snapshot_vitals(2, round_vitals)
            archive.snapshot_live_vitals(3, live_vitals)

            restarted = MatchLogArchive(root)
            self.assertTrue(restarted.resume_latest(("blue", "red"), max_age_sec=60))
            resumed = restarted.load_live_vitals()
            self.assertEqual(resumed["round"], 3)
            self.assertEqual(resumed["values"], live_vitals)
            self.assertEqual(restarted.load_vitals(2), round_vitals)

    def test_live_vitals_merge_preserves_watcher_and_timer_owned_fields(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("live-merge", ("blue", "red"))
            archive.snapshot_live_vitals(
                3,
                {
                    "blue": {"long": 35.0, "hp_ratio": 0.65},
                    "red": {"long": 42.0, "hp_ratio": 0.58},
                },
            )
            archive.merge_live_vitals(
                3,
                {
                    "blue": {"staminaPct": 47},
                    "red": {"staminaPct": 61},
                },
            )
            # A later watcher refresh must not erase TimerAuto's actual health.
            archive.snapshot_live_vitals(
                3,
                {
                    "blue": {"long": 36.0, "hp_ratio": 0.64},
                    "red": {"long": 43.0, "hp_ratio": 0.57},
                },
            )
            restored = archive.load_live_vitals()["values"]

        self.assertEqual(restored["blue"]["staminaPct"], 47)
        self.assertEqual(restored["red"]["staminaPct"], 61)
        self.assertEqual(restored["blue"]["long"], 36.0)
        self.assertEqual(restored["red"]["hp_ratio"], 0.57)

    def test_archived_total_damage_sums_all_rounds_by_attacker(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("damage-resume", ("blue", "red"))
            archive.record_damage(1, [
                {"time": 10.0, "attacker_side": "blue", "receiver_side": "red", "damage": 22.0},
            ])
            archive.record_damage(2, [
                {"time": 9.0, "attacker_side": "red", "receiver_side": "blue", "damage": 31.0},
                {"time": 8.0, "attacker_side": "blue", "receiver_side": "red", "damage": 18.0},
            ])
            watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
            watcher._match_archive = archive
            totals = watcher._archived_total_damage()

        self.assertEqual(totals, {"blue": 40.0, "red": 31.0})

    def test_restart_resumes_the_same_unfinished_pair_and_deduplicates_rows(self):
        with tempfile.TemporaryDirectory() as root:
            first = MatchLogArchive(root)
            first.start("match-original", ("blue", "red"))
            event = {"time": 100.0, "attacker_side": "blue", "receiver_side": "red", "damage": 22.0}
            first.record_damage(1, [event])
            original_dir = first.session_dir

            restarted = MatchLogArchive(root)
            self.assertEqual(restarted.resume_latest(("blue", "red"), max_age_sec=60), original_dir)
            self.assertEqual(restarted.session_id, "match-original")
            restarted.record_damage(1, [event])
            self.assertEqual(len(restarted.round_records()[1]["events"]), 1)

    def test_completed_archive_is_never_resumed_for_a_rematch(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("match-complete", ("blue", "red"))
            winner = Path(root) / "winner.txt"
            winner.write_text("blue", encoding="utf-8")
            archive.snapshot_winner(str(winner))

            restarted = MatchLogArchive(root)
            self.assertEqual(restarted.resume_latest(("blue", "red"), max_age_sec=60), "")

    def test_identical_event_in_different_rounds_is_not_deduplicated(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("round-aware", ("blue", "red"))
            event = {
                "time": 10.0,
                "attacker_side": "blue",
                "receiver_side": "red",
                "hand": "left",
                "damage": 25.0,
                "punch": "Jab",
            }
            archive.record_damage(1, [event])
            archive.record_damage(2, [event])

            records = archive.round_records()

            self.assertEqual(len(records[1]["events"]), 1)
            self.assertEqual(len(records[2]["events"]), 1)

    def test_cumulative_throw_snapshot_is_sliced_per_round(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("rolling-throws", ("blue", "red"))
            round_one = [
                {"time": 100.0 - index, "side": "blue", "hand": "left", "punch": "Jab"}
                for index in range(5)
            ]
            round_two = [
                {"time": 100.0 - index, "side": "red", "hand": "right", "punch": "Hook"}
                for index in range(4)
            ]

            archive.record_throws(1, round_one)
            archive.record_throws(2, round_one + round_two)
            records = archive.round_records()

            self.assertEqual(5, len(records[1]["throws"]))
            self.assertEqual(4, len(records[2]["throws"]))
            self.assertTrue(all(item["side"] == "red" for item in records[2]["throws"]))

    def test_old_polluted_archive_is_cleaned_for_report_projection(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("legacy-rolling", ("blue", "red"))
            repeated = [
                {"time": 90.0 - index, "side": "blue", "hand": "left", "punch": "Jab"}
                for index in range(4)
            ]
            new_round = [
                {"time": 100.0 - index, "side": "red", "hand": "right", "punch": "Cross"}
                for index in range(3)
            ]
            # Simulate a pre-fix ledger that assigned the cumulative snapshot to R2.
            archive._ledger.upsert_events(1, "throw", repeated)
            archive._ledger.upsert_events(2, "throw", repeated + new_round)

            records = archive.round_records()

            self.assertEqual(4, len(records[1]["throws"]))
            self.assertEqual(3, len(records[2]["throws"]))
            self.assertTrue(all(item["side"] == "red" for item in records[2]["throws"]))

    def test_round_report_projection_does_not_include_previous_round_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("round-report-slice", ("blue", "red"))
            round_one_throws = [
                {"time": 100.0 - index, "side": "blue", "hand": "left", "punch": "Jab"}
                for index in range(3)
            ]
            round_one_damage = [
                {
                    "time": 100.0 - index,
                    "attacker_side": "blue",
                    "receiver_side": "red",
                    "hand": "left",
                    "punch": "Jab",
                    "damage": 20.0 + index,
                    "damage_type": "Hit",
                }
                for index in range(3)
            ]
            round_two_throws = [
                {"time": 100.0 - index, "side": "red", "hand": "right", "punch": "Cross"}
                for index in range(2)
            ]
            round_two_damage = [
                {
                    "time": 100.0 - index,
                    "attacker_side": "red",
                    "receiver_side": "blue",
                    "hand": "right",
                    "punch": "Cross",
                    "damage": 30.0 + index,
                    "damage_type": "Hit",
                }
                for index in range(2)
            ]
            archive.record_throws(1, round_one_throws)
            archive.record_damage(1, round_one_damage)
            archive.record_throws(2, round_one_throws + round_two_throws)
            archive.record_damage(2, round_one_damage + round_two_damage)

            watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
            watcher._match_archive = archive
            watcher._scorecard_rounds = {}
            rounds = watcher._report_scorecard_rounds()

            self.assertEqual({"blue": 3, "red": 0}, rounds[1]["thrown"])
            self.assertEqual({"blue": 0, "red": 2}, rounds[2]["thrown"])
            self.assertEqual({"blue": 3, "red": 0}, rounds[1]["landed"])
            self.assertEqual({"blue": 0, "red": 2}, rounds[2]["landed"])
