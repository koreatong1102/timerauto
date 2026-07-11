import tempfile
import unittest
from pathlib import Path

from update_manager import _write_update_script


class UpdateManagerTests(unittest.TestCase):
    def test_generated_updater_waits_for_pid_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(
                _write_update_script(
                    str(Path(temp_dir) / "update.zip"),
                    str(Path(temp_dir) / "app"),
                    str(Path(temp_dir) / "app" / "timerauto.exe"),
                    12345,
                )
            )
            text = script.read_text(encoding="utf-8")
            raw = script.read_bytes()

        self.assertEqual(script.suffix.lower(), ".ps1")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Get-Process -Id $processId", text)
        self.assertIn("config.json", text)
        self.assertIn("profile.json", text)
        self.assertIn("image", text)
        self.assertIn("Start-Process -FilePath $exePath", text)


if __name__ == "__main__":
    unittest.main()
