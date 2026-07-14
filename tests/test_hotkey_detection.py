import inspect
import unittest

from timerauto import MainApp


class _DetectorToggleStub:
    settings_dlg = None

    def __init__(self, running):
        self.running = running
        self.calls = []

    def _detection_running(self):
        return self.running

    def _start_detectors(self):
        self.calls.append("start_all")

    def _stop_detectors(self):
        self.calls.append("stop_all")


class F11DetectorToggleTests(unittest.TestCase):
    def test_all_detector_toggle_starts_and_stops_as_one_unit(self):
        stopped = _DetectorToggleStub(running=False)
        MainApp._toggle_detectors(stopped)
        self.assertEqual(stopped.calls, ["start_all"])

        running = _DetectorToggleStub(running=True)
        MainApp._toggle_detectors(running)
        self.assertEqual(running.calls, ["stop_all"])

    def test_f11_handlers_use_all_detector_toggle(self):
        for handler in (MainApp._poll_hotkeys, MainApp._handle_global_key):
            source = inspect.getsource(handler)
            self.assertIn("self._toggle_detectors()", source)


if __name__ == "__main__":
    unittest.main()
