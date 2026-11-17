"""Grounded report stories and read-only rehearsal, never real speech."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import wave

from config_model import AppConfig
from commentary_reports import build_report_narration
from commentary_rehearsal import rehearse_archive
from commentary_pack import clip_path
from local_tts import commentary_voice
from event_engine import FightEventEngine


class ReportUpgradeTests(unittest.TestCase):
    def report(self):
        return {"round": 2,
                "blue": {"name": "통", "landed": 50, "damage": 900, "counterHits": 12,
                         "maxComboHits": 4, "maxComboDamage": 110, "knockdowns": 0},
                "red": {"name": "현선호", "landed": 30, "damage": 1200, "counterHits": 3,
                        "maxComboHits": 3, "maxComboDamage": 140, "knockdowns": 0}}

    def test_same_report_is_stable_and_never_mutated(self):
        data = self.report()
        before = copy.deepcopy(data)
        first = build_report_narration(data)
        self.assertEqual(first, build_report_narration(data))
        self.assertEqual(data, before)
        self.assertIn("길게 이은 쪽과 콤보 데미지가 높은 쪽은 달랐", first)

    def test_opening_follows_actual_core_topic_not_round_modulo(self):
        counter = self.report()
        counter["blue"].pop("damage")
        counter["red"].pop("damage")
        damage = self.report()
        a, b = build_report_narration(counter), build_report_narration(damage)
        self.assertNotEqual(a.split("공식 점수")[0].split("유효타")[0],
                            b.split("공식 점수")[0].split("유효타")[0])

    def test_missing_landed_values_do_not_fabricate_volume_damage_split(self):
        data = {"blue": {"name": "블루", "damage": 100}, "red": {"name": "레드", "damage": 200}}
        text = build_report_narration(data)
        self.assertNotIn("많이 맞힌 쪽", text)
        self.assertNotIn("유효타", text)
        self.assertIn("블루 100", text)
        self.assertIn("레드 200", text)

    def test_one_fighter_focus_leaves_room_for_other_fighters_measured_fact(self):
        data = {"round": 1,
                "blue": {"name": "블루", "landed": 40, "weakHitAll": [{"label": "왼쪽 눈", "count": 30}]},
                "red": {"name": "레드", "landed": 32, "maxPunch": {"label": "훅", "damage": 95}}}
        text = build_report_narration(data)
        self.assertIn("왼쪽 눈 적중이 30번", text)
        self.assertIn("레드 쪽 최고 펀치는 훅, 95", text)
        self.assertNotIn("레드 0", text)

    def test_verified_callback_replaces_extra_joke_and_final_never_predicts_next_round(self):
        data = self.report()
        callback = "아까 허락 얘기했죠. 카운터 기록으로 확인됐어요."
        text = build_report_narration({**data, "winner": "blue", "resultMethod": "decision"}, final=True,
                                      callback=callback)
        self.assertEqual(text.count(callback), 1)
        self.assertIn("통, 판정승", text)
        self.assertNotIn("다음 라운드", text)
        self.assertIn("공식 승자는 통", text)
        self.assertNotIn("많이 보냈다고 이자", text)


class RehearsalUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.cfg = AppConfig()

    def write(self, times):
        rows = [{"round": 1, "event": {"time": stamp, "damage": 35,
                 "attacker_side": "blue", "receiver_side": "red", "counter_mult": 1.03,
                 "punch": "Jab", "hand": "left"}} for stamp in times]
        path = self.root / "damage_events.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        return rows

    def test_elapsed_and_countdown_advance_same_simulation_without_reordering(self):
        self.write(range(0, 90, 3))
        up = rehearse_archive(self.root, self.cfg)
        self.write(range(180, 90, -3))
        down = rehearse_archive(self.root, self.cfg)
        self.assertEqual(up["simulated_span_seconds"], down["simulated_span_seconds"])
        self.assertEqual(up["calls"], down["calls"])
        self.assertEqual(up["clock_directions"], {"1": "elapsed"})
        self.assertEqual(down["clock_directions"], {"1": "remaining"})
        self.assertGreater(up["calls"], 5)
        self.assertEqual(up["mode"], "authored_script_simulation")
        self.assertFalse(up["audio_latency_measured"])

    def test_matching_saved_verdicts_outrank_raw_counter_mark_and_keep_database_unchanged(self):
        rows = self.write([180, 174, 168])
        database = self.root / "match_archive.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE events(round_no,kind,raw_json,classified_json,ruleset_version)")
            for item in rows:
                connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (1, "damage", json.dumps(item["event"]),
                    json.dumps({"counter": False, "combo_hits": 1, "tags": []}), FightEventEngine(self.cfg).ruleset_version()))
        connection.close()
        before = database.read_bytes()
        result = rehearse_archive(self.root, self.cfg)
        self.assertEqual(result["archived_verdicts"], 3)
        self.assertEqual(result["raw_reclassifications"], 0)
        self.assertFalse(any("counter" in scene for scene in result["scenes"]))
        self.assertEqual(before, database.read_bytes())

    def test_nonfinite_clock_is_counted_malformed_and_source_stays_unchanged(self):
        self.write([180, float("nan"), 170])
        path = self.root / "damage_events.jsonl"
        before = path.read_bytes()
        result = rehearse_archive(self.root, self.cfg)
        self.assertEqual(result["events"], 2)
        self.assertEqual(result["malformed"], 1)
        self.assertEqual(result["simulated_span_seconds"], 10)
        self.assertEqual(path.read_bytes(), before)

    def test_audio_audit_reads_only_existing_pcm_and_never_synthesizes(self):
        self.write(range(180, 60, -6))
        self.cfg.spectator_tts_engine = "qwen3"
        self.cfg.spectator_tts_pack_enabled = True
        with patch("commentary_pack.root", return_value=self.root / "packs"), patch("local_tts.save_local") as synth:
            initial = rehearse_archive(self.root, self.cfg)
            self.assertGreater(initial["missing_pack_turns"], 0)
            for item in initial["transcript"]:
                for turn in item["turns"]:
                    text = turn["text"]
                    for name in ("블루 선수", "레드 선수"):
                        if text.startswith(name + ", "):
                            text = text[len(name) + 2:]
                    path = clip_path(commentary_voice(self.cfg, turn["role"], ""), text)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(path), "wb") as w:
                        w.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                        w.writeframes(b"\x01\x00" * 8000)
            measured = rehearse_archive(self.root, self.cfg)
            self.assertEqual(measured["missing_pack_turns"], 0)
            self.assertGreater(measured["measured_reply_audio"], 0)
            self.assertFalse(measured["audio_latency_measured"])
            synth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
