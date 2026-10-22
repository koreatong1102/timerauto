"""Voice pack facts, identity and no-network playback using tiny PCM fixtures."""
import copy
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from config_model import AppConfig
from local_tts import commentary_voice, decode_voice, LocalTTSError
from commentary_pack import (catalog, clip_path, ready, build, render, usage_voice,
                             prepare_dialogue, base_voice, prepare_names)
from actions import ActionRunner
from commentary_entertainment import BGradeCommentary
from tests import test_commentary_tts_queue as queue_tests


def audio(path, sample=2, rate=24000):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(int(sample).to_bytes(2, "little", signed=True) * 100)


class CommentaryPackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name, "packs")
        patcher = patch("commentary_pack.root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = AppConfig()
        self.cfg.spectator_tts_engine = "qwen3"
        self.cfg.spectator_tts_pack_enabled = True
        self.voice = commentary_voice(self.cfg, "caster", "")

    def store(self, text, sample=2, role="caster", rate=24000):
        path = clip_path(commentary_voice(self.cfg, role, ""), text)
        audio(path, sample, rate)
        return path

    def test_corrupt_pack_file_is_regenerated(self):
        path = clip_path(self.voice, "통!")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"broken" * 20)
        result = build(self.cfg, "names", names=["통"],
                       renderer=lambda text, destination, voice: audio(destination))
        self.assertEqual(result["generated"], 2)
        self.assertTrue(ready(path))

    def test_rehearsal_is_offline_and_reports_missing_without_generating(self):
        from commentary_pack import rehearsal
        with patch("commentary_pack.save_local") as synth:
            steps, missing = rehearsal(self.cfg, names=["통"])
            self.assertFalse(steps)
            self.assertTrue(any("통!" in row for row in missing))
            self.store("카운터!")
            self.store("블루 선수!", role="analyst")
            steps, missing = rehearsal(self.cfg)
            self.assertTrue(any(s["role"] == "analyst" for s in steps))
            self.assertTrue(any(s["text"] == "카운터!" for s in steps))
            self.assertTrue(all(ready(s["media_path"]) for s in steps))
            synth.assert_not_called()

    def plan(self, name="통", side="blue"):
        original = {"focus": {"name": name, "named": True, "side": side, "scope": "match", "round": 1}}
        packet = prepare_dialogue(self.cfg, "caster", original)
        voice = usage_voice(self.cfg, "caster", "", {"kind": "live"}, packet)
        return original, packet, voice

    def test_catalog_is_unique_expands_exact_counts_and_excludes_dead_hit_jokes(self):
        rows = catalog()
        self.assertEqual(len(rows), len(set(rows)))
        self.assertEqual(len(catalog("sample")), 8)
        self.assertIn(("caster", "연타 들어갑니다!"), rows)
        self.assertIn(("caster", "연타가 멈추질 않아요!"), rows)
        self.assertFalse(any("10연타" in text or "2연타" in text for role, text in rows))
        self.assertIn(("caster", "왼쪽 눈 적중!"), rows)
        self.assertIn(("caster", "세 번째 다운!"), rows)
        self.assertIn(("caster", "이번엔 반대로 받아칩니다!"), rows)
        self.assertNotIn(("analyst", "이런 한 대를 그냥 주면 나중에 억울하죠."), rows)
        self.assertFalse(any("{" in text or "}" in text for role, text in rows))

    def test_live_bgrade_variants_are_represented_in_full_catalog(self):
        bank = BGradeCommentary()
        rows = set(catalog())
        for tag in ("counter", "combo", "counter_combo", "heavy", "weak", "stun", "knockdown", "tko"):
            for index in range(8):
                call = bank.make_call(tag, side="blue", receiver_side="red", name="통", receiver="현선호",
                                      target="왼쪽 눈", hits=3, count=2, now=1000 + index * 20)
                for turn_index, turn in enumerate(call.presentation["turns"]):
                    text = turn["text"]
                    if turn_index == 0:
                        name = call.presentation["focus"]["name"]
                        if text.startswith(name + ", "):
                            text = text[len(name) + 2:]
                    self.assertIn((turn["role"], text), rows, (tag, text))
                bank.accept_call(call)

    def test_voice_settings_separate_packs_but_port_does_not(self):
        first = clip_path(self.voice, "카운터!")
        other = copy.copy(self.cfg)
        other.spectator_qwen_port += 1
        self.assertEqual(first, clip_path(commentary_voice(other, "caster", ""), "카운터!"))
        other.spectator_qwen_caster_instruction = "Another delivery"
        self.assertNotEqual(first, clip_path(commentary_voice(other, "caster", ""), "카운터!"))

    def test_explicit_build_is_resumable_without_recreating_audio(self):
        made = []
        def renderer(text, path, voice):
            made.append((text, path))
            audio(path)
        first = build(self.cfg, "sample", renderer=renderer)
        self.assertEqual(first["done"], 8)
        self.assertTrue(first["complete"])
        self.assertEqual(len(made), 8)
        second = build(self.cfg, "sample", renderer=Mock(side_effect=AssertionError("recreated")))
        self.assertEqual(second["generated"], 0)

    def test_cancel_keeps_completed_files_and_resume_only_fills_missing(self):
        cancel = threading.Event()
        def renderer(text, path, voice):
            audio(path)
            cancel.set()
        stopped = build(self.cfg, "sample", cancel=cancel, renderer=renderer)
        self.assertFalse(stopped["complete"])
        self.assertEqual(stopped["done"], 1)
        self.assertEqual(len(list(self.root.rglob("*.wav"))), 1)
        resumed = build(self.cfg, "sample", renderer=lambda text, path, voice: audio(path))
        self.assertEqual(resumed["generated"], 7)

    def test_name_generation_is_whole_name_calls_for_both_roles(self):
        names = []
        result = build(self.cfg, "names", names=("통", "현선호", "통"),
                       renderer=lambda text, path, voice: (names.append(text), audio(path)))
        self.assertEqual(result["total"], 4)
        self.assertEqual(names.count("통!"), 2)
        self.assertTrue(ready(clip_path(self.voice, "통!")))

    def test_pack_missing_does_not_synthesize_or_fall_back_to_cloud(self):
        voice = usage_voice(self.cfg, "caster", "", {"kind": "live"})
        runner = SimpleNamespace(_ensure_tts_ready=Mock(side_effect=AssertionError("Edge")))
        with patch("local_tts.save_local", side_effect=AssertionError("Qwen")):
            self.assertFalse(ActionRunner._edge_save_cli(runner, "없는 멘트", str(Path(self.folder.name, "missing.wav")), voice, "+0%", "+0%"))
        runner._ensure_tts_ready.assert_not_called()

    def test_prepared_name_and_sentence_join_with_gap_and_no_model_request(self):
        self.store("통!", 11)
        self.store("카운터!", 22)
        original, packet, voice = self.plan()
        path = Path(self.folder.name, "joined.wav")
        with patch("local_tts.save_local", side_effect=AssertionError("network")):
            self.assertTrue(render("통, 카운터!", str(path), voice))
        self.assertEqual(packet["focus"], original["focus"])
        with wave.open(str(path), "rb") as wav:
            data = wav.readframes(wav.getnframes())
            self.assertEqual(wav.getnframes(), 200 + 1920)
            self.assertEqual(data[:2], (11).to_bytes(2, "little"))
            self.assertEqual(data[-2:], (22).to_bytes(2, "little"))

    def test_unready_name_uses_correct_corner_and_records_actual_spoken_identifier(self):
        self.store("레드 선수!", 33)
        self.store("첫 번째 다운!", 44)
        original, packet, voice = self.plan("피격 선수", "red")
        self.assertEqual(packet["focus"]["name"], "레드 선수")
        self.assertEqual(original["focus"]["name"], "피격 선수")
        self.assertEqual(packet["pack_requested_focus"]["name"], "피격 선수")
        path = Path(self.folder.name, "down.wav")
        self.assertTrue(render("피격 선수, 첫 번째 다운!", str(path), voice))
        with wave.open(str(path), "rb") as wav:
            self.assertEqual(wav.readframes(1), (33).to_bytes(2, "little"))

    def test_name_becoming_ready_changes_audio_identity_not_a_stale_corner_cache(self):
        self.store("블루 선수!")
        self.store("카운터!")
        original, packet, first = self.plan()
        self.store("통!")
        updated = prepare_dialogue(self.cfg, "caster", packet)
        second = usage_voice(self.cfg, "caster", "", {"kind": "live"}, updated)
        self.assertNotEqual(first, second)
        self.assertEqual(updated["focus"]["name"], "통")

    def test_nickname_substrings_are_never_removed_from_the_middle_of_a_sentence(self):
        self.store("블루 선수!")
        self.store("카운터!")
        _, _, voice = self.plan("카운터! 콤보, 통")
        with self.assertRaises(LocalTTSError):
            render("아무 문장 카운터! 콤보, 통, 카운터!", str(Path(self.folder.name, "bad.wav")), voice)

    def test_bare_followup_plays_without_repeating_the_name(self):
        text = "와 씨발. 일단 카운트 봅시다!"
        self.store(text)
        _, _, voice = self.plan()
        self.assertTrue(render(text, str(Path(self.folder.name, "reply.wav")), voice))

    def test_report_and_default_edge_never_enter_pack_rendering(self):
        voice = usage_voice(self.cfg, "analyst", "edge", {"kind": "report"})
        self.assertEqual(voice, "edge")
        self.cfg.spectator_tts_engine = "edge"
        self.assertEqual(usage_voice(self.cfg, "caster", "edge", {"kind": "live"}), "edge")

    def test_handoff_and_playback_use_the_same_pack_identity(self):
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app.cfg = self.cfg
        self.store("블루 선수!")
        original, packet, voice = self.plan()
        packet = prepare_dialogue(self.cfg, "caster", packet, narration_only=True)
        voice = usage_voice(self.cfg, "caster", "", {"kind": "live"}, packet)
        prepared = app._handoff_voice_settings("caster", {"_timing": {"kind": "live"}, "_dialogue": packet})[0]
        self.assertEqual(prepared, voice)
        self.assertEqual(base_voice(prepared), self.voice)

    def test_live_narration_plays_bare_call_without_name_or_corner_files(self):
        self.store("카운터!", sample=42)
        original, packet, _ = self.plan()
        packet = prepare_dialogue(self.cfg, "caster", packet, narration_only=True)
        self.assertIsNone(packet["focus"])
        self.assertEqual(original["focus"]["name"], "통")
        voice = usage_voice(self.cfg, "caster", "", {"kind": "live"}, packet)
        path = Path(self.folder.name, "bare.wav")
        render("통, 카운터!", str(path), voice)
        with wave.open(str(path), "rb") as wav:
            self.assertEqual(wav.getnframes(), 100)
            self.assertEqual(wav.readframes(1), (42).to_bytes(2, "little"))

    def test_no_automatic_name_job_until_pack_mode_is_enabled(self):
        self.cfg.spectator_tts_pack_enabled = False
        with patch("commentary_pack.threading.Thread") as thread:
            prepare_names(self.cfg, ["통", "현선호"])
        thread.assert_not_called()

    def test_different_pcm_formats_do_not_produce_invalid_combined_audio(self):
        self.store("통!", rate=24000)
        self.store("카운터!", rate=22050)
        _, _, voice = self.plan()
        path = Path(self.folder.name, "joined.wav")
        with self.assertRaises(LocalTTSError):
            render("통, 카운터!", str(path), voice)
        self.assertFalse(path.exists())
        self.assertFalse(list(Path(self.folder.name).glob("pack_*.wav")))
