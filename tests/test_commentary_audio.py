"""Actual PCM metadata and quiet points; no speech/timing fabrication."""
from array import array
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from commentary_audio import wav_info, write_delivery, pause_boundaries


def audio(path, seconds=1., rate=8000, samples=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(array("h", samples if samples is not None else [1000] * round(rate * seconds)).tobytes())


class CommentaryAudioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name, "line.wav")

    def test_duration_is_measured_from_pcm_not_sentence_characters(self):
        audio(self.path, 2.375)
        data = wav_info(self.path)
        self.assertEqual(data["duration_seconds"], 2.375)
        self.assertEqual(data["frames"], 19000)
        self.assertEqual(data["sample_rate"], 8000)

    def test_header_cache_is_stat_bound_and_replacement_invalidates_it(self):
        audio(self.path, 1.)
        self.assertEqual(wav_info(self.path)["duration_seconds"], 1.)
        with patch("commentary_audio.wave.open", side_effect=AssertionError("reopened unchanged audio")):
            self.assertEqual(wav_info(self.path)["duration_seconds"], 1.)
        audio(self.path, 2.)
        self.assertEqual(wav_info(self.path)["duration_seconds"], 2.)

    def test_missing_invalid_and_truncated_audio_never_get_a_duration(self):
        self.assertIsNone(wav_info(self.path))
        self.path.write_bytes(b"broken")
        self.assertIsNone(wav_info(self.path))
        audio(self.path)
        self.path.write_bytes(self.path.read_bytes()[:-10])
        self.assertIsNone(wav_info(self.path))

    def test_pause_points_use_actual_quiet_run_and_ignore_leading_trailing_silence(self):
        # 500ms lead, 500ms voice, 240ms quiet, 500ms voice, 500ms trailing.
        samples = [0] * 4000 + [1000] * 4000 + [0] * 1920 + [1000] * 4000 + [0] * 4000
        audio(self.path, samples=samples)
        data = write_delivery(self.path, role="analyst", delivery="dry")
        self.assertEqual(data["pause_boundaries_ms"], [1040])
        self.assertEqual(data["sentence_boundaries_ms"], [])
        self.assertEqual(pause_boundaries(self.path), (1040,))
        self.assertEqual(data["boundary_source"], "pcm_quiet_180ms")
        audio(self.path, .5)
        self.assertEqual(pause_boundaries(self.path), ())

    def test_short_quiet_windows_do_not_become_handoff_points(self):
        audio(self.path, samples=[1000] * 4000 + [0] * 800 + [1000] * 4000)
        self.assertEqual(write_delivery(self.path)["pause_boundaries_ms"], [])

    def test_valid_sidecar_is_reused_and_authored_label_does_not_change_audio(self):
        audio(self.path)
        original = self.path.read_bytes()
        first = write_delivery(self.path, role="caster", delivery="neutral")
        with patch("commentary_audio._observed_pauses", side_effect=AssertionError("rescanned")):
            self.assertEqual(write_delivery(self.path, role="caster"), first)
            self.assertEqual(write_delivery(self.path, role="caster", delivery="excited")["delivery"], "excited")
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_or_stale_metadata_cannot_fabricate_boundaries(self):
        audio(self.path)
        path = Path(str(self.path) + ".delivery.json")
        path.write_text(json.dumps({"pause_boundaries_ms": [500], "boundary_source": "pcm_quiet_180ms"}))
        self.assertEqual(pause_boundaries(self.path), ())
        write_delivery(self.path)
        data = json.loads(path.read_text())
        data["pause_boundaries_ms"] = [float("nan"), -100, "900", 10000, 600]
        path.write_text(json.dumps(data))
        self.assertEqual(pause_boundaries(self.path), (600,))


if __name__ == "__main__":
    unittest.main()
