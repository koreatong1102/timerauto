from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import patch

from spectator_log_watcher import SpectatorLogWatcher
from match_log_archive import MatchLogArchive


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

    def test_unmatched_opponent_throw_marks_whiff_counter(self):
        hit = {"attacker_side": "blue", "receiver_side": "red", "time": 99.5, "damage": 34.0}
        throws = [{"side": "red", "time": 100.0, "hand": "left", "punch": "Jab"}]
        self.watcher._annotate_whiff_counters_from_throws([hit], throws, [hit])
        self.assertTrue(hit["is_counter"])
        self.assertEqual(hit["counter_reason"], "whiff")

    def test_landed_opponent_throw_is_not_whiff_counter(self):
        previous = {"attacker_side": "red", "receiver_side": "blue", "time": 100.0, "damage": 18.0}
        hit = {"attacker_side": "blue", "receiver_side": "red", "time": 99.5, "damage": 34.0}
        throws = [{"side": "red", "time": 100.0, "hand": "left", "punch": "Jab"}]
        self.watcher._annotate_whiff_counters_from_throws([hit], throws, [previous, hit])
        self.assertFalse(bool(hit.get("is_counter")))

    def test_report_does_not_resurrect_central_false_counter(self):
        with tempfile.TemporaryDirectory() as root:
            match_dir = os.path.join(root, "match")
            os.makedirs(match_dir, exist_ok=True)
            damage_path = os.path.join(match_dir, "damage_events.txt")
            throws_path = os.path.join(match_dir, "punches_thrown.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t8\t1.2\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(throws_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n")

            event = {
                "time": 100.0,
                "attacker_side": "blue",
                "receiver_side": "red",
                "hand": "left",
                "damage": 8.0,
                "counter_mult": 1.2,
                "is_counter": False,
                "punch": "Jab",
                "damage_type": "Hit",
                "_central_event": {
                    "counter": False,
                    "tags": ["hit"],
                    "combo_hits": 0,
                    "combo_damage": 0.0,
                    "primary": "hit",
                },
            }
            thrown = {
                "time": 100.0,
                "side": "blue",
                "hand": "left",
                "punch": "Jab",
            }
            archive = MatchLogArchive(os.path.join(root, "archive"))
            archive.start("central-false-counter", ("BLUE", "RED"))
            archive.record_damage(1, [event])
            archive.record_throws(1, [thrown])
            archive.record_classified(1, [event], ruleset_version=self.watcher._event_ruleset_version())
            self.watcher._match_archive = archive
            self.watcher._last_round_state = "break"

            report = self.watcher._build_round_report_payload(
                damage_path, 1, ("BLUE", "RED"), force_final=False
            )

        self.assertEqual(report["blue"]["counterHits"], 0)

    def test_duplicate_damage_rows_count_as_one_landed_throw(self):
        thrown = [
            {"side": "blue", "hand": "left", "punch": "LeadHook", "time": 168.04},
            {"side": "blue", "hand": "left", "punch": "LeadHook", "time": 160.00},
        ]
        landed = [
            {
                "attacker_side": "blue", "receiver_side": "red", "hand": "left",
                "punch": "RearHook", "time": 168.05, "damage": 37.25,
            },
            {
                "attacker_side": "blue", "receiver_side": "red", "hand": "left",
                "punch": "RearHook", "time": 168.05, "damage": 31.00,
            },
        ]

        matched = self.watcher._match_damage_events_to_throws(thrown, landed)
        self.assertEqual(len(matched["matches"]), 1)
        self.assertEqual(matched["unmatched_damage_count"], 1)
        self.assertEqual(matched["unmatched_throw_count"], 1)

        self.watcher._record_scorecard_thrown_snapshot(1, thrown, landed)
        round_one = self.watcher._scorecard_rounds[1]
        self.assertEqual(round_one["thrown"]["blue"], 2)
        self.assertEqual(round_one["landed"]["blue"], 1)
        self.assertEqual(round_one["punches"]["blue"]["hook"]["count"], 1)

    def test_report_landed_requires_ten_damage_but_keeps_total_damage(self):
        events = [
            {
                "attacker_side": "blue", "receiver_side": "red",
                "punch": "Jab", "damage": 9.99, "weak_point": "Chin",
            },
            {
                "attacker_side": "blue", "receiver_side": "red",
                "punch": "RearHook", "damage": 10.0, "weak_point": "TempleLeft",
            },
        ]

        stats = self.watcher._scorecard_from_fallback_events(events, 1, "")[1]

        self.assertEqual(stats["landed"]["blue"], 1)
        self.assertAlmostEqual(stats["dealt"]["blue"], 19.99)
        self.assertNotIn("jab", stats["punches"]["blue"])
        self.assertEqual(stats["punches"]["blue"]["hook"]["count"], 1)
        self.assertNotIn("턱", stats["weak_received"]["red"])

    def test_snapshot_accuracy_excludes_sub_ten_damage_match(self):
        thrown = [
            {"side": "blue", "hand": "left", "punch": "Jab", "time": 100.0},
            {"side": "blue", "hand": "right", "punch": "RearHook", "time": 99.0},
        ]
        landed = [
            {
                "attacker_side": "blue", "receiver_side": "red", "hand": "left",
                "punch": "Jab", "time": 100.05, "damage": 8.0,
            },
            {
                "attacker_side": "blue", "receiver_side": "red", "hand": "right",
                "punch": "RearHook", "time": 99.05, "damage": 12.0,
            },
        ]

        self.watcher._record_scorecard_thrown_snapshot(1, thrown, landed)
        round_one = self.watcher._scorecard_rounds[1]

        self.assertEqual(round_one["thrown"]["blue"], 2)
        self.assertEqual(round_one["landed"]["blue"], 1)
        self.assertNotIn("jab", round_one["punches"]["blue"])
        self.assertEqual(round_one["punches"]["blue"]["hook"]["count"], 1)

    def test_damage_corner_is_receiver_when_matching_throw(self):
        thrown = [{"side": "red", "hand": "left", "punch": "BackHand", "time": 176.71}]
        landed = [{
            "attacker_side": "blue", "receiver_side": "red", "hand": "left",
            "punch": "Jab", "time": 176.72, "damage": 20.0,
        }]
        matched = self.watcher._match_damage_events_to_throws(thrown, landed)
        self.assertEqual(len(matched["matches"]), 0)

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
        self.assertAlmostEqual(snapshot["blue"]["hp_ratio"], 0.75)

    def test_live_gauge_does_not_flash_full_on_one_zero_read(self):
        first = self.watcher._stabilize_live_punishment_info(
            {"blue_punishment_long": 32.0, "red_punishment_long": 18.0}, "fight"
        )
        self.assertEqual(first["blue_punishment_long"], 32.0)

        # SpectatorLog briefly truncates the file during a rewrite. The HUD
        # must keep the damaged value instead of rendering 100% for one frame.
        transient = self.watcher._stabilize_live_punishment_info(
            {"blue_punishment_long": 0.0}, "fight"
        )
        self.assertEqual(transient["blue_punishment_long"], 32.0)

        normal = self.watcher._stabilize_live_punishment_info(
            {"blue_punishment_long": 33.0}, "fight"
        )
        self.assertEqual(normal["blue_punishment_long"], 33.0)

        # Outside an active round, a real reset is allowed through normally.
        reset = self.watcher._stabilize_live_punishment_info(
            {"blue_punishment_long": 0.0}, "results"
        )
        self.assertEqual(reset["blue_punishment_long"], 0.0)

    def test_resumed_live_gauge_is_emitted_only_once(self):
        self.watcher._resumed_live_punishment_snapshot = {
            "blue": {"mid": 0.0, "long": 7.5},
            "red": {"mid": 0.0, "long": 20.5},
        }
        self.watcher._resumed_live_punishment_round = 4

        first = self.watcher._restore_resumed_live_punishment_snapshot()
        second = self.watcher._restore_resumed_live_punishment_snapshot()

        self.assertEqual(first["blue_punishment_long"], 7.5)
        self.assertEqual(first["red_punishment_long"], 20.5)
        self.assertEqual(second, {})
        self.watcher._live_punishment_long = {"blue": 40.0, "red": 30.0}
        self.assertEqual(self.watcher._restore_resumed_live_punishment_snapshot(), {})
        self.assertEqual(self.watcher._live_punishment_long, {"blue": 40.0, "red": 30.0})

    def test_invalid_punishment_number_is_not_treated_as_a_gauge_value(self):
        self.assertEqual(self.watcher._punishment_percent("nan"), 0.0)
        self.assertEqual(self.watcher._punishment_percent("inf"), 0.0)

    def test_report_health_keeps_last_in_fight_long_snapshot(self):
        self.watcher._last_round_state = "fight"
        live = {
            "blue": {"mid": 80.0, "long": 35.0, "hp_ratio": 0.65},
            "red": {"mid": 20.0, "long": 10.0, "hp_ratio": 0.90},
        }
        self.watcher._report_punishment_snapshot(3, live)
        self.watcher._last_round_state = "results"
        reset = {
            "blue": {"mid": 0.0, "long": 0.0, "hp_ratio": 1.0},
            "red": {"mid": 0.0, "long": 0.0, "hp_ratio": 1.0},
        }
        report = self.watcher._report_punishment_snapshot(3, reset)
        self.assertEqual(report["blue"]["long"], 35.0)
        self.assertEqual(report["blue"]["hp_ratio"], 0.65)

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

    def test_round_report_keeps_official_knockdowns_after_live_slice(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t20\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,7,10,7,500,800,0,2\n")
            self.watcher._last_round_state = "break"
            report = self.watcher._build_round_report_payload(damage_path, 1, ("BLUE", "RED"))
        self.assertEqual(report["blue"]["knockdowns"], 2)
        self.assertEqual(report["red"]["knockdowns"], 0)

    def test_tko_round_report_keeps_official_score_row(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t20\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total\n")
                stream.write("2,10,7,20,17\n")
            self.watcher._last_round_state = "knockout"
            report = self.watcher._build_round_report_payload(damage_path, 2, ("BLUE", "RED"), force_final=False)
        self.assertEqual(report["blue"]["officialScore"], 10)
        self.assertEqual(report["red"]["officialScore"], 7)

    def test_tko_report_uses_last_completed_score_when_log_round_already_advanced(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t64\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tRearHook\tTechnicalKnockout\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tRearHook\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total\n")
                stream.write("2,10,7,20,17\n")
            self.watcher._last_round_state = "knockout"
            report = self.watcher._build_round_report_payload(damage_path, 3, ("BLUE", "RED"), force_final=False)

        self.assertEqual(report["round"], 2)
        self.assertEqual(report["blue"]["officialScore"], 10)
        self.assertEqual(report["red"]["officialScore"], 7)

    def test_tko_report_drops_future_placeholder_score_rows(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("1.0\t44\t1.0\tblue\tright\t.4\t.4\t0\t0\t0\tCross\tTechnicalKnockout\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("1.0\tred\tright\tCross\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,8,10,8,10,2530,2570,3,2\n")
                stream.write("2,10,10,18,20,0,0,0,0\n")
                stream.write("3,10,10,28,30,0,0,0,0\n")
            with open(os.path.join(root, "winner.txt"), "w", encoding="utf-8") as stream:
                stream.write("red\tRED\n")
            self.watcher._last_round_state = "knockout"
            report = self.watcher._build_round_report_payload(
                damage_path, 1, ("BLUE", "RED"), force_final=False
            )

        self.assertEqual(report["round"], 1)
        self.assertEqual(report["blue"]["officialScore"], 8)
        self.assertEqual(report["red"]["officialScore"], 10)
        self.assertEqual([row["round"] for row in report["officialScorecard"]["rounds"]], [1])

    def test_report_exposes_attack_target_and_event_average_per_fighter(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t20\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,8,10,8,300,800,0,0\n")
            self.watcher._last_round_state = "break"
            report = self.watcher._build_round_report_payload(damage_path, 1, ("BLUE", "RED"))

        self.assertEqual(report["blue"]["damage"], 800)
        self.assertEqual(report["blue"]["landedDamage"], 20.0)
        self.assertEqual(report["blue"]["averageDamage"], 20.0)
        self.assertEqual(report["blue"]["weakHitAll"][0]["label"], "턱")
        self.assertEqual(report["red"]["weakReceivedAll"][0]["label"], "턱")

    def test_next_round_hides_break_report_and_stops_both_commentary_roles(self):
        self.watcher.cfg.players = {}
        with tempfile.TemporaryDirectory() as root:
            for folder in ("blue", "red", "match"):
                os.makedirs(os.path.join(root, folder), exist_ok=True)
            with open(os.path.join(root, "blue", "name.txt"), "w", encoding="utf-8") as stream:
                stream.write("BLUE")
            with open(os.path.join(root, "red", "name.txt"), "w", encoding="utf-8") as stream:
                stream.write("RED")
            for name, value in (("round_number.txt", "1"), ("round_total.txt", "3"), ("round_time.txt", "60"), ("round_state.txt", "RoundBreak")):
                with open(os.path.join(root, "match", name), "w", encoding="utf-8") as stream:
                    stream.write(value)
            with open(os.path.join(root, "match", "damage_events.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\t20\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "match", "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n")
            self.watcher._runtime_baseline_ready = True
            self.watcher._last_round_state = "fight"
            self.watcher._read_update(root)
            with open(os.path.join(root, "match", "round_number.txt"), "w", encoding="utf-8") as stream:
                stream.write("2")
            with open(os.path.join(root, "match", "round_state.txt"), "w", encoding="utf-8") as stream:
                stream.write("RoundFight")
            update = self.watcher._read_update(root)

        self.assertTrue(update.get("spectator_round_report_hide"))
        self.assertEqual(update.get("commentary_tts_stop_roles"), ["caster", "analyst"])

    def test_new_match_clears_a_stale_portrait_before_the_new_file_is_ready(self):
        self.watcher.cfg.players = {}
        self.watcher._portrait_locked["blue"] = True
        self.watcher._portrait_lock_name["blue"] = "PREVIOUS_BLUE"
        self.watcher._last_player_payload_pair = ("PREVIOUS_BLUE", "PREVIOUS_RED")
        self.watcher._last_round_state = "fight"
        with tempfile.TemporaryDirectory() as root:
            self.watcher.cfg.spectator_match_archive_dir = os.path.join(root, "archive")
            for folder in ("blue", "red", "match"):
                os.makedirs(os.path.join(root, folder), exist_ok=True)
            for path, value in (
                (os.path.join(root, "blue", "name.txt"), "NEXT_BLUE"),
                (os.path.join(root, "red", "name.txt"), "NEXT_RED"),
                (os.path.join(root, "match", "round_number.txt"), "1"),
                (os.path.join(root, "match", "round_total.txt"), "3"),
                (os.path.join(root, "match", "round_time.txt"), "180"),
                (os.path.join(root, "match", "round_state.txt"), "MatchIntro"),
            ):
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(value)
            with patch.object(self.watcher, "_read_image_if_changed", return_value=(False, None)):
                update = self.watcher._read_update(root)

        self.assertIsNone(update.get("blue_player_img"))
        self.assertEqual(update.get("blue_name"), "NEXT_BLUE")
        self.assertFalse(self.watcher._portrait_locked["blue"])

    def test_starting_at_completed_cancel_still_arms_one_lobby_kick(self):
        """Launching TimerAuto on the result screen must not lose the next lobby edge."""
        self.watcher.cfg.players = {}
        with tempfile.TemporaryDirectory() as root:
            self.watcher.cfg.spectator_match_archive_dir = os.path.join(root, "archive")
            for folder in ("blue", "red", "match"):
                os.makedirs(os.path.join(root, folder), exist_ok=True)
            for path, value in (
                (os.path.join(root, "blue", "name.txt"), "BLUE"),
                (os.path.join(root, "red", "name.txt"), "RED"),
                (os.path.join(root, "match", "round_number.txt"), "3"),
                (os.path.join(root, "match", "round_total.txt"), "3"),
                (os.path.join(root, "match", "round_time.txt"), "0"),
                (os.path.join(root, "match", "round_state.txt"), "Cancel"),
                (os.path.join(root, "match", "scores.csv"), "round,blue_score,red_score\n1,10,9\n"),
                (os.path.join(root, "match", "winner.txt"), "blue\tBLUE"),
            ):
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(value)
            self.watcher._read_update(root)
            self.assertTrue(self.watcher._post_match_lobby_return_armed)
            with open(os.path.join(root, "lobby.txt"), "w", encoding="utf-8") as stream:
                stream.write("slot_0: type=Spectator occupied=true name=HOST ready=false\n")
            update = self.watcher._read_update(root)
            self.assertNotIn("spectator_lobby_returned", update)
            self.assertTrue(self.watcher._post_match_lobby_return_armed)
            with open(os.path.join(root, "lobby.txt"), "w", encoding="utf-8") as stream:
                stream.write(
                    "slot_0: type=Spectator occupied=true name=HOST ready=false\n"
                    "slot_1: type=Player occupied=true name=BLUE ready=false\n"
                )
            update = self.watcher._read_update(root)

        self.assertIn("spectator_lobby_returned", update)
        self.assertFalse(self.watcher._post_match_lobby_return_armed)

    def test_knockout_edge_arms_lobby_kick_before_results_state_exists(self):
        """A TKO may return to lobby without ever writing Results/End."""
        self.watcher.cfg.players = {}
        with tempfile.TemporaryDirectory() as root:
            self.watcher.cfg.spectator_match_archive_dir = os.path.join(root, "archive")
            for folder in ("blue", "red", "match"):
                os.makedirs(os.path.join(root, folder), exist_ok=True)
            files = {
                "blue/name.txt": "BLUE",
                "red/name.txt": "RED",
                "match/round_number.txt": "1",
                "match/round_total.txt": "3",
                "match/round_time.txt": "120",
                "match/round_state.txt": "MatchIntro",
            }
            for relative, value in files.items():
                with open(os.path.join(root, relative), "w", encoding="utf-8") as stream:
                    stream.write(value)
            self.watcher._read_update(root)
            with open(os.path.join(root, "match", "round_state.txt"), "w", encoding="utf-8") as stream:
                stream.write("Fight")
            self.watcher._read_update(root)
            with open(os.path.join(root, "match", "round_state.txt"), "w", encoding="utf-8") as stream:
                stream.write("RoundKnockout")
            self.watcher._read_update(root)
            self.assertTrue(self.watcher._post_match_lobby_return_armed)
            with open(os.path.join(root, "lobby.txt"), "w", encoding="utf-8") as stream:
                stream.write("slot_0: type=Spectator occupied=true name=HOST ready=false\n")
            update = self.watcher._read_update(root)
            self.assertNotIn("spectator_lobby_returned", update)
            self.assertTrue(self.watcher._post_match_lobby_return_armed)
            with open(os.path.join(root, "lobby.txt"), "w", encoding="utf-8") as stream:
                stream.write(
                    "slot_0: type=Spectator occupied=true name=HOST ready=false\n"
                    "slot_2: type=Player occupied=true name=RED ready=false\n"
                )
            update = self.watcher._read_update(root)
        self.assertIn("spectator_lobby_returned", update)
        self.assertFalse(self.watcher._post_match_lobby_return_armed)

    def test_unmatched_tko_event_still_resolves_correct_winner(self):
        watcher = SpectatorLogWatcher(SimpleNamespace(
            spectator_fight_style_enabled=True,
            spectator_fight_style_min_attempts=1,
            spectator_fight_style_min_landed=1,
        ))
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                # The corner column is the receiver. Red is stopped, so blue won.
                stream.write("100.0\t64\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tRearHook\tTechnicalKnockout\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                # Deliberately outside matching tolerance.
                stream.write("98.0\tblue\tleft\tRearHook\n")
            watcher._last_round_state = "knockout"
            report = watcher._build_round_report_payload(
                damage_path, 2, ("BLUE", "RED"), force_final=True
            )

        self.assertEqual(report["winner"], "blue")
        self.assertEqual(report["resultMethod"], "TKO")
        self.assertEqual(report["matchResult"]["winner"], "blue")
        self.assertIn("fightStyle", report["blue"])
        self.assertIn("fightStyle", report["red"])

    def test_report_keeps_highest_damage_when_throw_match_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t82\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tRearHook\tHit\tChin\n")
            # Deliberately outside the 0.35-second matching tolerance.
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("98.0\tblue\tleft\tRearHook\n")
            self.watcher._last_round_state = "break"
            report = self.watcher._build_round_report_payload(damage_path, 1, ("BLUE", "RED"))

        self.assertEqual(report["blue"]["maxPunch"]["damage"], 82.0)

    def test_break_report_best_punch_comes_only_from_requested_archive_round(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            throws_path = os.path.join(root, "punches_thrown.txt")
            round_one_hit = {
                "time": 100.0, "attacker_side": "blue", "receiver_side": "red",
                "hand": "left", "punch": "RearHook", "damage": 92.0,
                "damage_type": "Hit", "weak_point": "Chin",
            }
            round_two_hit = {
                "time": 100.0, "attacker_side": "blue", "receiver_side": "red",
                "hand": "right", "punch": "Cross", "damage": 41.0,
                "damage_type": "Hit", "weak_point": "",
            }
            round_one_throw = {"time": 100.0, "side": "blue", "hand": "left", "punch": "RearHook"}
            round_two_throw = {"time": 100.0, "side": "blue", "hand": "right", "punch": "Cross"}
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t92\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tRearHook\tHit\tChin\n")
                stream.write("100.0\t41\t1.0\tred\tright\t.4\t.4\t0\t0\t0\tCross\tHit\t\n")
            with open(throws_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tRearHook\n")
                stream.write("100.0\tblue\tright\tCross\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,9,0,92,0,0\n")
                stream.write("2,10,9,0,41,0,0\n")

            archive = MatchLogArchive(os.path.join(root, "archive"))
            archive.start("round-local-best", ("BLUE", "RED"))
            archive.record_damage(1, [round_one_hit])
            archive.record_throws(1, [round_one_throw])
            archive.record_damage(2, [round_two_hit])
            archive.record_throws(2, [round_two_throw])
            self.watcher._match_archive = archive
            self.watcher._last_round_state = "break"

            report = self.watcher._build_round_report_payload(
                damage_path, 2, ("BLUE", "RED"), force_final=False
            )

        self.assertEqual(41.0, report["blue"]["maxPunch"]["damage"])
        self.assertEqual(1, report["blue"]["landed"])
        self.assertEqual(1, report["blue"]["thrown"])

    def test_break_report_analyzes_style_from_that_round_payload(self):
        watcher = SpectatorLogWatcher(SimpleNamespace(
            spectator_fight_style_enabled=True,
            spectator_fight_style_min_attempts=1,
            spectator_fight_style_min_landed=1,
        ))
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t36\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.1\tblue\tleft\tJab\n")
            watcher._last_round_state = "break"
            report = watcher._build_round_report_payload(
                damage_path, 1, ("BLUE", "RED"), force_final=False
            )

        self.assertFalse(report["isFinal"])
        self.assertIn("fightStyle", report["blue"])
        self.assertIn("fightStyle", report["red"])

    def test_live_sp_throw_reader_consumes_only_appended_rows(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "punches_thrown.txt")
            self.assertEqual(self.watcher._read_new_punches_thrown(path), [])
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("10.0\tblue\tleft\tJab\n")
            first = self.watcher._read_new_punches_thrown(path)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("9.5\tred\tright\tRearHook\n")
            second = self.watcher._read_new_punches_thrown(path)

        self.assertEqual([(x["side"], x["punch"]) for x in first], [("blue", "Jab")])
        self.assertEqual([(x["side"], x["punch"]) for x in second], [("red", "RearHook")])

    def test_live_sp_activity_emits_cumulative_cost_once(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "punches_thrown.txt")
            self.watcher._read_new_punches_thrown(path)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("10.0\tblue\tleft\tJab\n")
            first = {}
            self.watcher._update_live_sp_activity(root, first)
            second = {}
            self.watcher._update_live_sp_activity(root, second)

        # Default global SP activity scale is 60%, preserving the relative
        # per-punch costs while reducing total drain by the requested 40%.
        self.assertAlmostEqual(first["spectator_sp_activity_spent"]["blue"], 0.00108)
        self.assertNotIn("spectator_sp_activity_spent", second)

    def test_live_commentary_keeps_only_current_sentence(self):
        text = self.watcher._compact_live_commentary(
            "블루가 강하게 압박합니다. 이어서 긴 설명이 계속됩니다."
        )
        self.assertEqual(text, "블루가 강하게 압박합니다.")

    def test_live_line_pool_does_not_repeat_recent_sentence(self):
        first = self.watcher._live_line("first", ["문장 하나", "문장 둘"])
        second = self.watcher._live_line("first", ["문장 하나", "문장 둘"])
        third = self.watcher._live_line("first", ["문장 하나", "문장 둘"])

        self.assertIn(first, ("문장 하나", "문장 둘"))
        self.assertIn(second, ("문장 하나", "문장 둘"))
        self.assertNotEqual(first, second)
        self.assertEqual(third, "")

    def test_live_strong_hit_uses_configured_minimum_damage(self):
        self.watcher.cfg.spectator_commentary_enabled = True
        self.watcher.cfg.spectator_commentary_mode = "active"
        self.watcher.cfg.spectator_commentary_min_damage = 30.0
        with patch.object(self.watcher, "_live_commentary_name", return_value="선수"):
            text, role = self.watcher._build_fight_summary_commentary(
                [{
                    "time": 100.0,
                    "damage": 35.0,
                    "attacker_side": "blue",
                    "receiver_side": "red",
                    "punch": "Cross",
                }],
                [],
                "",
            )

        self.assertTrue(text)
        self.assertEqual(role, "analyst")

    def test_current_damage_layout_is_replay_parseable(self):
        parsed = self.watcher._parse_damage_event_parts([
            "176.71", "42.5", "1.2", "red", "left",
            "0.44", "0.35", "1.0", "2.0", "3.0",
            "RearHook", "Hit", "Chin",
        ])
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["attacker_side"], "blue")
        self.assertEqual(parsed["receiver_side"], "red")
        self.assertEqual(parsed["punch"], "RearHook")
        self.assertTrue(parsed["is_counter"])

    def test_new_cumulative_damage_layout_preserves_round_and_region(self):
        parsed = self.watcher._parse_damage_event_parts([
            "2", "91.25", "38.5", "1.00", "blue", "right",
            "0.46", "0.51", "1.0", "2.0", "3.0", "Cross", "Hit", "Head",
        ])
        self.assertEqual(parsed["round"], 2)
        self.assertEqual(parsed["attacker_side"], "red")
        self.assertEqual(parsed["damage"], 38.5)
        self.assertEqual(parsed["screen_x"], 0.46)
        self.assertEqual(parsed["hit_location"], "Head")
        self.assertEqual(parsed["weak_point"], "")
        self.assertEqual(
            self.watcher._parse_damage_event_parts([
                "2", "90.9", "44", "1.15", "red", "left", ".4", ".5",
                "1", "2", "3", "LeadHook", "Hit", "Chin",
            ])["weak_point"], "Chin",
        )

    def test_new_cumulative_throws_keep_rounds(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "punches_thrown.txt")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("1\t100.00\tblue\tleft\tJab\n")
                stream.write("2\t99.80\tred\tright\tCross\n")
            throws = self.watcher._read_punches_thrown_file(path)
        self.assertEqual([(row["round"], row["side"]) for row in throws], [(1, "blue"), (2, "red")])
        self.assertEqual([len(rows) for rows in self.watcher._events_by_source_round(throws, 2).values()], [1, 1])

    def test_new_damage_file_updates_round_damage_and_hit_effect(self):
        with tempfile.TemporaryDirectory() as root:
            match_dir = os.path.join(root, "match")
            os.mkdir(match_dir)
            path = os.path.join(match_dir, "damage_events.txt")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("1\t100.0\t20\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tHead\n")
            self.watcher._last_fight_round_no = 2
            self.watcher._read_damage_update(path)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("2\t99.0\t40\t1.0\tblue\tright\t.6\t.5\t1\t2\t3\tCross\tHit\tChin\n")
            update = self.watcher._read_damage_update(path)
        self.assertEqual(update["blue_damage_dealt"], 20)
        self.assertEqual(update["red_damage_dealt"], 40)
        self.assertEqual(update["blue_round_damage_dealt"], 0)
        self.assertEqual(update["red_round_damage_dealt"], 40)
        self.assertTrue(update.get("spectator_hit_effect_events"))

    def test_round_damage_resets_when_round_changes_without_new_hit(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "damage_events.txt")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("1\t100\t35\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tChin\n")
            self.watcher._last_fight_round_no = 1
            first = self.watcher._read_damage_update(path)
            self.watcher._last_fight_round_no = 2
            second = self.watcher._read_damage_update(path)
        self.assertEqual(first["blue_round_damage_dealt"], 35)
        self.assertEqual(second["blue_round_damage_dealt"], 0)
        self.assertEqual(second["blue_damage_dealt"], 35)

    def test_new_round_report_excludes_prior_round_hits(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "damage_events.txt")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("1\t100\t70\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tChin\n")
                stream.write("2\t100\t35\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("1\t100\tblue\tleft\tJab\n")
                stream.write("2\t100\tblue\tleft\tJab\n")
            self.watcher._last_round_state = "break"
            report = self.watcher._build_round_report_payload(path, 2, ("BLUE", "RED"))
        self.assertEqual(report["blue"]["maxPunch"]["damage"], 35)

    def test_old_portrait_is_not_reused_for_new_player(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "portrait.png")
            name_path = os.path.join(root, "name.txt")
            with open(path, "wb") as stream:
                stream.write(b"placeholder")
            with open(name_path, "w", encoding="utf-8") as stream:
                stream.write("NEW_PLAYER")
            os.utime(path, (100, 100))
            os.utime(name_path, (200, 200))
            with patch("spectator_log_watcher._safe_cv2_imread") as read_image:
                self.assertEqual(self.watcher._read_image_if_changed("blue", path), (False, None))
                read_image.assert_not_called()
                os.utime(path, (201, 201))
                read_image.return_value = SimpleNamespace(size=1)
                changed, image = self.watcher._read_image_if_changed("blue", path)
                self.assertTrue(changed)
                self.assertEqual(image.size, 1)

    def test_cumulative_log_over_600_rows_does_not_replay_old_hit_effects(self):
        with tempfile.TemporaryDirectory() as root:
            match_dir = os.path.join(root, "match")
            os.mkdir(match_dir)
            path = os.path.join(match_dir, "damage_events.txt")
            with open(path, "w", encoding="utf-8") as stream:
                for i in range(601):
                    stream.write(f"1\t{i / 100:.2f}\t30\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tHead\n")
            self.watcher._last_fight_round_no = 1
            self.watcher._read_damage_update(path)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("1\t10.00\t35\t1.0\tred\tright\t.4\t.5\t1\t2\t3\tCross\tHit\tChin\n")
            update = self.watcher._read_damage_update(path)
        self.assertEqual(len(update.get("spectator_hit_effect_events") or []), 1)

    def test_report_exposes_score_power55_and_max_combo(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t60\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tRearHook\tHit\tChin\n")
                stream.write("99.5\t20\t1.0\tred\tright\t.4\t.4\t0\t0\t0\tCross\tHit\t\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tRearHook\n")
                stream.write("99.5\tblue\tright\tCross\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score\n1,10,9\n")
            self.watcher._last_round_state = "break"
            report = self.watcher._build_round_report_payload(damage_path, 1, ("BLUE", "RED"))

        self.assertEqual(report["blue"]["officialScore"], 10)
        self.assertEqual(report["blue"]["powerHits55"], 1)
        self.assertEqual(report["blue"]["maxComboHits"], 2)
        self.assertEqual(report["blue"]["maxComboDamage"], 80)

    def test_final_report_uses_all_round_event_rows_without_cross_round_combo(self):
        """A final card must retain prior-round combos, but a break resets them."""
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("100.0\t40\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
                stream.write("99.5\t45\t1.0\tred\tright\t.4\t.4\t0\t0\t0\tCross\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("100.0\tblue\tleft\tJab\n99.5\tblue\tright\tCross\n")
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,9,10,9,700,1000,0,1\n")
                stream.write("2,9,10,19,19,1300,900,1,2\n")
            with open(os.path.join(root, "winner.txt"), "w", encoding="utf-8") as stream:
                stream.write("blue\tBLUE")

            round_one = self.watcher._new_scorecard_round(1)
            round_one["events"] = 2
            round_one["event_rows"] = [
                {"attacker_side": "blue", "receiver_side": "red", "punch": "Jab", "damage": 30.0, "time": 100.0},
                {"attacker_side": "blue", "receiver_side": "red", "punch": "Cross", "damage": 35.0, "time": 99.5},
            ]
            round_two = self.watcher._new_scorecard_round(2)
            round_two["events"] = 2
            round_two["event_rows"] = [
                {"attacker_side": "blue", "receiver_side": "red", "punch": "Jab", "damage": 40.0, "time": 100.0},
                {"attacker_side": "blue", "receiver_side": "red", "punch": "Cross", "damage": 45.0, "time": 99.5},
            ]
            self.watcher._scorecard_rounds = {1: round_one, 2: round_two}
            self.watcher._last_round_state = "results"
            report = self.watcher._build_round_report_payload(
                damage_path, 2, ("BLUE", "RED"), force_final=True
            )

        self.assertTrue(report["isFinal"])
        self.assertEqual(report["blue"]["maxComboHits"], 2)
        self.assertEqual(report["blue"]["maxComboDamage"], 85)
        self.assertEqual(report["blue"]["damage"], 1900)
        self.assertEqual(report["red"]["damage"], 2000)
        self.assertEqual(report["blue"]["knockdowns"], 3)
        self.assertEqual(report["red"]["knockdowns"], 1)

    def test_final_style_metrics_keep_round_boundaries_and_archived_trend(self):
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("0.6\t40\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n")
            with open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8") as stream:
                stream.write("0.6\tblue\tleft\tJab\n")
            with open(os.path.join(root, "winner.txt"), "w", encoding="utf-8") as stream:
                stream.write("blue\tBLUE\n")

            round_one = self.watcher._new_scorecard_round(1)
            round_one["events"] = 1
            round_one["event_rows"] = [{
                "attacker_side": "red",
                "receiver_side": "blue",
                "punch": "Jab",
                "damage": 5.0,
                "time": 0.5,
            }]
            round_one["dealt"]["red"] = 5.0
            round_one["landed"]["red"] = 1

            round_two = self.watcher._new_scorecard_round(2)
            round_two["events"] = 1
            round_two["event_rows"] = [{
                "attacker_side": "blue",
                "receiver_side": "red",
                "punch": "Jab",
                "damage": 40.0,
                "time": 0.6,
                "_central_event": {"counter": True, "tags": ["hit", "counter"]},
                "event_tags": ["hit", "counter"],
                "event_primary": "hit",
            }]
            round_two["dealt"]["blue"] = 40.0
            round_two["landed"]["blue"] = 1
            round_two["counters_for"]["blue"] = 1

            self.watcher._scorecard_rounds = {1: round_one, 2: round_two}
            self.watcher._last_round_state = "results"
            report = self.watcher._build_round_report_payload(
                damage_path, 2, ("BLUE", "RED"), force_final=True
            )

        self.assertEqual(report["blue"]["defenseMetrics"]["returnCounters"], 0)
        self.assertEqual(report["blue"]["roundTrend"]["earlyDamage"], 0.0)
        self.assertEqual(report["blue"]["roundTrend"]["lateDamage"], 40.0)
        self.assertEqual(report["red"]["roundTrend"]["earlyDamage"], 5.0)
        self.assertEqual(report["red"]["roundTrend"]["lateDamage"], 0.0)

    def test_final_report_reads_frozen_archive_not_mutated_live_files(self):
        with tempfile.TemporaryDirectory() as root:
            match_dir = os.path.join(root, "live", "match")
            os.makedirs(match_dir, exist_ok=True)
            damage_path = os.path.join(match_dir, "damage_events.txt")
            throws_path = os.path.join(match_dir, "punches_thrown.txt")
            scores_path = os.path.join(match_dir, "scores.csv")
            winner_path = os.path.join(match_dir, "winner.txt")

            archived_events = [
                {"time": 100.0, "attacker_side": "blue", "receiver_side": "red", "hand": "left", "damage": 30.0, "punch": "Jab", "damage_type": "Hit"},
                {"time": 99.5, "attacker_side": "blue", "receiver_side": "red", "hand": "right", "damage": 50.0, "punch": "Cross", "damage_type": "Hit"},
            ]
            archived_throws = [
                {"time": 100.0, "side": "blue", "hand": "left", "punch": "Jab"},
                {"time": 99.5, "side": "blue", "hand": "right", "punch": "Cross"},
            ]
            with open(scores_path, "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,9,10,9,0,80,0,0\n")
            with open(winner_path, "w", encoding="utf-8") as stream:
                stream.write("blue\tBLUE\n")

            archive = MatchLogArchive(os.path.join(root, "archive"))
            archive.start("archive-only", ("BLUE", "RED"))
            archive.record_damage(1, archived_events)
            archive.record_throws(1, archived_throws)
            archive.snapshot_scores(1, scores_path, final=True)
            archive.snapshot_vitals(
                1,
                {
                    "blue": {"long": 20.0, "hp_ratio": 0.8},
                    "red": {"long": 45.0, "hp_ratio": 0.55},
                },
                final=True,
            )
            archive.snapshot_winner(winner_path)
            self.watcher._match_archive = archive
            self.watcher._match_session_id = "archive-only"
            self.watcher._last_round_state = "results"

            # These rolling files represent a cleared/new lobby and must have
            # no influence on the completed match report.
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("1.0\t99\t1.0\tblue\tleft\t.4\t.4\t0\t0\t0\tHook\tHit\tChin\n")
            with open(throws_path, "w", encoding="utf-8") as stream:
                stream.write("1.0\tred\tleft\tHook\n")
            with open(scores_path, "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score\n1,0,10\n")
            with open(winner_path, "w", encoding="utf-8") as stream:
                stream.write("red\tRED\n")

            report = self.watcher._build_round_report_payload(
                damage_path, 1, ("BLUE", "RED"), force_final=True
            )

        self.assertEqual(report["winner"], "blue")
        self.assertEqual(report["blue"]["damage"], 80)
        self.assertEqual(report["blue"]["landed"], 2)
        self.assertEqual(report["blue"]["thrown"], 2)
        self.assertEqual(report["blue"]["maxComboHits"], 2)
        self.assertEqual(report["blue"]["maxComboDamage"], 80)
        self.assertEqual(report["blue"]["averageDamage"], 40.0)
        self.assertEqual(report["blue"]["healthPct"], 80)
        self.assertEqual(report["red"]["healthPct"], 55)

    def test_terminal_result_without_live_events_still_builds_report(self):
        """A resignation may clear the live event files before Results arrives."""
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            open(damage_path, "w", encoding="utf-8").close()
            open(os.path.join(root, "punches_thrown.txt"), "w", encoding="utf-8").close()
            with open(os.path.join(root, "scores.csv"), "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total\n")
                stream.write("3,9,10,28,30\n")
            with open(os.path.join(root, "winner.txt"), "w", encoding="utf-8") as stream:
                stream.write("red\tRED\n")
            self.watcher._last_round_state = "results"
            report = self.watcher._build_round_report_payload(
                damage_path, 3, ("BLUE", "RED"), force_final=False
            )

        self.assertEqual(report["round"], 3)
        self.assertEqual(report["winner"], "red")
        self.assertEqual(report["red"]["officialScore"], 10)


if __name__ == "__main__":
    unittest.main()
