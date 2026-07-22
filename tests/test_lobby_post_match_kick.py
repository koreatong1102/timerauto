import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
            spectator_lobby_auto_start_target_title="The Thrill of the Fight 2",
            spectatorlog_path="SpectatorLog",
        )
        app._lobby_post_match_kick_lock = threading.Lock()
        app._lobby_post_match_kick_last_session_id = ""
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

        def fake_kick(slots, title):
            calls.append((list(slots), title))
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
            [([0, 1, 2], "The Thrill of the Fight 2")],
        )

    def test_new_match_can_kick_once_again(self):
        app = self._app()
        calls = []

        def fake_kick(slots, title):
            calls.append((list(slots), title))
            return True, "ok"

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", side_effect=fake_kick),
            patch.object(timerauto.time, "sleep", return_value=None),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})
            app.spectator_watcher._match_session_id = "match-2"
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-2"})

        self.assertEqual(len(calls), 2)

    def test_uses_the_configured_lobby_settle_delay(self):
        app = self._app()
        app.cfg.spectator_lobby_post_match_kick_delay_sec = 5.5
        sleeps = []

        with (
            patch.object(timerauto, "resolve_spectatorlog_path", return_value="SpectatorLog"),
            patch.object(timerauto, "kick_lobby_slots_for_window_title", return_value=(True, "ok")),
            patch.object(timerauto.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)),
            patch.object(timerauto.threading, "Thread", _ImmediateThread),
        ):
            app._schedule_lobby_post_match_kick({"matchSessionId": "match-1"})

        self.assertEqual(sleeps, [5.5])


if __name__ == "__main__":
    unittest.main()
