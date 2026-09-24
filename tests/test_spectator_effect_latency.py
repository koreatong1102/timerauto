import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QUrl

import timerauto
from spectator_log_watcher import SpectatorLogWatcher


class SpectatorEffectLatencyTests(unittest.TestCase):
    def test_dead_file_notifier_uses_fast_fallback_poll(self):
        watcher = SpectatorLogWatcher(SimpleNamespace(spectatorlog_backup_poll_ms=1500))
        self.assertEqual(watcher._change_wait_seconds(True), 0.25)
        watcher._change_thread = Mock()
        watcher._change_thread.is_alive.return_value = True
        watcher._change_handle = 123
        self.assertEqual(watcher._change_wait_seconds(True), 0.5)

    def test_urgent_effect_is_pushed_and_played_once(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        app.cfg = SimpleNamespace(browser_overlay_output_only=True)
        app.browser_overlay = SimpleNamespace(push_event=Mock())
        app._play_spectator_sfx = Mock()
        played, pushed = app._emit_urgent_spectator_effects({
            "spectator_effect_events": [
                {"kind": "knockdown", "side": "blue"},
                {"kind": "knockdown", "side": "blue"},
            ]
        })
        self.assertTrue(pushed)
        self.assertEqual(played, {("knockdown", "blue")})
        self.assertEqual(app.browser_overlay.push_event.call_count, 2)
        app._play_spectator_sfx.assert_called_once_with("knockdown")

    def test_short_effect_reuses_loaded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ko.wav"
            path.write_bytes(b"RIFF")
            url = QUrl.fromLocalFile(str(path))
            player = Mock()
            player.source.return_value = url
            with patch.object(timerauto, "_refresh_default_audio_device"):
                self.assertTrue(timerauto._play_media_sfx(player, Mock(), str(path)))
            player.setSource.assert_not_called()
            player.play.assert_called_once()


if __name__ == "__main__":
    unittest.main()
