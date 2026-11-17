"""Authored corpus contracts independent of TTS, Qt or live fight judgment."""
import unittest

from commentary_material import scene_material, call_material


class CommentaryMaterialTests(unittest.TestCase):
    def test_corpus_is_broad_but_not_fragment_combinatorics(self):
        material = scene_material()
        rows = [row for scene in material.values() for row in scene]
        self.assertGreaterEqual(len(rows), 140)
        self.assertLessEqual(len(rows), 160)
        self.assertGreaterEqual(len({row["topic"] for row in rows}), 65)
        self.assertEqual(len({row["reply"] for row in rows}), len(rows))
        self.assertEqual(len(material), 18)

    def test_terminal_pools_have_twelve_new_options_each(self):
        for scene in ("stun", "knockdown", "tko"):
            self.assertGreaterEqual(len(scene_material()[scene]), 12)

    def test_every_scene_has_a_short_safe_reply_and_interpretation(self):
        for scene, rows in scene_material().items():
            with self.subTest(scene=scene):
                self.assertTrue(any(row["length"] == "short" and row["swear"] == 0 for row in rows))
                self.assertTrue(any(row["intent"] in ("analysis", "change", "pattern") for row in rows))
                self.assertTrue(any(row["intent"] == "humor" or row["family"] == "self" for row in rows))

    def test_complete_short_sentences_have_explicit_delivery_and_semantics(self):
        for scene, rows in scene_material().items():
            for row in rows:
                with self.subTest(scene=scene, reply=row["reply"]):
                    self.assertEqual(row["lead"], "{setup}")
                    self.assertTrue(row["topic"])
                    self.assertIn(row["length"], ("short", "normal"))
                    self.assertIn(row["delivery"], ("neutral", "excited", "dry", "surprised"))
                    self.assertIn(row["swear"], (0, 1, 2))
                    self.assertIn(row["lead_role"], ("caster", "analyst"))
                    self.assertLessEqual(len(row["reply"]), 38)
                    if row["length"] == "short":
                        self.assertLessEqual(len(row["reply"]), 18)
                    self.assertNotIn("{", row["reply"])
                    self.assertNotIn("씨발", row["reply"])
                    self.assertFalse(any(char.isdigit() for char in row["reply"]))
                    self.assertFalse(row["requires_setup"])

    def test_role_swaps_and_profanity_are_not_the_whole_corpus(self):
        rows = [row for scene in scene_material().values() for row in scene]
        swaps = sum(row["lead_role"] == "analyst" for row in rows)
        self.assertGreaterEqual(swaps, 18)
        self.assertLess(swaps, len(rows) // 4)
        self.assertGreater(sum(row["swear"] == 0 for row in rows), len(rows) // 2)
        self.assertTrue(any("샤갈" in row["reply"] for row in rows))
        self.assertTrue(any("존나" in row["reply"] for row in rows))

    def test_same_premise_across_scenes_has_same_topic(self):
        material = scene_material()
        toll = [row for scene in ("whiff", "repeat_counter", "counter_release")
                for row in material[scene] if row["topic"] == "counter_toll"]
        self.assertEqual(len(toll), 3)
        message = [row for rows in material.values() for row in rows if row["topic"] == "counter_reply_message"]
        self.assertGreaterEqual(len(message), 3)

    def test_call_material_uses_only_proven_new_contexts(self):
        calls = call_material()
        self.assertEqual(set(calls), {"counter_release", "exchange_return", "target_switch"})
        for scene, texts in calls.items():
            self.assertIn(scene, scene_material())
            self.assertEqual(len(texts), len(set(texts)))
            self.assertGreaterEqual(len(texts), 4)
            self.assertTrue(all(len(text) <= 18 and "{" not in text for text in texts))

    def test_returned_rows_are_not_mutable_global_state(self):
        first = scene_material()
        first["counter"][0]["reply"] = "changed"
        self.assertNotEqual(scene_material()["counter"][0]["reply"], "changed")


if __name__ == "__main__":
    unittest.main()
