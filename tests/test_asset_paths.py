import json
import os
import tempfile
import unittest

from app_paths import normalize_builtin_asset_path
from config_model import AppConfig, DEFAULT_OVERLAY_PRESET
from pathlib import Path


class OverlayDefaultTests(unittest.TestCase):
    def test_first_run_and_missing_style_default_to_tekken8(self):
        self.assertEqual(DEFAULT_OVERLAY_PRESET, "tekken8")
        self.assertEqual(AppConfig().overlay_preset, "tekken8")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"config.json"
            self.assertEqual(AppConfig.from_json(str(path)).overlay_preset, "tekken8")
            for value in ({}, {"overlay_preset":None}, {"overlay_preset":""}, {"overlay_preset":"invalid"}):
                path.write_text(json.dumps(value),encoding="utf8")
                self.assertEqual(AppConfig.from_json(str(path)).overlay_preset, "tekken8")

    def test_existing_explicit_style_is_preserved_across_updates_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"config.json"
            for style in ("classic", "tekken8"):
                path.write_text(json.dumps({"overlay_preset":style}),encoding="utf8")
                cfg=AppConfig.from_json(str(path))
                self.assertEqual(cfg.overlay_preset,style)
                cfg.to_json(str(path))
                self.assertEqual(AppConfig.from_json(str(path)).overlay_preset,style)

    def test_distributed_first_run_config_explicitly_uses_tekken8(self):
        build=(Path(__file__).resolve().parents[1]/"build_release.ps1").read_text(encoding="utf8")
        config=build[build.index("$releaseCfg = [ordered]@{"):build.index("$releaseCfgPath =")]
        self.assertIn('overlay_preset = "tekken8"',config)


class AssetPathCompatibilityTests(unittest.TestCase):
    def test_known_legacy_relative_assets_move_to_assets_folder(self):
        self.assertEqual(
            normalize_builtin_asset_path("KD.png"),
            os.path.join("assets", "images", "overlays", "KD.png"),
        )
        self.assertEqual(
            normalize_builtin_asset_path("level\\3.png"),
            os.path.join("assets", "images", "levels", "3.png"),
        )
        self.assertEqual(
            normalize_builtin_asset_path("stun.wav"),
            os.path.join("assets", "audio", "effects", "stun.wav"),
        )

    def test_absolute_user_selected_asset_is_not_rewritten(self):
        path = r"C:\Users\Example\custom-kd.png"
        self.assertEqual(normalize_builtin_asset_path(path), path)

    def test_old_config_paths_are_loaded_from_new_layout(self):
        payload = {
            "overlay_kd_image_path": "KD.png",
            "overlay_tko_image_path": "TKO.png",
            "spectator_stun_sfx_path": "stun.wav",
            "win_effects": {"nameplates": {"images": ["level/1.png"]}},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "config.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            cfg = AppConfig.from_json(path)

        self.assertEqual(cfg.overlay_kd_image_path, os.path.join("assets", "images", "overlays", "KD.png"))
        self.assertEqual(cfg.overlay_tko_image_path, os.path.join("assets", "images", "overlays", "TKO.png"))
        self.assertEqual(cfg.spectator_stun_sfx_path, os.path.join("assets", "audio", "effects", "stun.wav"))
        self.assertEqual(
            cfg.win_effects["nameplates"]["images"][0],
            os.path.join("assets", "images", "levels", "1.png"),
        )


if __name__ == "__main__":
    unittest.main()
