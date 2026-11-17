"""Confirmed relationships, spoken-only memory and on-time pack dialogue."""
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from commentary_entertainment import BGradeCommentary
from commentary_story import MatchStory, SpokenMemory, Script, script_key, SCENES
from commentary_calls import SpokenFocus
from commentary_flow import ExchangeContext
from commentary_content import plan, subject
from config_model import AppConfig
from spectator_log_watcher import SpectatorLogWatcher


def hit(i, *, time=None, side="blue", counter=False, combo=1, weak="", tags=()):
    return {"event_id": str(i), "time": 180 - i if time is None else time,
            "attacker_side": side, "receiver_side": "red" if side == "blue" else "blue",
            "damage": 35., "punch": "Hook", "weak_point": weak,
            "_central_event": {"counter": counter, "combo_hits": combo,
                               "tags": list(tags), "counter_reason": "official" if counter else ""}}


class CommentaryUpgradeTests(unittest.TestCase):
    def bank(self):
        bank = BGradeCommentary()
        bank.story.memory = SpokenMemory()
        bank.story.focus = SpokenFocus()
        bank.story.configure(AppConfig())
        return bank

    def call(self, bank, row, round_no=1, now=1000):
        bank.story.observe(round_no, [row])
        return bank.event_call(row, name="통", receiver="상대", target="간", now=now)

    def test_counter_into_combo_is_a_relationship_not_three_new_counters(self):
        bank = self.bank()
        rows = [hit(1, time=179, counter=True), hit(2, time=178.5, combo=2), hit(3, time=178, combo=3)]
        original = copy.deepcopy(rows)
        for row in rows:
            call = self.call(bank, row)
        self.assertEqual(call.presentation["story"]["scene"], "counter_release")
        self.assertTrue(bank.story.context(rows[-1])["pacing_hot"])
        self.assertEqual(bank.story._stats[1]["blue"]["counter"], 1)
        self.assertFalse(rows[-1]["_central_event"]["counter"])
        self.assertEqual(rows, original)

    def test_elapsed_and_countdown_clocks_produce_same_relationships(self):
        for increasing in (False, True):
            bank = self.bank()
            for i in range(3):
                self.call(bank, hit(i, time=i * 2 if increasing else 180 - i * 2, counter=True))
            row = hit(4, side="red", time=7 if increasing else 173, counter=True)
            call = self.call(bank, row)
            self.assertEqual(call.presentation["story"]["scene"], "reversal")

    def test_chain_reset_and_round_boundary_do_not_inherit_old_counter(self):
        bank = self.bank()
        self.call(bank, hit(1, counter=True))
        self.call(bank, hit(2, combo=2))
        self.call(bank, hit(3, combo=1))
        self.call(bank, hit(4, combo=2))
        call = self.call(bank, hit(5, combo=3))
        self.assertNotEqual(call.presentation["story"]["scene"], "counter_release")
        call = self.call(bank, hit(6, combo=3), round_no=2)
        self.assertNotEqual(call.presentation["story"]["scene"], "counter_release")

    def test_return_requires_two_recent_opponent_hits_not_a_counter_inference(self):
        bank = self.bank()
        self.call(bank, hit(1, side="red"))
        self.call(bank, hit(2, side="red"))
        row = hit(3, tags=("answer_back",))
        call = self.call(bank, row)
        self.assertEqual(call.presentation["story"]["scene"], "exchange_return")
        self.assertEqual(bank.story._stats[1]["blue"]["counter"], 0)
        self.assertFalse(row["_central_event"]["counter"])
        self.assertNotEqual(self.call(bank, hit(4)).presentation["story"]["scene"], "exchange_return")

    def test_target_switch_needs_known_three_hit_history(self):
        bank = self.bank()
        for i in range(1, 4):
            self.call(bank, hit(i, weak="eyeleft", tags=("weak_point",)))
        row = hit(4, weak="liver", tags=("weak_point",))
        self.assertEqual(self.call(bank, row).presentation["story"]["scene"], "target_switch")
        bank = self.bank()
        self.call(bank, hit(1, weak="", tags=()))
        self.assertNotEqual(self.call(bank, row).presentation["story"]["scene"], "target_switch")

    def test_hot_exchange_prefers_short_script_but_keeps_call_if_no_reply_ready(self):
        bank = self.bank()
        call = self.call(bank, hit(1, combo=5))
        self.assertEqual(call.presentation["story"]["pacing_reason"], "fast_exchange")
        self.assertEqual(call.presentation["story"]["reply_budget_seconds"], 1.8)
        self.assertTrue(len(call.presentation["turns"]) == 1 or len(call.presentation["turns"][1]["text"]) <= 18)
        bank.story.reply_filter = lambda role, text, budget: budget is None
        call = self.call(bank, hit(2, combo=6), now=1010)
        self.assertEqual(len(call.presentation["turns"]), 1)
        self.assertFalse(call.presentation["story"]["seed"])

    def test_prepared_caster_call_survives_missing_optional_role_or_reply(self):
        bank = self.bank()
        bank.story.reply_filter = lambda role, text, budget: role == "caster" and budget is None
        call = self.call(bank, hit(1, counter=True))
        self.assertIsNotNone(call)
        self.assertEqual(call.role, "caster")
        self.assertEqual(len(call.presentation["turns"]), 1)
        bank.story.reply_filter = lambda role, text, budget: False
        self.assertIsNone(self.call(bank, hit(2)))

    def test_only_new_change_can_earn_reply_before_ordinary_gap(self):
        rows = [Script("{setup}", "반대쪽입니다.", "analysis", topic="switch", intent="change")]
        heard = [{"intent": "humor", "topic": "other", "evidence": False, "completed_at": 1000}]
        args = dict(scene="reversal", side="red", round_no=1, heard=heard, pending=[], now=1007, density="full")
        self.assertFalse(plan(rows, **args)[0])
        self.assertTrue(plan(rows, **args, change=True)[0])

    def test_broadcast_joke_rest_crosses_match_but_callback_permission_does_not(self):
        memory = SpokenMemory()
        first = MatchStory(memory)
        a, b = Script("{setup}", "첫 농담", "dry", topic="generic"), Script("{setup}", "다른 농담", "self", topic="other")
        memory.complete({"scope": first.scope, "id": "finished", "script": script_key(a), "seed": "permission",
                         "side": "blue", "family": "dry", "content": [{"intent": "humor", "topic": "generic", "evidence": False}]}, now=1000)
        second = MatchStory(memory)
        self.assertEqual(second._pick([a, b], now=1001), b)
        self.assertIn("generic", {row["topic"] for row in second.content_memory(now=1001)})
        self.assertFalse(second._heard("permission", "blue", now=1001))

    def test_every_new_reply_and_context_call_is_in_exact_role_catalog(self):
        from commentary_material import scene_material, call_material
        from commentary_pack import catalog
        rows = set(catalog("full"))
        for scene, scripts in scene_material().items():
            for script in scripts:
                role = "caster" if script["lead_role"] == "analyst" else "analyst"
                self.assertIn((role, script["reply"]), rows)
        for lines in call_material().values():
            for line in lines:
                self.assertIn(("caster", line), rows)
                self.assertIn(("analyst", line), rows)

    def test_pack_lifecycle_is_prepared_and_nonpack_round_numbers_are_preserved(self):
        from commentary_pack import catalog
        cfg = AppConfig()
        watcher = SpectatorLogWatcher(cfg)
        self.assertIn("2라운드", watcher._round_caster_text("start", 2, 3))
        cfg.spectator_tts_engine, cfg.spectator_tts_pack_enabled = "qwen3", True
        rows = set(catalog("full"))
        for event in ("start", "break", "results", "end", "cancel"):
            for round_no in (1, 3, 99):
                self.assertIn(("caster", watcher._round_caster_text(event, round_no, 3)), rows)
        self.assertIn(("caster", watcher._build_vs_caster_text()), rows)


if __name__ == "__main__":
    unittest.main()
