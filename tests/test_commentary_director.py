import unittest

from commentary_director import CommentaryCandidate, CommentaryDirector


class CommentaryDirectorTests(unittest.TestCase):
    def test_urgent_event_beats_combo(self):
        director = CommentaryDirector()
        decision = director.choose_live([
            CommentaryCandidate("좋은 콤보입니다.", "analyst", "combo", 78, urgent=True),
            CommentaryCandidate("레드, 크게 흔들립니다.", "caster", "stun", 96, urgent=True),
        ], cooldown_sec=6.0, now=10.0)
        self.assertEqual(decision.candidate.category, "stun")

    def test_counter_and_combo_are_merged_into_one_line(self):
        director = CommentaryDirector()
        decision = director.choose_live([
            CommentaryCandidate("카운터가 정확합니다.", "analyst", "counter", 84, key="counter-1", urgent=True, attacker_side="blue", attacker_name="진혁"),
            CommentaryCandidate("콤보가 좋습니다.", "analyst", "combo", 78, key="combo-1", urgent=True, attacker_side="blue", attacker_name="진혁"),
        ], cooldown_sec=6.0, now=20.0)
        self.assertEqual(decision.candidate.category, "counter_combo")
        self.assertEqual(decision.candidate.text, "진혁, 카운터 뒤에 연타까지 연결합니다.")

    def test_counter_respects_user_global_cooldown(self):
        director = CommentaryDirector()
        first = director.choose_live([CommentaryCandidate("압박이 이어집니다.", "analyst", "pressure", 58)], cooldown_sec=6.0, now=10.0)
        second = director.choose_live([CommentaryCandidate("카운터가 정확합니다.", "analyst", "counter", 84, urgent=True)], cooldown_sec=6.0, now=12.0)
        self.assertIsNotNone(first.candidate)
        self.assertIsNone(second.candidate)
        self.assertIn("counter:global_cooldown", second.suppressed)

    def test_answer_back_is_detected_from_adjacent_exchange(self):
        director = CommentaryDirector()
        candidate = director.observe_events(1, [
            {"time": 70.0, "damage": 32, "attacker_side": "red", "receiver_side": "blue", "punch": "Hook"},
            {"time": 69.4, "damage": 35, "attacker_side": "blue", "receiver_side": "red", "punch": "Straight"},
        ], {"blue": "진혁", "red": "알버"})
        self.assertEqual(candidate.category, "answer_back")
        self.assertIn("곧바로 받아칩니다", candidate.text)

    def test_round_leader_change_creates_adaptation_line(self):
        director = CommentaryDirector()
        names = {"blue": "블루 선수", "red": "레드 선수"}
        self.assertEqual(director.record_round(1, {"leader": "blue", "damage": {"blue": 100, "red": 60}}, names), "")
        second = director.record_round(2, {"leader": "red", "damage": {"blue": 70, "red": 130}}, names)
        self.assertIn("레드 선수", second)

    def test_exact_noncritical_sentence_does_not_repeat_after_global_cooldown(self):
        director = CommentaryDirector()
        line = CommentaryCandidate(
            "이번 타격은 충격이 큽니다.",
            "analyst",
            "event_analysis",
            58,
            key="event-1",
        )
        first = director.choose_live([line], cooldown_sec=6.0, now=100.0)
        repeated = director.choose_live([
            CommentaryCandidate(
                line.text,
                line.role,
                line.category,
                line.priority,
                key="event-2",
            )
        ], cooldown_sec=6.0, now=108.0)
        later = director.choose_live([
            CommentaryCandidate(
                line.text,
                line.role,
                line.category,
                line.priority,
                key="event-3",
            )
        ], cooldown_sec=6.0, now=146.0)

        self.assertIsNotNone(first.candidate)
        self.assertIsNone(repeated.candidate)
        self.assertIn("event_analysis:text_duplicate", repeated.suppressed)
        self.assertIsNotNone(later.candidate)

    def test_same_countdown_event_in_next_round_is_not_discarded(self):
        director = CommentaryDirector()
        event = {
            "time": 70.0,
            "damage": 32,
            "attacker_side": "blue",
            "receiver_side": "red",
            "punch": "Hook",
        }
        director.observe_events(1, [event], {"blue": "블루", "red": "레드"})
        director.observe_events(2, [event], {"blue": "블루", "red": "레드"})

        self.assertEqual(director._rounds[1]["landed"]["blue"], 1)
        self.assertEqual(director._rounds[2]["landed"]["blue"], 1)


if __name__ == "__main__":
    unittest.main()
