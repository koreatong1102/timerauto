from types import SimpleNamespace
import os
import tempfile
import unittest

from spectator_log_watcher import SpectatorLogWatcher


class RoundReportAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.watcher = SpectatorLogWatcher(SimpleNamespace())

    @staticmethod
    def _thrown(side, punch, count):
        return [{"side": side, "punch": punch}] * count

    def test_cumulative_thrown_log_is_split_per_round(self):
        round_one = self._thrown("blue", "Jab", 5)
        cumulative_round_two = (
            round_one
            + self._thrown("blue", "Jab", 3)
            + self._thrown("red", "Hook", 2)
        )

        self.watcher._record_scorecard_thrown_snapshot(1, round_one)
        self.watcher._record_scorecard_thrown_snapshot(2, cumulative_round_two)

        self.assertEqual(self.watcher._scorecard_rounds[1]["thrown"], {"blue": 5, "red": 0})
        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown"], {"blue": 3, "red": 2})
        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown_punches"]["blue"]["jab"]["count"], 3)
        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown_punches"]["red"]["hook"]["count"], 2)

    def test_round_snapshot_refresh_keeps_the_same_round_baseline(self):
        round_one = self._thrown("blue", "Jab", 5)
        self.watcher._record_scorecard_thrown_snapshot(1, round_one)

        first_round_two_snapshot = round_one + self._thrown("blue", "Jab", 2)
        refreshed_round_two_snapshot = first_round_two_snapshot + self._thrown("blue", "Jab", 1)
        self.watcher._record_scorecard_thrown_snapshot(2, first_round_two_snapshot)
        self.watcher._record_scorecard_thrown_snapshot(2, refreshed_round_two_snapshot)

        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown"]["blue"], 3)
        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown_punches"]["blue"]["jab"]["count"], 3)

    def test_final_scorecard_keeps_thrown_snapshot_after_fallback_damage_scan(self):
        thrown = self._thrown("blue", "Jab", 5)
        self.watcher._record_scorecard_thrown_snapshot(1, thrown)
        fallback_event = {
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 20.0,
            "punch": "Jab",
            "damage_type": "Hit",
            "weak_point": "",
        }

        scorecard = self.watcher._scorecard_compute("", 1, [fallback_event])
        round_one = scorecard["rounds"][1]

        self.assertEqual(round_one["landed"]["blue"], 1)
        self.assertEqual(round_one["thrown"]["blue"], 5)
        self.assertEqual(round_one["thrown_punches"]["blue"]["jab"]["count"], 5)

    def test_round_local_clock_snapshot_is_not_subtracted_from_prior_round(self):
        round_one = [{"side": "blue", "punch": "Jab", "time": 120 - i} for i in range(5)]
        round_two = [{"side": "red", "punch": "Hook", "time": 120 - i} for i in range(8)]
        self.watcher._record_scorecard_thrown_snapshot(1, round_one)
        self.watcher._record_scorecard_thrown_snapshot(2, round_two)
        self.assertEqual(self.watcher._scorecard_rounds[2]["thrown"], {"blue": 0, "red": 8})

    def test_landed_event_reclassifies_stale_thrown_punch_type(self):
        thrown = [
            {"side": "red", "hand": "right", "punch": "LeadHook", "time": 100.0},
            {"side": "red", "hand": "right", "punch": "LeadHook", "time": 99.0},
        ]
        landed = [{"attacker_side": "red", "hand": "right", "punch": "RearOverhand", "time": 100.1}]
        self.watcher._record_scorecard_thrown_snapshot(1, thrown, landed)
        breakdown = self.watcher._scorecard_rounds[1]["thrown_punches"]["red"]
        self.assertEqual(breakdown["over"]["count"], 1)
        self.assertEqual(breakdown["hook"]["count"], 1)

    def test_punishment_fraction_is_converted_to_percent(self):
        with tempfile.TemporaryDirectory() as root:
            match = os.path.join(root, "match")
            os.makedirs(match)
            for side, mid, long_value in (("blue", "0.40", "0.25"), ("red", "0.60", "0.50")):
                side_dir = os.path.join(root, side)
                os.makedirs(side_dir)
                with open(os.path.join(side_dir, "punishment_mid.txt"), "w", encoding="utf-8") as stream:
                    stream.write(mid)
                with open(os.path.join(side_dir, "punishment_long_weighted.txt"), "w", encoding="utf-8") as stream:
                    stream.write(long_value)
                with open(os.path.join(side_dir, "punishment_long_raw.txt"), "w", encoding="utf-8") as stream:
                    stream.write(long_value)
            snapshot = self.watcher._punishment_snapshot(os.path.join(match, "damage_events.txt"))
        self.assertEqual(snapshot["blue"]["mid"], 40.0)
        self.assertEqual(snapshot["blue"]["long"], 25.0)
        self.assertAlmostEqual(snapshot["blue"]["hp_ratio"], 0.45)

    def test_official_scores_replace_event_damage_and_knockdowns(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,8,10,8,1200,1600,0,1\n")
            with open(os.path.join(root, "winner.txt"), "w", encoding="utf-8") as stream:
                stream.write("blue\tBLUE")
            self.watcher._last_round_state = "end"
            fallback = [{"attacker_side": "blue", "receiver_side": "red", "damage": 10, "punch": "Jab"}]
            scorecard = self.watcher._scorecard_compute(damage_path, 1, fallback)
        round_one = scorecard["rounds"][1]
        self.assertEqual(round_one["dealt"], {"blue": 1600.0, "red": 1200.0})
        self.assertEqual(round_one["knockdowns_for"], {"blue": 1, "red": 0})


if __name__ == "__main__":
    unittest.main()
