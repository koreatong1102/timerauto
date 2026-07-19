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
