"""Content choices are evidence-bound and confirmed at actual audio boundaries."""
import unittest
from unittest.mock import patch

from commentary_content import plan, subject
from commentary_story import MatchStory, Script, SpokenMemory, SCENES
from tests import test_commentary_tts_queue as queue_tests


class ContentDirectionTests(unittest.TestCase):
    def setUp(self):
        self.memory = SpokenMemory()
        self.story = MatchStory(self.memory)

    def compose(self, tag="weak", now=1000, **kwargs):
        return self.story.compose(tag, setup="통, 왼쪽 눈 적중!", name="통", side="blue",
                                  now=now, brief=True, **kwargs)

    def test_completed_setup_does_not_claim_unheard_reply_or_seed(self):
        out = self.compose("counter", context={"repeat_counter": True})
        out["story"]["seed"] = "permission"
        self.memory.complete_turn(out["story"], 0, now=1000)
        heard = self.memory.recent_content(self.story.scope, now=1001)
        self.assertEqual([row["intent"] for row in heard], ["call"])
        self.assertFalse(self.story._heard("permission", "blue", now=1001))
        self.memory.complete_turn(out["story"], 1, now=1002)
        self.assertFalse(self.story._heard("permission", "blue", now=1003))
        self.memory.complete(out["story"], now=1003)
        self.assertTrue(self.story._heard("permission", "blue", now=1004))
        self.assertEqual(len(self.memory.recent_content(self.story.scope, now=1004)), 2)

    def test_different_words_same_joke_are_not_new_content(self):
        scripts = [Script("{setup}", "저는 맞아요.", "self"),
                   Script("{setup}", "저는 못 피해요.", "self")]
        meta = subject(scripts[0], "counter")
        pool, reason = plan(scripts, scene="counter", side="red", round_no=2,
            heard=[{**meta, "side": "blue", "round": 1, "completed_at": 1000}],
            pending=[], now=1020, density="full")
        self.assertFalse(pool)
        self.assertEqual(reason, "topics_rested")

    def test_selected_failed_content_only_reserves_eight_seconds(self):
        out = self.compose()
        self.story.selected(out)
        self.assertEqual(len(self.compose(now=1006)["turns"]), 1)
        self.assertEqual(len(self.compose(now=1009)["turns"]), 2)
        self.assertFalse(self.memory.recent_content(self.story.scope, now=1009))

    def test_target_count_paraphrases_share_one_observation(self):
        rows = SCENES["target_repeat"]
        generic = next(script for script in rows if script.family == "analysis" and not script.topic)
        explicit = next(script for script in rows if script.topic == "target_accumulation")
        paraphrase = next(script for script in rows if script.topic == "target_new_hit")
        self.assertEqual(subject(generic, "target_repeat")["topic"], subject(explicit, "target_repeat")["topic"])
        self.assertEqual(subject(explicit, "target_repeat")["topic"], subject(paraphrase, "target_repeat")["topic"])

    def test_actually_heard_reply_controls_density_not_modulo_counter(self):
        out = self.compose()
        self.memory.complete(out["story"], now=1003)
        self.assertEqual(len(self.compose(now=1010)["turns"]), 1)
        next_out = self.compose(now=1022)
        self.assertEqual(len(next_out["turns"]), 2)
        self.assertNotEqual(out["story"]["content"][1]["topic"], next_out["story"]["content"][1]["topic"])

    def test_change_is_prioritized_without_inventing_evidence(self):
        ordinary = self.compose("counter")
        reversal = self.compose("counter", context={"reversal": True, "receiver": "red"})
        self.assertNotEqual(ordinary["story"]["direction"], "change")
        self.assertEqual(reversal["story"]["direction"], "change")

    def test_exhausted_material_drops_reply_not_primary_call(self):
        for index, script in enumerate(SCENES["target_repeat"]):
            self.memory.complete({"scope": self.story.scope, "id": str(index), "side": "blue", "round": 1,
                "content": [subject(script, "target_repeat")]}, now=1000)
        out = self.compose(context={"weak_hits": 4, "weak": "chin"}, now=1020)
        self.assertEqual(out["story"]["direction"], "topics_rested")
        self.assertEqual(out["turns"], [{"role": out["turns"][0]["role"], "text": "통, 왼쪽 눈 적중!"}])
        self.assertFalse(out["story"]["seed"])

    def test_idle_can_stay_silent_instead_of_repeating_spent_material(self):
        first = self.story.idle(now=1000)
        self.memory.complete(first["story"], now=1000)
        self.assertIsNone(self.story.idle(now=1005))

    def test_content_memory_is_bounded_and_match_isolated(self):
        for index in range(150):
            self.memory.complete_turn({"scope": self.story.scope, "id": str(index),
                "content": [{"intent": "humor", "topic": "test"}]}, 0, now=1000)
        self.assertEqual(len(self.memory.recent_content(self.story.scope, now=1001)), 96)
        self.story.reset()
        self.assertFalse(self.memory.recent_content(self.story.scope, now=1001))

    def test_failed_callback_does_not_spend_thirty_second_heard_cooldown(self):
        self.memory.complete({"scope": self.story.scope, "id": "seed", "side": "blue",
                              "seed": "permission", "round": 1}, now=1000)
        first = self.compose("counter", now=1010, context={"repeat_counter": True})
        self.assertEqual(first["story"]["scene"], "permission_return")
        self.story.selected(first)
        self.assertEqual(self.compose("counter", now=1015, context={"repeat_counter": True})["story"]["scene"], "repeat_counter")
        retry = self.compose("counter", now=1019, context={"repeat_counter": True})
        self.assertEqual(retry["story"]["scene"], "permission_return")
        self.memory.complete(retry["story"], now=1020)
        self.assertEqual(self.compose("counter", now=1040, context={"repeat_counter": True})["story"]["scene"], "repeat_counter")

    def test_runtime_reply_remembers_its_own_topic_not_setup_twice(self):
        app = queue_tests.CommentaryTtsQueueTests()._app()
        out = self.compose()
        packet = app._commentary_dialogue_from_update({"commentary_tts_live_dialogue": True,
            "commentary_tts_story": out["story"], "commentary_tts_continuations": out["turns"][1:]})
        app._commentary_tts_dialogues["caster"] = {**packet, "play_started": True}
        with patch("timerauto.SPOKEN_MEMORY", self.memory):
            app._complete_commentary_dialogue("caster", ended=True)
            reply = app._commentary_tts_queue.popleft()["kwargs"]["_dialogue"]
            self.assertEqual(reply["turn_index"], 1)
            app._commentary_tts_dialogues["analyst"] = {**reply, "play_started": True}
            app._complete_commentary_dialogue("analyst", ended=True)
        content = self.memory.recent_content(self.story.scope)
        self.assertEqual([row["topic"] for row in content], [row["topic"] for row in out["story"]["content"]])
        self.assertEqual(len(self.memory.recent(self.story.scope)), 1)

    def test_runtime_records_only_finished_turn_before_new_action_cancels_reply(self):
        for started, ended, expected in ((True, True, 1), (False, True, 0), (True, False, 0)):
            app = queue_tests.CommentaryTtsQueueTests()._app()
            out = self.compose()
            packet = app._commentary_dialogue_from_update({"commentary_tts_live_dialogue": True,
                "commentary_tts_story": out["story"], "commentary_tts_continuations": out["turns"][1:]})
            app._commentary_tts_dialogues["caster"] = {**packet, "play_started": started, "live_serial": 1}
            app._commentary_live_serial = 2
            memory = SpokenMemory()
            with patch("timerauto.SPOKEN_MEMORY", memory):
                app._complete_commentary_dialogue("caster", ended=ended)
            self.assertEqual(len(memory.recent_content(self.story.scope)), expected)
            self.assertFalse(memory.recent(self.story.scope))
            self.assertFalse(app._commentary_tts_queue)

    def test_authored_expansions_stay_short_and_have_distinct_premises(self):
        rows = [script for scene in SCENES.values() for script in scene if script.topic]
        self.assertGreaterEqual(len(rows), 30)
        self.assertGreaterEqual(len({script.topic for script in rows}), 30)
        self.assertTrue(all(len(script.reply) <= 45 for script in rows))

    def test_opening_wording_varies_by_bout_but_archive_replay_is_reproducible(self):
        openings = set()
        for index in range(16):
            row = {"event_id": f"match-{index}", "attacker_side": "blue", "receiver_side": "red",
                   "damage": 35, "time": 170, "_central_event": {"counter": True}}
            scripts = []
            for _ in range(2):
                story = MatchStory(SpokenMemory())
                story.observe(1, [row])
                scripts.append(story.compose("weak", setup="급소!", name="통", now=1000, brief=True)["turns"])
            self.assertEqual(scripts[0], scripts[1])
            openings.add(scripts[0][1]["text"])
        self.assertGreater(len(openings), 2)
