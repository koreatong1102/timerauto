import unittest
from collections import deque
from unittest.mock import patch, Mock
from types import SimpleNamespace
from PyQt6.QtCore import QObject, QMetaObject, Qt, Q_ARG
from speech_runtime import commentary_cache_path

from timerauto import MainApp, SettingsDialog, QMediaPlayer


class CommentaryTtsQueueTests(unittest.TestCase):
    def _app(self):
        app = MainApp.__new__(MainApp)
        app._commentary_tts_queue = deque()
        app._commentary_live_serial = 0
        app._commentary_tts_deliveries = {}
        app._commentary_handoff_pending = None
        app._commentary_handoff_worker_id = 0
        app._commentary_handoff_counter = 0
        app._commentary_handoff_fade = None
        app._commentary_tts_queue_draining = False
        app._commentary_tts_busy = {"analyst": True, "caster": False}
        app._commentary_tts_dialogues = {}
        app._commentary_tts_generations = {"caster": 0, "analyst": 0}
        app._potm_presentation_active = False
        app._commentary_followup_epoch = {"caster": 0, "analyst": 0}
        app._commentary_tts_files = {"caster": [], "analyst": []}
        app._commentary_hide_round_report_on_complete = {}
        app._commentary_release_idle_highlight_on_complete = {}
        return app

    def _bind_dialogue(self, app):
        packet = app._commentary_dialogue_from_update({
            "commentary_tts_live_dialogue": True,
            "commentary_tts_continuations": [{"text": "남자 해설의 받아치기!", "role": "analyst"}],
        })
        app._commentary_tts_dialogues["caster"] = packet
        app._commentary_tts_busy = {"caster": True, "analyst": False}
        return packet

    def test_urgent_line_moves_ahead_of_live_punch_line(self):
        app = self._app()
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        MainApp._enqueue_commentary_tts(app, "레드 선수, 다운입니다!", "caster")

        self.assertEqual("레드 선수, 다운입니다!", app._commentary_tts_queue[0]["text"])
        # A down makes the previous ordinary call obsolete, not just lower priority.
        self.assertEqual(len(app._commentary_tts_queue), 1)

    def test_queued_line_is_played_when_shared_channel_is_free(self):
        app = self._app()
        played = []
        app._speak_commentary_tts = lambda text, role, **kwargs: played.append((text, role, kwargs))
        MainApp._enqueue_commentary_tts(app, "레드 선수, 다운입니다!", "caster")

        app._commentary_tts_busy = {"analyst": False, "caster": False}
        MainApp._drain_commentary_tts_queue(app)

        self.assertEqual(played[0][:2], ("레드 선수, 다운입니다!", "caster"))
        self.assertTrue(played[0][2]["_from_queue"])
        self.assertEqual(played[0][2]["_timing"]["kind"], "terminal")
        self.assertFalse(app._commentary_tts_queue)

    def test_duplicate_snapshot_line_is_queued_once(self):
        app = self._app()
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        self.assertEqual(1, len(app._commentary_tts_queue))

    def test_male_reply_follows_actual_end_not_setup_request_timer(self):
        app = self._app()
        self._bind_dialogue(app)
        played, callbacks = [], []
        app._speak_commentary_tts = lambda text, role, **kw: played.append((text, role))
        self.assertFalse(app._commentary_tts_queue)
        with patch("timerauto.QTimer.singleShot", side_effect=lambda _ms, fn: callbacks.append(fn)):
            app._on_commentary_media_status("caster", QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertFalse(played)
        self.assertEqual(app._commentary_tts_queue[0]["role"], "analyst")
        for callback in callbacks:
            callback()
        self.assertEqual(played, [("남자 해설의 받아치기!", "analyst")])
        # Duplicate EndOfMedia must not replay the reply.
        with patch("timerauto.QTimer.singleShot"):
            app._on_commentary_media_status("caster", QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertFalse(app._commentary_tts_queue)

    def test_reply_is_not_detached_from_a_queued_setup(self):
        app = self._app()
        packet = self._bind_dialogue(app)
        app._commentary_tts_dialogues.clear()
        app._commentary_tts_busy = {"caster": False, "analyst": True}
        # No voice/network work: the real method stops at the busy-channel queue.
        app._speak_commentary_tts("캐스터 상황 콜!", "caster", _dialogue=packet)
        self.assertEqual(len(app._commentary_tts_queue), 1)
        self.assertIs(app._commentary_tts_queue[0]["kwargs"]["_dialogue"], packet)
        self.assertFalse(app._commentary_tts_dialogues)
        played = []
        app._commentary_tts_busy["analyst"] = False
        app._speak_commentary_tts = lambda text, role, **kw: played.append((text, role, kw))
        app._drain_commentary_tts_queue()
        self.assertEqual(played[0][:2], ("캐스터 상황 콜!", "caster"))
        self.assertIs(played[0][2]["_dialogue"], packet)

    def test_decode_failure_cancels_reply_instead_of_reading_an_orphan_joke(self):
        for status in (QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.NoMedia):
            app = self._app()
            self._bind_dialogue(app)
            with patch("timerauto.QTimer.singleShot"):
                app._on_commentary_media_status("caster", status)
            self.assertFalse(app._commentary_tts_queue)
            self.assertFalse(app._commentary_tts_dialogues)

    def test_generation_failure_also_discards_reply(self):
        app = self._app()
        self._bind_dialogue(app)
        with patch("timerauto.QTimer.singleShot"):
            app._clear_commentary_tts_busy("caster")
        self.assertFalse(app._commentary_tts_dialogues)
        self.assertFalse(app._commentary_tts_queue)

    def test_urgent_down_or_report_takes_precedence_over_old_banter(self):
        for text in ("선수 다운!", "라운드 종료 리포트입니다."):
            app = self._app()
            self._bind_dialogue(app)
            app._enqueue_commentary_tts(text, "caster")
            with patch("timerauto.QTimer.singleShot"):
                app._on_commentary_media_status("caster", QMediaPlayer.MediaStatus.EndOfMedia)
            self.assertEqual([item["text"] for item in app._commentary_tts_queue], [text])

    def test_scene_boundary_or_stale_setup_does_not_release_reply(self):
        for reason in ("scene", "stale"):
            app = self._app()
            packet = self._bind_dialogue(app)
            if reason == "scene":
                app._commentary_followup_epoch["analyst"] += 1
            else:
                packet["expires_at"] = 0
            app._complete_commentary_dialogue("caster", ended=True)
            self.assertFalse(app._commentary_tts_queue)

    def test_reply_guard_survives_its_own_queue_wait(self):
        app = self._app()
        self._bind_dialogue(app)
        app._complete_commentary_dialogue("caster", ended=True)
        queued = app._commentary_tts_queue.popleft()
        self.assertTrue(queued["kwargs"]["_dialogue"])
        app._commentary_followup_epoch["caster"] += 1
        with patch("timerauto.DIAG.record"):
            app._speak_commentary_tts(queued["text"], queued["role"], **queued["kwargs"])
        self.assertFalse(app._commentary_tts_queue)

    def test_duo_uses_configured_female_caster_and_male_analyst_voices(self):
        app = self._app()
        app.cfg = SimpleNamespace(spectator_caster_voice="ko-KR-SunHiNeural",
                                  spectator_commentary_voice="ko-KR-InJoonNeural")
        app._commentary_tts_busy = {"caster": False, "analyst": False}
        app._commentary_players = {"caster": Mock(), "analyst": Mock()}
        app._commentary_audio_outs = {"caster": Mock(), "analyst": Mock()}
        voices = []
        app._commentary_tts_cache_path = lambda text, role, voice, *_: voices.append((role, voice)) or "cached.mp3"
        packet = app._commentary_dialogue_from_update({"commentary_tts_live_dialogue": True,
            "commentary_tts_continuations": [{"text": "받아치기!", "role": "analyst"}]})
        with patch("timerauto.HAS_QTMULTIMEDIA", True), patch("timerauto.os.path.isfile", return_value=True), \
             patch("timerauto.os.path.getsize", return_value=10), patch("timerauto.QMetaObject.invokeMethod"), \
             patch("timerauto.QTimer.singleShot", side_effect=lambda _, fn: fn()):
            app._speak_commentary_tts("상황 콜!", "caster", _dialogue=packet)
            self.assertTrue(app._commentary_tts_busy["caster"])
            app._on_commentary_media_status("caster", QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(voices, [("caster", "ko-KR-SunHiNeural"), ("analyst", "ko-KR-InJoonNeural")])
        self.assertTrue(app._commentary_tts_busy["analyst"])

    def test_preview_flattens_duo_to_serial_turns_without_mutating_steps(self):
        steps = [{"text": "캐스터!", "role": "caster", "followup_text": "남자 해설!", "post_ms": 600}]
        turns = SettingsDialog._commentary_preview_turns(steps)
        self.assertEqual([turn["role"] for turn in turns], ["caster", "analyst"])
        self.assertEqual(turns[1]["text"], "남자 해설!")
        self.assertNotIn("followup_text", turns[0])
        self.assertIn("followup_text", steps[0])

    def test_cancelled_old_audio_job_cannot_play_or_clear_a_new_turn(self):
        app = self._app()
        self._bind_dialogue(app)
        app._commentary_tts_generations["caster"] = 4
        with patch("timerauto.QTimer.singleShot"):
            app._clear_commentary_tts_busy("caster", 3)
        self.assertTrue(app._commentary_tts_busy["caster"])
        self.assertTrue(app._commentary_tts_dialogues)
        with patch("timerauto.os.path.isfile") as is_file:
            app._play_commentary_tts_file("caster", "old.mp3", 3)
        is_file.assert_not_called()

    def test_hard_stop_invalidates_generated_audio_and_queued_duo(self):
        app = self._app()
        packet = self._bind_dialogue(app)
        app._commentary_players = {}
        app._commentary_tts_cache_dir = ""
        app._enqueue_commentary_tts("대기 중인 상황 콜!", "caster", _dialogue=packet)
        app._stop_commentary_tts_role("caster", "round_end")
        self.assertFalse(app._commentary_tts_busy["caster"])
        self.assertEqual(app._commentary_tts_generations["caster"], 1)
        self.assertFalse(app._commentary_tts_dialogues)
        self.assertFalse(app._commentary_tts_queue)

    def test_real_qt_slots_accept_generation_guard_without_audio_or_network(self):
        app = self._app()
        QObject.__init__(app)
        app._commentary_tts_generations["caster"] = 2
        app._commentary_tts_busy["caster"] = True
        with patch("timerauto.os.path.isfile") as is_file:
            QMetaObject.invokeMethod(app, "_play_commentary_tts_file", Qt.ConnectionType.DirectConnection,
                Q_ARG(str, "caster"), Q_ARG(str, "old.mp3"), Q_ARG(int, 1))
            QMetaObject.invokeMethod(app, "_clear_commentary_tts_busy", Qt.ConnectionType.DirectConnection,
                Q_ARG(str, "caster"), Q_ARG(int, 1))
        is_file.assert_not_called()
        self.assertTrue(app._commentary_tts_busy["caster"])

    def test_preview_reuses_live_audio_cache_without_a_network_worker(self):
        dialog = SimpleNamespace(
            _ensure_tts_test_player=Mock(), _tts_test_players={"analyst": Mock()},
            _tts_test_audio_outs={"analyst": Mock()}, _tts_test_busy={"analyst": False},
            _tts_test_generation=0, _commentary_tts_voice=lambda role: "ko-KR-InJoonNeural",
            _commentary_tts_rate=lambda: 260, _commentary_tts_pitch=lambda: 10,
            _commentary_tts_volume=lambda: 100, _play_tts_test_file=Mock(), action_runner=Mock())
        with patch("timerauto.HAS_QTMULTIMEDIA", True), patch("timerauto.os.path.isfile", return_value=True), \
             patch("timerauto.os.path.getsize", return_value=100), patch("timerauto.threading.Thread") as worker:
            SettingsDialog._speak_tts_test_qt(dialog, "테스트", "analyst")
        worker.assert_not_called()
        dialog.action_runner._edge_save_cli.assert_not_called()
        dialog._play_tts_test_file.assert_called_once_with("analyst", commentary_cache_path(
            "테스트", "analyst", "ko-KR-InJoonNeural", 260, 100, 10), 1)

    def test_preview_end_does_not_delete_shared_live_cache(self):
        cached = commentary_cache_path("테스트", "analyst", "ko-KR-InJoonNeural", 260, 100, 10)
        dialog = SimpleNamespace(_tts_test_files={"analyst": [cached, "temporary_test_audio.mp3"]},
                                  _tts_test_busy={"analyst": True})
        with patch("timerauto.os.remove") as remove:
            SettingsDialog._on_tts_test_media_status(dialog, "analyst", QMediaPlayer.MediaStatus.EndOfMedia)
        remove.assert_called_once_with("temporary_test_audio.mp3")
        self.assertFalse(dialog._tts_test_busy["analyst"])

    def test_preview_server_failure_stops_script_and_stale_errors_do_not_reopen_popup(self):
        dialog = SimpleNamespace(_tts_test_generation=1, _commentary_test_script_token=object(),
            _commentary_test_script_queue=deque([{"text": "다음 요청"}]),
            _tts_test_players={}, _tts_test_busy={}, _tts_test_files={}, _noop_status=Mock())
        dialog._stop_spectator_commentary_test_script = lambda: SettingsDialog._stop_spectator_commentary_test_script(dialog)
        with patch("timerauto.QMessageBox.warning") as warning:
            SettingsDialog._show_tts_test_error(dialog, "서버 요청 제한(429)", 1)
            SettingsDialog._show_tts_test_error(dialog, "이전 테스트의 뒤늦은 실패", 1)
        warning.assert_called_once()
        self.assertIsNone(dialog._commentary_test_script_token)
        self.assertFalse(dialog._commentary_test_script_queue)
        self.assertEqual(dialog._tts_test_generation, 2)

    def test_story_is_confirmed_only_after_last_turn_started_and_finished(self):
        app = self._app()
        packet = self._bind_dialogue(app)
        packet["story"] = {"scope": "fixture", "id": "story", "seed": "permission", "scene": "repeat_counter"}
        with patch("timerauto.SPOKEN_MEMORY.complete") as complete:
            app._on_commentary_playback_state("caster", QMediaPlayer.PlaybackState.PlayingState)
            app._complete_commentary_dialogue("caster", ended=True)
            complete.assert_not_called()
            reply = app._commentary_tts_queue.popleft()["kwargs"]["_dialogue"]
            app._commentary_tts_dialogues["analyst"] = {**reply, "play_started": False}
            app._on_commentary_playback_state("analyst", QMediaPlayer.PlaybackState.PlayingState)
            app._complete_commentary_dialogue("analyst", ended=True)
            complete.assert_called_once_with(packet["story"])

    def test_unplayed_or_failed_story_never_authorizes_callbacks(self):
        for started, ended in ((False, True), (True, False)):
            app = self._app()
            app._commentary_tts_dialogues["analyst"] = {
                "lines": [], "story": {"scope": "fixture", "id": "unheard"}, "play_started": started,
                "epochs": dict(app._commentary_followup_epoch), "expires_at": 1e99}
            with patch("timerauto.SPOKEN_MEMORY.complete") as complete:
                app._complete_commentary_dialogue("analyst", ended=ended)
            complete.assert_not_called()

    def test_compact_single_turn_keeps_feedback_packet(self):
        app = self._app()
        packet = app._commentary_dialogue_from_update({"commentary_tts_live_dialogue": True,
            "commentary_tts_continuations": [], "commentary_tts_story": {"scope": "fixture", "id": "single"}})
        self.assertIsNotNone(packet)
        self.assertFalse(packet["lines"])

    def test_latest_action_replaces_backlog_instead_of_waiting_eight_seconds(self):
        app = self._app()
        with patch("timerauto.time.monotonic", return_value=100):
            app._enqueue_commentary_tts("이전 눈 적중!", "caster")
        with patch("timerauto.time.monotonic", return_value=102):
            app._enqueue_commentary_tts("새 카운터!", "caster")
        self.assertEqual([x["text"] for x in app._commentary_tts_queue], ["새 카운터!"])
        self.assertEqual(app._commentary_tts_queue[0]["expires_at"], 105.2)

    def test_queue_wait_and_generation_share_one_deadline(self):
        app = self._app()
        timing = {"kind": "live", "created_at": 100., "expires_at": 103.2}
        with patch("timerauto.time.monotonic", return_value=102):
            app._enqueue_commentary_tts("카운터!", "caster", _timing=timing)
        self.assertEqual(app._commentary_tts_queue[0]["expires_at"], 103.2)
        app._commentary_tts_busy = {"caster": False, "analyst": False}
        app._speak_commentary_tts = Mock()
        with patch("timerauto.time.monotonic", return_value=104):
            app._drain_commentary_tts_queue()
        app._speak_commentary_tts.assert_not_called()

    def test_cached_file_is_also_rejected_after_total_deadline(self):
        app = self._app()
        app._commentary_tts_generations["caster"] = 1
        app._commentary_tts_deliveries["caster"] = {"kind": "live", "created_at": 100., "expires_at": 103.2}
        app._clear_commentary_tts_busy = Mock()
        with patch("timerauto.time.monotonic", return_value=104), patch("timerauto.os.path.isfile") as exists:
            app._play_commentary_tts_file("caster", "cached.mp3", 1)
        exists.assert_not_called()
        app._clear_commentary_tts_busy.assert_called_once_with("caster", 1)

    def test_new_action_cancels_old_duo_reply_even_within_its_ttl(self):
        app = self._app()
        packet = self._bind_dialogue(app)
        packet["live_serial"] = 1
        app._commentary_live_serial = 2
        self.assertFalse(app._complete_commentary_dialogue("caster", ended=True))
        self.assertFalse(app._commentary_tts_queue)

    def test_priority_is_taken_from_event_metadata_not_profanity_text(self):
        with patch("timerauto.time.monotonic", return_value=100):
            live = MainApp._commentary_timing_from_update({"commentary_tts_category": "weak", "commentary_tts_observed_at": 99})
            down = MainApp._commentary_timing_from_update({"commentary_tts_category": "knockdown", "commentary_tts_observed_at": 99})
        self.assertEqual(live["expires_at"], 102.2)
        self.assertEqual(down["kind"], "terminal")

    def test_new_down_prepares_audio_before_interrupting_a_live_joke(self):
        app = self._app()
        app._commentary_tts_deliveries["analyst"] = {"kind": "reply"}
        app._stop_commentary_tts_role = Mock()
        app._prepare_commentary_handoff = Mock()
        app._speak_commentary_tts("새 다운!", "caster", _timing={"kind": "terminal", "created_at": 0, "expires_at": 1e99})
        app._stop_commentary_tts_role.assert_not_called()
        app._prepare_commentary_handoff.assert_called_once()
        app._commentary_tts_deliveries["analyst"] = {"kind": "report"}
        app._speak_commentary_tts("또 다운!", "caster", _timing={"kind": "terminal", "created_at": 0, "expires_at": 1e99})
        app._stop_commentary_tts_role.assert_not_called()

    def test_report_chunks_keep_final_board_and_idle_block_until_last_audio_end(self):
        app = self._app()
        app._push_browser_overlay_event = Mock()
        app._release_idle_highlight_after_presentation = Mock()
        app._commentary_tts_dialogues["analyst"] = {"is_report": True, "hide_on_end": True,
            "lines": [{"text": "끝 문장입니다.", "role": "analyst"}], "story": {},
            "epochs": dict(app._commentary_followup_epoch), "expires_at": 1e99}
        app._commentary_release_idle_highlight_on_complete["analyst"] = True
        with patch("timerauto.QTimer.singleShot"):
            app._on_commentary_media_status("analyst", QMediaPlayer.MediaStatus.EndOfMedia)
        app._push_browser_overlay_event.assert_not_called()
        app._release_idle_highlight_after_presentation.assert_not_called()
        item = app._commentary_tts_queue.pop()
        self.assertTrue(item["kwargs"]["hide_round_report_on_complete"])
        app._commentary_tts_dialogues["analyst"] = item["kwargs"]["_dialogue"]
        app._commentary_hide_round_report_on_complete["analyst"] = True
        with patch("timerauto.QTimer.singleShot"):
            app._on_commentary_media_status("analyst", QMediaPlayer.MediaStatus.EndOfMedia)
        app._push_browser_overlay_event.assert_called_once_with("round_report_hide")
        app._release_idle_highlight_after_presentation.assert_called_once()

    def test_report_split_does_not_drop_sentences_after_eight(self):
        app = self._app()
        text = " ".join(f"{i}번째 분석 문장입니다." for i in range(12))
        parts = app._split_commentary_tts_sentences(text, max_sentences=None)
        self.assertEqual(len(parts), 12)
        self.assertIn("11번째", parts[-1])

    def test_explicit_zero_followup_delay_is_not_replaced_by_2400ms(self):
        app = self._app()
        with patch("timerauto.QTimer.singleShot") as schedule:
            app._schedule_commentary_followup_tts("리포트", delay_ms=0)
        self.assertEqual(schedule.call_args.args[0], 0)

    def test_long_report_is_queued_as_short_first_chunk_without_truncation(self):
        app = self._app()
        text = " ".join(f"{i}번째 문장은 실제 리포트의 수치 비교 분석입니다." for i in range(12))
        app._speak_commentary_tts(text, "analyst", allow_slow=True, hide_round_report_on_complete=True)
        item = app._commentary_tts_queue.pop()
        packet = item["kwargs"]["_dialogue"]
        self.assertTrue(packet["is_report"])
        self.assertTrue(packet["hide_on_end"])
        self.assertFalse(item["kwargs"]["hide_round_report_on_complete"])
        self.assertLessEqual(len(item["text"]), 135)
        self.assertEqual(" ".join([item["text"]] + [x["text"] for x in packet["lines"]]), text)
        self.assertEqual(item["kwargs"]["_timing"]["kind"], "report")

    def test_failed_report_chunk_releases_the_board_and_idle_video(self):
        app = self._app()
        app._push_browser_overlay_event = Mock()
        app._release_idle_highlight_after_presentation = Mock()
        app._commentary_tts_dialogues["analyst"] = {"is_report": True, "hide_on_end": True,
            "lines": [{"text": "다음 문장", "role": "analyst"}], "story": {},
            "epochs": dict(app._commentary_followup_epoch), "expires_at": 1e99}
        app._commentary_release_idle_highlight_on_complete["analyst"] = True
        with patch("timerauto.QTimer.singleShot"):
            app._clear_commentary_tts_busy("analyst")
        self.assertFalse(app._commentary_tts_queue)
        app._push_browser_overlay_event.assert_called_once_with("round_report_hide")
        app._release_idle_highlight_after_presentation.assert_called_once()


if __name__ == "__main__":
    unittest.main()
