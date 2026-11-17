"""Prepared duration admission, complete roles, and same-voice delivery refs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentary_pack import (available_reply, reply_seconds, clip_path, catalog, build,
                             commentary_voice, PACK_ANNOUNCEMENTS, line_delivery)
from commentary_audio import pause_boundaries
from config_model import AppConfig
import qwen_duo_builder as builder
from tests.test_commentary_audio import audio
from tests.test_qwen_duo_builder import FakeRuntime


class PackDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cfg = AppConfig()
        self.cfg.spectator_tts_engine = "qwen3"
        self.cfg.spectator_tts_pack_enabled = True
        patcher = patch("commentary_pack.root", return_value=self.root / "packs")
        patcher.start()
        self.addCleanup(patcher.stop)

    def path(self, role, text):
        return clip_path(commentary_voice(self.cfg, role, ""), text)

    def test_admission_uses_real_duration_and_never_synthesizes_missing_audio(self):
        with patch("commentary_pack.save_local", side_effect=AssertionError("runtime synthesis")):
            self.assertFalse(available_reply(self.cfg, "analyst", "없는 멘트"))
            audio(self.path("analyst", "긴 멘트"), 4.)
            self.assertEqual(reply_seconds(self.cfg, "analyst", "긴 멘트"), 4.)
            self.assertFalse(available_reply(self.cfg, "analyst", "긴 멘트", max_seconds=1.8))
            self.assertTrue(available_reply(self.cfg, "analyst", "긴 멘트", max_seconds=4.))
            self.assertFalse(available_reply(self.cfg, "caster", "긴 멘트"))
            self.assertFalse(available_reply(self.cfg, "analyst", "긴 멘트", max_seconds=float("nan")))
        self.cfg.spectator_tts_pack_enabled = False
        self.assertTrue(available_reply(self.cfg, "analyst", "기존 TTS", max_seconds=1.))

    def test_full_catalog_covers_terminal_leads_for_both_speakers_and_announcements(self):
        rows = set(catalog("full"))
        for text in PACK_ANNOUNCEMENTS:
            self.assertIn(("caster", text), rows)
        for role in ("caster", "analyst"):
            for text in ("흔들립니다!", "첫 번째 다운!", "TKO! 경기 끝!", "이번엔 반대로 받아칩니다!"):
                self.assertIn((role, text), rows)
        self.assertEqual(len(catalog("sample")), 8)
        self.assertEqual(len(rows), len(catalog("full")))

    def test_explicit_build_measures_existing_audio_without_regeneration(self):
        rows = [("caster", "카운터!"), ("analyst", "설명입니다.")]
        for role, text in rows:
            audio(self.path(role, text), 1.)
        with patch("commentary_pack.catalog", return_value=rows), patch("commentary_pack.save_local", side_effect=AssertionError("regenerated")):
            result = build(self.cfg)
        self.assertEqual(result["generated"], 0)
        self.assertTrue(Path(str(self.path(*rows[0])) + ".delivery.json").exists())
        self.assertEqual(pause_boundaries(self.path(*rows[0])), ())

    def test_authored_delivery_is_exact_text_not_keyword_guessing(self):
        self.assertEqual(line_delivery("caster", "카운터!"), "surprised")
        self.assertEqual(line_delivery("caster", "첫 번째 다운!"), "excited")
        self.assertEqual(line_delivery("caster", "카운터라는 닉네임입니다"), "neutral")

    def test_style_refs_reuse_same_original_voice_and_get_an_isolated_revision(self):
        class StyleRuntime(FakeRuntime):
            supports_delivery_references = True
            instances = []

            def __init__(self, device="auto"):
                super().__init__(device)
                self.__class__.instances.append(self)

            def clone(self, text, prompt):
                self.clone_calls.append((text, prompt))
                # Long references remain the SAME role passed as base prompt.
                is_reference = any(text in rows.values() for rows in builder.DELIVERY_TEXTS.values())
                return [.1] * (24000 if is_reference else 1600), 8000

            def delivery_prompt(self, reference, text):
                role, delivery, _suffix = reference.stem.split("_", 2)
                return (role, delivery)

        rows = [("caster", "카운터!"), ("analyst", "설명입니다.")]
        events = []
        with patch("qwen_duo_builder.profile_root", return_value=self.root / "profile"), patch("qwen_duo_builder.catalog", return_value=rows), patch("commentary_pack.catalog", return_value=rows):
            first = builder.run_job({}, events.append, runtime_factory=StyleRuntime)
            runtime = StyleRuntime.instances[0]
            self.assertEqual(runtime.design_calls, ["caster", "analyst"])
            self.assertIn(("카운터!", ("caster", "surprised")), runtime.clone_calls)
            for role, texts in builder.DELIVERY_TEXTS.items():
                for text in texts.values():
                    self.assertIn((text, role), runtime.clone_calls)
            refs = json.loads((self.root / "profile" / "references.json").read_text(encoding="utf-8"))
            self.assertTrue(builder._deliveries_ready(self.root / "profile", refs))
            plain = copy.deepcopy(refs)
            plain.pop("deliveries")
            self.assertNotEqual(first["revision"], builder._revision(plain, refs["signature"]))
            second = builder.run_job({}, events.append, runtime_factory=StyleRuntime)
            self.assertEqual(second["generated"], 0)
            self.assertEqual(len(StyleRuntime.instances), 1)
            self.assertEqual(first["revision"], second["revision"])


if __name__ == "__main__":
    unittest.main()
