import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from timerauto import MainApp


class RuntimeMatchResumeTests(unittest.TestCase):
    @staticmethod
    def _app():
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(spectator_sp_break_recovery_pct=30.0)
        app._browser_sp_ratio = {"blue": 1.0, "red": 1.0}
        app._browser_sp_rest_start_ratio = {"blue": 1.0, "red": 1.0}
        app._browser_sp_restored_session_id = ""
        app._browser_sp_archive_last_at = 0.0
        app._browser_sp_archive_last_sig = tuple()
        return app

    def test_live_actual_health_is_restored_exactly(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "vitals_live.json").write_text(
                json.dumps({
                    "round": 3,
                    "values": {
                        "blue": {"long": 30.0, "staminaPct": 47},
                        "red": {"long": 40.0, "staminaPct": 61},
                    },
                }),
                encoding="utf-8",
            )
            app = self._app()
            restored = app._restore_live_sp_from_match_archive({
                "id": "match-1",
                "archiveDir": root,
            })

        self.assertTrue(restored)
        self.assertEqual(app._browser_sp_ratio, {"blue": 0.47, "red": 0.61})

    def test_legacy_archive_uses_last_round_plus_break_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "vitals_live.json").write_text(
                json.dumps({
                    "round": 3,
                    "values": {
                        "blue": {"long": 30.0},
                        "red": {"long": 40.0},
                    },
                }),
                encoding="utf-8",
            )
            Path(root, "vitals_round_02.json").write_text(
                json.dumps({
                    "blue": {"staminaPct": 50},
                    "red": {"staminaPct": 60},
                }),
                encoding="utf-8",
            )
            app = self._app()
            restored = app._restore_live_sp_from_match_archive({
                "id": "legacy-match",
                "archiveDir": root,
            })

        self.assertTrue(restored)
        self.assertEqual(app._browser_sp_ratio, {"blue": 0.65, "red": 0.72})


if __name__ == "__main__":
    unittest.main()
