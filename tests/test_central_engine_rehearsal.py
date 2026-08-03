import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from config_model import AppConfig
from timerauto import MainApp, SettingsDialog


class CentralEngineRehearsalTests(unittest.TestCase):
    @staticmethod
    def _app():
        app = SimpleNamespace(cfg=AppConfig(), _obs_stream_active=False)
        app._rehearsal_events = MethodType(MainApp._rehearsal_events, app)
        return app

    def test_preflight_exercises_all_canonical_verdicts(self):
        app = self._app()

        result = MainApp._run_central_engine_preflight(app)

        self.assertTrue(result["ok"])
        self.assertEqual(result["failed"], [])
        output = "\n".join(result["lines"])
        for verdict in ("counter_down", "graze_counter", "counter_tko", "clean_combo", "heavy", "weak_point"):
            self.assertIn(verdict, output)
        self.assertEqual(output.count("PASS"), 7)
        self.assertEqual(
            [step["label"] for step in result["visual_steps"]],
            ["헛침 카운터", "스침 카운터", "강조 콤보", "강타·약점·스턴", "다운", "TKO"],
        )
        self.assertTrue(all(step["event"] for step in result["visual_steps"]))

    def test_visual_test_shows_every_verdict_before_potm(self):
        app = self._app()
        result = MainApp._run_central_engine_preflight(app)
        emitted = []
        overlays = []
        calls = []

        class Log:
            def appendPlainText(self, text):
                calls.append(("log", text))

        class Check:
            @staticmethod
            def isChecked():
                return False

        class FakeDialog:
            _central_engine_test_token = None
            txt_rehearsal_log = Log()
            chk_rehearsal_tts = Check()

            @staticmethod
            def _emit_spectator_test_update(payload):
                emitted.append(payload)

            @staticmethod
            def _push_browser_overlay_event(kind, **payload):
                overlays.append((kind, payload))

            @staticmethod
            def _speak_tts_test_qt(*_args, **_kwargs):
                calls.append(("tts", None))

            @staticmethod
            def _test_set_spectator_info(info, extra=None):
                calls.append(("clear", info, extra))

            @staticmethod
            def _run_broadcast_rehearsal_from_settings():
                calls.append(("potm", None))

        dialog = FakeDialog()
        with patch("timerauto.QTimer.singleShot", side_effect=lambda _delay, callback: callback()):
            SettingsDialog._play_central_engine_visual_test(dialog, result)

        self.assertEqual(len(emitted), 6)
        self.assertEqual(len(overlays), 2)
        self.assertEqual(calls[-1][0], "potm")
        self.assertTrue(all(event["_test_event"] for payload in emitted for event in payload["spectator_hit_effect_events"]))

    def test_rehearsal_final_report_carries_its_own_commentary(self):
        payload = MainApp._rehearsal_report_payload(
            "BLUE", "RED", "blue", {"damage": 75, "label": "COUNTER"}
        )

        handoff = payload.get("_potmFinalCommentary", {})
        self.assertIn("BLUE", handoff.get("text", ""))
        self.assertEqual("analyst", handoff.get("role"))
        self.assertTrue(handoff.get("hide_round_report_on_complete"))


if __name__ == "__main__":
    unittest.main()
