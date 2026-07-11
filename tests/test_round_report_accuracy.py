from types import SimpleNamespace
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


if __name__ == "__main__":
    unittest.main()
