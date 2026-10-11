"""Regressions for the official log's countdown, append and portrait contract."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from match_log_archive import MatchLogArchive
from event_engine import FightEventEngine
from spectator_log_watcher import SpectatorLogWatcher


class SpectatorLogContractTests(unittest.TestCase):
    def setUp(self):
        self.watcher = SpectatorLogWatcher(SimpleNamespace(players={}))

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(text)

    @staticmethod
    def _hit(clock, damage=40, **extra):
        return dict(
            round=1, time=clock, attacker_side="blue", receiver_side="red",
            hand="left", punch="Jab", damage=damage, counter_mult=1.0,
            damage_type="Hit", weak_point="Chin", **extra,
        )

    def test_archive_combat_facts_do_not_require_a_matching_throw(self):
        with tempfile.TemporaryDirectory() as root:
            match = os.path.join(root, "match")
            os.makedirs(match)
            damage_path = os.path.join(match, "damage_events.txt")
            self._write(damage_path, "")
            self._write(os.path.join(match, "punches_thrown.txt"), "")
            scores = os.path.join(match, "scores.csv")
            self._write(scores,
                        "round,blue_score,red_score,blue_total,red_total,"
                        "blue_damage_taken,red_damage_taken,blue_kds,red_kds\n"
                        "1,10,8,10,8,0,222,0,1\n")
            winner = os.path.join(match, "winner.txt")
            self._write(winner, "blue\tBLUE\n")
            hits = [self._hit(clock) for clock in (100, 99.6, 99.2)]
            last = self._hit(98.8, 60)
            last["counter_mult"] = 1.2
            hits.append(last)
            # Official punishment records can have no corresponding punch.
            kd = self._hit(98.7, 0)
            kd.update(punch="Other", damage_type="PunishmentKnockdown", weak_point="")
            hits.append(kd)
            archive = MatchLogArchive(os.path.join(root, "archive"))
            archive.start("unmatched-facts", ("BLUE", "RED"))
            archive.record_damage(1, hits)
            archive.record_throws(1, [{
                "round": 1, "time": 100, "side": "blue", "hand": "left", "punch": "Jab",
            }])
            archive.snapshot_scores(1, scores, final=True)
            archive.snapshot_winner(winner)
            self.watcher._match_archive = archive
            self.watcher._match_session_id = "unmatched-facts"
            self.watcher._last_round_state = "break"
            stats = self.watcher._report_scorecard_rounds()[1]
            self.assertEqual(len(stats["event_rows"]), 5)
            self.assertEqual(stats["counters_for"]["blue"], 1)
            self.assertEqual(stats["knockdowns_for"]["blue"], 1)
            self.assertEqual(stats["bigs"]["blue"], 1)
            self.assertEqual(stats["landed"]["blue"], 1)
            self.assertEqual(stats["thrown"]["blue"], 1)
            self.assertEqual(sum(v["count"] for v in stats["weak"].values()), 4)
            for final in (False, True):
                with self.subTest(final=final):
                    report = self.watcher._build_round_report_payload(
                        damage_path, 1, ("BLUE", "RED"), force_final=final,
                    )
                    self.assertEqual(report["blue"]["counterHits"], 1)
                    self.assertEqual(report["blue"]["maxComboHits"], 4)
                    self.assertEqual(report["blue"]["maxComboDamage"], 180)
                    self.assertEqual(report["blue"]["damage"], 222)
                    self.assertEqual(report["blue"]["knockdowns"], 1)
                    self.assertEqual(report["blue"]["landed"], 1)
                    self.assertEqual(report["blue"]["thrown"], 1)

    def test_unmatched_combat_facts_remain_round_local(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(os.path.join(root, "archive"))
            archive.start("two-rounds", ("BLUE", "RED"))
            first = self._hit(100, 60)
            first["counter_mult"] = 1.2
            second = self._hit(100, 20)
            second["round"] = 2
            archive.record_damage(1, [first])
            archive.record_damage(2, [second])
            archive.record_throws(2, [dict(round=2, time=90, side="blue", hand="left", punch="Jab")])
            self.watcher._match_archive = archive
            stats = self.watcher._report_scorecard_rounds()
            self.assertEqual(stats[1]["counters_for"]["blue"], 1)
            self.assertEqual(stats[2]["counters_for"]["blue"], 0)
            self.assertEqual(stats[2]["dealt"]["blue"], 20)
            self.assertEqual(stats[2]["landed"]["blue"], 0)

    def test_partial_append_is_counted_once_after_newline(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "punches_thrown.txt")
            self._write(path, "")
            self.assertEqual(self.watcher._read_new_punches_thrown(path), [])
            self._write(path, "1\t100.00\tblue\t")
            self.assertEqual(self.watcher._read_new_punches_thrown(path), [])
            self.assertEqual(self.watcher._sp_throw_offset, 0)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("left\tJab\n")
            events = self.watcher._read_new_punches_thrown(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["side"], "blue")
            self.assertEqual(events[0]["round"], 1)
            self.assertEqual(self.watcher._read_new_punches_thrown(path), [])

    def test_attach_skips_history_but_preserves_a_partial_live_row(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "punches_thrown.txt")
            self._write(path, "1\t120\tred\tleft\tJab\n1\t100\tblue\t")
            self.assertEqual(self.watcher._read_new_punches_thrown(path), [])
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("right\tCross\n")
            events = self.watcher._read_new_punches_thrown(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["side"], "blue")
            # A reset/recreated file is a fresh stream, not old history.
            self._write(path, "2\t90\tred\tleft\tJab\n")
            events = self.watcher._read_new_punches_thrown(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["round"], 2)

    def test_combo_sp_uses_countdown_and_never_crosses_round_boundary(self):
        self.watcher.cfg.spectator_sp_activity_global_scale = 1.0
        events = [dict(round=1, time=t, side="blue", punch="Jab") for t in (0.6, 0.3, 0)]
        with patch.object(self.watcher, "_read_new_punches_thrown", return_value=events), \
                patch.object(self.watcher, "_read_pose_file", return_value=None):
            self.watcher._update_live_sp_activity("unused", {})
        self.assertEqual(self.watcher._sp_combo_count["blue"], 3)
        self.assertAlmostEqual(self.watcher._sp_activity_spent["blue"], 0.0018 * 3.15)
        with patch.object(self.watcher, "_read_new_punches_thrown", return_value=[
            dict(round=2, time=0.2, side="blue", punch="Jab"),
        ]), patch.object(self.watcher, "_read_pose_file", return_value=None):
            self.watcher._update_live_sp_activity("unused", {})
        self.assertEqual(self.watcher._sp_combo_count["blue"], 1)
        self.assertAlmostEqual(self.watcher._sp_activity_spent["blue"], 0.0018 * 4.15)
        self.watcher._reset_live_sp_motion_state()
        self.assertEqual(self.watcher._sp_combo_last_round["blue"], 0)

    def test_other_hand_landing_does_not_cancel_a_whiff(self):
        hit = self._hit(100, 35)
        throw = dict(round=1, time=100.5, side="red", hand="left", punch="Jab")
        previous = dict(round=1, time=100.48, attacker_side="red", receiver_side="blue",
                        hand="right", damage=20)
        self.watcher._annotate_whiff_counters_from_throws([hit], [throw], [previous, hit])
        self.assertTrue(hit["is_counter"])
        self.assertEqual(hit["counter_reason"], "whiff")

    def test_same_hand_or_unknown_hand_landing_is_not_a_whiff(self):
        for hand in ("left", ""):
            with self.subTest(hand=hand):
                hit = self._hit(100, 35)
                throw = dict(round=1, time=100.5, side="red", hand="left", punch="Jab")
                previous = dict(round=1, time=100.48, attacker_side="red", hand=hand, damage=20)
                self.watcher._annotate_whiff_counters_from_throws([hit], [throw], [previous, hit])
                self.assertFalse(hit.get("is_counter", False))

    def test_whiff_threshold_and_window_remain_unchanged(self):
        for damage, gap, expected in ((24.99, .5, False), (25, .7, True), (35, .71, False)):
            with self.subTest(damage=damage, gap=gap):
                hit = self._hit(100, damage)
                throw = dict(round=1, time=100 + gap, side="red", hand="left", punch="Jab")
                self.watcher._annotate_whiff_counters_from_throws([hit], [throw], [hit])
                self.assertEqual(bool(hit.get("is_counter")), expected)

    def test_graze_exact_window_boundary_is_accepted_by_both_paths(self):
        previous = dict(round=1, time=100.7, attacker_side="red", receiver_side="blue", damage=12)
        reply = self._hit(100, 30)
        engine = FightEventEngine(self.watcher.cfg)
        engine.classify(previous)
        result = engine.classify(reply)
        self.assertTrue(result["counter"])
        self.assertEqual(result["counter_reason"], "graze")
        self.assertEqual(self.watcher._counter_reason_against_previous(reply, previous), "graze")

    def test_winner_portrait_refresh_handles_late_writes_without_clearing(self):
        with tempfile.TemporaryDirectory() as root:
            self.watcher.cfg.spectator_match_archive_dir = os.path.join(root, "archive")
            for folder in ("blue", "red", "match"):
                os.makedirs(os.path.join(root, folder))
            self._write(os.path.join(root, "blue", "name.txt"), "BLUE")
            self._write(os.path.join(root, "red", "name.txt"), "RED")
            self._write(os.path.join(root, "match", "round_number.txt"), "1")
            state_path = os.path.join(root, "match", "round_state.txt")
            self._write(state_path, "MatchIntro")
            intro = SimpleNamespace(size=1)
            result = SimpleNamespace(size=1)
            with patch.object(self.watcher, "_read_image_if_changed", return_value=(True, intro)):
                update = self.watcher._read_update(root)
            self.assertIs(update.get("blue_player_img"), intro)
            self.assertTrue(self.watcher._portrait_locked["blue"])
            self._write(state_path, "RoundKnockout")
            self._write(os.path.join(root, "match", "winner.txt"), "blue\tBLUE\n")
            with patch.object(self.watcher, "_read_image_if_changed", return_value=(False, None)) as reader:
                update = self.watcher._read_update(root)
                self.assertEqual(reader.call_count, 2)
            self.assertNotIn("blue_player_img", update)
            # Images can finish writing after the winner file / state change.
            self.watcher._portrait_result_check_at = 0
            with patch.object(self.watcher, "_read_image_if_changed", return_value=(True, result)):
                update = self.watcher._read_update(root)
            self.assertIs(update.get("blue_player_img"), result)
            self.assertIs(update.get("red_player_img"), result)
            with patch.object(self.watcher, "_read_image_if_changed") as reader:
                self.watcher._read_update(root)
                reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
