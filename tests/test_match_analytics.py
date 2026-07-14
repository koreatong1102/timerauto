import unittest

from match_analytics import analyze_fight_style, build_match_commentary, detect_stoppage, resolve_match_result


class MatchAnalyticsTests(unittest.TestCase):
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
                "thrown": 45,
                "landed": 18,
                "damage": 720,
                "averageDamage": 40,
                "bigHits": 6,
                "powerHits55": 3,
                "knockdowns": 1,
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

        self.assertEqual(style["label"], "정밀 타격가")

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

        self.assertEqual(style["label"], "바디 헌터")

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
