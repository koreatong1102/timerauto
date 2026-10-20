import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QObject

from browser_overlay import BrowserOverlayServer
from config_model import AppConfig
from timerauto import MainApp


class PlayerIdentityLayoutTests(unittest.TestCase):
    def test_hud_and_vs_have_separate_nickname_and_id_nodes(self):
        html = BrowserOverlayServer()._html()
        for prefix in ("blue", "red", "vsBlue", "vsRed"):
            self.assertIn(f'id="{prefix}Nickname"', html)
            self.assertIn(f'id="{prefix}GameId"', html)
            self.assertIn(f"setText('{prefix}Nickname'", html)
        self.assertNotIn("setText('blueName',s.blueName", html)
        self.assertNotIn("setText('vsBlue',s.blueName", html)
        self.assertIn("syncPlayerIdentities(s);syncVsImages(s);", html)
        self.assertIn("if(label.textContent!==id)label.textContent=id", html)
        self.assertIn("s.showPlayerIds!==false&&id.length>0", html)
        self.assertIn(".vsName.hasPlayerId{top:650px", html)
        self.assertIn(".name.hasPlayerId{min-height:48px", html)

    def test_nickname_glyphs_have_vertical_and_italic_overhang_room(self):
        html = BrowserOverlayServer()._html()
        self.assertIn("box-sizing:border-box;line-height:1.3;padding:1px 2px", html)
        self.assertIn(".name{height:auto!important;min-height:28px", html)
        self.assertIn(".name .nicknameText{line-height:1.3}", html)
        self.assertIn(".vsName .nicknameText{line-height:1.25;padding:.04em .12em}", html)
        self.assertNotIn(".name.hasPlayerId .nicknameText{line-height:1.05}", html)

    def test_server_defaults_do_not_show_stale_or_placeholder_id(self):
        state = BrowserOverlayServer().snapshot()
        self.assertEqual("", state["bluePlayerId"])
        self.assertEqual("", state["redPlayerId"])
        self.assertTrue(state["showPlayerIds"])

    def test_visibility_setting_round_trips_and_old_config_defaults_on(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "config.json")
            Path(path).write_text("{}", encoding="utf-8")
            self.assertTrue(AppConfig.from_json(path).overlay_show_player_ids)
            cfg = AppConfig()
            cfg.overlay_show_player_ids = False
            cfg.to_json(path)
            self.assertFalse(json.loads(Path(path).read_text(encoding="utf-8"))["overlay_show_player_ids"])
            self.assertFalse(AppConfig.from_json(path).overlay_show_player_ids)


class PlayerIdentityStateTests(unittest.TestCase):
    def app(self):
        app = MainApp.__new__(MainApp)
        QObject.__init__(app)
        app.cfg = SimpleNamespace(timer_current_round=1, timer_total_rounds=3, timer_seconds_left=180)
        app.browser_overlay = Mock()
        app.browser_overlay.snapshot.return_value = {}
        app._sync_browser_overlay_player_assets = lambda data: {}
        return app

    def test_new_fighters_and_explicit_clear_replace_previous_ids(self):
        app = self.app()
        for blue, red in (("FRANCIS_NGANNOU", "BONES"), ("NEW_BLUE", "NEW_RED"), ("", "")):
            app._apply_browser_overlay_direct_update({"blue_player_id": blue, "red_player_id": red})
            state = app.browser_overlay.update.call_args.kwargs
            self.assertEqual(blue, state["bluePlayerId"])
            self.assertEqual(red, state["redPlayerId"])

    def test_toggle_is_live_and_unrelated_updates_do_not_erase_ids(self):
        app = self.app()
        app._apply_browser_overlay_direct_update({"overlay_show_player_ids": False})
        self.assertFalse(app.browser_overlay.update.call_args.kwargs["showPlayerIds"])
        app._apply_browser_overlay_direct_update({"seconds_left": 90})
        self.assertNotIn("bluePlayerId", app.browser_overlay.update.call_args.kwargs)
        self.assertNotIn("redPlayerId", app.browser_overlay.update.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
