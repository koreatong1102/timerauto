import unittest

from commentary_demo import build_commentary_director_demo


class CommentaryDemoTests(unittest.TestCase):
    def test_demo_exercises_every_director_scenario(self):
        steps, checks = build_commentary_director_demo()

        self.assertTrue(checks)
        self.assertTrue(all(checks.values()), checks)
        categories = {str(step.get("category") or "") for step in steps}
        self.assertIn("counter_combo", categories)
        self.assertIn("stun", categories)
        self.assertIn("answer_back", categories)
        self.assertIn("momentum_flip", categories)
        self.assertIn("round_adaptation", categories)
        self.assertIn("match_narrative", categories)
        self.assertTrue(all(str(step.get("text") or "").strip() for step in steps))


if __name__ == "__main__":
    unittest.main()
