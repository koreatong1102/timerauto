import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from timerauto import MainApp


class ChapterResumeTests(unittest.TestCase):
    def _app(self, root):
        app = MainApp.__new__(MainApp)
        app.cfg = SimpleNamespace(chapter_output_dir=root, chapter_anchor_epoch=0.0, chapter_offset_sec=0, chapter_hide_time=False)
        app.cfg_path = os.path.join(root, "config.json")
        app._chapter_events = []
        app._chapter_result_signatures = {}
        app._chapter_last_title = ""
        app._chapter_last_elapsed = -999999
        app._chapter_seen_keys = set()
        app._chapter_session_stamp = "new"
        app._chapter_jsonl_path = ""
        app._chapter_txt_path = ""
        app._chapter_obs_stream_start_epoch = 0.0
        app._chapter_fallback_anchor_epoch = time.time()
        return app

    def test_restarts_resume_open_chapter_and_preserve_dedupe(self):
        with tempfile.TemporaryDirectory() as root:
            anchor = time.time() - 120
            path = os.path.join(root, "chapters_test.jsonl")
            event = {"anchor_epoch": anchor, "elapsed_sec": 60, "title": "BLUE vs RED", "dedupe_key": "match:blue:red"}
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            app = self._app(root)

            self.assertTrue(app._resume_chapter_session(max_age_sec=3600))
            self.assertEqual(app._chapter_jsonl_path, path)
            self.assertEqual(len(app._chapter_events), 1)
            self.assertIn("match:blue:red", app._chapter_seen_keys)

    def test_closed_chapter_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as root:
            anchor = time.time() - 120
            path = os.path.join(root, "chapters_closed.jsonl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({"anchor_epoch": anchor, "elapsed_sec": 60, "title": "OLD"}) + "\n")
            open(path + ".closed", "w", encoding="utf-8").close()
            self.assertFalse(self._app(root)._resume_chapter_session(max_age_sec=3600))

    def test_cold_start_refuses_a_chapter_from_a_different_obs_stream(self):
        with tempfile.TemporaryDirectory() as root:
            old_anchor = time.time() - 900
            path = os.path.join(root, "chapters_old.jsonl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({"anchor_epoch": old_anchor, "elapsed_sec": 10, "title": "OLD"}) + "\n")
            # OBS says the currently active stream began only 30 seconds ago.
            self.assertFalse(self._app(root)._resume_chapter_session(
                max_age_sec=3600,
                expected_anchor_epoch=time.time() - 30,
                anchor_tolerance_sec=60,
            ))

    def test_cold_start_resumes_when_obs_identity_matches_even_if_app_anchor_differs(self):
        with tempfile.TemporaryDirectory() as root:
            stream_start = time.time() - 1800
            # TimerAuto began 15 minutes after the OBS stream, which is the
            # normal mid-broadcast restart case that used to create a new file.
            app_anchor = stream_start + 900
            path = os.path.join(root, "chapters_current.jsonl")
            event = {
                "anchor_epoch": app_anchor,
                "obs_stream_start_epoch": stream_start,
                "elapsed_sec": 100,
                "title": "BLUE VS RED",
            }
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            app = self._app(root)
            self.assertTrue(app._resume_chapter_session(
                max_age_sec=3600,
                expected_anchor_epoch=stream_start,
                anchor_tolerance_sec=60,
            ))
            self.assertEqual(app._chapter_jsonl_path, path)
            self.assertAlmostEqual(app._chapter_obs_stream_start_epoch, stream_start, places=1)

    def test_fresh_obs_interrupt_marker_recovers_the_previous_journal(self):
        with tempfile.TemporaryDirectory() as root:
            old_stream_start = time.time() - 1800
            path = os.path.join(root, "chapters_interrupted.jsonl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "anchor_epoch": old_stream_start,
                    "obs_stream_start_epoch": old_stream_start,
                    "elapsed_sec": 60,
                    "title": "BLUE VS RED",
                }) + "\n")
            # OBS restarted, so its duration-derived identity is different.
            # A fresh interruption marker is the explicit exception to the
            # normal protection against joining two separate broadcasts.
            open(path + ".obs_interrupted", "w", encoding="utf-8").close()
            app = self._app(root)
            self.assertTrue(app._resume_chapter_session(
                max_age_sec=3600,
                expected_anchor_epoch=time.time(),
                anchor_tolerance_sec=60,
            ))
            self.assertEqual(app._chapter_jsonl_path, path)

    def test_rematch_uses_a_new_match_session_dedupe_key(self):
        app = self._app(tempfile.mkdtemp())
        self.assertTrue(app._append_chapter_event("BLUE VS RED", dedupe_key="vs:match-1:BLUE:RED"))
        self.assertTrue(app._append_chapter_event("BLUE VS RED", elapsed_sec=90, dedupe_key="vs:match-2:BLUE:RED"))
        self.assertEqual(len(app._chapter_events), 2)

    def test_export_title_uses_a_player_registered_after_match_start(self):
        app = self._app(tempfile.mkdtemp())
        app.cfg.players = {"LATE_ID": "Late Nickname"}
        title = app._chapter_event_display_title({
            "title": "BLUE VS LATE_ID",
            "source": "spectatorlog_vs_intro",
            "blue_id": "BLUE_ID",
            "blue_name": "Blue",
            "red_id": "LATE_ID",
            "red_name": "LATE_ID",
            "red_registered": False,
        })
        self.assertEqual(title, "BLUE_ID VS Late Nickname(LATE_ID)")

    def test_match_result_is_written_as_separate_bottom_block(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            app._append_chapter_event(
                "Blue Nick VS Red Nick",
                {
                    "source": "spectatorlog_vs_intro",
                    "match_session_id": "match-1",
                    "blue_name": "Blue Nick",
                    "red_name": "Red Nick",
                },
                elapsed_sec=30,
                dedupe_key="vs:match-1:blue:red",
            )
            self.assertTrue(app._record_chapter_match_result({
                "isFinal": True,
                "matchSessionId": "match-1",
                "winner": "blue",
                "resultMethod": "TKO",
                "officialScorecard": {
                    "blueName": "BLUE",
                    "redName": "RED",
                    "blueTotal": 29,
                    "redTotal": 27,
                    "rounds": [
                        {"round": 1, "blue_score": 10, "red_score": 9},
                        {"round": 2, "blue_score": 9, "red_score": 10},
                        {"round": 3, "blue_score": 10, "red_score": 8},
                    ],
                },
            }))
            with open(app._chapter_txt_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            self.assertIn("# 경기 결과 요약", text)
            self.assertIn("대진: Blue Nick VS Red Nick", text)
            self.assertIn("승자: Blue Nick", text)
            self.assertIn("승리 방식: TKO", text)
            self.assertIn("최종 점수: 29 - 27", text)
            self.assertIn("라운드별 점수:\nR1: 10 - 9\nR2: 9 - 10\nR3: 10 - 8", text)
            self.assertNotIn("MATCH_RESULT_SUMMARY", text)
            self.assertIn("# 챕터 수: 1", text)

    def test_late_official_score_revision_replaces_exported_result(self):
        with tempfile.TemporaryDirectory() as root:
            app = self._app(root)
            base = {
                "isFinal": True,
                "matchSessionId": "match-2",
                "winner": "red",
                "resultMethod": "decision",
                "officialScorecard": {
                    "blueName": "Blue",
                    "redName": "Red",
                    "blueTotal": 19,
                    "redTotal": 20,
                    "rounds": [
                        {"round": 1, "blue_score": 9, "red_score": 10},
                        {"round": 2, "blue_score": 10, "red_score": 10},
                    ],
                },
            }
            self.assertTrue(app._record_chapter_match_result(base))
            revised = json.loads(json.dumps(base))
            revised["officialScorecard"]["blueTotal"] = 18
            revised["officialScorecard"]["rounds"][1]["blue_score"] = 9
            self.assertTrue(app._record_chapter_match_result(revised))
            self.assertFalse(app._record_chapter_match_result(revised))
            with open(app._chapter_txt_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            self.assertEqual(text.count("[경기 1]"), 1)
            self.assertIn("승리 방식: 판정", text)
            self.assertIn("최종 점수: 18 - 20", text)
            self.assertNotIn("최종 점수: 19 - 20", text)

    def test_brief_obs_inactive_state_does_not_split_the_chapter(self):
        class FakeObsIntegration:
            def __init__(self):
                self.events = []

            def drain_events(self, _limit):
                events, self.events = self.events, []
                return events

        app = self._app(tempfile.mkdtemp())
        app.cfg.obs_auto_chapter_enabled = True
        app.cfg.obs_chapter_export_on_stop = True
        app.cfg.obs_chapter_add_start_event = True
        app.obs_integration = FakeObsIntegration()
        app._obs_stream_active = True
        app._obs_unexpected_disconnect_at = 0.0
        app._chapter_obs_interrupt_pending_until = 0.0
        app._chapter_stream_stop_generation = 0
        app._source_record_incoming_clear_generation = 0
        app._chapter_jsonl_path = os.path.join(app.cfg.chapter_output_dir, "chapters_live.jsonl")
        closed = []
        app._mark_chapter_obs_interrupt = lambda: None
        app._clear_chapter_obs_interrupt = lambda: None
        app._close_chapter_session = lambda: closed.append(True)
        app._schedule_source_record_incoming_clear = lambda: None
        app._export_chapter_txt = lambda: ""
        callbacks = []

        app.obs_integration.events = [{"type": "stream_state", "active": False, "duration_ms": 0}]
        with patch("timerauto.QTimer.singleShot", side_effect=lambda delay, callback: callbacks.append((delay, callback))):
            app._poll_obs_integration()
        self.assertFalse(closed)
        self.assertEqual(callbacks[0][0], 15000)

        app.obs_integration.events = [{"type": "stream_state", "active": True, "duration_ms": 0}]
        app._poll_obs_integration()
        callbacks[0][1]()
        self.assertFalse(closed)
        self.assertEqual(app._chapter_jsonl_path, os.path.join(app.cfg.chapter_output_dir, "chapters_live.jsonl"))

    def test_restart_repairs_an_already_split_chapter_from_previous_txt(self):
        with tempfile.TemporaryDirectory() as root:
            first_anchor = time.time() - 7200
            reconnect_at = first_anchor + 3600
            prior_base = os.path.join(root, "chapters_prior")
            with open(prior_base + ".txt", "w", encoding="utf-8") as stream:
                stream.write(
                    f"# 기준 시각: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(first_anchor))}\n"
                    "# 보정(초): +3\n\n"
                    "00:00 시작\n"
                    "00:03 방송 시작\n"
                    "13:13 BLUE VS RED\n"
                )
            with open(prior_base + ".jsonl.closed", "w", encoding="utf-8") as stream:
                stream.write(datetime.fromtimestamp(reconnect_at - 3).isoformat(timespec="seconds"))
            current_path = os.path.join(root, "chapters_current.jsonl")
            current_event = {
                "wall_time": datetime.fromtimestamp(reconnect_at).isoformat(timespec="seconds"),
                "anchor_epoch": reconnect_at,
                "obs_stream_start_epoch": reconnect_at,
                "offset_sec": 3,
                "elapsed_sec": 3,
                "title": "방송 시작",
                "source": "obs_websocket",
            }
            with open(current_path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(current_event, ensure_ascii=False) + "\n")

            app = self._app(root)
            self.assertTrue(app._resume_chapter_session(
                max_age_sec=10800,
                expected_anchor_epoch=reconnect_at,
                anchor_tolerance_sec=60,
            ))
            self.assertEqual(len(app._chapter_events), 3)
            self.assertAlmostEqual(app.cfg.chapter_anchor_epoch, int(first_anchor), delta=1.0)
            with open(app._chapter_txt_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            self.assertIn("13:13 BLUE VS RED", text)
            self.assertIn("1:00:03 방송 시작", text)


if __name__ == "__main__":
    unittest.main()
