from types import SimpleNamespace
from collections import deque
import unittest

from event_engine import FightEventEngine
from spectator_log_watcher import SpectatorLogWatcher


def config():
    return SimpleNamespace(
        event_combo_min_damage=15.0,
        event_combo_window_sec=0.8,
        event_combo_break_damage=20.0,
        event_heavy_damage=50.0,
        event_signature_damage=60.0,
        event_counter_min_damage=40.0,
        event_counter_official_min_mult=1.02,
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

    def test_combo_accepts_countdown_clock_in_append_order(self):
        engine = FightEventEngine(config())
        rows = engine.classify_many([
            {"time": 100.0, "attacker_side": "blue", "receiver_side": "red", "damage": 20},
            {"time": 99.5, "attacker_side": "blue", "receiver_side": "red", "damage": 25},
            {"time": 99.1, "attacker_side": "blue", "receiver_side": "red", "damage": 30},
        ])
        self.assertEqual([row["combo_hits"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[-1]["combo_damage"], 75.0)

    def test_game_declared_down_is_always_decisive(self):
        engine = FightEventEngine(config())
        row = engine.classify({"time": 1, "attacker_side": "red", "receiver_side": "blue", "damage": 38, "effect_kind": "knockdown"})
        self.assertEqual(row["primary"], "decisive")
        self.assertIn("knockdown", row["tags"])

    def test_weak_point_is_classified_once_for_all_consumers(self):
        engine = FightEventEngine(config())
        row = engine.classify({
            "time": 1,
            "attacker_side": "red",
            "receiver_side": "blue",
            "damage": 18,
            "weak_point": "EyeLeft",
        })
        self.assertEqual(row["primary"], "weak_point")
        self.assertIn("weak_point", row["tags"])
        self.assertIn("weak_eyeleft", row["tags"])

    def test_answer_back_is_not_mislabeled_as_counter(self):
        engine = FightEventEngine(config())
        engine.classify({
            "time": 100.0, "attacker_side": "red", "receiver_side": "blue", "damage": 22,
        })
        answer = engine.classify({
            "time": 99.0, "attacker_side": "blue", "receiver_side": "red", "damage": 38,
        })
        self.assertFalse(answer["counter"])
        self.assertIn("answer_back", answer["tags"])

    def test_momentum_requires_three_unanswered_meaningful_hits(self):
        engine = FightEventEngine(config())
        rows = engine.classify_many([
            {"time": 100.0, "attacker_side": "blue", "receiver_side": "red", "damage": 25},
            {"time": 99.2, "attacker_side": "blue", "receiver_side": "red", "damage": 27},
            {"time": 98.4, "attacker_side": "blue", "receiver_side": "red", "damage": 30},
        ])
        self.assertNotIn("momentum", rows[1]["tags"])
        self.assertIn("momentum", rows[2]["tags"])

    def test_target_lock_requires_repeated_damage_to_same_weak_point(self):
        engine = FightEventEngine(config())
        rows = engine.classify_many([
            {"time": 100.0, "attacker_side": "red", "receiver_side": "blue", "damage": 24, "weak_point": "EyeLeft"},
            {"time": 97.0, "attacker_side": "red", "receiver_side": "blue", "damage": 23, "weak_point": "EyeLeft"},
            {"time": 93.0, "attacker_side": "red", "receiver_side": "blue", "damage": 25, "weak_point": "EyeLeft"},
        ])
        self.assertNotIn("target_lock", rows[1]["tags"])
        self.assertIn("target_lock", rows[2]["tags"])

    def test_ruleset_version_changes_with_a_shared_threshold(self):
        cfg = config()
        engine = FightEventEngine(cfg)
        before = engine.ruleset_version()
        cfg.event_combo_window_sec = 1.1
        self.assertNotEqual(before, engine.ruleset_version())

    def test_official_or_fast_graze_punish_is_counter(self):
        engine = FightEventEngine(config())
        official = engine.classify({
            "time": 100.0, "attacker_side": "blue", "receiver_side": "red",
            "damage": 8, "counter_mult": 1.2,
        })
        engine.classify({
            "time": 90.0, "attacker_side": "red", "receiver_side": "blue",
            "damage": 12,
        })
        inferred = engine.classify({
            "time": 89.4, "attacker_side": "blue", "receiver_side": "red",
            "damage": 31,
        })
        self.assertTrue(official["official_counter"])
        self.assertEqual(official["counter_reason"], "")
        self.assertFalse(official["counter"])
        self.assertTrue(inferred["inferred_counter"])
        self.assertEqual(inferred["counter_reason"], "graze")

    def test_tiny_official_multiplier_is_audited_but_not_broadcast(self):
        engine = FightEventEngine(config())
        tiny = engine.classify({
            "time": 100.0, "attacker_side": "blue", "receiver_side": "red",
            "damage": 35.0, "counter_mult": 1.01, "is_counter": True,
        })
        accepted = engine.classify({
            "time": 90.0, "attacker_side": "red", "receiver_side": "blue",
            "damage": 35.0, "counter_mult": 1.02, "is_counter": True,
        })
        self.assertTrue(tiny["official_counter_raw"])
        self.assertFalse(tiny["official_counter"])
        self.assertFalse(tiny["counter"])
        self.assertTrue(accepted["official_counter"])
        self.assertTrue(accepted["counter"])

    def test_one_opponent_attack_can_create_only_one_counter(self):
        engine = FightEventEngine(config())
        engine.classify({
            "event_id": "opponent-graze",
            "time": 100.0, "attacker_side": "red", "receiver_side": "blue",
            "damage": 10.0,
        })
        first = engine.classify({
            "time": 99.6, "attacker_side": "blue", "receiver_side": "red",
            "damage": 31.0,
        })
        followup = engine.classify({
            "time": 99.4, "attacker_side": "blue", "receiver_side": "red",
            "damage": 42.0,
        })
        self.assertTrue(first["counter"])
        self.assertEqual(first["counter_reason"], "graze")
        self.assertFalse(followup["counter"])
        self.assertEqual(followup["combo_hits"], 2)

    def test_official_counter_also_consumes_the_shared_opportunity(self):
        engine = FightEventEngine(config())
        engine.classify({
            "time": 100.0, "attacker_side": "red", "receiver_side": "blue",
            "damage": 10.0,
        })
        official = engine.classify({
            "time": 99.6, "attacker_side": "blue", "receiver_side": "red",
            "damage": 31.0, "counter_mult": 1.02, "is_counter": True,
        })
        followup = engine.classify({
            "time": 99.4, "attacker_side": "blue", "receiver_side": "red",
            "damage": 42.0,
        })
        self.assertTrue(official["counter"])
        self.assertEqual(official["counter_reason"], "official")
        self.assertFalse(followup["counter"])

    def test_one_whiff_throw_opportunity_can_create_only_one_counter(self):
        engine = FightEventEngine(config())
        first = engine.classify({
            "time": 99.6, "attacker_side": "blue", "receiver_side": "red",
            "damage": 31.0, "is_counter": True, "counter_reason": "whiff",
            "counter_opportunity_id": "throw:red:100.0:right:Jab",
        })
        followup = engine.classify({
            "time": 99.4, "attacker_side": "blue", "receiver_side": "red",
            "damage": 42.0, "is_counter": True, "counter_reason": "whiff",
            "counter_opportunity_id": "throw:red:100.0:right:Jab",
        })
        self.assertTrue(first["counter"])
        self.assertFalse(followup["counter"])
        self.assertEqual(followup["combo_hits"], 2)

    def test_whiff_throw_is_consumed_once_during_annotation(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        replies = [
            {"time": 99.6, "attacker_side": "blue", "receiver_side": "red", "damage": 31.0},
            {"time": 99.4, "attacker_side": "blue", "receiver_side": "red", "damage": 42.0},
        ]
        annotated = watcher._annotate_whiff_counters_from_throws(
            replies,
            [{"time": 100.0, "side": "red", "hand": "right", "punch": "Jab"}],
            replies,
        )
        self.assertTrue(annotated[0].get("is_counter"))
        self.assertFalse(annotated[1].get("is_counter", False))

    def test_central_false_counter_verdict_overrides_legacy_multiplier(self):
        cfg = config()
        cfg.event_engine_shadow_mode = False
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        event = {
            "damage": 8.0,
            "counter_mult": 1.2,
            "is_counter": False,
            "_central_event": {"counter": False, "tags": ["hit"]},
            "event_tags": ["hit"],
            "event_primary": "hit",
        }
        self.assertFalse(watcher._is_counter_event(event))

    def test_legacy_counter_fallback_remains_for_unclassified_events(self):
        cfg = config()
        cfg.event_engine_shadow_mode = False
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        self.assertTrue(watcher._is_counter_event({"counter_mult": 1.2, "damage": 30.0}))
        self.assertTrue(watcher._is_counter_event({
            "counter_mult": 1.0,
            "_central_event": {"counter": True, "tags": ["hit", "counter"]},
        }))

    def test_reply_after_complete_miss_requires_25_damage(self):
        cfg = config()
        cfg.event_counter_window_sec = 0.7
        cfg.event_counter_graze_max_damage = 15.0
        cfg.event_counter_response_min_damage = 30.0
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        reason = watcher._counter_reason_against_previous(
            {"time": 99.5, "attacker_side": "blue", "receiver_side": "red", "damage": 24.0},
            {"time": 100.0, "attacker_side": "red", "receiver_side": "blue", "damage": 0.0},
        )
        self.assertEqual(reason, "")
        engine = FightEventEngine(cfg)
        engine.classify({
            "time": 100.0,
            "attacker_side": "red",
            "receiver_side": "blue",
            "damage": 0.0,
        })
        classified = engine.classify({
            "time": 99.5,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 24.0,
        })
        self.assertFalse(classified["counter"])
        classified = engine.classify({
            "time": 99.4,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 25.0,
        })
        self.assertTrue(classified["counter"])
        self.assertEqual(classified["counter_reason"], "whiff")

    def test_reply_after_complete_miss_still_obeys_counter_window(self):
        cfg = config()
        cfg.event_counter_window_sec = 0.7
        cfg.event_counter_graze_max_damage = 15.0
        cfg.event_counter_response_min_damage = 30.0
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        reason = watcher._counter_reason_against_previous(
            {"time": 99.2, "attacker_side": "blue", "receiver_side": "red", "damage": 1.0},
            {"time": 100.0, "attacker_side": "red", "receiver_side": "blue", "damage": 0.0},
        )
        self.assertEqual(reason, "")

    def test_throw_whiff_counter_requires_causal_order_on_countdown_clock(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        reply = {
            "time": 99.5,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 32.0,
        }
        # 100.0 happened before 99.5 on the countdown clock: valid whiff.
        valid = watcher._annotate_whiff_counters_from_throws(
            [dict(reply)],
            [{"time": 100.0, "side": "red", "punch": "Jab"}],
            [dict(reply)],
        )
        self.assertTrue(valid[0].get("is_counter"))
        self.assertEqual(valid[0].get("counter_reason"), "whiff")

        # 99.0 happened after the reply. It is a new opponent attack and must
        # not retroactively turn the earlier hit into a whiff counter.
        invalid = watcher._annotate_whiff_counters_from_throws(
            [dict(reply)],
            [{"time": 99.0, "side": "red", "punch": "Jab"}],
            [dict(reply)],
        )
        self.assertFalse(invalid[0].get("is_counter", False))

    def test_throw_whiff_counter_allows_small_log_write_jitter_only(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        reply = {
            "time": 99.5,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 32.0,
        }
        jittered = watcher._annotate_whiff_counters_from_throws(
            [dict(reply)],
            [{"time": 99.44, "side": "red", "punch": "Jab"}],
            [dict(reply)],
        )
        self.assertTrue(jittered[0].get("is_counter"))
        too_late = watcher._annotate_whiff_counters_from_throws(
            [dict(reply)],
            [{"time": 99.30, "side": "red", "punch": "Jab"}],
            [dict(reply)],
        )
        self.assertFalse(too_late[0].get("is_counter", False))

    def test_small_reply_after_graze_is_not_broadcast_counter(self):
        cfg = config()
        cfg.event_counter_window_sec = 0.7
        cfg.event_counter_graze_max_damage = 15.0
        cfg.event_counter_response_min_damage = 30.0
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        reason = watcher._counter_reason_against_previous(
            {"time": 99.5, "attacker_side": "blue", "receiver_side": "red", "damage": 12.0},
            {"time": 100.0, "attacker_side": "red", "receiver_side": "blue", "damage": 10.0},
        )
        self.assertEqual(reason, "")

    def test_combo_hud_preserves_countdown_append_order(self):
        cfg = config()
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        watcher._engine_combo_display = {}
        watcher._combo_state = {}
        watcher._live_line = lambda *_args, **_kwargs: ""
        rows = [
            {"time": 100.0, "_central_event": {
                "side": "blue", "receiver_side": "red", "damage": 20,
                "combo_hits": 1, "combo_damage": 20, "counter": False,
            }},
            {"time": 99.5, "_central_event": {
                "side": "blue", "receiver_side": "red", "damage": 25,
                "combo_hits": 2, "combo_damage": 45, "counter": False,
            }},
        ]
        update = watcher._build_combo_update_from_engine(rows)
        self.assertEqual(update["blue_combo_hit_text"], "2 HIT COMBO")
        self.assertEqual(update["blue_combo_damage_text"], "45 DAMAGE")

    def test_combo_hud_does_not_blank_banner_on_first_hit_after_chain(self):
        """The browser TTL, not a following ordinary hit, ends the banner."""
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        watcher._engine_combo_display = {"attacker": "blue", "receiver": "red", "hits": 2}
        watcher._combo_state = {}
        watcher._live_line = lambda *_args, **_kwargs: ""
        update = watcher._build_combo_update_from_engine([{
            "_central_event": {
                "side": "blue", "receiver_side": "red", "damage": 32.0,
                "combo_hits": 1, "combo_damage": 32.0, "counter": False,
            },
        }])
        self.assertEqual(update, {})
        self.assertEqual(watcher._engine_combo_display["hits"], 1)

    def test_counter_hud_does_not_blank_when_opponent_throws_an_ordinary_reply(self):
        """A normal reply 0.1s later must not erase the counter banner."""
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        watcher._engine_combo_display = {"attacker": "red", "receiver": "blue", "hits": 1}
        watcher._combo_state = {}
        watcher._live_line = lambda *_args, **_kwargs: ""
        update = watcher._build_combo_update_from_engine([{
            "_central_event": {
                "side": "blue", "receiver_side": "red", "damage": 29.0,
                "combo_hits": 1, "combo_damage": 29.0, "counter": False,
            },
        }])
        self.assertEqual(update, {})
        self.assertNotIn("red_combo_hit_text", update)
        self.assertNotIn("red_combo_damage_text", update)

    def test_counter_combo_keeps_varied_counter_commentary(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        watcher._engine_combo_display = {}
        watcher._combo_state = {}
        watcher._commentary_recent_lines = deque()
        row = {
            "attacker_side": "blue",
            "receiver_side": "red",
            "_central_event": {
                "side": "blue",
                "receiver_side": "red",
                "damage": 42.0,
                "counter": True,
                "counter_reason": "whiff",
                "combo_hits": 2,
                "combo_damage": 67.0,
            },
        }
        update = watcher._build_combo_update_from_engine([row])
        self.assertEqual(update["blue_combo_hit_text"], "COUNTER\nHIT 2")
        self.assertTrue(update.get("_counter_commentary_text"))
        self.assertNotIn("_combo_commentary_text", update)
        self.assertEqual(len(watcher._counter_commentary_candidates("whiff", 42.0, 2)), 4)

    def test_live_commentary_candidate_pools_do_not_contain_garbled_text(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        pools = [
            watcher._exchange_commentary_candidates("counter"),
            watcher._exchange_commentary_candidates("combo"),
            watcher._counter_commentary_candidates("whiff", 42.0),
            watcher._counter_commentary_candidates("graze", 42.0),
            watcher._counter_commentary_candidates("normal", 62.0),
            watcher._counter_commentary_candidates("normal", 42.0, 2),
        ]
        for candidates in pools:
            self.assertEqual(len(candidates), 4)
            for line in candidates:
                self.assertNotIn("?", line)
                self.assertNotIn("\ufffd", line)
                self.assertTrue(line.endswith("."))

    def test_causal_live_commentary_explains_whiff_counter(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = config()
        watcher._commentary_recent_lines = deque()
        watcher._commentary_semantic_last_at = {}
        watcher._commentary_semantic_last_key = {}
        watcher._live_commentary_name = lambda side: "진혁" if side == "blue" else "레드"
        text = watcher._causal_live_commentary({
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 42.0,
            "counter_reason": "whiff",
            "is_counter": True,
        })
        self.assertTrue(text)
        self.assertIn("진혁", text)
        self.assertTrue(any(word in text for word in ("헛친", "비어", "카운터")))

    def test_live_watcher_attachment_is_canonical_and_idempotent(self):
        cfg = config()
        cfg.event_engine_shadow_mode = False
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        watcher._event_engine = FightEventEngine(cfg)
        rows = [{
            "event_id": "one",
            "time": 1.0,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 55,
            "is_counter": True,
        }]
        first = watcher._attach_central_event_classification(rows)
        second = watcher._attach_central_event_classification(rows)
        self.assertEqual(first, second)
        self.assertEqual(rows[0]["combo_hits"], 1)
        self.assertIn("heavy", rows[0]["event_tags"])
        self.assertIn("counter", rows[0]["event_tags"])

    def test_shadow_attachment_does_not_change_live_fields(self):
        cfg = config()
        cfg.event_engine_shadow_mode = True
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher.cfg = cfg
        watcher._event_engine = FightEventEngine(cfg)
        rows = [{
            "event_id": "shadow-one",
            "time": 1.0,
            "attacker_side": "blue",
            "receiver_side": "red",
            "damage": 55,
        }]
        watcher._attach_central_event_classification(rows)
        self.assertIn("_central_event", rows[0])
        self.assertNotIn("event_tags", rows[0])
        self.assertNotIn("combo_hits", rows[0])
