import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QImage

from browser_overlay import BrowserOverlayServer
from spectator_log_watcher import SpectatorLogWatcher
from timerauto import MainApp
from venue_backgrounds import VENUES, normalize_venue_id, venue_from_update


class VenueBackgroundTests(unittest.TestCase):
    def test_all_five_ids_map_to_supplied_assets_and_decode(self):
        server = BrowserOverlayServer()
        expected = ["home_gym.png", "night_gym.jpg", "hotel.png", "memorial_hall.png", "philly_parkway.jpg"]
        for venue_id, filename in enumerate(expected):
            self.assertEqual(filename, Path(VENUES[venue_id][1]).name)
            path = server.asset_path(f"venue{venue_id}")
            self.assertEqual(filename, Path(path).name)
            self.assertFalse(QImage(path).isNull())
            self.assertGreater(server.snapshot()[f"venue{venue_id}Rev"], 0)
        self.assertIsNone(server.snapshot()["venueId"])

    def test_zero_is_valid_and_unknown_id_does_not_select_previous_map(self):
        self.assertEqual(0, normalize_venue_id(0))
        self.assertEqual(0, normalize_venue_id("0"))
        for value in (None, "", "5", -1, True, "../image", "hotel"):
            self.assertIsNone(normalize_venue_id(value))
        self.assertEqual((False, None), venue_from_update({"seconds_left": 150}))
        self.assertEqual((True, None), venue_from_update({"venue_id": 99}))

    def test_intro_venue_has_priority_over_previous_lobby(self):
        self.assertEqual((True, 2), venue_from_update({"vs_intro_event": {"venueId": 2}, "spectator_lobby_status": {"venueId": 1}}))

    def test_original_first_background_layer_and_portraits_are_preserved(self):
        html = BrowserOverlayServer()._html()
        vs = html[html.index('<div id="vs" class="fullscreen vs">'):]
        self.assertLess(vs.index('id="vsBg"'), vs.index('class="dark"'))
        self.assertLess(vs.index('id="vsBg"'), vs.index('id="vsBlueImg"'))
        self.assertIn("function syncVsVenueBackground(s){", html)
        self.assertIn("syncVsVenueBackground(s);syncPlayerIdentities(s);syncVsImages(s);", html)
        self.assertIn("known?'venue'+id:'vsbg'", html)
        self.assertIn("bg.removeAttribute('src')", html)
        self.assertIn("bg.onerror=", html)
        self.assertNotIn("if((s.vsbgRev||0)>0)", html[html.index("function showVs(s){"):html.index("function syncVsImages(s){")])

    def test_live_update_and_intro_reach_browser_without_extra_portrait_work(self):
        app = MainApp.__new__(MainApp)
        QObject.__init__(app)
        app.cfg = SimpleNamespace(timer_current_round=1, timer_total_rounds=3, timer_seconds_left=180)
        app.browser_overlay = Mock()
        app.browser_overlay.snapshot.return_value = {"venueId": 4}
        app._sync_browser_overlay_player_assets = lambda data: {}
        app._update_pending_browser_vs_intro = lambda data: None
        for venue in range(5):
            app._apply_browser_overlay_direct_update({"spectator_lobby_status": {"venueId": venue}})
            self.assertEqual(venue, app.browser_overlay.update.call_args.kwargs["venueId"])
        app._apply_browser_overlay_direct_update({"vs_intro_event": {"venueId": 0}})
        self.assertEqual(0, app.browser_overlay.update.call_args.kwargs["venueId"])
        app._apply_browser_overlay_direct_update({"venue_id": 99})
        self.assertIsNone(app.browser_overlay.update.call_args.kwargs["venueId"])
        app._apply_browser_overlay_direct_update({"seconds_left": 150})
        self.assertNotIn("venueId", app.browser_overlay.update.call_args.kwargs)

    def test_temporary_lobby_rewrite_does_not_lose_venue_zero(self):
        watcher = SpectatorLogWatcher.__new__(SpectatorLogWatcher)
        watcher._remember_lobby_settings({"venue_id": 0})
        watcher._remember_lobby_settings({"rounds": 3})
        self.assertEqual(0, watcher._last_lobby_venue_id)
        watcher._remember_lobby_settings({"venue_id": 4})
        self.assertEqual(4, watcher._last_lobby_venue_id)
        watcher._remember_lobby_settings({"venue_id": -1})
        self.assertEqual(-1, watcher._last_lobby_venue_id)
