import json
from pathlib import Path
import tempfile
import unittest
from config_model import AppConfig


class CameraHotkeyConfigTests(unittest.TestCase):
    def test_new_and_old_configs_do_not_claim_camera_f6(self):
        self.assertEqual(AppConfig().action_test_hotkey, "")
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/"config.json")
            for raw in ({}, {"action_test_hotkey":"F6"}, {"action_test_hotkey":" f6 "}):
                Path(path).write_text(json.dumps(raw),encoding="utf-8")
                self.assertEqual(AppConfig.from_json(path).action_test_hotkey, "")

    def test_other_explicit_test_bindings_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/"config.json")
            Path(path).write_text(json.dumps({"action_test_hotkey":"Ctrl+F8"}),encoding="utf-8")
            self.assertEqual(AppConfig.from_json(path).action_test_hotkey,"Ctrl+F8")
