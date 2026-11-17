"""One-click controls are tested offscreen without a model, server or download."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


PRELUDE = '''
import sys, types
from unittest.mock import Mock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox
module = types.ModuleType("qwen_duo_setup")
module.PROFILE_ID = "ko_sports_duo_v1"
module.DuoSetupJob = Mock()
ready = {"value": False}
module.profile_ready = lambda profile=module.PROFILE_ID, revision=None: ready["value"]
module.profile_revision = lambda profile=module.PROFILE_ID: "a" * 64 if ready["value"] else ""
sys.modules["qwen_duo_setup"] = module
from config_model import AppConfig
from tts_settings import TtsEngineControls
app = QApplication([])
cfg = AppConfig()
control = TtsEngineControls(cfg)
'''


class DuoControlTests(unittest.TestCase):
    def run_ui(self, code):
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, "-c", PRELUDE + textwrap.dedent(code)],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                text=True, capture_output=True, encoding='utf-8',
                                errors='backslashreplace', timeout=30)
        self.assertEqual(result.returncode, 0, (result.stdout or '') + (result.stderr or ''))

    def test_child_failure_keeps_korean_error_instead_of_hiding_it_with_decode_error(self):
        with self.assertRaisesRegex(AssertionError, '한글 오류 메시지'):
            self.run_ui("raise RuntimeError('한글 오류 메시지')")

    def test_one_click_visible_for_existing_edge_user_and_incomplete_profile_locked(self):
        self.run_ui('''
            assert control.engine.currentData() == "edge"
            assert not control.duo_build.isHidden()
            assert control.details.isHidden()
            assert not control.voice_profile.model().item(1).isEnabled()
            assert not control.duo_stop.isEnabled()
            module.DuoSetupJob.assert_not_called()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                control.build_duo()
            module.DuoSetupJob.assert_not_called()
        ''')

    def test_complete_applies_all_fields_once_only_after_validation(self):
        self.run_ui('''
            job = Mock()
            module.DuoSetupJob.return_value = job
            job.poll.return_value = [{"status": "complete", "profile": module.PROFILE_ID, "revision": "a" * 64}] * 2
            seen, completed = [], []
            def changed():
                snapshot = control.snapshot()
                seen.append((snapshot.spectator_tts_engine, snapshot.spectator_tts_pack_enabled,
                             snapshot.spectator_qwen_duo_profile, snapshot.spectator_qwen_duo_revision))
            control.changed.connect(changed)
            control.duo_completed.connect(lambda: completed.append(True))
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                control.build_duo()
            job.start.assert_called_once()
            assert not seen and cfg.spectator_tts_engine == "edge"
            assert not control.pack_build.isEnabled() and control.duo_stop.isEnabled()
            assert not control.engine.isEnabled()
            ready["value"] = True
            control._poll_duo()
            assert seen == [("qwen3", True, module.PROFILE_ID, "a" * 64)], seen
            assert completed == [True]
            job.close.assert_called_once()
            assert cfg.spectator_tts_engine == "edge", "UI must let the owner persist atomically"
            assert not control._duo_timer.isActive() and control._duo_job is None
            assert control.duo_build.isEnabled() and not control.duo_stop.isEnabled()
            assert not control.speakers["analyst"].isEnabled()
            assert not control.model.isEnabled() and not control.speed.isEnabled()
        ''')

    def test_error_cancel_and_unverified_completion_preserve_current_settings(self):
        for status in ("error", "cancelled", "complete"):
            with self.subTest(status=status):
                self.run_ui(f'''
                    job = Mock()
                    module.DuoSetupJob.return_value = job
                    job.poll.return_value = [{{"status": {status!r}, "profile": module.PROFILE_ID,
                                               "revision": "a" * 64, "message": "not ready"}}]
                    completed = []
                    control.duo_completed.connect(lambda: completed.append(True))
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                        control.build_duo()
                    control.stop_pack()
                    job.cancel.assert_called_once()
                    control._poll_duo()
                    job.close.assert_called_once()
                    assert not completed and control.engine.currentData() == "edge"
                    assert control.voice_profile.currentData() == ""
                    assert control.duo_build.isEnabled() and not control.duo_stop.isEnabled()
                ''')

    def test_selected_duo_build_uses_worker_not_customvoice_http(self):
        self.run_ui('''
            ready["value"] = True
            cfg.spectator_tts_engine = "qwen3"
            cfg.spectator_qwen_duo_profile = module.PROFILE_ID
            cfg.spectator_qwen_duo_revision = "a" * 64
            control.load(cfg)
            control._refresh()
            with patch.object(control, "build_duo") as automatic, patch("tts_settings.check_server") as http:
                control.build_pack()
            automatic.assert_called_once()
            http.assert_not_called()
            loaded = control.snapshot()
            assert loaded.spectator_qwen_duo_revision == "a" * 64
        ''')

    def test_manual_pack_job_blocks_automatic_and_start_failure_is_recoverable(self):
        self.run_ui('''
            control._pack_running = True
            control.build_duo()
            module.DuoSetupJob.assert_not_called()
            control._pack_running = False
            module.DuoSetupJob.return_value.start.side_effect = RuntimeError("missing runtime")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                control.build_duo()
            assert control._duo_job is None and control.duo_build.isEnabled()
            assert "missing runtime" in control.duo_status.text()
            assert control.engine.currentData() == "edge"
            module.DuoSetupJob.return_value.close.assert_called_once()
        ''')

    def test_programmatic_selection_cannot_activate_incomplete_profile(self):
        self.run_ui('''
            seen = []
            control.changed.connect(lambda: seen.append(True))
            control.voice_profile.setCurrentIndex(1)
            assert control.voice_profile.currentData() == ""
            assert not seen
            assert control.snapshot().spectator_qwen_duo_profile == ""
        ''')

    def test_widget_destruction_closes_only_owned_job(self):
        self.run_ui('''
            from PyQt6.QtCore import QCoreApplication, QEvent
            job = Mock()
            module.DuoSetupJob.return_value = job
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                control.build_duo()
            control.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            job.close.assert_called_once()
        ''')

    def test_loading_incomplete_existing_profile_never_silently_changes_voice(self):
        self.run_ui('''
            cfg.spectator_tts_engine = "qwen3"
            cfg.spectator_tts_pack_enabled = True
            cfg.spectator_qwen_duo_profile = module.PROFILE_ID
            cfg.spectator_qwen_duo_revision = "b" * 64
            seen = []
            control.changed.connect(lambda: seen.append(True))
            control.load(cfg)
            assert not seen
            snapshot = control.snapshot()
            assert snapshot.spectator_qwen_duo_profile == module.PROFILE_ID
            assert snapshot.spectator_qwen_duo_revision == "b" * 64
            assert control.voice_profile.currentData() == module.PROFILE_ID
            assert control.speakers["caster"].isHidden()
            assert control.speakers["analyst"].isHidden()
        ''')


if __name__ == "__main__":
    unittest.main()
