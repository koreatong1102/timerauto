import copy
import unittest

from commentary_reports import build_report_narration


def report():
    return {"round": 2,
            "blue": {"name": "통", "landed": 50, "damage": 900, "counterHits": 12,
                     "maxComboHits": 4, "maxComboDamage": 110, "knockdowns": 0},
            "red": {"name": "현선호", "landed": 30, "damage": 1200, "counterHits": 3,
                    "maxComboHits": 3, "maxComboDamage": 140, "knockdowns": 0}}


class ReportNarrationTests(unittest.TestCase):
    def test_volume_damage_split_and_both_combos_are_independent(self):
        data = report()
        before = copy.deepcopy(data)
        text = build_report_narration(data)
        for value in ("50번", "30번", "900", "1200", "12번", "3번", "4연타에 110", "3연타에 140"):
            self.assertIn(value, text)
        self.assertIn("많이 맞힌 쪽과 더 아프게 때린 쪽이 달랐", text)
        self.assertNotIn("통, 승리", text)
        self.assertEqual(before, data)

    def test_final_result_is_not_inferred_from_damage_or_missing_method(self):
        data = report()
        data["winner"] = "blue"
        text = build_report_narration(data, final=True)
        self.assertIn("통, 승리", text)
        self.assertNotIn("판정승", text)
        self.assertNotIn("다음 라운드", text)
        self.assertIn("1200", text)

    def test_forfeit_and_tko_are_not_called_decisions(self):
        for method, expected in (("forfeit", "기권승"), ("TKO", "TKO승"), ("decision", "판정승")):
            text = build_report_narration({**report(), "winner": "red", "resultMethod": method}, final=True)
            self.assertIn("현선호, " + expected, text)

    def test_round_scope_never_uses_full_scorecard_trajectory(self):
        data = report()
        data["officialScorecard"] = {"rounds": [
            {"round": 1, "blue_score": 10, "red_score": 9},
            {"round": 2, "blue_score": 8, "red_score": 10}]}
        self.assertNotIn("1번 바뀌", build_report_narration(data))
        self.assertIn("1번 바뀌", build_report_narration(data, final=True))
        self.assertNotIn("전술을 바꾸", build_report_narration(data, final=True))

    def test_weak_point_is_attacker_hit_target_not_own_received_location(self):
        data = {"round": 1, "blue": {"name": "통", "landed": 18,
                "weakHitAll": [{"label": "왼쪽 눈", "count": 12}],
                "weakReceivedAll": [{"label": "간", "count": 50}]},
                "red": {"name": "현선호", "landed": 10}}
        text = build_report_narration(data)
        self.assertIn("통 쪽은 왼쪽 눈 적중이 12번", text)
        self.assertNotIn("50번", text)
        self.assertNotIn("실제체력 안정", text)

    def test_no_missing_accuracy_or_combo_is_fabricated_as_zero(self):
        data = {"blue": {"name": "통", "maxComboHits": 5}, "red": {"name": "현선호"}}
        text = build_report_narration(data)
        self.assertIn("통 5연타", text)
        self.assertNotIn("현선호 0", text)
        self.assertNotIn("적중률", text)
        self.assertNotIn("공식 데미지", text)

    def test_invalid_accuracy_and_empty_report_do_not_make_claims(self):
        data = report()
        for side in ("blue", "red"):
            data[side].update(accuracy=90, accuracyValid=False, thrown=20)
        self.assertNotIn("적중률", build_report_narration(data))
        self.assertEqual(build_report_narration({}), "")

    def test_profanity_control_and_verified_callback_are_preserved(self):
        data = report()
        for side in ("blue", "red"):
            data[side].pop("damage")
        self.assertIn("씨발", build_report_narration(data, swearing="strong"))
        self.assertNotIn("씨발", build_report_narration(data, swearing="light"))
        callback = "아까 허락 이야기했죠. 통, 카운터 12번입니다."
        self.assertIn(callback, build_report_narration(data, callback=callback))

