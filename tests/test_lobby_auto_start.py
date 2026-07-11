import json
import os
import tempfile
import unittest

from config_model import AppConfig
from spectator_log_watcher import SpectatorLogWatcher


class LobbyAutoStartTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig()
        self.cfg.spectator_lobby_auto_start_enabled = True
        self.watcher = SpectatorLogWatcher(self.cfg)

    @staticmethod
    def lobby(*, blue_ready: bool, red_ready: bool, ready_to_start: bool = True):
        return {
            "ready_to_start": ready_to_start,
            "slots": [
                {"slot": 0, "occupied": True, "ready": blue_ready, "name": "BLUE"},
                {"slot": 1, "occupied": True, "ready": red_ready, "name": "RED"},
            ],
        }

    def test_fires_once_on_ready_rising_edge(self):
        first = {}
        self.assertTrue(
            self.watcher._apply_lobby_auto_start_edge(
                self.lobby(blue_ready=True, red_ready=True),
                first,
            )
        )
        self.assertEqual(first["spectator_lobby_auto_start"]["players"], ["BLUE", "RED"])

        duplicate = {}
        self.assertFalse(
            self.watcher._apply_lobby_auto_start_edge(
                self.lobby(blue_ready=True, red_ready=True),
                duplicate,
            )
        )
        self.assertNotIn("spectator_lobby_auto_start", duplicate)

    def test_rearms_after_either_player_unreadies(self):
        self.watcher._apply_lobby_auto_start_edge(
            self.lobby(blue_ready=True, red_ready=True),
            {},
        )
        self.watcher._apply_lobby_auto_start_edge(
            self.lobby(blue_ready=True, red_ready=False, ready_to_start=False),
            {},
        )
        second = {}
        self.assertTrue(
            self.watcher._apply_lobby_auto_start_edge(
                self.lobby(blue_ready=True, red_ready=True),
                second,
            )
        )

    def test_does_not_fire_without_two_ready_occupied_slots(self):
        out = {}
        self.assertFalse(
            self.watcher._apply_lobby_auto_start_edge(
                self.lobby(blue_ready=True, red_ready=False),
                out,
            )
        )
        self.assertNotIn("spectator_lobby_auto_start", out)

    def test_extra_spectator_slot_does_not_block_two_ready_players(self):
        lobby = self.lobby(blue_ready=True, red_ready=True, ready_to_start=False)
        lobby["slots"].append({"slot": 2, "occupied": True, "ready": False, "name": "SPECTATOR"})
        out = {}
        self.assertTrue(self.watcher._apply_lobby_auto_start_edge(lobby, out))
        self.assertEqual(out["spectator_lobby_auto_start"]["players"], ["BLUE", "RED"])

    def test_host_spectator_in_slot_zero_is_ignored(self):
        lobby = {
            "ready_to_start": False,
            "slots": [
                {"slot": 0, "type": "Spectator", "occupied": True, "ready": False, "name": "HOST"},
                {"slot": 1, "type": "Player", "occupied": True, "ready": True, "name": "BLUE"},
                {"slot": 2, "type": "Player", "occupied": True, "ready": True, "name": "RED"},
            ],
        }
        out = {}
        self.assertTrue(self.watcher._apply_lobby_auto_start_edge(lobby, out))
        self.assertEqual(out["spectator_lobby_auto_start"]["players"], ["BLUE", "RED"])

    def test_disabled_option_does_not_emit(self):
        self.cfg.spectator_lobby_auto_start_enabled = False
        out = {}
        self.assertFalse(
            self.watcher._apply_lobby_auto_start_edge(
                self.lobby(blue_ready=True, red_ready=True),
                out,
            )
        )
        self.assertNotIn("spectator_lobby_auto_start", out)

    def test_settings_round_trip(self):
        self.cfg.spectator_lobby_auto_start_target_title = "Spectator"
        self.cfg.spectator_lobby_auto_start_client_x = 641
        self.cfg.spectator_lobby_auto_start_client_y = 392
        self.cfg.spectator_lobby_auto_start_delay_ms = 450
        self.cfg.spectator_lobby_auto_start_click_count = 3
        self.cfg.spectator_lobby_auto_start_restore_focus = False
        self.cfg.spectator_lobby_auto_start_minimize_target = True
        self.cfg.spectator_lobby_auto_start_reference_width = 1920
        self.cfg.spectator_lobby_auto_start_reference_height = 1080
        self.cfg.spectator_final_report_delay_sec = 7.5

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "config.json")
            self.cfg.to_json(path)
            loaded = AppConfig.from_json(path)

        self.assertTrue(loaded.spectator_lobby_auto_start_enabled)
        self.assertEqual(loaded.spectator_lobby_auto_start_target_title, "Spectator")
        self.assertEqual(loaded.spectator_lobby_auto_start_client_x, 641)
        self.assertEqual(loaded.spectator_lobby_auto_start_client_y, 392)
        self.assertEqual(loaded.spectator_lobby_auto_start_delay_ms, 450)
        self.assertEqual(loaded.spectator_lobby_auto_start_click_count, 3)
        self.assertFalse(loaded.spectator_lobby_auto_start_restore_focus)
        self.assertTrue(loaded.spectator_lobby_auto_start_minimize_target)
        self.assertEqual(loaded.spectator_lobby_auto_start_reference_width, 1920)
        self.assertEqual(loaded.spectator_lobby_auto_start_reference_height, 1080)
        self.assertEqual(loaded.spectator_final_report_delay_sec, 7.5)

    def test_default_window_title_and_zero_commentary_cooldown(self):
        cfg = AppConfig()
        self.assertEqual(
            cfg.spectator_lobby_auto_start_target_title,
            "The Thrill of the Fight 2",
        )
        cfg.spectator_commentary_cooldown_sec = 0.0
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "config.json")
            cfg.to_json(path)
            loaded = AppConfig.from_json(path)
        self.assertEqual(loaded.spectator_commentary_cooldown_sec, 0.0)


class RemovedOcrConfigTests(unittest.TestCase):
    def test_legacy_ocr_settings_and_actions_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "config.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "ocr": {"samples": 5, "sim_threshold": 99},
                        "roi_blue_name": {"x": 1, "y": 2, "w": 3, "h": 4},
                        "actions": {
                            "on_trigger": [
                                {"type": "ocr_refresh"},
                                {"type": "mouse_click", "x": 10, "y": 20},
                            ],
                            "pixel:test": [{"type": "koth_winner_ocr"}],
                        },
                    },
                    stream,
                )
            cfg = AppConfig.from_json(path)
            self.assertFalse(hasattr(cfg, "ocr"))
            self.assertFalse(hasattr(cfg, "roi_blue_name"))
            self.assertEqual(
                [action["type"] for action in cfg.actions["on_trigger"]],
                ["mouse_click"],
            )
            self.assertEqual(cfg.actions.get("pixel:test", []), [])

            output_path = os.path.join(temp_dir, "saved.json")
            cfg.to_json(output_path)
            with open(output_path, "r", encoding="utf-8") as stream:
                saved = json.load(stream)
            self.assertNotIn("ocr", saved)
            self.assertNotIn("roi_blue_name", saved)


if __name__ == "__main__":
    unittest.main()
