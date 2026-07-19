from types import SimpleNamespace
import unittest

from event_engine import FightEventEngine


def config():
    return SimpleNamespace(
        event_combo_min_damage=15.0,
        event_combo_window_sec=0.8,
        event_combo_break_damage=20.0,
        event_heavy_damage=50.0,
        event_signature_damage=60.0,
        event_counter_min_damage=40.0,
        event_combo_emphasis_hits=5,
    )


class FightEventEngineTests(unittest.TestCase):
    def test_signature_requires_damage_and_technical_context(self):
        engine = FightEventEngine(config())
        plain = engine.classify({"time": 1, "attacker_side": "blue", "receiver_side": "red", "damage": 65})
        counter = engine.classify({"time": 2, "attacker_side": "blue", "receiver_side": "red", "damage": 65, "is_counter": True})
        self.assertIn("heavy", plain["tags"])
        self.assertNotIn("signature", plain["tags"])
        self.assertIn("signature", counter["tags"])

    def test_combo_requires_same_target_inside_window(self):
        engine = FightEventEngine(config())
        rows = engine.classify_many([
            {"time": 10.0, "attacker_side": "blue", "receiver_side": "red", "damage": 20},
            {"time": 10.5, "attacker_side": "blue", "receiver_side": "red", "damage": 20},
            {"time": 11.5, "attacker_side": "blue", "receiver_side": "red", "damage": 20},
        ])
        self.assertEqual(rows[1]["combo_hits"], 2)
        self.assertIn("combo", rows[1]["tags"])
        self.assertEqual(rows[2]["combo_hits"], 1)

    def test_game_declared_down_is_always_decisive(self):
        engine = FightEventEngine(config())
        row = engine.classify({"time": 1, "attacker_side": "red", "receiver_side": "blue", "damage": 38, "effect_kind": "knockdown"})
        self.assertEqual(row["primary"], "decisive")
        self.assertIn("knockdown", row["tags"])

