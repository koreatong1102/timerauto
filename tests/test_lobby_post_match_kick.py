import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import timerauto
from timerauto import MainApp


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self._target = target

    def start(self):
        self._target()


class LobbyPostMatchKickTests(unittest.TestCase):
    def _app(self):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(
            spectator_lobby_post_match_kick_enabled=True,
            spectator_lobby_post_match_kick_delay_sec=5.0,
            spectator_lobby_auto_start_target_title="Test Spectator Window",
            spectatorlog_path="SpectatorLog",
        )
        app._lobby_post_match_kick_lock = threading.Lock()
        app._lobby_post_match_kick_last_session_id = ""
        app._lobby_restore_hwnd_by_session = {}
        app.spectator_watcher = SimpleNamespace(
            _match_session_id="match-1",
            _read_lobby_info=lambda _root: {
                "slots": [
                    {"slot": 0, "occupied": True, "name": "HOST"},
                    {"slot": 1, "occupied": True, "name": "BLUE"},
                    {"slot": 2, "occupied": True, "name": "RED"},
                ]
            },
        )
        return app

    def test_same_match_kicks_only_one_wave(self):
        app = self._app()
        calls = []

        def fake_kick(slots, title, **_kwargs):
            calls.append((list(slots), title))
            app.spectator_watcher._read_lobby_info = lambda _root: {
                "slots": [{"slot": 0, "occupied": True, "name": "HOST"}]
            }
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", return_value=None),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            payload = {"matchSessionId": "match-1"}
            app._schedule_lobby_post_match_kick(payload)
            app._schedule_lobby_post_match_kick(payload)

        self.assertEqual(
            calls,
            [([1, 2], "Test Spectator Window")],
        )

    def test_new_match_can_kick_once_again(self):
        app = self._app()
        calls = []

        def fake_kick(slots, title, **_kwargs):
            calls.append((list(slots), title))
            app.spectator_watcher._read_lobby_info = lambda _root: {
                "slots": [{"slot": 0, "occupied": True, "name": "HOST"}]
            }
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", return_value=None),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})
            app.spectator_watcher._match_session_id = "match-2"
            app.spectator_watcher._read_lobby_info = lambda _root: {
                "slots": [
                    {"slot": 0, "occupied": True, "name": "HOST"},
                    {"slot": 1, "occupied": True, "name": "BLUE"},
                    {"slot": 2, "occupied": True, "name": "RED"},
                ]
            }
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-2"})

        self.assertEqual(len(calls), 2)

    def test_uses_the_configured_lobby_settle_delay(self):
        app = self._app()
        app.cfg.spectator_lobby_post_match_kick_delay_sec = 5.5
        sleeps = []

        def fake_kick(_slots, _title, **_kwargs):
            app.spectator_watcher._read_lobby_info = lambda _root: {
                "slots": [{"slot": 0, "occupied": True, "name": "HOST"}]
            }
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})

        self.assertGreaterEqual(len(sleeps), 1)
        self.assertEqual(sleeps[0], 5.5)

    def test_retries_only_slots_that_remain_occupied(self):
        app = self._app()
        calls = []

        def fake_kick(slots, title, **_kwargs):
            calls.append((list(slots), title))
            if len(calls) == 2:
                app.spectator_watcher._read_lobby_info = lambda _root: {
                    "slots": [{"slot": 0, "occupied": True, "name": "HOST"}]
                }
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", return_value=None),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})

        self.assertEqual(calls, [
            ([1, 2], "Test Spectator Window"),
            ([1, 2], "Test Spectator Window"),
        ])

    def test_kick_keeps_spectator_open_without_restoring_previous_window(self):
        app = self._app()
        events = []
        kwargs_seen = {}
        fake_user32 = SimpleNamespace(
            GetForegroundWindow=lambda: events.append(("focus", 800)) or 800,
            ShowWindow=lambda *_args: True,
        )

        def fake_kick(_slots, _title, **kwargs):
            events.append(("kick", list(_slots)))
            kwargs_seen.update(kwargs)
            app.spectator_watcher._read_lobby_info = lambda _root: {
                "slots": [{"slot": 0, "occupied": True, "name": "HOST"}]
            }
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "_find_window_by_title_contains", return_value=700),
            patch.object(timerauto, "_activate_window_reliably", return_value=(True, "ok")),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", side_effect=lambda seconds: events.append(("sleep", seconds))),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})

        self.assertEqual(events[:2], [("sleep", 5.0), ("kick", [1, 2])])
        self.assertFalse(kwargs_seen["restore_previous"])
        self.assertFalse(kwargs_seen["minimize_target_after"])
        self.assertNotIn("previous_hwnd_override", kwargs_seen)

    def test_match_end_opens_spectator_and_leaves_it_foreground(self):
        app = self._app()
        activate = Mock(return_value=(True, "ok"))
        fake_user32 = SimpleNamespace(GetForegroundWindow=lambda: 800)
        with (
            patch.object(timerauto, "_find_window_by_title_contains", return_value=700),
            patch.object(timerauto, "_activate_window_reliably", activate),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
        ):
            app._remember_window_before_lobby_kick({"matchSessionId": "match-1"})

        activate.assert_called_once_with(700, restore=True)
        self.assertEqual(app._lobby_restore_hwnd_by_session["match-1"], 800)


class LobbyWindowInputSafetyTests(unittest.TestCase):
    def test_log_driven_kick_preserves_recovery_click_and_filters_legacy_kicks(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        app.cfg = SimpleNamespace(
            spectator_lobby_post_match_kick_enabled=True,
            pixel_rules=[
                {
                    "id": "pixel_legacy_lobby",
                    "name": "로비복귀",
                }
            ],
            actions={
                "pixel_id:pixel_legacy_lobby": [
                    {"type": "mouse_click", "x": 10, "y": 20},
                    {"type": "delay_ms", "ms": 10000},
                    {"type": "hotkey", "keys": ["k1"]},
                    {"type": "hotkey", "keys": ["k", "2"]},
                ]
            },
        )
        app._enqueue_action_run = Mock()

        app.on_pixel_rule("pixel_legacy_lobby")

        app._enqueue_action_run.assert_called_once_with(
            "pixel_id:pixel_legacy_lobby",
            [{"type": "mouse_click", "x": 10, "y": 20}],
        )

    def test_log_driven_kick_does_not_suppress_recovery_only_rule(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        app.cfg = SimpleNamespace(
            spectator_lobby_post_match_kick_enabled=True,
            pixel_rules=[
                {
                    "id": "pixel_red_return",
                    "name": "레드승리로비복귀",
                }
            ],
            actions={
                "pixel_id:pixel_red_return": [
                    {"type": "mouse_click", "x": 30, "y": 40},
                ]
            },
        )
        app._enqueue_action_run = Mock()

        app.on_pixel_rule("pixel_red_return")

        app._enqueue_action_run.assert_called_once_with(
            "pixel_id:pixel_red_return",
            [{"type": "mouse_click", "x": 30, "y": 40}],
        )

    def test_f5_is_not_sent_when_spectator_window_activation_fails(self):
        fake_user32 = SimpleNamespace(
            GetForegroundWindow=lambda: 41,
            ShowWindow=lambda *_args: True,
        )
        send_input = Mock(return_value=(True, "unexpected"))
        with (
            patch.object(timerauto.os, "name", "nt"),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
            patch.object(timerauto, "_find_window_by_title_contains", return_value=99),
            patch.object(timerauto, "_window_title", side_effect=lambda hwnd: f"window-{hwnd}"),
            patch.object(timerauto, "_activate_window_reliably", return_value=(False, "blocked")),
            patch.object(timerauto, "_press_vk_sendinput_held", send_input),
        ):
            ok, detail = timerauto.press_vk_for_window_title(
                0x74,
                "The Thrill of the Fight 2",
                activate=True,
                restore_previous=True,
                minimize_target_after=True,
            )

        self.assertFalse(ok)
        self.assertIn("activate failed", detail)
        send_input.assert_not_called()

    def test_f5_input_method_can_use_virtual_key_sendinput(self):
        fake_user32 = SimpleNamespace(
            GetForegroundWindow=lambda: 99,
            ShowWindow=lambda *_args: True,
        )
        virtual_input = Mock(return_value=(True, ""))
        scan_input = Mock(return_value=(True, "unexpected"))
        with (
            patch.object(timerauto.os, "name", "nt"),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
            patch.object(timerauto, "_find_window_by_title_contains", return_value=99),
            patch.object(timerauto, "_window_title", side_effect=lambda hwnd: f"window-{hwnd}"),
            patch.object(timerauto, "_activate_window_reliably", return_value=(True, "ok")),
            patch.object(timerauto, "_press_vk_sendinput_virtual_held", virtual_input),
            patch.object(timerauto, "_press_vk_sendinput_held", scan_input),
            patch.object(timerauto.time, "sleep", return_value=None),
        ):
            ok, detail = timerauto.press_vk_for_window_title(
                0x74,
                "The Thrill of the Fight 2",
                input_method="virtual_key",
                restore_previous=False,
            )

        self.assertTrue(ok)
        self.assertIn("method=virtual_key_sendinput", detail)
        virtual_input.assert_called_once_with(0x74, hold_sec=0.08)
        scan_input.assert_not_called()

    def test_f5_input_method_can_use_keybd_event(self):
        fake_user32 = SimpleNamespace(
            GetForegroundWindow=lambda: 99,
            ShowWindow=lambda *_args: True,
        )
        legacy_input = Mock(return_value=(True, ""))
        with (
            patch.object(timerauto.os, "name", "nt"),
            patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=fake_user32)),
            patch.object(timerauto, "_find_window_by_title_contains", return_value=99),
            patch.object(timerauto, "_window_title", side_effect=lambda hwnd: f"window-{hwnd}"),
            patch.object(timerauto, "_activate_window_reliably", return_value=(True, "ok")),
            patch.object(timerauto, "_press_vk_keybd_event_held", legacy_input),
            patch.object(timerauto.time, "sleep", return_value=None),
        ):
            ok, detail = timerauto.press_vk_for_window_title(
                0x74,
                "The Thrill of the Fight 2",
                input_method="keybd_event",
                restore_previous=False,
            )

        self.assertTrue(ok)
        self.assertIn("method=keybd_event", detail)
        legacy_input.assert_called_once_with(0x74, hold_sec=0.08)


if __name__ == "__main__":
    unittest.main()
