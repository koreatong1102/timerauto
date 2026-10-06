import os
import tempfile
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from timerauto import MainApp, SettingsDialog


class _FakeObsIntegration:
    status = "connected"

    def __init__(self):
        self.program_saves = []
        self.source_saves = []

    def save_replay(self, reason, context=None):
        self.program_saves.append((reason, dict(context or {})))

    def save_source_record_replay(self, source, reason, context=None):
        self.source_saves.append((source, reason, dict(context or {})))


class SourceRecordAutoReplayTests(unittest.TestCase):
    def test_native_buffer_request_snapshots_the_attacker_name(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            app.cfg.obs_source_record_enabled = False
            app.cfg.obs_auto_replay_source = "replay_buffer"
            app._source_record_names["blue"] = "Original Nick"
            self.assertTrue(app._maybe_save_obs_highlight("knockdown", attacker_side="blue", event_key="kd-name"))
            app._source_record_names["blue"] = "Next Match"
            self.assertEqual(app.obs_integration.program_saves[0][1]["attacker_name"], "Original Nick")

    def test_native_buffer_down_clip_uses_saved_attacker_name_and_ko_subfolder(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            app.cfg.obs_replay_buffer_archive_enabled = True
            app.cfg.obs_replay_buffer_archive_down_only = True
            app._prune_source_record_archive = Mock()
            app._source_record_names = {"blue": "NEXT MATCH", "red": "OTHER"}
            source = os.path.join(root, "replay.mkv")
            with open(source, "wb") as stream:
                stream.write(b"saved replay")
            context = {"attacker_side": "blue", "attacker_name": "Original Nick", "highlight_kind": "knockdown", "round": 2, "seconds_left": 0, "potm_candidate_id": "candidate"}
            with patch("timerauto.threading.Thread", side_effect=lambda target, **kwargs: SimpleNamespace(start=target)):
                app._copy_program_replay_to_player_archive(source, "knockdown", context)
            player_dir = os.path.join(app.cfg.obs_source_record_archive_dir, "Original Nick", "KO_REPLAY")
            files = os.listdir(player_dir)
            self.assertEqual(len(files), 1)
            with open(os.path.join(player_dir, files[0]), "rb") as stream:
                self.assertEqual(stream.read(), b"saved replay")
            self.assertTrue(os.path.isfile(source))
            self.assertFalse(os.path.isdir(os.path.join(app.cfg.obs_source_record_archive_dir, "NEXT MATCH")))

    def test_native_buffer_archive_down_only_does_not_copy_counter_or_manual_save(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            app.cfg.obs_replay_buffer_archive_enabled = True
            app.cfg.obs_replay_buffer_archive_down_only = True
            source = os.path.join(root, "replay.mp4")
            with open(source, "wb") as stream:
                stream.write(b"replay")
            with patch("timerauto.threading.Thread") as thread:
                app._copy_program_replay_to_player_archive(source, "counter-60", {"attacker_side": "blue", "highlight_kind": "counter"})
                app._copy_program_replay_to_player_archive(source, "", {})
                thread.assert_not_called()

    def test_native_buffer_all_events_option_and_disabled_archive(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            app.cfg.obs_replay_buffer_archive_enabled = False
            app.cfg.obs_replay_buffer_archive_down_only = False
            app._prune_source_record_archive = Mock()
            source = os.path.join(root, "replay.mp4")
            with open(source, "wb") as stream:
                stream.write(b"replay")
            with patch("timerauto.threading.Thread", side_effect=lambda target, **kwargs: SimpleNamespace(start=target)):
                app._copy_program_replay_to_player_archive(source, "counter-60", {"attacker_side": "blue"})
                self.assertEqual(os.listdir(app.cfg.obs_source_record_archive_dir), [])
                app.cfg.obs_replay_buffer_archive_enabled = True
                app._copy_program_replay_to_player_archive(source, "counter-60", {"attacker_side": "blue"})
            self.assertEqual(len(os.listdir(os.path.join(app.cfg.obs_source_record_archive_dir, "BLUE"))), 1)

    def _app(self, root, *, fallback):
        app = MainApp.__new__(MainApp)
        incoming = os.path.join(root, "incoming")
        archive = os.path.join(root, "archive")
        os.makedirs(incoming)
        os.makedirs(archive)
        app.cfg = SimpleNamespace(
            obs_integration_enabled=True,
            obs_replay_buffer_enabled=True,
            obs_source_record_enabled=True,
            obs_source_record_context="Scene 2",
            obs_source_record_incoming_dir=incoming,
            obs_source_record_archive_dir=archive,
            obs_highlight_kd=True,
            obs_auto_replay_enabled=True,
            obs_auto_replay_kd=True,
            obs_auto_replay_tko=True,
            obs_auto_replay_source="source_record",
            obs_auto_replay_source_fallback=fallback,
            obs_auto_replay_source_wait_sec=5.0,
            obs_auto_replay_pre_event_sec=3.0,
            obs_auto_replay_post_event_sec=1.0,
            obs_auto_replay_capture_delay_sec=0.0,
            obs_highlight_cooldown_sec=0.0,
            potm_capture_source="source_record",
            timer_current_round=1,
        )
        app.obs_integration = _FakeObsIntegration()
        app._obs_highlight_event_keys = deque(maxlen=300)
        app._obs_highlight_event_key_set = set()
        app._obs_highlight_capture_generation = 0
        app._obs_last_highlight_at = 0.0
        app._source_record_pending = deque()
        app._source_record_auto_replays = {}
        app._source_record_names = {"blue": "BLUE", "red": "RED"}
        app._source_record_round = 1
        app._source_record_seconds_left = 120
        return app

    def test_source_record_mode_does_not_save_duplicate_program_replay(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            with patch("timerauto.QTimer.singleShot", side_effect=lambda _ms, fn: fn()):
                self.assertTrue(
                    app._maybe_save_obs_highlight(
                        "knockdown",
                        event_key="kd-1",
                        attacker_side="blue",
                    )
                )
            self.assertEqual(len(app.obs_integration.source_saves), 1)
            self.assertEqual(len(app.obs_integration.program_saves), 0)
            context = app.obs_integration.source_saves[0][2]
            self.assertEqual(context["replay_capture_delay_sec"], 1.0)

    def test_checked_fallback_saves_both_sources(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=True)
            with patch("timerauto.QTimer.singleShot", side_effect=lambda _ms, fn: fn()):
                self.assertTrue(
                    app._maybe_save_obs_highlight(
                        "knockdown",
                        event_key="kd-2",
                        attacker_side="blue",
                    )
                )
            self.assertEqual(len(app.obs_integration.source_saves), 1)
            self.assertEqual(len(app.obs_integration.program_saves), 1)

    def test_source_file_uses_event_anchored_playback_window(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root, fallback=False)
            target = os.path.join(root, "source.mp4")
            open(target, "wb").close()
            calls = []
            app._schedule_obs_auto_replay = (
                lambda path, reason, context: calls.append((path, reason, context)) or True
            )
            context = {
                "event_key": "kd-3",
                "auto_replay_kind": "kd",
                "auto_replay_source": "source_record",
                "trigger_monotonic": time.monotonic(),
                "replay_capture_delay_sec": 1.9,
                "replay_pre_event_sec": 3.0,
                "replay_post_event_sec": 1.0,
            }
            self.assertTrue(
                app._play_source_record_auto_replay(
                    target,
                    {"event": "KD", "context": context},
                )
            )
            self.assertEqual(calls[0][2]["replay_start_from_end_sec"], 4.9)
            self.assertAlmostEqual(calls[0][2]["replay_end_from_end_sec"], 0.9)

    def test_decisive_clip_uses_player_ko_replay_folder_without_potm_ownership(self):
        target, managed = MainApp._source_record_clip_destination(
            r"D:\archive",
            {
                "nickname": "BLUE",
                "event": "TKO",
                "potm_candidate_id": "best-1",
                "context": {"auto_replay_kind": "tko"},
            },
        )
        self.assertEqual(target, os.path.join(r"D:\archive", "BLUE", "KO_REPLAY"))
        self.assertFalse(managed)

    def test_non_decisive_potm_candidate_keeps_managed_candidate_folder(self):
        target, managed = MainApp._source_record_clip_destination(
            r"D:\archive",
            {
                "nickname": "BLUE",
                "event": "COUNTER",
                "potm_candidate_id": "best-2",
                "context": {"highlight_kind": "counter"},
            },
        )
        self.assertEqual(target, os.path.join(r"D:\archive", "_potm_candidates"))
        self.assertTrue(managed)

    def test_merge_archive_preserves_ko_replay_subfolder(self):
        with tempfile.TemporaryDirectory() as player_dir:
            ko_dir = os.path.join(player_dir, "KO_REPLAY")
            os.makedirs(ko_dir)
            source = os.path.join(ko_dir, "ko.mp4")
            open(source, "wb").close()
            moved, failures = SettingsDialog._archive_merged_source_clips(
                [source],
                player_dir,
            )
            self.assertEqual(moved, 1)
            self.assertEqual(failures, [])
            self.assertTrue(
                os.path.isfile(os.path.join(player_dir, "_used", "KO_REPLAY", "ko.mp4"))
            )


if __name__ == "__main__":
    unittest.main()
