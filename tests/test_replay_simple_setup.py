import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import timerauto
from config_model import AppConfig
from timerauto import MainApp, SettingsDialog


def immediate_thread(*, target, **kwargs):
    return SimpleNamespace(start=target)


class ReplaySimpleSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = timerauto.QApplication.instance() or timerauto.QApplication([])

    def _dialog(self):
        dialog = SettingsDialog.__new__(SettingsDialog)
        timerauto.QDialog.__init__(dialog)
        dialog.cfg = AppConfig()
        dialog.tab_obs = timerauto.QWidget()
        dialog.tab_potm = timerauto.QWidget()
        dialog._schedule_apply = Mock()
        dialog._refresh_obs_status_label = Mock()
        dialog.apply_only = Mock()
        dialog._build_obs()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_real_settings_ui_builds_without_applying_preset(self):
        dialog = self._dialog()
        dialog.apply_only.assert_not_called()
        self.assertEqual(dialog.cmb_replay_simple_mode.count(), 2)
        self.assertFalse(dialog.chk_obs_potm_archive.isChecked())

    def test_broadcast_preset_aligns_all_real_controls_and_shared_folder(self):
        dialog = self._dialog()
        dialog.le_replay_simple_folder.setText("D:/Highlights")
        self.assertEqual(dialog.le_obs_source_record_archive.text(), "D:/Highlights")
        dialog.cmb_replay_simple_mode.setCurrentIndex(0)
        dialog._apply_replay_simple_setup()
        for name, value in SettingsDialog._replay_simple_preset("replay_buffer").items():
            self.assertEqual(getattr(dialog, name).isChecked(), value, name)
        self.assertEqual(dialog.cmb_potm_source.currentData(), "replay_buffer")
        self.assertEqual(dialog.cmb_obs_auto_replay_source.currentData(), "replay_buffer")
        dialog.apply_only.assert_called_once_with(silent=True)
        dialog.le_obs_source_record_archive.setText("D:/Other")
        self.assertEqual(dialog.le_replay_simple_folder.text(), "D:/Other")

    def test_game_preset_does_not_also_record_program_buffer(self):
        dialog = self._dialog()
        dialog.le_replay_simple_folder.setText("D:/Highlights")
        dialog.cmb_replay_simple_mode.setCurrentIndex(1)
        dialog._apply_replay_simple_setup()
        for name, value in SettingsDialog._replay_simple_preset("source_record").items():
            self.assertEqual(getattr(dialog, name).isChecked(), value, name)
        self.assertEqual(dialog.cmb_potm_source.currentData(), "source_record")

    def test_missing_folder_does_not_change_settings(self):
        dialog = self._dialog()
        with patch("timerauto.QMessageBox.warning") as warning:
            dialog._apply_replay_simple_setup()
        warning.assert_called_once()
        dialog.apply_only.assert_not_called()

    def test_archive_option_round_trips_and_defaults_off(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            self.assertFalse(AppConfig.from_json(path).obs_potm_archive_enabled)
            cfg = AppConfig()
            cfg.obs_potm_archive_enabled = True
            cfg.to_json(path)
            self.assertTrue(AppConfig.from_json(path).obs_potm_archive_enabled)


class PotmSourceAndArchiveTests(unittest.TestCase):
    def _app(self, root, selected="replay_buffer"):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(potm_capture_source=selected, obs_potm_archive_enabled=True,
                                  obs_source_record_archive_dir=os.path.join(root, "archive"))
        app._potm_best = {"id": "best-1", "capture_source": selected, "score": 70}
        app._potm_played = False
        app._potm_rehearsal_active = False
        app._persist_potm_candidate = Mock()
        app._maybe_play_potm = Mock()
        app._prune_source_record_archive = Mock()
        app._source_record_names = {"blue": "NEXT PLAYER"}
        return app

    def test_only_selected_source_can_register_regardless_of_arrival_order(self):
        for selected in ("replay_buffer", "source_record"):
            for order in (("replay_buffer", "source_record"), ("source_record", "replay_buffer")):
                with self.subTest(selected=selected, order=order), tempfile.TemporaryDirectory() as root:
                    app = self._app(root, selected)
                    for source in order:
                        app._register_potm_file(source + ".mp4", "best-1", capture_source=source)
                    self.assertEqual(app._potm_best["file"], selected + ".mp4")
                    app._maybe_play_potm.assert_called_once()

    def test_pending_candidate_remembers_source_when_settings_change(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            app.cfg.potm_capture_source = "source_record"
            app._register_potm_file("buffer.mp4", "best-1", capture_source="replay_buffer")
            app._register_potm_file("source.mp4", "best-1", capture_source="source_record")
            self.assertEqual(app._potm_best["file"], "buffer.mp4")

    def test_late_file_cannot_replace_file_while_potm_is_playing(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            app._potm_best["file"] = "original.mp4"
            app._potm_played = True
            app._register_potm_file("late.mp4", "best-1", capture_source="replay_buffer")
            self.assertEqual(app._potm_best["file"], "original.mp4")

    def test_final_archive_keeps_snapshot_nickname_original_and_only_one_winner(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            source = os.path.join(root, "winner.mkv")
            with open(source, "wb") as stream:
                stream.write(b"complete OBS composition")
            candidate = {"id": "unique-winner", "file": source, "side": "blue",
                         "nickname": "Actual Player", "round": 3}
            with patch("timerauto.threading.Thread", side_effect=immediate_thread):
                app._archive_final_potm(candidate)
                app._archive_final_potm(candidate)
            folder = os.path.join(app.cfg.obs_source_record_archive_dir, "Actual Player", "POTM")
            files = os.listdir(folder)
            self.assertEqual(len(files), 1)
            with open(os.path.join(folder, files[0]), "rb") as stream:
                self.assertEqual(stream.read(), b"complete OBS composition")
            self.assertTrue(os.path.isfile(source))
            self.assertFalse(os.path.exists(os.path.join(app.cfg.obs_source_record_archive_dir, "NEXT PLAYER")))

    def test_disabled_or_rehearsal_does_not_archive_any_file(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            with patch("timerauto.threading.Thread") as thread:
                app.cfg.obs_potm_archive_enabled = False
                app._archive_final_potm({"id": "winner", "file": "x"})
                app.cfg.obs_potm_archive_enabled = True
                app._potm_rehearsal_active = True
                app._archive_final_potm({"id": "winner", "file": "x"})
                thread.assert_not_called()

    def test_only_final_selected_candidate_is_archived_when_play_is_committed(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            source = os.path.join(root, "candidate.mp4")
            with open(source, "wb") as stream:
                stream.write(b"candidate")
            app._potm_best.update(file=source)
            app._potm_terminal_pending = False
            app._potm_opening_round_report_shown = True
            app._potm_play_generation = 1
            app._potm_opening_round_report_display_ms = 6000
            app._archive_final_potm = Mock()
            with patch("timerauto.QTimer.singleShot") as schedule:
                MainApp._maybe_play_potm(app)
                app._archive_final_potm.assert_not_called()
                app._potm_terminal_pending = True
                MainApp._maybe_play_potm(app)
                MainApp._maybe_play_potm(app)
                app._archive_final_potm.assert_called_once_with(app._potm_best)
                self.assertEqual(schedule.call_count, 1)


class ReplaySaveTestTests(unittest.TestCase):
    def _app(self, root):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(obs_replay_buffer_enabled=True, obs_source_record_archive_dir=root)
        app.obs_integration = SimpleNamespace(status="connected", reconfigure=Mock(),
                                             ensure_replay_buffer=Mock(), save_replay=Mock())
        return app

    def test_buffer_test_waits_ten_seconds_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            calls = []
            with patch("timerauto.QTimer.singleShot", side_effect=lambda delay, cb: calls.append((delay, cb))):
                state = app._test_replay_buffer_setup(True)
            self.assertEqual(calls[0][0], 10000)
            app.obs_integration.save_replay.assert_not_called()
            calls[0][1]()
            self.assertEqual(app.obs_integration.save_replay.call_args.kwargs["context"]["replay_setup_test_id"], state["id"])
            source = os.path.join(root, "obs.mp4")
            with open(source, "wb") as stream:
                stream.write(b"broadcast frame")
            with patch("timerauto.threading.Thread", side_effect=immediate_thread):
                app._receive_replay_setup_test(source, state["id"])
            self.assertTrue(os.path.isfile(app._test_replay_buffer_setup(False)["path"]))
            self.assertTrue(os.path.isfile(source))

    def test_disconnected_obs_is_a_clear_error_not_a_false_success(self):
        app = self._app("unused")
        app.obs_integration.status = "disconnected"
        self.assertIn("error", app._test_replay_buffer_setup(True))
        app.obs_integration.save_replay.assert_not_called()

    def test_remote_unreachable_file_has_shared_path_explanation(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            app._replay_setup_test_result = {"id": "test"}
            app._receive_replay_setup_test(os.path.join(root, "missing.mp4"), "test")
            self.assertIn("공유", app._test_replay_buffer_setup(False)["error"])

    def test_stale_test_response_does_not_replace_new_test(self):
        app = self._app("unused")
        app._replay_setup_test_result = {"id": "new"}
        app._receive_replay_setup_test("old.mp4", "old")
        self.assertEqual(app._test_replay_buffer_setup(False), {"id": "new"})

    def test_test_video_does_not_play_on_air_or_drop_other_obs_events(self):
        app = self._app("unused")
        app._receive_replay_setup_test = Mock()
        app._handle_program_auto_replay_file = Mock()
        app._copy_program_replay_to_player_archive = Mock()
        app._register_potm_file = Mock()
        app.settings_dlg = None
        app.obs_integration.drain_events = Mock(return_value=[
            {"type": "replay_file_saved", "path": "test.mp4", "context": {"replay_setup_test_id": "test"}},
            {"type": "replay_file_saved", "path": "real.mp4", "reason": "kd", "context": {"potm_candidate_id": "real"}},
        ])
        app._poll_obs_integration()
        app._receive_replay_setup_test.assert_called_once_with("test.mp4", "test")
        app._handle_program_auto_replay_file.assert_called_once_with("real.mp4", "kd", {"potm_candidate_id": "real"})
        app._register_potm_file.assert_called_once_with("real.mp4", "real", capture_source="replay_buffer")


if __name__ == "__main__":
    unittest.main()
