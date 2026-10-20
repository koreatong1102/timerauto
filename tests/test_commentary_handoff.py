import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from commentary_handoff import handoff_delay, importance, sentence_ends
from tests import test_commentary_tts_queue as queue_tests


class HandoffPolicyTests(unittest.TestCase):
    def test_ordinary_hit_does_not_interrupt_even_a_joke(self):
        self.assertIsNone(handoff_delay({"kind": "live", "scene": "weak"}, {"kind": "reply"}, boundaries=(100,), position_ms=0))

    def test_counter_uses_real_clause_boundary_with_bounded_wait(self):
        incoming = {"kind": "live", "category": "counter"}
        self.assertEqual(handoff_delay(incoming, {"kind": "reply"}, position_ms=1000, boundaries=(1300,)), 300)
        self.assertIsNone(handoff_delay(incoming, {"kind": "reply"}, position_ms=1000, boundaries=(1700,)))
        self.assertIsNone(handoff_delay(incoming, {"kind": "reply"}, duration_ms=4000, position_ms=1000))

    def test_natural_end_is_preferred_if_clip_is_almost_over(self):
        self.assertIsNone(handoff_delay({"kind": "live", "category": "combo"}, {"kind": "reply"}, position_ms=3800, duration_ms=4000, boundaries=(3900,)))

    def test_down_is_immediate_but_report_and_tko_are_protected(self):
        down = {"kind": "terminal", "category": "knockdown"}
        self.assertEqual(handoff_delay(down, {"kind": "reply"}), 0)
        self.assertIsNone(handoff_delay(down, {"kind": "report"}))
        self.assertIsNone(handoff_delay(down, {"kind": "terminal", "category": "tko"}))
        self.assertEqual(importance({"kind": "terminal", "category": "stun"}), 2)

    def test_sentence_ticks_and_bad_or_legacy_sidecars(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "speech.mp3")
            self.assertEqual(sentence_ends(path), ())
            metadata = Path(str(path) + ".timing.jsonl")
            rows = [{"type": "SentenceBoundary", "offset": 5_000_000, "duration": 10_000_000},
                    {"type": "WordBoundary", "offset": 1, "duration": 2}]
            metadata.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
            self.assertEqual(sentence_ends(path), (1500,))
            metadata.write_text("not json", encoding="utf-8")
            self.assertEqual(sentence_ends(path), ())


class PreparedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name, "next.mp3"))
        Path(self.path).write_bytes(b"ready audio")
        self.app = app = queue_tests.CommentaryTtsQueueTests()._app()
        app.cfg = SimpleNamespace(spectator_caster_voice="ko-KR-SunHiNeural", spectator_commentary_voice="ko-KR-InJoonNeural")
        app._commentary_players = {"caster": Mock(), "analyst": Mock()}
        app._commentary_players["analyst"].position.return_value = 1000
        app._commentary_players["analyst"].duration.return_value = 5000
        app._commentary_audio_outs = {"caster": Mock(), "analyst": Mock()}
        app._commentary_audio_outs["analyst"].volume.return_value = .8
        app._commentary_tts_cache_dir = self.folder.name
        app._commentary_tts_deliveries["analyst"] = {"kind": "reply", "boundaries": (1450,)}
        app._commentary_tts_cache_path = lambda *args: self.path
        self.now = [100.]
        self.clock = patch("timerauto.time.monotonic", side_effect=lambda: self.now[0])
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.callbacks = []
        self.timer = patch("timerauto.QTimer.singleShot", side_effect=lambda ms, fn: self.callbacks.append((ms, fn)))
        self.timer.start()
        self.addCleanup(self.timer.stop)

    def kwargs(self, *, kind="live", category="counter"):
        return {"_timing": {"kind": kind, "category": category, "created_at": 100., "expires_at": 103.2},
                "_dialogue": None, "allow_slow": False}

    def pending(self, *, category="counter", kind="live"):
        app = self.app
        kwargs = self.kwargs(kind=kind, category=category)
        app._commentary_handoff_pending = {"token": 1, "role": "caster", "text": "새 카운터!",
            "kwargs": kwargs, "settings": app._handoff_voice_settings("caster", kwargs),
            "path": self.path, "epochs": dict(app._commentary_followup_epoch), "ready": True}
        return app._commentary_handoff_pending

    def run_next(self):
        ms, fn = self.callbacks.pop(0)
        fn()
        return ms

    def test_existing_audio_is_not_stopped_before_new_audio_is_ready(self):
        app = self.app
        Path(self.path).unlink()
        app._start_commentary_handoff_worker = Mock()
        app._prepare_commentary_handoff("새 카운터!", "caster", self.kwargs())
        app._commentary_players["analyst"].stop.assert_not_called()
        self.assertFalse(app._commentary_handoff_pending["ready"])
        self.assertTrue(app._commentary_tts_busy["analyst"])

    def test_ready_counter_fades_to_sentence_end_then_switches_without_network(self):
        app = self.app
        self.pending()
        app._speak_commentary_tts = Mock()
        app._try_commentary_handoff(1)
        self.assertEqual(self.callbacks[0][0], 370)  # 450ms boundary minus 80ms fade.
        app._commentary_players["analyst"].stop.assert_not_called()
        self.run_next()
        for _ in range(3):
            self.assertEqual(self.run_next(), 20)
            app._commentary_players["analyst"].stop.assert_not_called()
        self.run_next()
        app._commentary_players["analyst"].stop.assert_called_once()
        app._speak_commentary_tts.assert_called_once()
        self.assertTrue(app._speak_commentary_tts.call_args.kwargs["_from_queue"])
        self.assertIsNone(app._commentary_handoff_pending)
        self.assertEqual(app._commentary_audio_outs["analyst"].setVolume.call_args.args[0], .8)

    def test_missing_timing_does_not_guess_word_position(self):
        self.pending()
        self.app._commentary_tts_deliveries["analyst"]["boundaries"] = ()
        self.app._try_commentary_handoff(1)
        self.assertEqual(self.callbacks[0][0], 80)
        self.app._commentary_players["analyst"].stop.assert_not_called()

    def test_emergency_has_no_clause_wait_and_a_100ms_fade(self):
        app = self.app
        self.pending(category="knockdown", kind="terminal")
        app._speak_commentary_tts = Mock()
        app._try_commentary_handoff(1)
        self.assertEqual(self.run_next(), 0)
        for _ in range(4):
            self.assertEqual(self.run_next(), 25)
        app._speak_commentary_tts.assert_called_once()

    def test_preparation_failure_never_interrupts_current_audio(self):
        self.pending()["ready"] = False
        self.app._on_commentary_handoff_ready(1, "")
        self.assertIsNone(self.app._commentary_handoff_pending)
        self.app._commentary_players["analyst"].stop.assert_not_called()

    def test_expiry_during_fade_restores_volume_without_switching(self):
        self.pending(category="knockdown", kind="terminal")
        self.app._speak_commentary_tts = Mock()
        self.app._fade_commentary_handoff(1, "analyst")
        self.run_next()
        self.now[0] = 104
        self.run_next()
        self.app._commentary_players["analyst"].stop.assert_not_called()
        self.app._speak_commentary_tts.assert_not_called()
        self.assertEqual(self.app._commentary_audio_outs["analyst"].setVolume.call_args.args[0], .8)

    def test_scene_change_potm_or_voice_change_cancels_prepared_audio(self):
        for change in ("scene", "potm", "voice"):
            with self.subTest(change=change):
                self.app._potm_presentation_active = False
                self.app.cfg.spectator_caster_voice = "ko-KR-SunHiNeural"
                self.pending()
                if change == "scene":
                    self.app._commentary_followup_epoch["caster"] += 1
                elif change == "potm":
                    self.app._potm_presentation_active = True
                else:
                    self.app.cfg.spectator_caster_voice = "different"
                self.app._try_commentary_handoff(1)
                self.assertIsNone(self.app._commentary_handoff_pending)
        self.app._commentary_players["analyst"].stop.assert_not_called()

    def test_report_is_not_interrupted_and_natural_end_consumes_ready_item(self):
        self.pending()
        self.app._commentary_tts_deliveries["analyst"] = {"kind": "report"}
        self.app._try_commentary_handoff(1)
        self.app._commentary_players["analyst"].stop.assert_not_called()
        self.app._commentary_tts_busy["analyst"] = False
        self.app._speak_commentary_tts = Mock()
        self.app._drain_commentary_tts_queue()
        self.app._speak_commentary_tts.assert_called_once()

    def test_only_one_preparation_worker_with_latest_pending_item(self):
        app = self.app
        Path(self.path).unlink()
        with patch("timerauto.threading.Thread") as worker:
            for text in ("카운터 하나", "카운터 둘", "카운터 셋"):
                app._prepare_commentary_handoff(text, "caster", self.kwargs())
            self.assertEqual(worker.call_count, 1)
            self.assertEqual(app._commentary_handoff_pending["text"], "카운터 셋")
            app._on_commentary_handoff_ready(1, self.path)
            self.assertEqual(worker.call_count, 2)
            self.assertEqual(app._commentary_handoff_worker_id, 3)

    def test_old_ready_callback_after_stop_cannot_resurrect_audio(self):
        self.pending()
        self.app._commentary_handoff_worker_id = 1
        self.app._stop_commentary_tts_role("analyst", "round_start")
        self.app._on_commentary_handoff_ready(1, self.path)
        self.assertIsNone(self.app._commentary_handoff_pending)
        self.assertFalse(self.callbacks)

    def test_ordinary_hit_does_not_preempt_an_important_pending_call(self):
        self.pending()
        self.app._speak_commentary_tts("그냥 적중", "caster", _timing={"kind": "live", "scene": "weak", "created_at": 100., "expires_at": 103.2})
        self.assertEqual(self.app._commentary_live_serial, 0)
        self.assertEqual(self.app._commentary_handoff_pending["token"], 1)
        self.assertFalse(self.app._commentary_tts_queue)

    def test_preparation_uses_same_override_values_as_playback(self):
        voice, rate, volume, pitch = self.app._handoff_voice_settings("caster", {"rate_override": 0, "pitch_override": 0})
        self.assertEqual(rate, 80)
        self.assertEqual(pitch, 0)

    def test_first_event_cache_warmup_is_bounded_to_four_named_clips(self):
        app = self.app
        app.cfg.spectator_commentary_enabled = True
        app.cfg.spectator_commentary_style = "b_grade"
        app._commentary_tts_busy = {"caster": False, "analyst": False}
        app._commentary_tts_cache_path = lambda text, *args: str(Path(self.folder.name, str(abs(hash(text))) + ".mp3"))
        app.action_runner = Mock()
        app.action_runner._ensure_tts_ready.return_value = True
        app.action_runner._edge_save_cli.return_value = True
        def run_thread(**kwargs):
            return SimpleNamespace(start=kwargs["target"])
        with patch("timerauto.threading.Thread", side_effect=run_thread), patch("timerauto.HAS_QTMULTIMEDIA", True):
            app._prewarm_commentary_emergency_calls(["통", "통", "현선호"])
        calls = app.action_runner._edge_save_cli.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("다운" in c.args[0] or "TKO" in c.args[0] for c in calls))
        self.assertEqual(sum("통" in c.args[0] for c in calls), 2)
        app._commentary_players["analyst"].play.assert_not_called()

    def test_slow_preparation_cannot_block_queue_past_its_deadline(self):
        pending = self.pending()
        pending["ready"] = False
        self.app._commentary_tts_busy["analyst"] = False
        self.app._speak_commentary_tts = Mock()
        self.app._enqueue_commentary_tts("경기 종료 리포트", "analyst", allow_slow=True)
        self.now[0] = 104
        self.app._drain_commentary_tts_queue()
        self.assertIsNone(self.app._commentary_handoff_pending)
        self.app._speak_commentary_tts.assert_called_once()

