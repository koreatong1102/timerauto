"""No downloads or model imports: controller, isolation and profile activation."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import qwen_duo_setup as duo
from config_model import AppConfig
from local_tts import commentary_voice, decode_voice, save_local, LocalTTSError, check_server
from commentary_pack import clip_path


class DuoSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        path = lambda *parts: str(self.root.joinpath(*parts))
        for module in ("qwen_duo_setup", "commentary_pack"):
            p = patch(module + ".app_path", side_effect=path)
            p.start()
            self.addCleanup(p.stop)
        self.cfg = AppConfig()
        self.cfg.spectator_tts_engine = "qwen3"
        self.cfg.spectator_qwen_duo_profile = duo.PROFILE_ID
        self.cfg.spectator_qwen_duo_revision = "a" * 64

    def manifest(self):
        path = self.root / ".qwen_duo_profiles" / duo.PROFILE_ID / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "complete", "profile": duo.PROFILE_ID, "revision": "a" * 64}), encoding="utf-8")
        return path

    def audio(self, role, text):
        path = clip_path(commentary_voice(self.cfg, role, ""), text)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            w.writeframes(b"\x01\x00" * 100)
        return path

    def test_manifest_alone_or_partial_catalog_does_not_enable_profile(self):
        rows = [("caster", "카운터!"), ("analyst", "타이밍이 좋았어요.")]
        with patch("commentary_pack.catalog", return_value=rows):
            self.assertFalse(duo.profile_ready())
            self.manifest()
            self.assertEqual(duo.profile_revision(), "a" * 64)
            self.assertFalse(duo.profile_ready())
            self.audio(*rows[0])
            self.assertFalse(duo.profile_ready())
            self.audio(*rows[1])
            self.assertTrue(duo.profile_ready())
            self.assertFalse(duo.profile_ready(revision="b" * 64))
            self.assertFalse(duo.profile_ready("../../elsewhere"))

    def test_profile_identity_is_stable_distinct_and_never_sent_to_customvoice(self):
        voice = commentary_voice(self.cfg, "analyst", "edge")
        opts = decode_voice(voice)
        self.assertEqual(opts["duo_revision"], "a" * 64)
        self.assertNotEqual(voice, commentary_voice(self.cfg, "caster", "edge"))
        self.cfg.spectator_qwen_analyst_speaker = "Aiden"
        self.cfg.spectator_qwen_analyst_instruction = "changed"
        self.cfg.spectator_qwen_speed = 1.5
        self.assertEqual(voice, commentary_voice(self.cfg, "analyst", "edge"))
        self.cfg.spectator_qwen_duo_revision = "b" * 64
        self.assertNotEqual(voice, commentary_voice(self.cfg, "analyst", "edge"))
        with patch("local_tts._request") as request:
            with self.assertRaisesRegex(LocalTTSError, "해설팩"):
                save_local("test", str(self.root / "no.wav"), voice)
            request.assert_not_called()

    def test_config_roundtrip_and_invalid_revision_cannot_be_used(self):
        path = self.root / "config.json"
        self.cfg.to_json(str(path))
        loaded = AppConfig.from_json(str(path))
        self.assertEqual(loaded.spectator_qwen_duo_profile, duo.PROFILE_ID)
        self.assertEqual(loaded.spectator_qwen_duo_revision, "a" * 64)
        self.cfg.spectator_qwen_duo_revision = "not-a-revision"
        with self.assertRaises(LocalTTSError):
            commentary_voice(self.cfg, "caster", "edge")

    def test_pack_profile_probe_never_contacts_a_server(self):
        with patch("qwen_duo_setup.profile_ready", return_value=True), patch("local_tts._request") as request:
            self.assertTrue(check_server(self.cfg)["pack_only"])
            request.assert_not_called()

    def test_start_is_hidden_isolated_and_does_not_export_secrets(self):
        for name in ("qwen_duo_launch.ps1", "qwen_duo_builder.py"):
            (self.root / name).touch()
        self.cfg.obs_ws_password = "must-not-leave"
        job = duo.DuoSetupJob(self.cfg)
        with patch("qwen_duo_setup.subprocess.Popen") as popen:
            job.start()
            args = popen.call_args
            self.assertIn("-NoProfile", args.args[0])
            self.assertIn("-CancelFile", args.args[0])
            self.assertEqual(args.kwargs["stdin"], -3)
            self.assertEqual(args.kwargs["env"]["HF_HOME"], str(self.root / ".qwen_models"))
        data = (job.directory / "job.json").read_text(encoding="utf-8")
        self.assertNotIn("must-not-leave", data)
        self.assertEqual(self.cfg.spectator_qwen_duo_revision, "a" * 64)
        job._close_log()

    def job_with_event(self, records):
        job = duo.DuoSetupJob(self.cfg)
        job.directory.mkdir(parents=True)
        job.progress_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        job.process = SimpleNamespace(poll=lambda: None)
        return job

    def test_cancel_wins_over_late_success_and_terminal_is_final(self):
        complete = {"status": "complete", "profile": duo.PROFILE_ID, "revision": "a" * 64}
        job = self.job_with_event([complete])
        job.cancel()
        with patch("qwen_duo_setup.profile_ready", return_value=True):
            self.assertEqual(job.poll()[0]["status"], "cancelled")
        job = self.job_with_event([{"status": "error", "message": "no"}, complete])
        self.assertEqual([r["status"] for r in job.poll()], ["error"])
        self.assertEqual(job.poll(), [])

    def test_incomplete_success_is_rejected(self):
        job = self.job_with_event([{"status": "complete", "profile": duo.PROFILE_ID, "revision": "a" * 64}])
        self.assertEqual(job.poll()[0]["status"], "error")

    def test_exit_race_re_reads_final_progress_before_failing(self):
        job = duo.DuoSetupJob(self.cfg)
        job.directory.mkdir(parents=True)
        job.process = SimpleNamespace(poll=lambda: 0)
        self.assertEqual(job.poll(), [])
        job.progress_path.write_text(json.dumps({"status": "cancelled", "message": "stopped"}) + "\n", encoding="utf-8")
        self.assertEqual(job.poll()[0]["status"], "cancelled")

    def test_settings_completion_enables_authored_pack_and_saves(self):
        from timerauto import SettingsDialog
        index = Mock()
        index.findData.return_value = 1
        checkbox = Mock()
        app = SimpleNamespace(_local_tts_controls=object(), cmb_spectator_commentary_style=index,
                              chk_spectator_commentary=checkbox, apply_only=Mock())
        SettingsDialog._apply_completed_duo_pack(app)
        index.findData.assert_called_once_with("b_grade")
        index.setCurrentIndex.assert_called_once_with(1)
        checkbox.setChecked.assert_called_once_with(True)
        app.apply_only.assert_called_once_with(silent=True)


if __name__ == "__main__":
    unittest.main()
