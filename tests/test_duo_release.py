"""Optional voice worker packaging and private-data update safety; no models."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release_integrity import LOCAL_TTS_DATA_DIRS, MANIFEST, create_manifest, digest, verify_package
from update_manager import _write_update_script


ROOT = Path(__file__).resolve().parents[1]
WORKER_FILES = (
    "qwen_duo_builder.py", "qwen_duo_setup.py", "qwen_duo_launch.ps1", "app_paths.py", "local_tts.py",
    "commentary_pack.py", "commentary_calls.py", "commentary_story.py", "commentary_content.py",
    "commentary_material.py", "commentary_flow.py", "commentary_audio.py",
)


class DuoReleaseTests(unittest.TestCase):
    def test_isolated_worker_sources_are_copied_and_required(self):
        build = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        start = build.index("$qwenRuntimeFiles = @(")
        block = build[start:build.index("\n)", start)]
        for name in WORKER_FILES:
            self.assertIn('"' + name + '"', block)
        self.assertIn("$files += $qwenRuntimeFiles", build)
        self.assertIn("$requiredReleaseFiles += $qwenRuntimeFiles", build)
        requirements = (ROOT / "requirements-release.lock").read_text(encoding="utf-8")
        self.assertNotIn("qwen-tts", requirements)
        self.assertNotIn("torch==", requirements)

    def test_worker_can_start_with_only_shipped_sources_and_no_gui_or_models(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in WORKER_FILES:
                shutil.copyfile(ROOT / name, root / name)
            # --help must not need the release executable's PYZ, Qt, torch,
            # model downloads, a listening HTTP server, or a user config.
            result = subprocess.run([sys.executable, str(root / "qwen_duo_builder.py"), "--help"],
                                    cwd=root, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--job", result.stdout)

    def test_local_generated_voice_data_is_not_release_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, package = root / "source", root / "package"
            source.mkdir()
            package.mkdir()
            (source / "requirements-release.lock").write_text("numpy==2.5.4\n")
            for name in ("timerauto.py", "timer_ui.qml", "cinematic_overlay.qml", "timer_controls.qml", "timerauto.spec"):
                (source / name).write_text("test")
            (package / "timerauto.exe").write_bytes(b"new exe")
            for dirname in LOCAL_TTS_DATA_DIRS:
                path = package / dirname / "private.bin"
                path.parent.mkdir()
                path.write_bytes(b"local user data")
            (package / "qwen_duo_builder.py").write_text("# shipped source")
            with patch("release_integrity.check_environment"), patch("release_integrity.subprocess.check_output", return_value="commit\n"):
                manifest = create_manifest(source, package, "test")
            self.assertEqual(set(manifest["files"]), {"timerauto.exe", "qwen_duo_builder.py"})
            for dirname in LOCAL_TTS_DATA_DIRS:
                (package / dirname / "private.bin").write_bytes(b"locally changed")
            self.assertTrue(verify_package(package)["ok"])

    def test_updater_explicitly_refuses_to_replace_voice_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = Path(_write_update_script(str(root / "update.zip"), str(root / "app"), str(root / "app/timerauto.exe")))
            try:
                text = script.read_text(encoding="utf-8-sig")
                protected = next(line for line in text.splitlines() if "$protectedDirs =" in line)
                for dirname in LOCAL_TTS_DATA_DIRS:
                    self.assertIn("'" + dirname + "'", protected)
                self.assertLess(text.index("Release attempts to replace user data"), text.index("Move-Item -LiteralPath $target"))
            finally:
                script.unlink(missing_ok=True)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows updater test")
    def test_normal_update_keeps_all_local_voice_and_runtime_data(self):
        with tempfile.TemporaryDirectory(prefix="voice_update_") as directory:
            root = Path(directory)
            package, app = root / "package", root / "app"
            package.mkdir()
            app.mkdir()
            (package / "timerauto.exe").write_bytes(b"new exe")
            (package / MANIFEST).write_text(json.dumps({"schema": 1, "version": "test", "commit": "abc", "python": "3.12", "files": {
                "timerauto.exe": {"sha256": digest(package / "timerauto.exe"), "size": 7},
            }}))
            (app / "timerauto.exe").write_bytes(b"old exe")
            for dirname in LOCAL_TTS_DATA_DIRS:
                path = app / dirname / "private.bin"
                path.parent.mkdir()
                path.write_bytes(dirname.encode())
            zip_path = Path(shutil.make_archive(str(root / "update"), "zip", package))
            script = Path(_write_update_script(str(zip_path), str(app), str(app / "timerauto.exe")))
            try:
                # Test runners may execute separate suites concurrently. Keep
                # this simulated update's log inside its own temporary root,
                # rather than contending with another runner's apply.log.
                lines = script.read_text(encoding="utf-8-sig").splitlines()
                log = str(root / "apply.log").replace("'", "''")
                lines = ["$logPath = '" + log + "'" if line.startswith("$logPath = ") else line for line in lines]
                script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
                command = "function Start-Sleep {}\nfunction Start-Process {}\n& '" + str(script).replace("'", "''") + "'"
                result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, timeout=40)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual((app / "timerauto.exe").read_bytes(), b"new exe")
                for dirname in LOCAL_TTS_DATA_DIRS:
                    self.assertEqual((app / dirname / "private.bin").read_bytes(), dirname.encode())
            finally:
                script.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
