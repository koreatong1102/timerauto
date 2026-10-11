import os
import tempfile
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import timerauto
from spectator_log_watcher import SpectatorLogWatcher
from timerauto import MainApp


class ImmediateThread:
    def __init__(self, *, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class LobbyAutoStartRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        os.makedirs(os.path.join(self.root, "match"))
        self.state_path = os.path.join(self.root, "match", "round_state.txt")
        self.lobby_path = os.path.join(self.root, "lobby.txt")
        self._write(self.state_path, "End")
        self._lobby()
        self.cfg = SimpleNamespace(
            spectator_lobby_auto_start_enabled=True,
            spectator_lobby_auto_start_target_title="Test Spectator",
            spectator_lobby_auto_start_mode="f5",
            spectator_lobby_auto_start_delay_ms=300,
            spectator_lobby_auto_start_minimize_target=True,
            spectator_lobby_auto_start_restore_focus=True,
            spectatorlog_path=self.root,
        )
        self.watcher = SpectatorLogWatcher(self.cfg)
        self.app = MainApp.__new__(MainApp)
        self.app.cfg = self.cfg
        self.app.spectator_watcher = self.watcher
        # Reproduce the exact fault: the previous report still blocks idle video.
        self.app._match_active = True
        self.app._lobby_auto_start_lock = threading.Lock()
        self.app._lobby_auto_start_last_at = 0.0
        self.app._lobby_auto_start_input_method = "keybd_event"
        self.app._lobby_auto_start_window_lock = threading.Lock()
        self.app._lobby_auto_start_window_pending = None
        self.app._lobby_focus_guard_session = "previous-match"
        self.app._lobby_window_restore_pending_session = "previous-match"
        self.clock = 100.0
        self.signal = SimpleNamespace(emit=Mock())
        self.user32 = SimpleNamespace(
            GetForegroundWindow=Mock(return_value=800),
            ShowWindow=Mock(), IsIconic=Mock(return_value=True),
        )

    @staticmethod
    def _write(path, value):
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(value)

    def _lobby(self, *, red="RED", red_ready=True):
        self._write(self.lobby_path,
                    "slot_0: type=DesktopSpectator occupied=true name=HOST ready=false\n"
                    "slot_1: type=PlayerBlue occupied=true name=BLUE ready=true\n"
                    f"slot_2: type=PlayerRed occupied=true name={red} ready={str(red_ready).lower()}\n")

    def _sleep(self, duration):
        self.clock += duration

    def _request(self):
        out = {}
        self.watcher._apply_lobby_auto_start_edge(self.watcher._read_lobby_info(self.root), out, state="end")
        return out.get("spectator_lobby_auto_start")

    def _run(self, send_key, after=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(timerauto.time, "monotonic", side_effect=lambda: self.clock))
            stack.enter_context(patch.object(timerauto.time, "sleep", side_effect=self._sleep))
            stack.enter_context(patch.object(timerauto.threading, "Thread", ImmediateThread))
            stack.enter_context(patch.object(timerauto.ctypes, "windll", SimpleNamespace(user32=self.user32)))
            stack.enter_context(patch.object(MainApp, "_lobby_auto_start_result", self.signal))
            stack.enter_context(patch.object(timerauto, "resolve_spectatorlog_path", return_value=self.root))
            stack.enter_context(patch.object(timerauto, "_find_window_by_title_contains", return_value=700))
            activate = stack.enter_context(patch.object(timerauto, "_activate_window_reliably", return_value=(True, "ok")))
            press = stack.enter_context(patch.object(timerauto, "press_vk_for_window_title", side_effect=send_key))
            payload = self._request()
            self.app._schedule_lobby_auto_start_click(payload)
            if after:
                after()
            return press, activate

    def _late_start(self, *, blue="BLUE", red="RED"):
        self._write(self.state_path, "MatchIntro")
        for side, name in (("blue", blue), ("red", red)):
            os.makedirs(os.path.join(self.root, side), exist_ok=True)
            self._write(os.path.join(self.root, side, "name.txt"), name)
        self.app._observe_lobby_auto_start_window({"spectator_round_state": "intro"})

    def test_late_real_start_after_input_timeout_still_minimizes_once(self):
        def after():
            self.assertFalse(self.signal.emit.call_args.args[0])
            self.user32.ShowWindow.assert_not_called()
            self.clock += 1.2
            self._late_start()
            self._late_start()

        _, restore = self._run(lambda *a, **k: (True, "accepted"), after)
        self.user32.ShowWindow.assert_called_once()
        # One restoration on failure, one after the delayed real start.
        self.assertEqual(restore.call_count, 2)
        self.assertIsNone(self.app._lobby_auto_start_window_pending)

    def test_late_start_of_different_players_cannot_minimize(self):
        self._run(lambda *a, **k: (True, "accepted"), lambda: self._late_start(red="OTHER"))
        self.user32.ShowWindow.assert_not_called()
        self.assertIsNone(self.app._lobby_auto_start_window_pending)

    def test_expired_pending_start_cannot_minimize_later_match(self):
        def after():
            self.clock += 46
            self._late_start()

        self._run(lambda *a, **k: (True, "accepted"), after)
        self.user32.ShowWindow.assert_not_called()
        self.assertIsNone(self.app._lobby_auto_start_window_pending)

    def test_late_start_waits_for_rewritten_player_names(self):
        def after():
            self.app._observe_lobby_auto_start_window({"spectator_round_state": "intro"})
            self.user32.ShowWindow.assert_not_called()
            self.assertIsNotNone(self.app._lobby_auto_start_window_pending)
            self._late_start()

        self._run(lambda *a, **k: (True, "accepted"), after)
        self.user32.ShowWindow.assert_called_once()

    def test_late_start_respects_disabled_minimization(self):
        def after():
            self.cfg.spectator_lobby_auto_start_minimize_target = False
            self._late_start()

        self._run(lambda *a, **k: (True, "accepted"), after)
        self.user32.ShowWindow.assert_not_called()

    def test_report_hold_does_not_skip_f5_and_confirmed_start_minimizes(self):
        def send(*args, **kwargs):
            self._write(self.state_path, "RoundIntro")
            return True, "sent"

        press, restore = self._run(send)
        self.assertEqual(press.call_count, 1)
        self.assertEqual(press.call_args.kwargs["input_method"], "keybd_event")
        self.assertFalse(press.call_args.kwargs["minimize_target_after"])
        self.user32.ShowWindow.assert_called_once()
        self.assertEqual(self.user32.ShowWindow.call_args.args[0].value, 700)
        self.assertEqual(self.user32.ShowWindow.call_args.args[1], 6)
        restore.assert_called_once_with(800, restore=True)
        self.assertTrue(self.signal.emit.call_args.args[0])
        self.assertEqual(self.app._lobby_focus_guard_session, "")
        self.assertEqual(self.watcher._lobby_auto_start_retry_at, 0)

    def test_input_api_acceptance_is_not_a_start_confirmation(self):
        press, restore = self._run(lambda *a, **k: (True, "API accepted but no start"))
        self.assertEqual(press.call_count, 3)
        self.assertFalse(self.signal.emit.call_args.args[0])
        self.user32.ShowWindow.assert_not_called()
        self.assertGreater(self.watcher._lobby_auto_start_retry_at, self.clock)
        self.assertFalse(self.app._lobby_auto_start_lock.locked())

    def test_failed_input_gets_only_one_additional_ready_request(self):
        press, _ = self._run(lambda *a, **k: (False, "blocked"))
        self.assertEqual(press.call_count, 3)
        with patch.object(timerauto.time, "monotonic", side_effect=lambda: self.clock):
            self.assertIsNone(self._request())
            self.clock += 2.1
            retry = self._request()
            self.assertEqual(retry["attempt"], 2)
            self.watcher.lobby_auto_start_finished(retry["requestId"], False)
            self.clock += 100
            self.assertIsNone(self._request())

    def test_unready_after_input_aborts_retries_without_minimizing(self):
        def send(*a, **k):
            self._lobby(red_ready=False)
            return True, "sent"

        press, _ = self._run(send)
        self.assertEqual(press.call_count, 1)
        self.assertFalse(self.signal.emit.call_args.args[0])
        self.user32.ShowWindow.assert_not_called()

    def test_roster_changes_during_delay_abort_before_any_input(self):
        sleep = self._sleep

        def change_roster(duration):
            sleep(duration)
            self._lobby(red="NEW_RED")

        self._sleep = change_roster
        press, _ = self._run(lambda *a, **k: (True, "sent"))
        press.assert_not_called()
        self.assertFalse(self.signal.emit.call_args.args[0])
        self.user32.ShowWindow.assert_not_called()

    def test_disabled_minimization_is_respected_after_real_start(self):
        self.cfg.spectator_lobby_auto_start_minimize_target = False

        def send(*a, **k):
            self._write(self.state_path, "RoundFight")
            return True, "sent"

        press, restore = self._run(send)
        self.assertEqual(press.call_count, 1)
        self.user32.ShowWindow.assert_not_called()
        restore.assert_called_once_with(800, restore=True)

    def test_minimize_is_rechecked_and_retried_once(self):
        self.user32.IsIconic.side_effect = [False, True]

        def send(*a, **k):
            self._write(self.state_path, "MatchIntro")
            return True, "sent"

        self._run(send)
        self.assertEqual(self.user32.ShowWindow.call_count, 2)
        self.assertEqual(self.user32.IsIconic.call_count, 2)

    def test_missing_state_is_not_a_start_or_permission_to_send(self):
        self._write(self.state_path, "")
        self.assertEqual(self.app._lobby_auto_start_context(["BLUE", "RED"]), "waiting")

    def test_stale_lobby_file_does_not_emit_start_during_fight(self):
        out = {}
        self.assertFalse(self.watcher._apply_lobby_auto_start_edge(
            self.watcher._read_lobby_info(self.root), out, state="fight"))
        self.assertNotIn("spectator_lobby_auto_start", out)

    def test_old_failure_ack_cannot_rearm_a_different_pair(self):
        original = self._request()
        self._lobby(red="NEW_RED")
        replacement = self._request()
        self.assertNotEqual(original["requestId"], replacement["requestId"])
        self.watcher.lobby_auto_start_finished(original["requestId"], False)
        self.assertEqual(self.watcher._lobby_auto_start_retry_at, 0)

    def test_dropped_request_has_a_bounded_watchdog_retry(self):
        with patch.object(timerauto.time, "monotonic", side_effect=lambda: self.clock):
            self.assertEqual(self._request()["attempt"], 1)
            self.clock += 31
            self.assertEqual(self._request()["attempt"], 2)
            self.clock += 31
            self.assertIsNone(self._request())

    def test_lobby_focus_guard_stops_when_new_match_is_live(self):
        self._write(self.state_path, "RoundFight")
        self.app._lobby_focus_guard_until = 999999
        with patch.object(timerauto, "_activate_window_reliably") as activate:
            self.app._poll_lobby_focus_guard()
            self.app._restore_spectator_window_on_lobby_observed()
        activate.assert_not_called()
        self.assertEqual(self.app._lobby_focus_guard_session, "")


if __name__ == "__main__":
    unittest.main()
