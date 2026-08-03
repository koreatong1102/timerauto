import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import screen_watcher
import timerauto
from config_model import AppConfig
from screen_watcher import ScreenWatcher
from timerauto import MainApp


class _FakeMss:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ScreenWatcherForegroundTests(unittest.TestCase):
    def test_paused_foreground_clears_stale_detection_windows(self):
        watcher = ScreenWatcher(AppConfig(), foreground_guard=lambda: False)
        watcher._window[:] = [True, True]
        watcher._trigger_level_active = True
        watcher._pixel_state["rule"] = {
            "window": [True],
            "level_active": True,
            "last_hit": True,
        }

        watcher._pause_detection_state()

        self.assertEqual(watcher._window, [])
        self.assertFalse(watcher._trigger_level_active)
        self.assertEqual(watcher._pixel_state["rule"]["window"], [])
        self.assertFalse(watcher._pixel_state["rule"]["level_active"])
        self.assertFalse(watcher._pixel_state["rule"]["last_hit"])

    def test_capture_loop_does_not_sample_when_spectator_is_not_foreground(self):
        watcher = ScreenWatcher(AppConfig(), foreground_guard=lambda: False)
        watcher.set_detection_modes(trigger=True, pixel=True)
        stop_event = threading.Event()
        watcher._check_pixel_rules = Mock()

        def stop_after_first_cycle(_seconds):
            stop_event.set()

        with (
            patch.object(screen_watcher.mss, "mss", return_value=_FakeMss()),
            patch.object(screen_watcher.time, "sleep", side_effect=stop_after_first_cycle),
        ):
            watcher._run(stop_event)

        watcher._check_pixel_rules.assert_not_called()
        self.assertTrue(watcher._foreground_paused)

    def test_main_app_matches_only_configured_spectator_foreground_window(self):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(
            spectator_lobby_auto_start_target_title="The Thrill of the Fight 2"
        )
        app._screen_detect_target_title_cache = ""
        app._screen_detect_target_hwnd_cache = 0
        app._screen_detect_target_checked_at = 0.0
        active = {"hwnd": 700}
        fake_user32 = SimpleNamespace(
            IsWindow=lambda _hwnd: True,
            GetForegroundWindow=lambda: active["hwnd"],
        )

        with (
            patch.object(timerauto.os, "name", "nt"),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
            patch.object(timerauto, "_find_window_by_title_contains", return_value=700),
        ):
            self.assertTrue(app._screen_detection_target_is_foreground())
            active["hwnd"] = 800
            self.assertFalse(app._screen_detection_target_is_foreground())


if __name__ == "__main__":
    unittest.main()
