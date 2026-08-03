import unittest

from match_analytics import (
    _josa,
    analyze_fight_style,
    analyze_round_approach,
    build_match_commentary,
    detect_stoppage,
    resolve_match_result,
)


class MatchAnalyticsTests(unittest.TestCase):
    def test_round_approach_keeps_knockdown_as_result_not_style(self):
        blue = {
            "thrown": 130,
            "landed": 67,
            "accuracy": 52,
            "counterHits": 17,
            "maxComboHits": 3,
            "knockdowns": 1,
            "stuns": 0,
            "bigHits": 8,
            "powerHits55": 2,
            "staminaPct": 43,
            "landedBreakdown": [
                {"key": "jab", "count": 21},
                {"key": "cross", "count": 27},
                {"key": "hook", "count": 14},
            ],
        }
        red = {
            "thrown": 164,
            "landed": 71,
            "accuracy": 43,
            "counterHits": 25,
            "maxComboHits": 3,
            "knockdowns": 1,
            "stuns": 0,
            "bigHits": 9,
            "powerHits55": 1,
            "staminaPct": 26,
            "landedBreakdown": [
                {"key": "jab", "count": 33},
                {"key": "cross", "count": 27},
                {"key": "hook", "count": 10},
            ],
        }

        blue_round = analyze_round_approach(blue, red)
        red_round = analyze_round_approach(red, blue)

        self.assertNotEqual(blue_round["label"], "다운 마무리")
        self.assertNotEqual(red_round["label"], "다운 마무리")
        self.assertIn("다운 1회", blue_round["chips"])
        self.assertIn("다운 1회", red_round["chips"])
        self.assertIn("실제체력 부담 43%", blue_round["chips"])
        self.assertIn("실제체력 위험 26%", red_round["chips"])
        self.assertTrue(blue_round["roundApproach"])
        self.assertTrue(red_round["roundApproach"])

    def test_round_approach_separates_method_from_result(self):
        attacker = {
            "thrown": 113,
            "landed": 66,
            "accuracy": 58,
            "counterHits": 15,
            "maxComboHits": 5,
            "knockdowns": 2,
            "stuns": 1,
            "bigHits": 10,
            "powerHits55": 3,
            "staminaPct": 78,
            "landedBreakdown": [{"key": "hook", "count": 23}],
        }
        opponent = {
            "thrown": 116,
            "landed": 70,
            "accuracy": 60,
            "counterHits": 20,
            "maxComboHits": 3,
            "knockdowns": 1,
            "stuns": 0,
            "bigHits": 7,
            "powerHits55": 1,
            "landedBreakdown": [{"key": "jab", "count": 32}],
        }

        result = analyze_round_approach(attacker, opponent)

        self.assertNotIn("다운", result["label"])
        self.assertEqual(result["roundResultLabel"], "다운 우세 2:1")
        self.assertIn("실제체력 안정 78%", result["chips"])
        self.assertEqual(result["tier"], "")

    def test_commentary_uses_correct_korean_particles_for_display_names(self):
        self.assertEqual(_josa("통", "이/가"), "통이")
        self.assertEqual(_josa("통", "은/는"), "통은")
        self.assertEqual(_josa("가나", "이/가"), "가나가")
        self.assertEqual(_josa("가나", "은/는"), "가나는")

        text = build_match_commentary({
            "winner": "blue",
            "resultMethod": "KO",
            "blue": {"name": "통", "fightStyle": {"label": "카운터 마스터"}},
            "red": {"name": "가나", "fightStyle": {"label": "균형형 파이터"}},
        })
        self.assertIn("통이 결정적인 한 방", text)
        self.assertIn("통은 결정적인 교전", text)
        self.assertIn("가나는 균형형 파이터", text)

    def test_style_keeps_roles_distinct_and_limits_total_styles(self):
        style = analyze_fight_style(
            {
                "thrown": 96,
                "landed": 48,
                "accuracy": 62,
                "averageDamage": 41,
                "bigHits": 12,
                "powerHits55": 4,
                "knockdowns": 2,
                "counterHits": 14,
                "maxComboHits": 5,
                "weakHitAll": [
                    {"label": "턱", "count": 8},
                    {"label": "관자놀이", "count": 4},
                ],
                "landedBreakdown": [{"key": "hook", "count": 24}],
                "defenseMetrics": {
                    "opponentMisses": 31,
                    "lowDamageDefenses": 12,
                    "returnCounters": 5,
                    "returnPowerHits": 2,
                    "heavyReceived": 1,
                },
                "roundTrend": {"earlyDamage": 100, "lateDamage": 180, "earlyLanded": 8, "lateLanded": 12},
            },
            {"thrown": 60, "landed": 24},
            min_attempts=20,
            min_landed=10,
        )

        labels = [style.get("label")] + list(style.get("chips") or [])
        self.assertLessEqual(len(labels), 5)
        self.assertEqual(len(set(labels)), len(labels))
        self.assertRegex(str(style.get("tier") or ""), r"^레벨 (?:10|[1-9])$")
        self.assertGreaterEqual(int(style.get("level") or 0), 1)
        self.assertLessEqual(int(style.get("level") or 0), 10)
        self.assertIn("헤드 헌터", style.get("chips") or [])

    def test_style_can_add_one_defensive_chip_from_inferred_events(self):
        style = analyze_fight_style(
            {
                "thrown": 180,
                "landed": 120,
                "accuracy": 50,
                "counterHits": 40,
                "defenseMetrics": {
                    "opponentMisses": 12,
                    "lowDamageDefenses": 4,
                    "returnCounters": 5,
                    "returnPowerHits": 2,
                },
            },
            {"thrown": 180, "landed": 90},
            min_attempts=20,
            min_landed=10,
        )

        self.assertEqual(style["label"], "카운터 마스터")
        self.assertIn("유도 반격형", style.get("chips") or [])

    def test_style_level_distinguishes_a_plain_sample_from_an_elite_counter_sample(self):
        plain = analyze_fight_style(
            {"thrown": 24, "landed": 11, "accuracy": 46, "averageDamage": 18},
            {"thrown": 24, "landed": 10},
            min_attempts=20,
            min_landed=10,
        )
        elite = analyze_fight_style(
            {"thrown": 72, "landed": 35, "accuracy": 62, "averageDamage": 31,
             "counterHits": 40, "maxComboHits": 5},
            {"thrown": 180, "landed": 90},
            min_attempts=20,
            min_landed=10,
        )

        self.assertLess(int(plain["level"]), int(elite["level"]))
        self.assertEqual(elite["label"], "카운터 마스터")

    def test_counter_mastery_uses_rate_and_sustain_not_early_caps(self):
        """The archived six-round 121:69 shape must not collapse to one tier."""
        tong = {
            "roundsObserved": 6, "thrown": 575, "landed": 319,
            "accuracy": 55, "counterHits": 121, "maxComboHits": 3,
        }
        hyun = {
            "roundsObserved": 6, "thrown": 507, "landed": 207,
            "accuracy": 41, "counterHits": 69, "maxComboHits": 3,
        }
        tong_style = analyze_fight_style(tong, hyun)
        hyun_style = analyze_fight_style(hyun, tong)
        counter_master = "\uce74\uc6b4\ud130 \ub9c8\uc2a4\ud130"
        self.assertEqual(tong_style["label"], counter_master)
        self.assertEqual(hyun_style["label"], counter_master)
        self.assertEqual(tong_style["level"], 8)
        self.assertEqual(hyun_style["level"], 5)
        self.assertGreaterEqual(tong_style["level"] - hyun_style["level"], 3)
        self.assertEqual(tong_style["levelBreakdown"]["roundsObserved"], 6)

    def test_actual_health_creates_operation_medal_and_affects_level(self):
        protected = analyze_fight_style(
            {
                "thrown": 180, "landed": 92, "accuracy": 61, "counterHits": 24,
                "maxComboHits": 4, "knockdowns": 1,
                "healthPct": 40, "staminaPct": 82, "isWinner": True,
            },
            {
                "thrown": 120, "landed": 64, "accuracy": 53,
                "healthPct": 70, "staminaPct": 55,
            },
            min_attempts=20,
            min_landed=10,
        )
        worn_down = analyze_fight_style(
            {
                "thrown": 180, "landed": 92, "accuracy": 61, "counterHits": 24,
                "maxComboHits": 4, "knockdowns": 1,
                "healthPct": 40, "staminaPct": 42, "isWinner": True,
            },
            {
                "thrown": 120, "landed": 64, "accuracy": 53,
                "healthPct": 70, "staminaPct": 55,
            },
            min_attempts=20,
            min_landed=10,
        )
        self.assertEqual(protected["operationMedal"]["label"], "THE READ")
        self.assertEqual(int(protected["level"]), int(worn_down["level"]))
        self.assertGreater(int(protected["performanceLevel"]), int(worn_down["performanceLevel"]))
        self.assertEqual(
            set(protected["levelBreakdown"]),
            {"styleStrength", "mastery", "roundsObserved", "components"},
        )
        self.assertEqual(
            set(protected["performanceBreakdown"]),
            {"technique", "result", "operation", "damage"},
        )

    def test_direct_tko_event_resolves_attacker_as_winner(self):
        stoppage = detect_stoppage([
            {
                "attacker_side": "blue",
                "receiver_side": "red",
                "damage_type": "TechnicalKnockout",
                "time": 12.5,
            }
        ], round_no=2)

        result = resolve_match_result({}, stoppage, "knockout", blue_total=8, red_total=20)

        self.assertEqual(stoppage["winner"], "blue")
        self.assertEqual(result["winner"], "blue")
        self.assertEqual(result["method"], "TKO")

    def test_official_winner_keeps_matching_stoppage_method(self):
        result = resolve_match_result(
            {"side": "red"},
            {"winner": "red", "loser": "blue", "method": "TKO", "source": "damage_events"},
            "knockout",
            blue_total=30,
            red_total=10,
        )

        self.assertEqual(result["winner"], "red")
        self.assertEqual(result["method"], "TKO")
        self.assertEqual(result["source"], "winner.txt+stoppage")

    def test_point_totals_do_not_guess_winner_during_knockout(self):
        result = resolve_match_result({}, {}, "knockout", blue_total=30, red_total=10)
        self.assertEqual(result["winner"], "")
        self.assertEqual(result["source"], "pending")

    def test_style_names_and_descriptions_are_korean(self):
        style = analyze_fight_style(
            {
                "thrown": 220,
                "landed": 90,
                "damage": 720,
                "averageDamage": 40,
                "bigHits": 24,
                "powerHits55": 10,
                "knockdowns": 2,
                "landedBreakdown": [],
            },
            {},
            min_attempts=20,
            min_landed=10,
        )

        self.assertEqual(style["label"], "슬러거")
        self.assertIn("한 방", style["signature"])
        self.assertIn("유형입니다", style["description"])

    def test_official_score_damage_does_not_force_slugger_style(self):
        style = analyze_fight_style(
            {
                "thrown": 30,
                "landed": 21,
                "accuracy": 70,
                "damage": 3200,
                "landedDamage": 420,
                "averageDamage": 20,
                "bigHits": 1,
                "powerHits55": 0,
                "knockdowns": 0,
                "counterHits": 1,
                "landedBreakdown": [{"key": "cross", "count": 21}],
            },
            {},
            min_attempts=20,
            min_landed=10,
        )

        self.assertEqual(style["label"], "균형형 파이터")

    def test_style_uses_own_attack_target_payload(self):
        style = analyze_fight_style(
            {
                "thrown": 35,
                "landed": 16,
                "accuracy": 46,
                "weakHitAll": [
                    {"label": "명치", "count": 5},
                    {"label": "간", "count": 4},
                    {"label": "턱", "count": 1},
                ],
                "landedBreakdown": [{"key": "hook", "count": 16}],
            },
            {"weakReceivedAll": [{"label": "턱", "count": 20}]},
            min_attempts=20,
            min_landed=10,
        )

        self.assertIn("바디 헌터", style.get("chips") or [])

    def test_match_commentary_interprets_styles_instead_of_reading_table(self):
        text = build_match_commentary({
            "winner": "blue",
            "resultMethod": "TKO",
            "blue": {
                "name": "진혁",
                "damage": 920,
                "knockdowns": 2,
                "counterHits": 4,
                "fightStyle": {"label": "슬러거"},
            },
            "red": {
                "name": "아버",
                "damage": 610,
                "knockdowns": 0,
                "counterHits": 1,
                "fightStyle": {"label": "카운터 마스터"},
            },
        })

        self.assertIn("테크니컬 녹아웃", text)
        self.assertIn("슬러거", text)
        self.assertIn("카운터 마스터", text)
        self.assertNotIn("전체 기록은", text)

    def test_match_commentary_describes_comeback_from_official_rounds(self):
        text = build_match_commentary({
            "winner": "blue",
            "resultMethod": "판정",
            "officialScorecard": {"rounds": [
                {"round": 1, "blue_score": 8, "red_score": 10, "blue_damage_taken": 180, "red_damage_taken": 120},
                {"round": 2, "blue_score": 10, "red_score": 8, "blue_damage_taken": 110, "red_damage_taken": 210},
                {"round": 3, "blue_score": 10, "red_score": 9, "blue_damage_taken": 130, "red_damage_taken": 190},
            ]},
            "blue": {"name": "진혁", "damage": 520, "counterHits": 4, "fightStyle": {"label": "카운터 마스터", "confidence": 80}},
            "red": {"name": "아버", "damage": 420, "counterHits": 1, "fightStyle": {"label": "압박형 파이터", "confidence": 75}},
        })

        self.assertIn("흐름을 뒤집었습니다", text)
        self.assertIn("카운터 타이밍", text)


if __name__ == "__main__":
    unittest.main()
