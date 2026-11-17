import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from obs_integration import ObsIntegration
from config_model import AppConfig
from idle_highlight_policy import IdleHighlightPolicy


def command(kind="", score=False):
    return {"requestType": "SaveReplayBuffer", "reason": kind or "normal",
            "context": {"auto_replay_kind": kind, "potm_candidate_id": "p" if score else ""}}


class ReplayAdmissionIdleTests(unittest.TestCase):
    def test_single_inflight_priority_and_minimum_gap(self):
        client = ObsIntegration(AppConfig())
        client._send_request = AsyncMock(side_effect=["first", "second"])
        with patch("obs_integration.time.monotonic", return_value=100):
            client._queue_replay_save(command())
            asyncio.run(client._service_replay_save(None))
            client._queue_replay_save(command("kd"))
            client._queue_replay_save(command())
            asyncio.run(client._service_replay_save(None))
        self.assertEqual(client._send_request.await_count, 1)
        self.assertEqual(client._replay_waiting["context"]["auto_replay_kind"], "kd")
        with patch("obs_integration.time.monotonic", return_value=100.8):
            asyncio.run(client._handle_message(None, {"op": 5, "d": {"eventType": "ReplayBufferSaved", "eventData": {"savedReplayPath": "first.mkv"}}}))
            asyncio.run(client._service_replay_save(None))
        self.assertEqual(client._send_request.await_count, 1)
        with patch("obs_integration.time.monotonic", return_value=101.3):
            asyncio.run(client._service_replay_save(None))
        self.assertEqual(client._send_request.await_count, 2)
        self.assertEqual(client._pending_replay_requests[0]["context"]["auto_replay_kind"], "kd")

    def test_timeout_discards_association_and_late_event_cannot_steal_new_request(self):
        client = ObsIntegration(AppConfig())
        client._pending_replay_requests.append({"request_id": "old", "sent_at": 100, "context": {"auto_replay_kind": "kd"}})
        with patch("obs_integration.time.monotonic", return_value=109):
            with self.assertRaisesRegex(RuntimeError, "timeout"):
                asyncio.run(client._service_replay_save(None))
            asyncio.run(client._handle_message(None, {"op": 5, "d": {"eventType": "ReplayBufferSaved", "eventData": {"savedReplayPath": "late.mkv"}}}))
        self.assertFalse(client._pending_replay_requests)
        self.assertFalse(any(e["type"] == "replay_file_saved" for e in client.drain_events()))

    def test_stale_pending_capture_never_saves_wrong_late_scene(self):
        client = ObsIntegration(AppConfig())
        client._send_request = AsyncMock()
        with patch("obs_integration.time.monotonic", return_value=100):
            client._queue_replay_save(command("kd"))
        with patch("obs_integration.time.monotonic", return_value=106):
            asyncio.run(client._service_replay_save(None))
        client._send_request.assert_not_awaited()

    def test_two_idle_options_independent_and_combined(self):
        cfg = AppConfig()
        p = IdleHighlightPolicy()
        lobby = {"spectator_lobby_status": {"slots": [{"occupied": True, "type": "Player"}]}}
        self.assertFalse(p.update(cfg, lobby, now=0)["idleHighlightPolicyBlocked"])
        cfg.idle_highlight_stop_on_player = True
        self.assertTrue(p.update(cfg, {}, now=0)["idleHighlightPolicyBlocked"])
        cfg.idle_highlight_stop_on_player = False
        cfg.idle_highlight_delay_enabled = True
        self.assertTrue(p.update(cfg, {"spectator_round_state": "results"}, now=10)["idleHighlightPolicyBlocked"])
        # Repeated terminal snapshots cannot keep restarting five minutes.
        self.assertFalse(p.update(cfg, {"spectator_round_state": "end"}, now=310)["idleHighlightPolicyBlocked"])
        cfg.idle_highlight_stop_on_player = True
        self.assertTrue(p.update(cfg, {}, now=311)["idleHighlightPolicyBlocked"])
        self.assertFalse(p.update(cfg, {"spectator_lobby_status": {"slots": []}}, now=311)["idleHighlightPolicyBlocked"])
        p.update(cfg, {"spectator_round_state": "fight"}, now=400)
        self.assertTrue(p.update(cfg, {"spectator_round_state": "results"}, now=410)["idleHighlightPolicyBlocked"])

    def test_host_spectator_not_fighter_and_delay_can_be_zero(self):
        cfg = AppConfig()
        cfg.idle_highlight_stop_on_player = cfg.idle_highlight_delay_enabled = True
        cfg.idle_highlight_after_match_sec = 0
        p = IdleHighlightPolicy()
        self.assertFalse(p.update(cfg, {"spectator_round_state": "end", "spectator_lobby_status": {"slots": [{"occupied": True, "type": "Host"}, {"occupied": True, "type": "Spectator"}]}}, now=0)["idleHighlightPolicyBlocked"])

    def test_policy_config_roundtrip(self):
        cfg = AppConfig()
        cfg.idle_highlight_stop_on_player = cfg.idle_highlight_delay_enabled = True
        cfg.idle_highlight_after_match_sec = 420
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d, "config.json")); cfg.to_json(p)
            loaded = AppConfig.from_json(p)
        self.assertTrue(loaded.idle_highlight_stop_on_player)
        self.assertTrue(loaded.idle_highlight_delay_enabled)
        self.assertEqual(loaded.idle_highlight_after_match_sec, 420)

    def test_policy_reaches_browser_and_does_not_stream_unused_countdown(self):
        from browser_overlay import BrowserOverlayServer
        from timerauto import MainApp
        server = BrowserOverlayServer()
        cfg = AppConfig()
        cfg.idle_highlight_delay_enabled = True
        app = SimpleNamespace(cfg=cfg, browser_overlay=server)
        with patch("idle_highlight_policy.time.monotonic", return_value=10):
            MainApp._update_idle_highlight_policy(app, {"spectator_round_state": "results"})
        self.assertTrue(server.snapshot()["idleHighlightPolicyBlocked"])
        seq = server.snapshot()["seq"]
        for now in range(11, 50):
            with patch("idle_highlight_policy.time.monotonic", return_value=now):
                MainApp._update_idle_highlight_policy(app, {})
        self.assertEqual(server.snapshot()["seq"], seq)
        with patch("idle_highlight_policy.time.monotonic", return_value=310):
            MainApp._update_idle_highlight_policy(app, {})
        self.assertFalse(server.snapshot()["idleHighlightPolicyBlocked"])
        html = server._html()
        self.assertIn("if(s.idleHighlightPolicyBlocked===true)return true", html)
        self.assertIn("if(!video.paused)video.pause()", html)

    def test_ready_backup_protected_then_replaced_and_released(self):
        from timerauto import MainApp
        from PyQt6.QtCore import QObject
        with tempfile.TemporaryDirectory() as d:
            owned = Path(d, "_potm_candidates"); owned.mkdir()
            first = owned / "first.mkv"; first.write_bytes(b"fixture")
            second = owned / "second.mkv"; second.write_bytes(b"fixture")
            original = Path(d, "original.mkv"); original.write_bytes(b"fixture")
            app = MainApp.__new__(MainApp); QObject.__init__(app)
            app.cfg = SimpleNamespace(obs_source_record_archive_dir=d)
            app._potm_best = {}
            app._set_potm_ready_fallback({"file": str(first)})
            app._release_round_highlight_files([str(first)])
            self.assertTrue(first.exists())
            app._set_potm_ready_fallback({"file": str(second)})
            self.assertFalse(first.exists())
            app._set_potm_ready_fallback({"file": str(original)})
            self.assertFalse(second.exists())
            app._set_potm_ready_fallback({})
            self.assertTrue(original.exists())

    def test_potm_uses_current_match_ready_backup_only_on_explicit_recovery(self):
        from timerauto import MainApp
        with tempfile.TemporaryDirectory() as d:
            video = Path(d, "ready.mkv"); video.write_bytes(b"fixture")
            app = SimpleNamespace(_potm_play_generation=2, _potm_played=False, _potm_terminal_pending=True,
                _potm_opening_round_report_shown=True, _potm_best={"id": "high", "score": 88},
                _potm_ready_fallback={"id": "ready", "score": 87, "file": str(video)}, _maybe_play_potm=Mock())
            MainApp._maybe_play_potm(app)
            self.assertEqual(app._potm_best["id"], "high")
            MainApp._maybe_play_potm(app, allow_ready_fallback=True)
            self.assertEqual(app._potm_best["id"], "ready")
            app._maybe_play_potm.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
