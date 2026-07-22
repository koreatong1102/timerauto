import os
import tempfile
import unittest
from types import SimpleNamespace

from config_model import AppConfig
from timerauto import MainApp


class RoundBreakPromoTests(unittest.TestCase):
    def _app(self, *, enabled=True, text="구독과 좋아요 부탁드려요"):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(
            spectator_break_promo_enabled=enabled,
            spectator_break_promo_text=text,
        )
        return app

    def test_promo_starts_before_round_summary_is_queued(self):
        app = self._app()
        promo_calls = []
        summary_calls = []
        app._estimate_commentary_sentence_ms = lambda _text: 1700
        app._schedule_commentary_followup_tts = lambda *args, **kwargs: promo_calls.append((args, kwargs))
        app._schedule_commentary_round_summary_tts = lambda *args, **kwargs: summary_calls.append((args, kwargs))

        MainApp._schedule_round_break_commentary_tts(
            app, "1라운드 요약입니다.", "analyst", delay_ms=2400
        )

        self.assertEqual(len(promo_calls), 1)
        promo_args, promo_kwargs = promo_calls[0]
        self.assertEqual(promo_args[:2], ("구독과 좋아요 부탁드려요", "caster"))
        self.assertEqual(promo_kwargs["delay_ms"], 2400)
        self.assertEqual(summary_calls, [])

        promo_kwargs["on_started"]()
        self.assertEqual(summary_calls[0][0][:2], ("1라운드 요약입니다.", "analyst"))
        self.assertGreaterEqual(summary_calls[0][1]["delay_ms"], 2050)

    def test_disabled_promo_keeps_direct_summary_path(self):
        app = self._app(enabled=False)
        promo_calls = []
        summary_calls = []
        app._schedule_commentary_followup_tts = lambda *args, **kwargs: promo_calls.append((args, kwargs))
        app._schedule_commentary_round_summary_tts = lambda *args, **kwargs: summary_calls.append((args, kwargs))

        MainApp._schedule_round_break_commentary_tts(
            app, "라운드 요약", "analyst", delay_ms=800
        )

        self.assertEqual(promo_calls, [])
        self.assertEqual(summary_calls[0][0][:2], ("라운드 요약", "analyst"))
        self.assertEqual(summary_calls[0][1]["delay_ms"], 800)

    def test_config_round_trip(self):
        cfg = AppConfig()
        self.assertTrue(cfg.spectator_break_promo_enabled)
        self.assertEqual(cfg.spectator_break_promo_text, "구독과 좋아요 부탁드려요")
        cfg.spectator_break_promo_enabled = False
        cfg.spectator_break_promo_text = "채널 구독 부탁드립니다"
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            cfg.to_json(path)
            loaded = AppConfig.from_json(path)
        self.assertFalse(loaded.spectator_break_promo_enabled)
        self.assertEqual(loaded.spectator_break_promo_text, "채널 구독 부탁드립니다")


if __name__ == "__main__":
    unittest.main()
