import copy
import json
from pathlib import Path
import tempfile
import sqlite3
from types import SimpleNamespace
import unittest

from commentary_story import MatchStory, SpokenMemory, SCENES
from commentary_entertainment import BGradeCommentary, bgrade_demo_steps
from commentary_rehearsal import rehearse_archive
from config_model import AppConfig
from event_engine import FightEventEngine


def hit(index, *, side="blue", weak="", counter=True, round_no=1):
    return {"event_id": str(index), "time": 170 - index * 3, "damage": 35,
        "attacker_side": side, "receiver_side": "red" if side == "blue" else "blue",
        "weak_point": weak, "round": round_no,
        "_central_event": {"counter": counter, "counter_reason": "official", "tags": ["weak_point"] if weak else []}}


class CommentaryStoryTests(unittest.TestCase):
    def bank(self):
        bank = BGradeCommentary()
        bank.story.memory = SpokenMemory()
        return bank

    def call(self, bank, row, *, now=1000, round_no=1):
        bank.story.observe(round_no, [row])
        return bank.event_call(row, name="통" if row["attacker_side"] == "blue" else "현선호",
            receiver="상대", target="눈", key=row["event_id"], now=now)

    def seed(self, story, seed="permission", side="blue", *, now=1000, round_no=1):
        story.memory.complete({"scope": story.scope, "id": "heard-seed", "seed": seed,
            "side": side, "round": round_no}, now=now)

    def test_counts_only_unique_central_verdicts_and_resets_round_context(self):
        bank = self.bank()
        rows = [hit(i) for i in range(3)]
        saved = copy.deepcopy(rows)
        bank.story.observe(1, rows + rows)
        self.assertTrue(bank.story.context(rows[-1])["repeat_counter"])
        self.assertEqual(bank.story._stats[1]["blue"]["counter"], 3)
        bank.story.observe(2, [rows[0]])
        self.assertFalse(bank.story.context(rows[0])["repeat_counter"])
        self.assertEqual(rows, saved)

    def test_central_false_overrides_old_raw_counter_flag(self):
        bank = self.bank()
        row = hit(0, counter=False)
        row["is_counter"] = True
        call = self.call(bank, row)
        self.assertNotIn("counter", call.key)
        self.assertEqual(bank.story._stats[1]["blue"]["counter"], 0)

    def test_repeated_counter_requires_recent_prior_evidence(self):
        bank = self.bank()
        for i in range(3):
            call = self.call(bank, hit(i), now=1000 + i * 6)
        self.assertEqual(call.presentation["story"]["scene"], "repeat_counter")
        later = hit(3)
        later["time"] = 80
        call = self.call(bank, later, now=1100)
        self.assertEqual(call.presentation["story"]["scene"], "counter")

    def test_reversal_uses_the_opponents_history_not_the_wrong_fighter(self):
        bank = self.bank()
        bank.story.observe(1, [hit(i) for i in range(3)])
        call = self.call(bank, hit(3, side="red"), now=1020)
        self.assertEqual(call.presentation["story"]["scene"], "reversal")
        self.assertEqual(call.presentation["story"]["side"], "red")
        self.assertIn("현선호", call.text)
        following = self.call(bank, hit(4, side="red"), now=1026)
        self.assertNotEqual(following.presentation["story"]["scene"], "reversal")

    def test_selected_but_unheard_seed_cannot_authorize_callback(self):
        bank = self.bank()
        story = bank.story
        with self.subTest("merely selected"):
            story.selected({"story": {"seed": "permission", "side": "blue", "family": "dry"}, "selected_at": 1000})
            out = story.compose("counter", setup="통, 카운터!", name="통", side="blue",
                context={"repeat_counter": True}, now=1010)
            self.assertEqual(out["story"]["scene"], "repeat_counter")
        self.seed(story)
        out = story.compose("counter", setup="통, 카운터!", name="통", side="blue",
            context={"repeat_counter": True}, now=1010)
        self.assertEqual(out["story"]["scene"], "permission_return")

    def test_callback_requires_matching_side_scope_and_unexpired_audio(self):
        story = self.bank().story
        self.seed(story, side="red")
        kwargs = dict(setup="통, 카운터!", name="통", side="blue", context={"repeat_counter": True})
        self.assertEqual(story.compose("counter", now=1010, **kwargs)["story"]["scene"], "repeat_counter")
        self.seed(story, side="blue", now=1001)  # same ID is intentionally deduplicated
        story.memory.complete({"scope": story.scope, "id": "blue-seed", "seed": "permission", "side": "blue"}, now=1001)
        self.assertEqual(story.compose("counter", now=1010, **kwargs)["story"]["scene"], "permission_return")
        self.assertEqual(story.compose("counter", now=1122, **kwargs)["story"]["scene"], "repeat_counter")
        story.reset()
        self.assertEqual(story.compose("counter", now=1010, **kwargs)["story"]["scene"], "repeat_counter")

    def test_permission_reversal_refers_to_the_original_counter_fighter(self):
        story = self.bank().story
        self.seed(story, side="blue")
        out = story.compose("counter", setup="현선호, 카운터!", name="현선호", side="red",
            context={"reversal": True, "receiver": "blue"}, now=1010)
        self.assertEqual(out["story"]["scene"], "permission_reverse")

    def test_eye_story_needs_sufficient_actual_hits_and_completed_seed(self):
        bank = self.bank()
        for i in range(6):
            call = self.call(bank, hit(i, weak="EyeLeft" if i % 2 else "EyeRight", counter=False), now=1000 + i * 6)
        self.assertEqual(call.presentation["story"]["scene"], "eye_seed")
        self.seed(bank.story, seed="eyes", now=1030)
        call = self.call(bank, hit(6, weak="EyeRight", counter=False), now=1040)
        self.assertEqual(call.presentation["story"]["scene"], "eye_return")

    def test_only_one_active_comedy_seed_per_fighter(self):
        bank = self.bank()
        self.seed(bank.story, seed="permission", now=1000)
        for i in range(7):
            call = self.call(bank, hit(i, weak="EyeRight", counter=False), now=1000 + i * 6)
        self.assertEqual(call.presentation["story"]["scene"], "target_repeat")
        self.assertFalse(call.presentation["story"]["seed"])

    def test_long_combo_and_stoppage_have_different_short_scripts(self):
        story = self.bank().story
        combo = story.compose("combo", setup="통, 6연타!", name="통", hits=6, now=1000)
        self.assertEqual(combo["story"]["scene"], "long_combo")
        for tag in ("stun", "knockdown", "tko"):
            out = story.compose(tag, setup="현선호, 다운!", name="통", side="blue",
                context={"repeat_counter": True, "reversal": True}, now=1006)
            self.assertEqual(out["story"]["scene"], tag)
            self.assertEqual(len(out["turns"]), 2)
            self.assertLess(len(out["turns"][1]["text"]), 42)

    def test_profane_reactions_and_humor_families_rotate_without_word_substitution(self):
        story = self.bank().story
        texts, families, roles = [], set(), set()
        for i in range(24):
            out = story.compose("heavy", setup="통, 강타!", name="통", now=1000 + 6 * i)
            story.selected(out)
            texts.extend(turn["text"] for turn in out["turns"])
            families.add(out["story"]["family"])
            roles.add(out["turns"][0]["role"])
        self.assertGreaterEqual(len(families), 5)
        self.assertEqual(roles, {"caster", "analyst"})
        self.assertGreaterEqual(sum(word in " ".join(texts) for word in ("씨발", "존나", "미쳤네")), 3)

    def test_light_and_compact_are_independent_and_round_trip(self):
        story = self.bank().story
        cfg = AppConfig()
        cfg.spectator_bgrade_density, cfg.spectator_bgrade_swearing = "compact", "light"
        story.configure(cfg)
        lengths = []
        for i in range(12):
            out = story.compose("counter", setup="통, 카운터!", name="통", now=1000 + i * 6)
            self.assertEqual(out["story"]["swear"], 0)
            lengths.append(len(out["turns"]))
            story.selected(out)
        self.assertIn(1, lengths)
        self.assertIn(2, lengths)
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root, "config.json"))
            cfg.to_json(path)
            restored = AppConfig.from_json(path)
            self.assertEqual(restored.spectator_bgrade_density, "compact")
            self.assertEqual(restored.spectator_bgrade_swearing, "light")

    def test_report_callback_needs_heard_seed_and_matching_report_evidence(self):
        story = self.bank().story
        report = {"round": 1, "blue": {"name": "통", "counterHits": 8}, "red": {"counterHits": 1}}
        original = copy.deepcopy(report)
        self.assertEqual(story.report_callback(report, now=1010), "")
        self.seed(story)
        self.assertIn("8번", story.report_callback(report, now=1010))
        self.assertEqual(story.report_callback({**report, "round": 2}, now=1010), "")
        self.assertEqual(story.report_callback({**report, "blue": {"counterHits": 1}}, now=1010), "")
        self.assertEqual(report, original)

    def test_demo_exercises_repetition_callback_reversal_and_two_roles(self):
        steps = bgrade_demo_steps()
        labels = {step.get("label") for step in steps}
        self.assertTrue({"repeat_counter", "permission_return", "reversal"} <= labels)
        self.assertTrue(any(step["role"] == "analyst" and step.get("followup_role") == "caster" for step in steps))

    def test_archive_rehearsal_is_offline_and_failed_speech_never_authorizes_callback(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "damage_events.jsonl")
            rows = []
            for i in range(60):
                event = {"time": 180 - i * 2, "damage": 35, "attacker_side": "blue", "receiver_side": "red",
                         "counter_mult": 1.03, "punch": "Jab", "hand": "left"}
                rows.append(json.dumps({"round": 1, "event": event}))
            path.write_text("\n".join(rows), encoding="utf-8")
            before = path.read_bytes()
            cfg = AppConfig()
            result = rehearse_archive(root, cfg)
            self.assertEqual(result["events"], 60)
            self.assertGreater(result["calls"], 10)
            self.assertEqual(result["invalid_callbacks"], 0)
            dropped = rehearse_archive(root, cfg, drop_every=1)
            self.assertNotIn("callback", dropped["families"])
            self.assertEqual(dropped["invalid_callbacks"], 0)
            self.assertEqual(path.read_bytes(), before)

    def test_rehearsal_prefers_matching_saved_central_verdict_without_writing_database(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = AppConfig()
            row = {"time": 170, "damage": 35, "attacker_side": "blue", "receiver_side": "red",
                   "counter_mult": 1.0, "punch": "Jab", "hand": "left"}
            Path(root, "damage_events.jsonl").write_text(json.dumps({"round": 1, "event": row}), encoding="utf-8")
            database = Path(root, "match_archive.db")
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE events(round_no,kind,raw_json,classified_json,ruleset_version)")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (1, "damage", json.dumps(row),
                json.dumps({"counter": True, "counter_reason": "whiff", "combo_hits": 1}), FightEventEngine(cfg).ruleset_version()))
            connection.commit()
            connection.close()
            before = database.read_bytes()
            result = rehearse_archive(root, cfg)
            self.assertEqual(result["archived_verdicts"], 1)
            self.assertEqual(result["raw_reclassifications"], 0)
            self.assertIn("whiff", result["scenes"])
            self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
