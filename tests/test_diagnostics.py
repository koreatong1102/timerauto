import asyncio
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from diagnostics import DiagnosticRecorder, _mask_string
from diagnostic_context import prepare_diagnostic_export
from diagnostic_replay import replay_match_rows
from event_engine import FightEventEngine
from match_log_archive import MatchLogArchive
from obs_integration import ObsIntegration


class DiagnosticRecorderTests(unittest.TestCase):
    def test_paths_and_plaintext_secrets_are_masked(self):
        text = _mask_string(r'C:\Users\Alice\clips C:/Users/Bob/clips password="secret words" token=secret Bearer abc.def')
        self.assertNotIn("Alice", text)
        self.assertNotIn("Bob", text)
        self.assertNotIn("secret words", text)
        self.assertNotIn("abc.def", text)
        self.assertEqual(json.loads(_mask_string('{"password": "secret"}'))["password"], "<redacted>")

    def test_config_overlay_late_fields_and_replay_ids_survive(self):
        recorder = DiagnosticRecorder()
        cfg = {f"field_{i}": i for i in range(700)}
        cfg.update(obs_password="private", nested={"api_key": "private"})
        overlay = {f"field_{i}": i for i in range(300)}
        overlay["obsReplayToken"] = "instance-123"
        with tempfile.TemporaryDirectory() as root:
            path = recorder.export_zip(root, cfg_snapshot=cfg, overlay_snapshot=overlay, mask_sensitive=False, app_base=root)
            with zipfile.ZipFile(path) as zf:
                settings = json.loads(zf.read("settings_snapshot.json"))
                state = json.loads(zf.read("overlay_snapshot.json"))
                self.assertEqual(settings["field_699"], 699)
                self.assertEqual(settings["obs_password"], "<redacted>")
                self.assertEqual(settings["nested"]["api_key"], "<redacted>")
                self.assertEqual(state["obsReplayToken"], "instance-123")
                self.assertNotIn("<truncated>", state)
                self.assertEqual(json.loads(zf.read("diagnostic_meta.json"))["schema_version"], 2)

    def test_incident_pre_context_survives_ring_overflow_and_post_window_expires(self):
        recorder = DiagnosticRecorder()
        recorder.set_options(max_events=300)
        recorder.record("ordinary_before", value="keep")
        recorder.mark_incident("problem")
        for i in range(350):
            recorder.record("ordinary_after", value=i)
        with patch("diagnostics.time.monotonic", return_value=recorder._incident_windows[-1]["until_monotonic"] + 1):
            recorder.record("too_late")
        snap = recorder.snapshot()
        self.assertFalse(any(ev["type"] == "ordinary_before" for ev in snap["events"]))
        self.assertEqual(snap["incident_windows"][0]["before"][0]["type"], "ordinary_before")
        self.assertFalse(any(ev["type"] == "too_late" for ev in snap["incident_windows"][0]["after"]))
        self.assertGreater(snap["dropped_events"], 0)

    def test_trace_time_uses_monotonic_and_time_retention(self):
        recorder = DiagnosticRecorder()
        recorder.start_monotonic = 0
        recorder.set_options(trace_seconds=120)
        with patch("diagnostics.time.monotonic", return_value=1), patch("diagnostics.time.time", return_value=100):
            recorder.record("early")
        with patch("diagnostics.time.monotonic", return_value=130), patch("diagnostics.time.time", return_value=50):
            recorder.record("late")
        self.assertEqual(len(recorder.events), 1)
        self.assertEqual(recorder.events[-1]["dt"], 130)

    def test_important_events_are_separate_from_gauge_traffic(self):
        recorder = DiagnosticRecorder()
        recorder.set_options(max_events=300)
        recorder.record("potm_file_attached", candidate_id="c1", replay_token="r1")
        for i in range(350):
            recorder.record("gauge_tick", value=i)
        self.assertEqual(recorder.critical_events[0]["payload"]["candidate_id"], "c1")
        self.assertEqual(recorder.snapshot(mask_sensitive=True)["critical_events"][0]["payload"]["replay_token"], "r1")

    def test_blackbox_survives_new_recorder_and_always_masks(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = DiagnosticRecorder()
            recorder.configure_storage(root)
            recorder.record("potm_file_attached", path=r"C:\Users\Private\a.mp4", password="secret", replay_token="same-id")
            recorder.close()
            next_recorder = DiagnosticRecorder()
            next_recorder.configure_storage(root)
            path = next_recorder.export_zip(root, app_base=root)
            next_recorder.close()
            with zipfile.ZipFile(path) as zf:
                text = zf.read("blackbox/critical.jsonl").decode()
                self.assertIn("same-id", text)
                self.assertNotIn("Private", text)
                self.assertNotIn("secret", text)

    def test_disk_rotation_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = DiagnosticRecorder()
            recorder.store_max_bytes = 1024
            recorder.configure_storage(root)
            for i in range(70):
                recorder.record("obs_event", value=i)
            recorder.close()
            files = list(Path(root).glob("critical.jsonl*"))
            self.assertLessEqual(len(files), 2)
            self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
            rows = [json.loads(line) for path in files for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(row["payload"]["value"] == 69 for row in rows))

    def test_disabled_recorder_does_not_record_flow(self):
        recorder = DiagnosticRecorder()
        recorder.set_options(enabled=False)
        recorder.record("potm_event")
        self.assertEqual(len(recorder.events), 0)

    def test_app_logs_keep_more_than_400_lines_and_raw_format_is_included(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "logs").mkdir()
            (base / "logs" / "app.log").write_text("important-first\n" + "tick\n" * 700, encoding="utf-8")
            (base / "format.txt").write_text("official contract", encoding="utf-8")
            (base / "lobby.txt").write_text("players", encoding="utf-8")
            path = DiagnosticRecorder().export_zip(root, spectator_root=root, app_base=root)
            with zipfile.ZipFile(path) as zf:
                self.assertIn(b"important-first", zf.read("app_logs/app.log"))
                self.assertEqual(zf.read("raw_log_samples/format.txt"), b"official contract")
                manifest = json.loads(zf.read("evidence_manifest.json"))
                self.assertTrue(any(row["status"] == "missing" for row in manifest))

    def test_archive_ledger_official_blob_export_is_read_only_and_reproducible(self):
        with tempfile.TemporaryDirectory() as root:
            archive = MatchLogArchive(root)
            archive.start("test-match", ("A", "B"))
            archive.record_damage(1, [{"time": 10., "attacker_side": "blue", "receiver_side": "red", "damage": 35., "counter_mult": 1.03}])
            scores = Path(root) / "scores.csv"
            scores.write_text("round,blue_score,red_score\n1,10,9\n", encoding="utf-8")
            archive.snapshot_scores(1, str(scores), final=True)
            manifest_before = (Path(archive.session_dir) / "manifest.json").read_bytes()
            path = DiagnosticRecorder().export_zip(root, app_base=root, context={"match_dirs": [archive.session_dir]})
            with zipfile.ZipFile(path) as zf:
                raw = [json.loads(line) for line in zf.read("match_evidence/0/ledger_official_snapshots.jsonl").decode().splitlines()]
                self.assertIn("round,blue_score", raw[0]["payload"])
                replay = json.loads(zf.read("reproduction_check.json"))
                self.assertEqual(replay["matches"][0]["status"], "replayed")
                self.assertEqual(replay["matches"][0]["rounds"]["1"]["blue"]["landed_rows"], 1)
                self.assertNotIn("match_archive.db", zf.namelist())
            self.assertEqual((Path(archive.session_dir) / "manifest.json").read_bytes(), manifest_before)
            archive.close()

    def test_background_export_reports_success_and_failure(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = DiagnosticRecorder()
            job = recorder.start_export(output_dir=root, app_base=root)
            self.assertTrue(job.done.wait(5))
            self.assertTrue(os.path.isfile(job.path))
            with patch.object(recorder, "export_zip", side_effect=OSError("disk full")):
                job = recorder.start_export(output_dir=root)
                self.assertTrue(job.done.wait(2))
                self.assertIn("disk full", job.error)

    def test_media_missing_or_probe_unavailable_is_not_guessed(self):
        self.assertFalse(DiagnosticRecorder._media_info("missing.mp4")["exists"])
        with tempfile.NamedTemporaryFile(suffix=".mp4") as stream, patch("diagnostics.shutil.which", return_value=None):
            info = DiagnosticRecorder._media_info(stream.name)
            self.assertEqual(info["probe_status"], "unavailable")
            self.assertNotIn("metadata", info)

    def test_snapshot_names_do_not_collide_within_one_second(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = DiagnosticRecorder()
            first = recorder.export_zip(root, app_base=root)
            second = recorder.export_zip(root, app_base=root)
            self.assertNotEqual(first, second)
            self.assertTrue(os.path.isfile(first))

    def test_failed_export_never_leaves_a_partial_zip(self):
        with tempfile.TemporaryDirectory() as root, patch.object(DiagnosticRecorder, "_build_fingerprints", side_effect=RuntimeError("export failure")):
            with self.assertRaises(RuntimeError):
                DiagnosticRecorder().export_zip(root, app_base=root)
            self.assertFalse(list(Path(root).glob("RFC_Diagnostic_*")))

    def test_failed_optional_reproduction_keeps_other_evidence(self):
        with tempfile.TemporaryDirectory() as root, patch("diagnostic_replay.replay_diagnostic_zip", side_effect=RuntimeError("replay failure")):
            path = DiagnosticRecorder().export_zip(root, app_base=root)
            with zipfile.ZipFile(path) as zf:
                self.assertEqual(json.loads(zf.read("reproduction_check.json"))["status"], "failed")
                self.assertIn("settings_snapshot.json", zf.namelist())

    def test_large_archive_evidence_is_explicitly_omitted(self):
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / "match"
            archive.mkdir()
            (archive / "damage_events.jsonl").write_bytes(b"x" * (4*1024*1024 + 1))
            path = DiagnosticRecorder().export_zip(root, app_base=root, context={"match_dirs": [str(archive)]})
            with zipfile.ZipFile(path) as zf:
                manifest = json.loads(zf.read("evidence_manifest.json"))
                self.assertTrue(any(item["status"] == "omitted_size" for item in manifest))
                self.assertNotIn("match_evidence/0/damage_events.jsonl", zf.namelist())

    def test_context_is_detached_from_live_mutable_state(self):
        with tempfile.TemporaryDirectory() as root:
            owner = SimpleNamespace(cfg=SimpleNamespace(), _potm_best={"id": "original", "nested": {"v": 1}},
                _diagnostic_folder=lambda: root, _diagnostic_app_state=lambda: {}, _diagnostic_spectator_root=lambda: "")
            result = prepare_diagnostic_export(owner)
            owner._potm_best["nested"]["v"] = 2
            self.assertEqual(result["context"]["runtime"]["potm_candidate"]["nested"]["v"], 1)

    def test_disk_io_lock_cannot_block_live_event_recording(self):
        recorder = DiagnosticRecorder()
        complete = threading.Event()
        with recorder._disk_lock:
            thread = threading.Thread(target=lambda: (recorder.record("potm_event"), complete.set()))
            thread.start()
            self.assertTrue(complete.wait(.5))
        thread.join(1)

    def test_findings_distinguish_mismatch_and_missing_evidence(self):
        context = {"runtime": {"potm_candidate": {"capture_source": "replay_buffer", "file_source": "source_record"}}}
        findings = DiagnosticRecorder._findings(context, [], {"matches": []})
        self.assertTrue(any(item["certainty"] == "확정" for item in findings))
        self.assertTrue(any(item["certainty"] == "확인 불가" for item in findings))
        self.assertFalse(any("컴퓨터" in item["message"] for item in findings))

    def test_reproduction_only_flags_comparable_rules_and_resets_rounds(self):
        cfg = {}
        engine = FightEventEngine(SimpleNamespace())
        raw = {"time": 10, "attacker_side": "blue", "receiver_side": "red", "damage": 30, "counter_mult": 1}
        verdict = engine.classify(raw)
        rows = [{"event_id": "e1", "round_no": 1, "kind": "damage", "sequence_no": 1, "raw_json": json.dumps(raw),
                 "classified_json": json.dumps(verdict), "ruleset_version": engine.ruleset_version()},
                {"event_id": "e2", "round_no": 2, "kind": "damage", "sequence_no": 2, "raw_json": json.dumps(raw),
                 "classified_json": json.dumps({**verdict, "combo_hits": 99}), "ruleset_version": "older-rules"}]
        result = replay_match_rows(rows, cfg)
        self.assertEqual(result["compared"], 1)
        self.assertEqual(result["different"], 0)
        self.assertEqual(result["different_ruleset_or_unclassified"], 1)
        self.assertEqual(result["rounds"]["2"]["blue"]["max_combo_hits"], 1)
        rows[0]["classified_json"] = json.dumps({**verdict, "combo_hits": 99})
        self.assertEqual(replay_match_rows(rows, cfg)["different"], 1)


class ObsDiagnosticTests(unittest.TestCase):
    def test_disconnected_query_does_not_start_or_queue_capture(self):
        client = ObsIntegration(SimpleNamespace())
        result = client.diagnostic_snapshot()
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(client._commands.empty())

    def test_read_only_response_never_auto_starts_buffer(self):
        async def run():
            client = ObsIntegration(SimpleNamespace())
            client._set_status("connected")
            result = {}
            thread = threading.Thread(target=lambda: result.update(client.diagnostic_snapshot(timeout=1)))
            thread.start()
            command = client._commands.get(timeout=1)
            token = command["token"]
            requests = []
            async def send_json(message):
                requests.append(message["d"])
            ws = SimpleNamespace(send_json=send_json)
            for kind in ("GetReplayBufferStatus", "GetCurrentProgramScene", "GetInputList"):
                await client._send_diagnostic_read(ws, token, kind)
            while requests:
                request = requests.pop(0)
                kind = request["requestType"]
                self.assertTrue(kind.startswith("Get"))
                response = {"GetReplayBufferStatus": {"outputActive": False},
                    "GetCurrentProgramScene": {"currentProgramSceneName": "Broadcast"},
                    "GetSceneItemList": {"sceneItems": [{"sourceName": "Timer", "sceneItemEnabled": True}]},
                    "GetInputList": {"inputs": [{"inputName": "Game"}]} }.get(kind, {})
                await client._handle_message(ws, {"op": 7, "d": {**request, "requestStatus": {"result": True}, "responseData": response}})
            thread.join(2)
            self.assertEqual(result["status"], "complete")
            self.assertIn("GetSceneItemList", result["responses"])
            self.assertTrue(client._commands.empty())
            self.assertFalse(any(event["type"] == "replay_buffer_status" for event in client.drain_events()))
        asyncio.run(run())

    def test_query_timeout_is_explicit_and_cleans_pending_query(self):
        client = ObsIntegration(SimpleNamespace())
        client._set_status("connected")
        result = client.diagnostic_snapshot(timeout=0)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(client._diagnostic_queries, {})


class DiagnosticUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import timerauto
        cls.timerauto = timerauto
        cls.qt = timerauto.QApplication.instance() or timerauto.QApplication([])

    def test_export_captures_ui_state_then_polls_background_job(self):
        timerauto = self.timerauto
        class Owner:
            def _diagnostic_prepare_export(self):
                return {"app_state": {"ui_thread": threading.get_ident()}}
            def _diagnostic_export_zip(self):
                raise AssertionError("synchronous compression must not be called")
        dialog = timerauto.SettingsDialog.__new__(timerauto.SettingsDialog)
        timerauto.QDialog.__init__(dialog)
        dialog._diagnostics_apply_options = Mock()
        dialog._diagnostic_export_zip = Owner()._diagnostic_export_zip
        dialog.btn_diag_export = timerauto.QPushButton()
        dialog.lbl_diag_status = timerauto.QLabel()
        job = SimpleNamespace(done=threading.Event(), path="test.zip", error="")
        with patch.object(timerauto.DIAG, "start_export", return_value=job) as start, patch.object(timerauto.QMessageBox, "information") as info:
            dialog._diagnostics_export_clicked()
            self.assertEqual(start.call_args.kwargs["app_state"]["ui_thread"], threading.get_ident())
            self.assertFalse(dialog.btn_diag_export.isEnabled())
            dialog._diagnostics_export_clicked()
            self.assertEqual(start.call_count, 1)
            job.done.set()
            dialog._diagnostic_poll_timer.timeout.emit()
            self.assertTrue(dialog.btn_diag_export.isEnabled())
            info.assert_called_once()
            self.assertFalse(dialog._diagnostic_poll_timer.isActive())
        dialog.deleteLater()

    def test_latency_ack_has_local_monotonic_clock(self):
        from browser_overlay import BrowserOverlayServer
        overlay = BrowserOverlayServer()
        overlay.record_latency_beacon("ko_probe_show", "probe", "5000", "900000")
        self.assertIsInstance(overlay.latency_beacon("probe")["received_monotonic"], float)


if __name__ == "__main__":
    unittest.main()
