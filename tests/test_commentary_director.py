import unittest

from commentary_director import CommentaryCandidate, CommentaryDirector


class CommentaryDirectorTests(unittest.TestCase):
    def test_urgent_event_beats_combo(self):
        director = CommentaryDirector()
        decision = director.choose_live([
            CommentaryCandidate("좋은 콤보입니다.", "analyst", "combo", 78, urgent=True),
            CommentaryCandidate("레드, 크게 흔들립니다!", "caster", "stun", 96, urgent=True),
        ], cooldown_sec=6.0, now=10.0)

        self.assertIsNotNone(decision.candidate)
        self.assertEqual(decision.candidate.category, "stun")

    def test_counter_and_combo_are_merged_into_one_line(self):
        director = CommentaryDirector()
        decision = director.choose_live([
            CommentaryCandidate(
                "카운터가 적중됩니다.", "analyst", "counter", 84,
                key="counter-1", urgent=True, attacker_side="blue", attacker_name="진혁",
            ),
            CommentaryCandidate(
                "좋은 콤보가 적중합니다.", "analyst", "combo", 78,
                key="combo-1", urgent=True, attacker_side="blue", attacker_name="진혁",
            ),
        ], cooldown_sec=6.0, now=20.0)

        self.assertEqual(decision.candidate.category, "counter_combo")
        self.assertEqual(decision.candidate.text, "진혁, 카운터로 연타를 연결합니다!")

    def test_answer_back_is_detected_from_adjacent_exchange(self):
        director = CommentaryDirector()
        candidate = director.observe_events(1, [
            {"time": 70.0, "damage": 32, "attacker_side": "red", "receiver_side": "blue", "punch": "Hook"},
            {"time": 69.4, "damage": 35, "attacker_side": "blue", "receiver_side": "red", "punch": "Straight"},
        ], {"blue": "진혁", "red": "아버"})

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.category, "answer_back")
        self.assertIn("곧바로 받아칩니다", candidate.text)

    def test_round_leader_change_creates_adaptation_line(self):
        director = CommentaryDirector()
        names = {"blue": "블루 선수", "red": "레드 선수"}
        first = director.record_round(1, {
            "leader": "blue", "damage": {"blue": 100, "red": 60},
            "top_punch": {"blue": "잽", "red": "훅"},
        }, names)
        second = director.record_round(2, {
            "leader": "red", "damage": {"blue": 70, "red": 130},
            "top_punch": {"blue": "잽", "red": "스트레이트"},
        }, names)

        self.assertEqual(first, "")
        self.assertIn("레드 선수 쪽이 흐름을 되찾", second)


if __name__ == "__main__":
    unittest.main()
