"""Offline protocol/UI regressions; no torch install, downloads, OBS, or audio."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import wave
from queue import Queue

from config_model import AppConfig
from local_tts import (commentary_voice, decode_voice, is_local_voice, LocalTTSError,
                       save_local, check_server, MODELS, _request, request_options)
from qwen_tts_server import Engine, make_server, validate_request
from speech_runtime import commentary_cache_path, last_speech_error
from actions import ActionRunner
from timerauto import MainApp
from tests import test_commentary_tts_queue as queue_tests


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 2400)
    return output.getvalue()


@contextmanager
def resident_server():
    engine = Engine(MODELS["1.7B"])
    engine.ready, engine.device, engine.speakers = True, "test-cpu", ["sohee", "ryan"]
    engine.synthesize = Mock(return_value=wav_bytes())
    server = make_server(engine, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, engine
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


class LocalTtsTests(unittest.TestCase):
    def cfg(self, **kwargs):
        cfg = AppConfig()
        cfg.spectator_tts_engine = "qwen3"
        for key, value in kwargs.items():
            setattr(cfg, "spectator_qwen_" + key, value)
        return cfg

    def test_existing_users_remain_on_edge_and_keep_cache_keys(self):
        cfg = AppConfig()
        voice = commentary_voice(cfg, "caster", "ko-KR-SunHiNeural")
        self.assertEqual(voice, "ko-KR-SunHiNeural")
        self.assertTrue(commentary_cache_path("test", "caster", voice, 200, 100, 0).endswith(".mp3"))

    def test_descriptor_role_voice_and_qwen_cache_are_isolated(self):
        cfg = self.cfg()
        voice = commentary_voice(cfg, "caster", "edge")
        self.assertTrue(is_local_voice(voice))
        self.assertEqual(decode_voice(voice)["speaker"], "Sohee")
        self.assertEqual(decode_voice(commentary_voice(cfg, "analyst", "edge"))["speaker"], "Ryan")
        first = commentary_cache_path("test", "caster", voice, 200, 100, 0)
        self.assertTrue(first.endswith(".wav"))
        for key, value in (("model", "0.6B"), ("caster_speaker", "Ryan"), ("speed", 1.2),
                           ("caster_instruction", "Different"), ("language", "English"), ("port", 8769)):
            other = self.cfg(**{key: value})
            self.assertNotEqual(first, commentary_cache_path("test", "caster", commentary_voice(other, "caster", "edge"), 200, 100, 0), key)

    def test_small_model_does_not_claim_instruction_support(self):
        cfg = self.cfg(model="0.6B", caster_instruction="SHOUT")
        voice = commentary_voice(cfg, "caster", "edge")
        self.assertEqual(decode_voice(voice)["instruction"], "")
        self.assertEqual(commentary_voice(cfg, "caster", voice), voice)

    def test_preview_wait_is_longer_than_reported_eighteen_second_generation(self):
        voice = commentary_voice(self.cfg(), "caster", "")
        self.assertEqual(request_options(voice), {"local_timeout": 90.})
        with tempfile.TemporaryDirectory() as folder, patch("local_tts._request", return_value=wav_bytes()) as request:
            save_local("18.6초 걸리는 모델의 테스트", str(Path(folder, "test.wav")), voice)
        self.assertEqual(request.call_args.kwargs["timeout"], 90.)

    def test_live_and_report_waits_never_exceed_original_deadline(self):
        voice = commentary_voice(self.cfg(), "caster", "")
        self.assertAlmostEqual(request_options(voice, deadline=103.2, now=102)["local_timeout"], 1.2)
        self.assertEqual(request_options(voice, deadline=190, now=120), {"local_timeout": 70})
        with self.assertRaises(LocalTTSError):
            request_options(voice, deadline=99, now=100)
        self.assertEqual(request_options("ko-KR-SunHiNeural", deadline=190, now=100), {})

    def test_windows_connection_abort_discards_response_without_traceback(self):
        engine = Engine(MODELS["1.7B"])
        server = make_server(engine, 0)
        try:
            handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = SimpleNamespace(write=Mock(side_effect=ConnectionAbortedError(10053, "host aborted")))
            with patch("builtins.print") as log:
                handler.reply(200, wav_bytes(), "audio/wav")
            log.assert_called_once_with("QWEN_CLIENT_DISCONNECTED response_discarded=true", flush=True)
        finally:
            server.server_close()

    def test_config_round_trip_and_old_profiles(self):
        cfg = self.cfg(model="0.6B", port=8769, speed=1.15, caster_instruction="흥분한 캐스터")
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder, "config.json"))
            cfg.to_json(path)
            loaded = AppConfig.from_json(path)
            for key in ("spectator_tts_engine", "spectator_qwen_model", "spectator_qwen_port",
                        "spectator_qwen_speed", "spectator_qwen_caster_instruction"):
                self.assertEqual(getattr(cfg, key), getattr(loaded, key))

    def test_bad_descriptor_fails_locally(self):
        with self.assertRaises(LocalTTSError):
            decode_voice("rfc-qwen3:not-json")

    def test_action_queue_never_lowercases_an_encoded_voice(self):
        voice = commentary_voice(self.cfg(), "caster", "")
        runner = SimpleNamespace(_start_tts_worker=Mock(), _tts_queue=Queue(), _runner_tag="test", _safe_status=Mock())
        ActionRunner._enqueue_tts(runner, "test", 200, voice_mode=voice)
        self.assertEqual(runner._tts_queue.get_nowait()[-1], voice)

    def test_empty_instruction_can_be_saved_and_does_not_return_to_default(self):
        cfg = self.cfg(caster_instruction="")
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder, "config.json"))
            cfg.to_json(path)
            self.assertEqual(AppConfig.from_json(path).spectator_qwen_caster_instruction, "")

    def test_http_health_and_actual_pcm_file_protocol_without_torch(self):
        with resident_server() as (port, engine), tempfile.TemporaryDirectory() as folder:
            cfg = self.cfg(port=port)
            self.assertEqual(check_server(cfg)["device"], "test-cpu")
            path = str(Path(folder, "cache.wav"))
            self.assertTrue(save_local("통, 카운터!", path, commentary_voice(cfg, "caster", ""), volume="-20%"))
            self.assertEqual(Path(path).read_bytes(), wav_bytes())
            request = engine.synthesize.call_args.args[0]
            self.assertEqual(request["text"], "통, 카운터!")
            self.assertAlmostEqual(request["gain"], .8)
            self.assertEqual(list(Path(folder).glob("qwen_*")), [])
            self.assertTrue(save_local("통, 카운터!", path, commentary_voice(cfg, "caster", "")))
            engine.synthesize.assert_called_once()

    def test_server_model_mismatch_and_loading_are_explicit(self):
        with resident_server() as (port, engine):
            with self.assertRaisesRegex(LocalTTSError, "모델"):
                check_server(self.cfg(port=port, model="0.6B"))
            engine.ready = False
            with self.assertRaisesRegex(LocalTTSError, "준비"):
                check_server(self.cfg(port=port))

    def test_busy_server_does_not_queue_synthesis(self):
        with resident_server() as (port, engine):
            engine.lock.acquire()
            try:
                with self.assertRaisesRegex(LocalTTSError, "생성 중"):
                    _request(port, "/synthesize", payload={})
            finally:
                engine.lock.release()
            engine.synthesize.assert_not_called()

    def test_server_rejects_browsers_and_remote_model_paths(self):
        with resident_server() as (port, engine):
            request = urllib.request.Request(f"http://127.0.0.1:{port}/synthesize", data=b"{}",
                headers={"Content-Type": "application/json", "Origin": "https://example.com", "X-RFC-TTS": "1"})
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(raised.exception.code, 403)
            raised.exception.close()
            with self.assertRaisesRegex(LocalTTSError, "모델"):
                _request(port, "/synthesize", payload={"model": "https://example.com/model"})
            engine.synthesize.assert_not_called()

    def test_invalid_or_partial_audio_is_never_published(self):
        with resident_server() as (port, engine), tempfile.TemporaryDirectory() as folder:
            voice = commentary_voice(self.cfg(port=port), "caster", "")
            path = str(Path(folder, "cache.wav"))
            for data in (b"not audio", wav_bytes()[:-20]):
                engine.synthesize.return_value = data
                with self.assertRaisesRegex(LocalTTSError, "WAV"):
                    save_local("test", path, voice)
                self.assertFalse(Path(path).exists())
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_failure_never_imports_or_falls_back_to_edge(self):
        runner = SimpleNamespace(_ensure_tts_ready=Mock(side_effect=AssertionError("Edge called")))
        voice = commentary_voice(self.cfg(), "caster", "")
        with patch("local_tts.save_local", side_effect=LocalTTSError("Qwen 서버 연결 실패")):
            self.assertFalse(ActionRunner._edge_save_cli(runner, "test", "x.wav", voice, "+0%", "+0%"))
        self.assertEqual(last_speech_error(), "Qwen 서버 연결 실패")
        runner._ensure_tts_ready.assert_not_called()
        self.assertEqual(ActionRunner._edge_voice_for_mode(runner, voice, "test"), voice)

    def test_health_uses_numeric_loopback_no_system_proxy(self):
        with resident_server() as (port, _), patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1"}):
            self.assertTrue(check_server(self.cfg(port=port))["ready"])

    def test_input_bounds_and_no_arbitrary_speaker_or_nan(self):
        engine = Engine(MODELS["1.7B"])
        engine.speakers = ["sohee"]
        valid = {"model": engine.model_id, "text": "안녕", "speaker": "Sohee"}
        self.assertEqual(validate_request(valid, engine)["language"], "Korean")
        for changes in ({"text": "x" * 1201}, {"speaker": "path.wav"}, {"gain": float("nan")},
                        {"speed": 5}, {"instruction": "x" * 501}, {"language": "NotALanguage"}):
            with self.assertRaises(ValueError):
                validate_request({**valid, **changes}, engine)

    def test_live_and_handoff_select_same_local_identity(self):
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app.cfg = self.cfg()
        self.assertTrue(is_local_voice(app._handoff_voice_settings("caster", {})[0]))

    def test_background_warmup_does_not_contact_any_provider_in_local_mode(self):
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app.cfg = self.cfg()
        app.action_runner = Mock()
        with patch("timerauto.threading.Thread") as thread:
            app._prewarm_commentary_tts_cache()
            app._prewarm_commentary_emergency_calls(["통"])
            app._prewarm_potm_announcement({"side": "blue"})
        thread.assert_not_called()
        app.action_runner._edge_save_cli.assert_not_called()

    def test_generated_audio_is_dropped_if_engine_or_local_voice_changes(self):
        app = queue_tests.CommentaryTtsQueueTests()._app()
        app.cfg = self.cfg()
        voice = app._handoff_voice_settings("caster", {})[0]
        app._commentary_tts_generations["caster"] = 1
        app._commentary_tts_deliveries["caster"] = {"voice_identity": voice}
        app.cfg.spectator_tts_engine = "edge"
        app._clear_commentary_tts_busy = Mock()
        with patch("timerauto.os.path.isfile") as exists:
            app._play_commentary_tts_file("caster", "local.wav", 1)
        exists.assert_not_called()
        app._clear_commentary_tts_busy.assert_called_once_with("caster", 1)

    def test_controls_are_offline_optional_and_saved_without_mutating_edge_voice(self):
        script = '''
from PyQt6.QtWidgets import QApplication
from config_model import AppConfig
from tts_settings import TtsEngineControls
from local_tts import decode_voice
app = QApplication([])
cfg = AppConfig()
control = TtsEngineControls(cfg)
assert control.engine.currentData() == 'edge'
assert control.details.isHidden()
control.engine.setCurrentIndex(control.engine.findData('qwen3'))
control.model.setCurrentIndex(control.model.findData('0.6B'))
assert not control.instructions['caster'].isEnabled()
control.port.setValue(8777)
control.write(cfg)
assert cfg.spectator_tts_engine == 'qwen3' and cfg.spectator_qwen_port == 8777
assert cfg.spectator_caster_voice == 'ko-KR-InJoonNeural'
assert decode_voice(control.voice('caster', 'edge'))['instruction'] == ''
control.model.setCurrentIndex(control.model.findData('1.7B'))
assert control.instructions['caster'].isEnabled()
assert control.status.wordWrap()
from unittest.mock import patch
paths = []
with patch('commentary_pack.render', side_effect=lambda text, path, voice: paths.append(path)):
    control.preview_pack()
    control.preview_pack()
assert len(paths) == 2 and paths[0] != paths[1], paths
assert all('pack_preview_' in path and path.endswith('.wav') for path in paths)
'''
        result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_optional_runtime_is_shipped_but_never_part_of_base_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        release = (root / "build_release.ps1").read_text(encoding="utf-8-sig")
        for name in ("LOCAL_TTS.md", "qwen_tts_server.py", "requirements-qwen.txt", "setup_qwen.ps1", "run_qwen.ps1"):
            self.assertIn('"' + name + '"', release)
            self.assertTrue((root / name).is_file())
        self.assertNotIn("qwen-tts", (root / "requirements-release.lock").read_text(encoding="utf-8"))
