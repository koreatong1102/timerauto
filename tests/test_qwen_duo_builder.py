"""Offline original-duo builder checks; no downloads, torch or audio output."""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import qwen_duo_builder as builder
from commentary_pack import clip_path, ready
from local_tts import commentary_voice, decode_voice


class FakeRuntime:
    def __init__(self, device="auto"):
        self.device = "test-cpu"
        self.events = []
        self.design_calls = []
        self.clone_calls = []
        self.active = None
        self.fail_clone = False

    def load(self, model):
        self.events.append(("load", model))
        self.active = model

    def release(self):
        self.events.append(("release", self.active))
        self.active = None

    def design(self, role):
        self.design_calls.append(role)
        value = .15 if role == "caster" else .25
        return [value] * 24000, 8000

    def prompt(self, role, reference):
        self.events.append(("prompt", role))
        if not ready(reference):
            raise AssertionError("reference is not ready")
        return role

    def clone(self, text, prompt):
        self.clone_calls.append((text, prompt))
        if self.fail_clone:
            raise RuntimeError("synthesis failed")
        return [.1 if prompt == "caster" else .2] * 1600, 8000


class QwenDuoBuilderTests(unittest.TestCase):
    def setUp(self):
        # CLI entry points configure child-process defaults. Do not leak those
        # defaults into later tests whose parent Python started in CP949 mode.
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.packs = self.root / "packs"
        self.rows = [("caster", "카운터!"), ("analyst", "타이밍이 좋았어요."), ("caster", "연타 들어갑니다!")]
        for patcher in (patch("qwen_duo_builder.profile_root", return_value=self.profile),
                        patch("commentary_pack.root", return_value=self.packs),
                        patch("qwen_duo_builder.catalog", return_value=self.rows),
                        patch("commentary_pack.catalog", return_value=self.rows)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = FakeRuntime()
        self.factory = Mock(return_value=self.runtime)
        self.events = []

    def run_job(self, **kwargs):
        return builder.run_job({"config": {}}, self.events.append,
                               runtime_factory=self.factory, **kwargs)

    def config(self, revision):
        cfg = builder.candidate_config({})
        cfg.spectator_qwen_duo_revision = revision
        return cfg

    def test_complete_pack_uses_both_original_references_and_unloads_design_first(self):
        result = self.run_job()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["generated"], len(self.rows))
        self.assertEqual(self.runtime.design_calls, ["caster", "analyst"])
        self.assertEqual({role for text, role in self.runtime.clone_calls}, {"caster", "analyst"})
        design = self.runtime.events.index(("load", builder.DESIGN_MODEL))
        release = self.runtime.events.index(("release", builder.DESIGN_MODEL))
        base = self.runtime.events.index(("load", builder.CLONE_MODEL))
        self.assertLess(design, release)
        self.assertLess(release, base)
        manifest = json.loads((self.profile / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["revision"], result["revision"])
        self.assertEqual(len(result["revision"]), 64)
        cfg = self.config(result["revision"])
        for role, text in self.rows:
            path = clip_path(commentary_voice(cfg, role, ""), text)
            self.assertTrue(ready(path))
            with wave.open(str(path), "rb") as stream:
                self.assertEqual(stream.getsampwidth(), 2)
                self.assertEqual(stream.getnchannels(), 1)

    def test_repeat_click_verifies_without_loading_any_model(self):
        first = self.run_job()
        self.factory.reset_mock()
        second = self.run_job()
        self.factory.assert_not_called()
        self.assertEqual(second["generated"], 0)
        self.assertEqual(first["revision"], second["revision"])

    def test_resume_reuses_references_and_completed_clips(self):
        first = self.run_job()
        cfg = self.config(first["revision"])
        role, text = self.rows[1]
        clip_path(commentary_voice(cfg, role, ""), text).unlink()
        replacement = FakeRuntime()
        self.factory.return_value = replacement
        second = self.run_job()
        self.assertEqual(second["generated"], 1)
        self.assertEqual(replacement.design_calls, [])
        self.assertNotIn(("load", builder.DESIGN_MODEL), replacement.events)
        self.assertEqual(replacement.clone_calls, [(text, role)])

    def test_partial_cancel_keeps_valid_clips_without_activating_manifest(self):
        cancel = self.root / "cancel"
        def emit(event):
            self.events.append(event)
            if event.get("done") == 1:
                cancel.touch()
        with self.assertRaises(builder.Cancelled):
            builder.run_job({}, emit, cancel_file=cancel, runtime_factory=self.factory)
        self.assertFalse((self.profile / "manifest.json").exists())
        self.assertTrue((self.profile / "references.json").exists())
        self.assertEqual(len(list(self.packs.rglob("*.wav"))), 1)
        cancel.unlink()
        replacement = FakeRuntime()
        self.factory.return_value = replacement
        result = self.run_job()
        self.assertEqual(result["generated"], len(self.rows) - 1)
        self.assertEqual(replacement.design_calls, [])

    def test_failed_resume_does_not_replace_previous_complete_manifest(self):
        first = self.run_job()
        previous = (self.profile / "manifest.json").read_bytes()
        cfg = self.config(first["revision"])
        role, text = self.rows[-1]
        clip_path(commentary_voice(cfg, role, ""), text).unlink()
        self.runtime.fail_clone = True
        with self.assertRaisesRegex(RuntimeError, "synthesis failed"):
            self.run_job()
        self.assertEqual((self.profile / "manifest.json").read_bytes(), previous)
        self.assertIsNone(self.runtime.active)

    def test_changed_reference_has_new_revision_never_reuses_old_voice_clips(self):
        first = self.run_job()
        old_files = set(self.packs.rglob("*.wav"))
        (self.profile / "analyst_reference.wav").write_bytes(b"corrupt")
        changed = FakeRuntime()
        original = changed.design
        changed.design = lambda role: ([.35] * 24000, 8000) if role == "analyst" else original(role)
        self.factory.return_value = changed
        second = self.run_job()
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(second["generated"], len(self.rows))
        self.assertTrue(all(path.exists() for path in old_files))
        self.assertEqual(len(list(self.packs.rglob("*.wav"))), len(self.rows) * 2)

    def test_cancel_before_start_never_loads_models_or_updates_manifest(self):
        cancel = self.root / "cancel"
        cancel.touch()
        with self.assertRaises(builder.Cancelled):
            self.run_job(cancel_file=cancel)
        self.factory.assert_not_called()
        self.assertFalse((self.profile / "manifest.json").exists())

    def test_invalid_audio_never_replaces_existing_file(self):
        path = self.root / "audio.wav"
        builder._write_wave(path, [.1] * 800, 8000)
        prior = path.read_bytes()
        for values, rate in (([float("nan")] * 800, 8000), ([0.] * 800, 8000),
                             ([.1] * 5, 8000), ([.1] * 800, 1), ([.1] * 800, 8000.5)):
            with self.subTest(rate=rate, sample=values[0]):
                with self.assertRaises(ValueError):
                    builder._write_wave(path, values, rate)
                self.assertEqual(path.read_bytes(), prior)
        self.assertEqual(list(self.root.glob("duo_*")), [])

    def test_job_fields_cannot_select_arbitrary_models_or_real_voice_files(self):
        cfg = builder.candidate_config({"config": {"spectator_qwen_model": "unknown/model",
            "spectator_qwen_duo_profile": "../voice", "spectator_qwen_caster_speaker": "other.wav",
            "spectator_qwen_speed": 1.5, "spectator_qwen_caster_instruction": "pretend"}})
        self.assertEqual(cfg.spectator_qwen_duo_profile, builder.PROFILE_ID)
        self.assertEqual(cfg.spectator_qwen_model, "1.7B")
        self.assertEqual(cfg.spectator_qwen_speed, 1.)
        self.assertEqual(cfg.spectator_qwen_caster_instruction, "")
        with self.assertRaises(ValueError):
            builder.run_job({"device": "remote"}, self.events.append, runtime_factory=self.factory)
        self.factory.assert_not_called()

    def test_process_lock_refuses_concurrent_builder_and_releases_cleanly(self):
        path = self.root / "build.lock"
        with builder._exclusive(path):
            with self.assertRaisesRegex(RuntimeError, "이미 제작"):
                with builder._exclusive(path):
                    self.fail("second builder acquired lock")
        with builder._exclusive(path):
            pass

    def test_cli_records_cancelled_or_error_as_final_machine_readable_status(self):
        job = self.root / "job.json"
        progress = self.root / "progress.jsonl"
        cancel = self.root / "cancel"
        job.write_text("{}", encoding="utf-8")
        cancel.touch()
        code = builder.main(["--job", str(job), "--progress", str(progress), "--cancel", str(cancel)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(progress.read_text(encoding="utf-8").splitlines()[-1])["status"], "cancelled")
        job.write_text("[]", encoding="utf-8")
        code = builder.main(["--job", str(job), "--progress", str(progress)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(progress.read_text(encoding="utf-8").splitlines()[-1])["status"], "error")


if __name__ == "__main__":
    unittest.main()
