import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release_integrity import MANIFEST, check_environment, create_manifest, digest, verify_package
from update_manager import _write_update_script


def make_package(root):
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, content in {"timerauto.exe": b"new exe", "_internal/test.dll": b"new DLL"}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files[name] = {"sha256": digest(path), "size": len(content)}
    (root / MANIFEST).write_text(json.dumps({"schema": 1, "version": "test", "commit": "abc", "python": "3.12.10", "files": files}), encoding="utf-8")


class ReleaseIntegrityTests(unittest.TestCase):
    def test_detects_internal_corruption_and_missing_files_not_just_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            self.assertTrue(verify_package(root)["ok"])
            (root / "config.json").write_text("user settings")
            self.assertTrue(verify_package(root)["ok"])
            (root / "_internal/test.dll").write_bytes(b"bad DLL")
            result = verify_package(root)
            self.assertEqual([{"path": "_internal/test.dll", "problem": "changed"}], result["errors"])
            (root / "timerauto.exe").unlink()
            self.assertEqual(2, len(verify_package(root)["errors"]))

    def test_rejects_manifest_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            manifest = json.loads((root / MANIFEST).read_text())
            for name in ("../outside", "C:/outside", "_internal\\..\\outside"):
                manifest["files"] = {name: {"size": 0, "sha256": ""}}
                (root / MANIFEST).write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_package(root)

    def test_environment_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".python-version").write_text("3.12.10")
            (root / "requirements-release.lock").write_text("numpy==1.0\n")
            with patch("release_integrity.platform.python_version", return_value="3.14.6"), patch("release_integrity.importlib.metadata.version", return_value="2.5.4"):
                with self.assertRaisesRegex(RuntimeError, "Python 3.14.6 != 3.12.10"):
                    check_environment(root)

    def test_frozen_entry_exits_before_live_app_imports(self):
        source = (Path(__file__).resolve().parents[1] / "timerauto.py").read_text(encoding="utf-8")
        self.assertLess(source.index('"--release-self-test" in sys.argv'), source.index("import numpy"))
        self.assertLess(source.index("raise SystemExit(_release_selftest_main())"), source.index("_set_dpi_awareness()"))

    def test_build_cannot_float_versions_or_borrow_ambient_native_libraries(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build_release.ps1").read_text(encoding="utf-8")
        spec = (root / "timerauto.spec").read_text(encoding="utf-8")
        workflow = (root / ".github/workflows/release-latest.yml").read_text(encoding="utf-8")
        self.assertNotIn("pip install --upgrade", build)
        self.assertIn("Source files changed during build", build)
        self.assertLess(build.index("$env:PATH = @("), build.index("-m PyInstaller"))
        self.assertIn("$env:PATH = $originalBuildPath", build)
        self.assertIn("Uncontrolled native dependency", spec)
        self.assertIn('python-version: "' + (root / ".python-version").read_text().strip() + '"', workflow)

    def test_release_manifest_excludes_private_config_profiles_and_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, package = root / "source", root / "package"
            source.mkdir()
            make_package(package)
            for name in ("timerauto.py", "timer_ui.qml", "cinematic_overlay.qml", "timer_controls.qml", "timerauto.spec"):
                (source / name).write_text("test")
            (source / "requirements-release.lock").write_text("numpy==2.5.4\n")
            for name in ("config.json", "profile.json", "image/player.png", "MatchLogArchive/match.txt"):
                path = package / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("private")
            with patch("release_integrity.check_environment"), patch("release_integrity.subprocess.check_output", return_value="commit123\n"):
                manifest = create_manifest(source, package, "1.2.3")
            self.assertEqual({"timerauto.exe", "_internal/test.dll"}, set(manifest["files"]))
            self.assertEqual("commit123", manifest["commit"])
            self.assertTrue(verify_package(package)["ok"])


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows updater test")
class TransactionalUpdateTests(unittest.TestCase):
    def apply(self, corrupt=False, copy_failure=False):
        with tempfile.TemporaryDirectory(prefix="업데이트 검증 ") as directory:
            root = Path(directory)
            package, app = root / "package", root / "app"
            make_package(package)
            if corrupt:
                (package / "_internal/test.dll").write_bytes(b"corrupt")
            app.mkdir()
            (app / "timerauto.exe").write_bytes(b"old exe")
            (app / "_internal").mkdir()
            (app / "_internal/old.dll").write_bytes(b"old DLL")
            (app / "config.json").write_bytes(b"personal config")
            (app / "custom.txt").write_bytes(b"personal file")
            (app / "image").mkdir()
            (app / "image/player.png").write_bytes(b"personal portrait")
            zip_path = Path(shutil.make_archive(str(root / "update"), "zip", package))
            script = Path(_write_update_script(str(zip_path), str(app), str(app / "timerauto.exe")))
            try:
                # No actual app launch or sleeps. All writes stay in temp paths.
                prelude = "function Start-Sleep {}\nfunction Start-Process {}\n"
                if copy_failure:
                    prelude += "function Copy-Item { param($LiteralPath,$Destination,[switch]$Recurse,[switch]$Force) throw 'simulated copy failure' }\n"
                command = prelude + "& '" + str(script).replace("'", "''") + "'"
                completed = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, timeout=40)
                expected_ok = not (corrupt or copy_failure)
                self.assertEqual(0 if expected_ok else 1, completed.returncode, completed.stderr.decode(errors="replace"))
                self.assertEqual(b"personal config", (app / "config.json").read_bytes())
                self.assertEqual(b"personal file", (app / "custom.txt").read_bytes())
                self.assertEqual(b"personal portrait", (app / "image/player.png").read_bytes())
                self.assertEqual(b"new exe" if expected_ok else b"old exe", (app / "timerauto.exe").read_bytes())
                if expected_ok:
                    self.assertTrue(verify_package(app)["ok"])
                    self.assertFalse((app / "_internal/old.dll").exists())
                else:
                    self.assertEqual(b"old DLL", (app / "_internal/old.dll").read_bytes())
                    log = (Path(tempfile.gettempdir()) / "TimerAutoUpdate/apply.log").read_text(encoding="utf-8", errors="replace")
                    self.assertIn("Release hash mismatch" if corrupt else "simulated copy failure", log)
            finally:
                script.unlink(missing_ok=True)

    def test_success_replaces_complete_runtime_preserves_user_data(self):
        self.apply()

    def test_corrupt_staged_package_leaves_install_untouched(self):
        self.apply(corrupt=True)

    def test_copy_failure_restores_previous_install(self):
        self.apply(copy_failure=True)
