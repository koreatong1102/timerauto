import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from timerauto import MainApp


class VsIntroPortraitTests(unittest.TestCase):
    def test_waits_for_both_late_portraits_during_intro(self):
        gate = MainApp._browser_vs_gate_action
        self.assertEqual(gate(False, False, 0.0, "intro"), "wait")
        self.assertEqual(gate(True, False, 10.0, "intro"), "wait")
        self.assertEqual(gate(True, True, 10.5, "intro"), "show")

    def test_never_falls_back_to_missing_portraits(self):
        gate = MainApp._browser_vs_gate_action
        self.assertEqual(gate(False, False, 12.0, "intro"), "wait")
        self.assertEqual(gate(True, False, 60.0, "intro"), "wait")
        self.assertEqual(gate(True, True, 12.0, "fight"), "skip")

    def _app(self):
        app = MainApp.__new__(MainApp)
        app._browser_vs_pending_since = None
        app.browser_overlay = MagicMock()
        app.browser_overlay.snapshot.return_value = {"roundState": "intro"}
        app.browser_overlay.image_path.return_value = "browser-image"
        app.spectator_watcher = SimpleNamespace(_portrait_locked={"blue": False, "red": False})
        app._log_portrait_path_for_side = MagicMock(return_value="fresh-official.png")
        return app

    def test_shows_immediately_when_second_fresh_portrait_arrives_once(self):
        app = self._app()
        with patch("timerauto.time.monotonic", return_value=42.0):
            app._update_pending_browser_vs_intro({"vs_intro_event": {}, "spectator_round_state": "intro"})
        app.spectator_watcher._portrait_locked["blue"] = True
        app._update_pending_browser_vs_intro({"spectator_round_state": "intro"})
        app.browser_overlay.push_event.assert_not_called()
        app.spectator_watcher._portrait_locked["red"] = True
        app._update_pending_browser_vs_intro({"spectator_round_state": "intro"})
        app._update_pending_browser_vs_intro({"spectator_round_state": "intro"})
        app.browser_overlay.push_event.assert_called_once_with("vs")
        self.assertIsNone(app._browser_vs_pending_since)

    def test_intro_with_missing_photos_keeps_waiting_past_twelve_seconds(self):
        app = self._app()
        with patch("timerauto.time.monotonic", return_value=42.0):
            app._update_pending_browser_vs_intro({"vs_intro_event": {}})
        with patch("timerauto.time.monotonic", return_value=72.0):
            app._update_pending_browser_vs_intro({})
        app.browser_overlay.push_event.assert_not_called()
        self.assertEqual(app._browser_vs_pending_since, 42.0)

    def test_existing_profile_or_browser_images_do_not_count_as_fresh_photos(self):
        app = self._app()
        app._update_pending_browser_vs_intro({"vs_intro_event": {}})
        app.browser_overlay.push_event.assert_not_called()

    def test_stale_official_file_cannot_use_previous_match_image(self):
        app = self._app()
        app.spectator_watcher._portrait_locked = {"blue": True, "red": True}
        app._log_portrait_path_for_side.side_effect = lambda side: "fresh.png" if side == "blue" else ""
        app._update_pending_browser_vs_intro({"vs_intro_event": {}})
        app.browser_overlay.push_event.assert_not_called()

    def test_fight_or_terminal_state_cancels_pending_even_without_state_in_payload(self):
        for state in ("fight", "break", "knockdown", "foul", "end", "results", "cancel", "knockout", "disqualified"):
            with self.subTest(state=state):
                app = self._app()
                app._update_pending_browser_vs_intro({"vs_intro_event": {}})
                app.browser_overlay.snapshot.return_value = {"roundState": state}
                app.spectator_watcher._portrait_locked = {"blue": True, "red": True}
                app._update_pending_browser_vs_intro({})
                app.browser_overlay.push_event.assert_not_called()
                self.assertIsNone(app._browser_vs_pending_since)
                app.browser_overlay.snapshot.return_value = {"roundState": "intro"}
                app._update_pending_browser_vs_intro({})
                app.browser_overlay.push_event.assert_not_called()

    def test_unknown_state_does_not_show_fullscreen_intro(self):
        self.assertEqual(MainApp._browser_vs_gate_action(True, True, 20, ""), "wait")

    def test_manual_layout_test_still_works_without_live_portraits(self):
        app = self._app()
        app.browser_overlay.snapshot.return_value = {"roundState": "fight"}
        app._update_pending_browser_vs_intro({"vs_intro_event": {"source": "settings_test"}})
        app.browser_overlay.push_event.assert_called_once_with("vs")
        self.assertIsNone(app._browser_vs_pending_since)

    def test_portraits_alone_cannot_start_an_unrequested_vs(self):
        app = self._app()
        app.spectator_watcher._portrait_locked = {"blue": True, "red": True}
        app._update_pending_browser_vs_intro({"spectator_round_state": "intro"})
        app.browser_overlay.push_event.assert_not_called()
