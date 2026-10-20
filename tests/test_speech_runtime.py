import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import actions
from speech_runtime import SpeechRequestGate, commentary_cache_path, last_speech_error, set_speech_error


class RateLimited(Exception):
    status = 429
    headers = {"Retry-After": "2"}


class SpeechRuntimeTests(unittest.TestCase):
    def clock_gate(self):
        now = [100.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        return SpeechRequestGate(clock=lambda: now[0], sleep=sleep), now, sleeps

    def test_paces_successive_requests_but_cached_audio_needs_no_wait(self):
        gate, now, sleeps = self.clock_gate()
        call = Mock(return_value=True)
        gate.run(call)
        gate.run(call)
        self.assertEqual(sleeps, [1.25])
        gate._blocked_until = 200
        self.assertTrue(gate.run(call, cached=lambda: True))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(sleeps, [1.25])

    def test_429_retries_once_after_server_delay(self):
        gate, now, sleeps = self.clock_gate()
        call = Mock(side_effect=[RateLimited(), True])
        self.assertTrue(gate.run(call))
        self.assertEqual(call.call_count, 2)
        self.assertEqual(sleeps, [2.0])

    def test_persistent_429_retains_shared_cooldown_and_stops_after_two_attempts(self):
        gate, now, sleeps = self.clock_gate()
        call = Mock(side_effect=RateLimited())
        with self.assertRaises(RateLimited):
            gate.run(call)
        self.assertEqual(call.call_count, 2)
        following = Mock(return_value=True)
        gate.run(following)
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_long_server_delay_does_not_hang_or_bypass_retry_after(self):
        gate, now, sleeps = self.clock_gate()
        error = RateLimited()
        error.headers = {"Retry-After": "120"}
        call = Mock(side_effect=error)
        with self.assertRaises(RateLimited):
            gate.run(call)
        self.assertEqual(call.call_count, 1)
        with self.assertRaises(TimeoutError):
            gate.run(call)
        self.assertFalse(sleeps)
        self.assertEqual(call.call_count, 1)

    def test_other_errors_are_not_blindly_retried(self):
        gate, _, sleeps = self.clock_gate()
        call = Mock(side_effect=ValueError("invalid voice"))
        with self.assertRaises(ValueError):
            gate.run(call)
        call.assert_called_once()
        self.assertFalse(sleeps)

    def test_background_workers_never_open_simultaneous_requests(self):
        gate = SpeechRequestGate(interval=0)
        active, highest = [0], [0]
        def request(_timeout):
            active[0] += 1
            highest[0] = max(highest[0], active[0])
            time.sleep(.005)
            active[0] -= 1
            return True
        with ThreadPoolExecutor(max_workers=5) as workers:
            self.assertTrue(all(workers.map(lambda _: gate.run(request), range(10))))
        self.assertEqual(highest[0], 1)

    def test_existing_live_cache_keys_are_unchanged(self):
        data = {"text": "통, 카운터!", "role": "caster", "voice": "ko-KR-SunHiNeural",
                "rate": 260, "volume": 100.0, "pitch": 10}
        expected = hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest() + ".mp3"
        self.assertEqual(Path(commentary_cache_path(**data)).name, expected)
        self.assertNotEqual(commentary_cache_path(**data), commentary_cache_path(**{**data, "pitch": 0}))

    def test_cached_parallel_synthesis_generates_only_once_and_publishes_complete_file(self):
        runner = SimpleNamespace(_runner_tag="test", _ensure_tts_ready=lambda: True)
        made = []
        async def save(path, metadata=None):
            made.append(path)
            Path(path).write_bytes(b"complete audio")
        library = SimpleNamespace(Communicate=Mock(return_value=SimpleNamespace(save=save)))
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "edge_tts", library), \
             patch.object(actions, "SPEECH_REQUESTS", SpeechRequestGate(interval=0)):
            path = os.path.join(directory, "cached.mp3")
            with ThreadPoolExecutor(max_workers=5) as workers:
                results = list(workers.map(lambda _: actions.ActionRunner._edge_save_cli(
                    runner, "테스트", path, "ko-KR-InJoonNeural", "+30%", "+0%", "+10Hz"), range(5)))
            self.assertTrue(all(results))
            self.assertEqual(len(made), 1)
            self.assertEqual(Path(path).read_bytes(), b"complete audio")
            self.assertEqual(os.listdir(directory), ["cached.mp3"])

    def test_failed_partial_audio_is_not_published_or_left_behind(self):
        runner = SimpleNamespace(_runner_tag="test", _ensure_tts_ready=lambda: True)
        gate, _, _ = self.clock_gate()
        async def save(path, metadata=None):
            Path(path).write_bytes(b"partial audio")
            raise RateLimited("secret auth URL must not appear")
        library = SimpleNamespace(Communicate=Mock(return_value=SimpleNamespace(save=save)))
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "edge_tts", library), \
             patch.object(actions, "SPEECH_REQUESTS", gate), self.assertLogs(level="WARNING") as messages:
            path = os.path.join(directory, "failed.mp3")
            self.assertFalse(actions.ActionRunner._edge_save_cli(
                runner, "테스트", path, "ko-KR-InJoonNeural", "+0%", "+0%"))
            self.assertEqual(os.listdir(directory), [])
            self.assertIn("429", last_speech_error())
        self.assertNotIn("secret auth URL", " ".join(messages.output))

    def test_error_detail_is_thread_local_and_never_contains_authentication(self):
        set_speech_error(RateLimited("wss://server?token=secret"))
        self.assertIn("429", last_speech_error())
        self.assertNotIn("secret", last_speech_error())
        other = []
        def work():
            set_speech_error(ValueError("private value"))
            other.append(last_speech_error())
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertIn("ValueError", other[0])
        self.assertIn("429", last_speech_error())

    def test_commentary_audio_and_sentence_metadata_publish_without_staging_leaks(self):
        runner = SimpleNamespace(_runner_tag="test", _ensure_tts_ready=lambda: True)
        async def save(path, metadata):
            Path(path).write_bytes(b"complete audio")
            Path(metadata).write_text(json.dumps({"type": "SentenceBoundary", "offset": 0,
                "duration": 10_000_000, "text": "문장입니다."}) + "\n", encoding="utf-8")
        library = SimpleNamespace(Communicate=Mock(return_value=SimpleNamespace(save=save)))
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "edge_tts", library), \
             patch.object(actions, "is_cached_commentary", return_value=True), \
             patch.object(actions, "SPEECH_REQUESTS", SpeechRequestGate(interval=0)):
            path = str(Path(directory, "cached.mp3"))
            self.assertTrue(actions.ActionRunner._edge_save_cli(runner, "문장입니다.", path,
                "ko-KR-InJoonNeural", "+0%", "+0%"))
            self.assertEqual(set(os.listdir(directory)), {"cached.mp3", "cached.mp3.timing.jsonl"})
            from commentary_handoff import sentence_ends
            self.assertEqual(sentence_ends(path), (1000,))

    def test_failed_metadata_and_partial_audio_are_cleaned_together(self):
        runner = SimpleNamespace(_runner_tag="test", _ensure_tts_ready=lambda: True)
        async def save(path, metadata):
            Path(path).write_bytes(b"partial audio")
            Path(metadata).write_text("partial metadata", encoding="utf-8")
            raise ValueError("network failed")
        library = SimpleNamespace(Communicate=Mock(return_value=SimpleNamespace(save=save)))
        with tempfile.TemporaryDirectory() as directory, patch.object(actions, "edge_tts", library), \
             patch.object(actions, "is_cached_commentary", return_value=True), \
             patch.object(actions, "SPEECH_REQUESTS", SpeechRequestGate(interval=0)):
            self.assertFalse(actions.ActionRunner._edge_save_cli(runner, "문장입니다.", str(Path(directory, "bad.mp3")),
                "ko-KR-InJoonNeural", "+0%", "+0%"))
            self.assertEqual(os.listdir(directory), [])
