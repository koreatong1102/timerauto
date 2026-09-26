import unittest
from unittest.mock import MagicMock

from timerauto import MainApp


class VsIntroPortraitTests(unittest.TestCase):
    def test_waits_for_both_late_portraits_during_intro(self):
        gate = MainApp._browser_vs_gate_action
        self.assertEqual(gate(False, False, 0.0, "intro"), "wait")
        self.assertEqual(gate(True, False, 10.0, "intro"), "wait")
        self.assertEqual(gate(True, True, 10.5, "intro"), "show")

    def test_falls_back_before_fight_but_never_overlays_fight(self):
        gate = MainApp._browser_vs_gate_action
        self.assertEqual(gate(False, False, 12.0, "intro"), "show")
        self.assertEqual(gate(True, True, 12.0, "fight"), "skip")

    def test_timeout_shows_name_only_intro_if_game_never_writes_portraits(self):
        app = MainApp.__new__(MainApp)
        app._browser_vs_pending_since = 42.0
        app.browser_overlay = MagicMock()
        app.browser_overlay.snapshot.return_value = {"roundState": "intro"}
        app.browser_overlay.image_path.return_value = ""
        app._expire_pending_browser_vs_intro(42.0)
        app.browser_overlay.push_event.assert_called_once_with("vs")
        self.assertIsNone(app._browser_vs_pending_since)

    def test_timeout_does_not_cover_live_fight(self):
        app = MainApp.__new__(MainApp)
        app._browser_vs_pending_since = 42.0
        app.browser_overlay = MagicMock()
        app.browser_overlay.snapshot.return_value = {"roundState": "fight"}
        app._expire_pending_browser_vs_intro(42.0)
        app.browser_overlay.push_event.assert_not_called()
