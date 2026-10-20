import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from edge_tts_compat import configure_edge_tts_endpoint


LEGACY_URL = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
    "?TrustedClientToken=test-public-client-key"
)


class EdgeTtsEndpointTests(unittest.TestCase):
    def _modules(self, url=LEGACY_URL):
        communicate = SimpleNamespace(WSS_URL=url)
        constants = SimpleNamespace(WSS_URL=url, VOICE_LIST="unchanged-voice-list")
        modules = {"edge_tts.communicate": communicate, "edge_tts.constants": constants}
        return communicate, constants, patch(
            "edge_tts_compat.importlib.import_module", side_effect=modules.__getitem__
        )

    def test_migrates_effective_url_and_keeps_voice_list(self):
        communicate, constants, imports = self._modules()
        with imports:
            self.assertTrue(configure_edge_tts_endpoint())
        parsed = urlsplit(communicate.WSS_URL)
        self.assertEqual("api.msedgeservices.com", parsed.netloc)
        self.assertEqual("/tts/cognitiveservices/websocket/v1", parsed.path)
        self.assertEqual(
            {"Ocp-Apim-Subscription-Key": ["test-public-client-key"]},
            parse_qs(parsed.query),
        )
        self.assertEqual(communicate.WSS_URL, constants.WSS_URL)
        self.assertEqual("unchanged-voice-list", constants.VOICE_LIST)

    def test_repeated_initialization_is_idempotent(self):
        communicate, _, imports = self._modules()
        with imports:
            self.assertTrue(configure_edge_tts_endpoint())
            first = communicate.WSS_URL
            self.assertFalse(configure_edge_tts_endpoint())
        self.assertEqual(first, communicate.WSS_URL)

    def test_parallel_workers_migrate_once_without_restoring_old_endpoint(self):
        communicate, _, imports = self._modules()
        with imports, ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: configure_edge_tts_endpoint(), range(20)))
        self.assertEqual(1, sum(results))
        self.assertEqual("api.msedgeservices.com", urlsplit(communicate.WSS_URL).netloc)

    def test_future_library_endpoint_is_not_overridden(self):
        for url in (
            "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?new-auth=1",
            "wss://future.example/speech?token=1",
            LEGACY_URL.replace("TrustedClientToken", "FutureAuthentication"),
        ):
            with self.subTest(url=url):
                communicate, constants, imports = self._modules(url)
                with imports:
                    self.assertFalse(configure_edge_tts_endpoint())
                self.assertEqual(url, communicate.WSS_URL)
                self.assertEqual(url, constants.WSS_URL)

    def test_preserves_other_query_parameters_and_escapes_key(self):
        communicate, _, imports = self._modules(LEGACY_URL + "%26suffix&extra=value")
        with imports:
            configure_edge_tts_endpoint()
        self.assertEqual(
            {"Ocp-Apim-Subscription-Key": ["test-public-client-key&suffix"], "extra": ["value"]},
            parse_qs(urlsplit(communicate.WSS_URL).query),
        )

    def test_empty_client_key_is_not_silently_accepted(self):
        communicate, _, imports = self._modules(LEGACY_URL.split("=", 1)[0] + "=")
        with imports, self.assertRaises(RuntimeError):
            configure_edge_tts_endpoint()
        self.assertIn("TrustedClientToken=", communicate.WSS_URL)

    def test_migration_log_does_not_contain_authentication(self):
        _, _, imports = self._modules()
        with imports, self.assertLogs(level="INFO") as captured:
            configure_edge_tts_endpoint()
        self.assertNotIn("test-public-client-key", " ".join(captured.output))


class EdgeTtsActionIntegrationTests(unittest.TestCase):
    def test_initializer_handles_both_first_import_and_already_loaded_library(self):
        import actions

        runner = SimpleNamespace(_runner_tag="test", _safe_status=Mock())
        fake_library = SimpleNamespace()
        for loaded in (False, True):
            with self.subTest(loaded=loaded), patch.dict("sys.modules", {"edge_tts": fake_library}), patch.object(
                actions, "edge_tts", fake_library if loaded else None
            ), patch.object(actions, "HAS_EDGE_TTS", loaded), patch.object(
                actions, "configure_edge_tts_endpoint"
            ) as configure:
                self.assertTrue(actions.ActionRunner._ensure_tts_ready(runner))
                configure.assert_called_once_with()
                self.assertIs(fake_library, actions.edge_tts)

    def test_save_keeps_selected_voice_rate_volume_and_pitch(self):
        import actions

        runner = SimpleNamespace(_runner_tag="test", _ensure_tts_ready=Mock(return_value=True))
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "speech.mp3")

            async def save(output):
                with open(output, "wb") as handle:
                    handle.write(b"test-audio")

            save_mock = AsyncMock(side_effect=save)
            library = SimpleNamespace(Communicate=Mock(return_value=SimpleNamespace(save=save_mock)))
            with patch.object(actions, "edge_tts", library):
                self.assertTrue(actions.ActionRunner._edge_save_cli(
                    runner, "음성 확인", path, "ko-KR-InJoonNeural", "+15%", "-10%", "+10Hz"
                ))
            library.Communicate.assert_called_once_with(
                "음성 확인", "ko-KR-InJoonNeural", rate="+15%", volume="-10%", pitch="+10Hz"
            )
            save_mock.assert_awaited_once()
            staging = save_mock.await_args.args[0]
            self.assertEqual(os.path.dirname(staging), os.path.dirname(path))
            self.assertTrue(os.path.basename(staging).startswith(".speech_"))
            self.assertFalse(os.path.exists(staging))
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), b"test-audio")


if __name__ == "__main__":
    unittest.main()
