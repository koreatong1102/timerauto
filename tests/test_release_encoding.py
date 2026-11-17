"""Publishing must work without preconfigured UTF-8 shell environment variables."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseEncodingTests(unittest.TestCase):
    def test_publish_and_build_enable_utf8_before_any_python_validation(self):
        for filename in ('publish_release.ps1', 'build_release.ps1'):
            with self.subTest(script=filename):
                source = (ROOT / filename).read_text(encoding='utf-8-sig')
                first_python = source.index('& $python')
                self.assertLess(source.index('$env:PYTHONUTF8 = "1"'), first_python)
                self.assertLess(source.index('$env:PYTHONIOENCODING = "utf-8"'), first_python)

    def test_builder_then_shutdown_pass_in_a_non_utf8_parent_without_environment_leak(self):
        code = '''
import os, sys, unittest
from tests.test_qwen_duo_builder import QwenDuoBuilderTests
from tests.test_shutdown_runtime import ShutdownTests
assert sys.flags.utf8_mode == 0
before = dict(os.environ)
suite = unittest.TestSuite([QwenDuoBuilderTests('test_cli_records_cancelled_or_error_as_final_machine_readable_status')])
first = unittest.TextTestRunner().run(suite)
assert dict(os.environ) == before, 'builder test leaked process environment'
second = unittest.TextTestRunner().run(unittest.TestSuite([
    ShutdownTests('test_slow_and_failed_cleanup_keeps_event_loop_alive_and_has_deadline'),
    ShutdownTests('test_korean_output_is_captured_without_parent_locale_assumptions')]))
raise SystemExit(0 if first.wasSuccessful() and second.wasSuccessful() else 1)
'''
        env = dict(os.environ, PYTHONUTF8='0', PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-X', 'utf8=0', '-c', code],
                                cwd=ROOT, env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='backslashreplace', timeout=30)
        self.assertEqual(result.returncode, 0, (result.stdout or '') + (result.stderr or ''))


if __name__ == '__main__':
    unittest.main()
