import asyncio
import json
import os
import socket
import tempfile
import unittest
from urllib.request import Request, urlopen

from browser_overlay import BrowserOverlayServer
from config_model import AppConfig
from obs_auto_replay import ObsAutoReplayController
from obs_integration import ObsIntegration, ObsSettings, build_obs_auth, source_record_hotkey_context, source_record_source_name


class ObsHighlightIntegrationTests(unittest.TestCase):
    def test_source_record_scene_name_converts_to_obs_filter_context(self):
        self.assertEqual(source_record_hotkey_context("장면 2"), "장면 2 - Source Record")
        self.assertEqual(
            source_record_hotkey_context("장면 2 - Source Record"),
            "장면 2 - Source Record",
        )
        self.assertEqual(source_record_source_name("장면 2 - Source Record"), "장면 2")

    def test_auto_replay_uses_event_relative_delay_and_config(self):
        class FakeOverlay:
            def __init__(self):
                self.calls = []

            def play_obs_replay(self, path, **options):
                self.calls.append((path, options))
                return "token-1"

            def stop_obs_replay(self):
                return True

        cfg = AppConfig()
        cfg.obs_auto_replay_delay_sec = 2.0
        cfg.obs_auto_replay_muted = False
        cfg.obs_auto_replay_volume = 64
        cfg.obs_auto_replay_fit = "contain"
        cfg.obs_auto_replay_fade_ms = 220
        overlay = FakeOverlay()
        clock = [100.0]
        scheduled = []
        controller = ObsAutoReplayController(
            lambda: cfg,
            lambda: overlay,
            lambda delay, callback: scheduled.append((delay, callback)),
            clock=lambda: clock[0],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            replay = os.path.join(temp_dir, "replay.mp4")
            open(replay, "wb").close()
            self.assertTrue(
                controller.schedule(
                    replay,
                    "knockdown",
                    {"auto_replay_kind": "kd", "trigger_monotonic": 99.0},
                )
            )
            self.assertEqual(scheduled[0][0], 1000)
            scheduled[0][1]()
        self.assertEqual(len(overlay.calls), 1)
        self.assertFalse(overlay.calls[0][1]["muted"])
        self.assertEqual(overlay.calls[0][1]["volume"], 64)
        self.assertEqual(overlay.calls[0][1]["fit"], "contain")
        self.assertEqual(overlay.calls[0][1]["fade_ms"], 220)

    def test_auto_replay_cancel_blocks_pending_and_late_saved_files(self):
        class FakeOverlay:
            def __init__(self):
                self.play_count = 0
                self.stop_count = 0

            def play_obs_replay(self, path, **options):
                self.play_count += 1
                return "token"

            def stop_obs_replay(self):
                self.stop_count += 1
                return True

        cfg = AppConfig()
        clock = [100.0]
        scheduled = []
        overlay = FakeOverlay()
        controller = ObsAutoReplayController(
            lambda: cfg,
            lambda: overlay,
            lambda delay, callback: scheduled.append(callback),
            clock=lambda: clock[0],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            replay = os.path.join(temp_dir, "replay.mp4")
            open(replay, "wb").close()
            self.assertTrue(
                controller.schedule(
                    replay,
                    "knockdown",
                    {"auto_replay_kind": "kd", "trigger_monotonic": 100.0},
                )
            )
            clock[0] = 100.5
            controller.cancel("next_round")
            scheduled[0]()
            self.assertEqual(overlay.play_count, 0)
            self.assertFalse(
                controller.schedule(
                    replay,
                    "knockdown",
                    {"auto_replay_kind": "kd", "trigger_monotonic": 100.25},
                )
            )
        self.assertEqual(overlay.stop_count, 1)

    def test_obs_auth_matches_known_websocket_v5_vector(self):
        self.assertEqual(
            build_obs_auth("secret", "salt", "challenge"),
            "39cfhx7et2iyoMZvoQ6o3OPLNSKgtMmy48GQ7jnvsdE=",
        )

    def test_obs_settings_are_normalized(self):
        cfg = AppConfig()
        cfg.obs_integration_enabled = True
        cfg.obs_host = "  localhost  "
        cfg.obs_port = 99999
        settings = ObsSettings.from_config(cfg)
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.host, "localhost")
        self.assertEqual(settings.port, 65535)

    def test_unchanged_obs_settings_do_not_force_reconnect(self):
        cfg = AppConfig()
        client = ObsIntegration(cfg)
        client.start = lambda: None
        client.reconfigure(cfg)
        self.assertEqual(client._commands.qsize(), 0)
        cfg.obs_port = 4456
        client.reconfigure(cfg)
        self.assertEqual(client._commands.qsize(), 1)

    def test_config_round_trip_preserves_obs_and_idle_highlight_options(self):
        cfg = AppConfig()
        cfg.obs_integration_enabled = True
        cfg.obs_host = "192.0.2.10"
        cfg.obs_port = 4460
        cfg.obs_replay_buffer_enabled = True
        cfg.obs_replay_buffer_auto_start = False
        cfg.obs_highlight_counter_damage_min = 37.5
        cfg.obs_highlight_combo_min = 5
        cfg.obs_highlight_damage_min = 62.5
        cfg.obs_auto_replay_enabled = True
        cfg.obs_auto_replay_kd = False
        cfg.obs_auto_replay_tko = True
        cfg.obs_auto_replay_capture_delay_sec = 3.4
        cfg.obs_auto_replay_delay_sec = 2.7
        cfg.obs_auto_replay_muted = False
        cfg.obs_auto_replay_volume = 64
        cfg.obs_auto_replay_fit = "contain"
        cfg.obs_auto_replay_fade_ms = 220
        cfg.obs_auto_replay_stop_on_round = False
        cfg.idle_highlight_enabled = True
        cfg.idle_highlight_path = r"D:\highlights"
        cfg.idle_highlight_muted = False
        cfg.idle_highlight_volume = 35
        cfg.idle_highlight_fit = "contain"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "config.json")
            cfg.to_json(path)
            loaded = AppConfig.from_json(path)
        self.assertTrue(loaded.obs_integration_enabled)
        self.assertEqual(loaded.obs_host, "192.0.2.10")
        self.assertEqual(loaded.obs_port, 4460)
        self.assertTrue(loaded.obs_replay_buffer_enabled)
        self.assertFalse(loaded.obs_replay_buffer_auto_start)
        self.assertEqual(loaded.obs_highlight_counter_damage_min, 37.5)
        self.assertEqual(loaded.obs_highlight_combo_min, 5)
        self.assertEqual(loaded.obs_highlight_damage_min, 62.5)
        self.assertTrue(loaded.obs_auto_replay_enabled)
        self.assertFalse(loaded.obs_auto_replay_kd)
        self.assertTrue(loaded.obs_auto_replay_tko)
        self.assertEqual(loaded.obs_auto_replay_capture_delay_sec, 3.4)
        self.assertEqual(loaded.obs_auto_replay_delay_sec, 2.7)
        self.assertFalse(loaded.obs_auto_replay_muted)
        self.assertEqual(loaded.obs_auto_replay_volume, 64)
        self.assertEqual(loaded.obs_auto_replay_fit, "contain")
        self.assertEqual(loaded.obs_auto_replay_fade_ms, 220)
        self.assertFalse(loaded.obs_auto_replay_stop_on_round)
        self.assertTrue(loaded.idle_highlight_enabled)
        self.assertEqual(loaded.idle_highlight_path, r"D:\highlights")
        self.assertFalse(loaded.idle_highlight_muted)
        self.assertEqual(loaded.idle_highlight_volume, 35)
        self.assertEqual(loaded.idle_highlight_fit, "contain")

    def test_browser_playlist_accepts_supported_video_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "highlight.mp4")
            ignored = os.path.join(temp_dir, "notes.txt")
            open(video, "wb").close()
            open(ignored, "wb").close()
            overlay = BrowserOverlayServer(path_resolver=lambda value: value)
            overlay.set_highlight_playlist([video, ignored])
            self.assertEqual(overlay.snapshot()["idleHighlightCount"], 1)
            self.assertEqual(overlay.highlight_path(0), os.path.abspath(video))
            self.assertEqual(overlay.highlight_path(1), "")

    def test_browser_html_contains_idle_video_and_priority_gate(self):
        html = BrowserOverlayServer()._html()
        self.assertIn('id="idleHighlightVideo"', html)
        self.assertIn("function idleHighlightBlocked", html)
        self.assertIn("function canPlayIdleHighlight", html)
        self.assertIn("if(s.matchActive===true)return true", html)
        self.assertIn("syncIdleHighlight(s)", html)
        self.assertIn("body.idle-highlight-active #root>.hud", html)

    def test_browser_html_contains_obs_replay_player(self):
        html = BrowserOverlayServer()._html()
        self.assertIn('id="obsReplayVideo"', html)
        self.assertIn("function syncObsReplay", html)
        self.assertIn("function prepareObsReplay", html)
        self.assertIn("afterTransition", html)
        self.assertIn("function startObsReplayAfterTransition", html)
        self.assertIn("obsReplayAfterTimer", html)
        self.assertIn("preparingReplay", html)
        self.assertIn("styleTertiary", html)
        self.assertIn("/api/obs-replay/ended", html)

    def test_replay_buffer_saved_event_keeps_path_and_context(self):
        client = ObsIntegration(AppConfig())
        client._pending_replay_requests.append(
            {
                "request_id": "save-1",
                "reason": "knockdown",
                "context": {"auto_replay_kind": "kd", "trigger_monotonic": 12.5},
            }
        )
        asyncio.run(
            client._handle_message(
                None,
                {
                    "op": 5,
                    "d": {
                        "eventType": "ReplayBufferSaved",
                        "eventData": {"savedReplayPath": r"D:\OBS\Replay 001.mp4"},
                    },
                },
            )
        )
        event = client.drain_events(1)[0]
        self.assertEqual(event["type"], "replay_file_saved")
        self.assertEqual(event["path"], r"D:\OBS\Replay 001.mp4")
        self.assertEqual(event["reason"], "knockdown")
        self.assertEqual(event["context"]["auto_replay_kind"], "kd")
        self.assertFalse(client._pending_replay_requests)

    def test_browser_replay_route_supports_range_and_stale_token_guard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "replay.mp4")
            with open(video, "wb") as handle:
                handle.write(b"0123456789")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            overlay = BrowserOverlayServer(port, path_resolver=lambda value: value)
            self.assertTrue(overlay.start())
            try:
                token = overlay.play_obs_replay(video, muted=False, volume=64, fit="contain", fade_ms=220)
                self.assertTrue(token)
                state = overlay.snapshot()
                self.assertTrue(state["obsReplayActive"])
                self.assertFalse(state["obsReplayMuted"])
                self.assertEqual(state["obsReplayVolume"], 64)
                request = Request(
                    f"http://127.0.0.1:{port}/obs-replay/{token}",
                    headers={"Range": "bytes=2-5"},
                )
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), b"2345")
                self.assertFalse(overlay.stop_obs_replay("stale-token"))
                payload = json.dumps({"token": token}).encode("utf-8")
                ended = Request(
                    f"http://127.0.0.1:{port}/api/obs-replay/ended",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(ended, timeout=3) as response:
                    self.assertEqual(response.status, 204)
                self.assertFalse(overlay.snapshot()["obsReplayActive"])
            finally:
                overlay.stop()

    def test_inactive_replay_buffer_is_started_after_status_check(self):
        class FakeWebSocket:
            def __init__(self):
                self.messages = []

            async def send_json(self, payload):
                self.messages.append(payload)

        client = ObsIntegration(AppConfig())
        websocket = FakeWebSocket()
        asyncio.run(
            client._handle_message(
                websocket,
                {
                    "op": 7,
                    "d": {
                        "requestType": "GetReplayBufferStatus",
                        "requestStatus": {"result": True},
                        "responseData": {"outputActive": False},
                    },
                },
            )
        )
        self.assertEqual(websocket.messages[0]["d"]["requestType"], "StartReplayBuffer")
        event = client.drain_events(1)[0]
        self.assertEqual(event["type"], "replay_buffer_status")
        self.assertFalse(event["active"])


if __name__ == "__main__":
    unittest.main()
