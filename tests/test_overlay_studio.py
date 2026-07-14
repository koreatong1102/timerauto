import json
import os
import socket
import tempfile
import unittest
from urllib.request import Request, urlopen

from browser_overlay import BrowserOverlayServer
from overlay_studio import OverlayStudioStore, runtime_js, sanitize_preset, studio_html


class OverlayStudioTests(unittest.TestCase):
    def test_sanitize_rejects_unknown_elements_and_clamps_values(self):
        result = sanitize_preset({
            "name": "test",
            "elements": {
                "timer": {"x": 99999, "opacity": -4, "visible": False, "color": "#ffeeaa"},
                "notReal": {"x": 30},
            },
        })
        self.assertEqual(result["elements"]["timer"]["x"], 1920.0)
        self.assertEqual(result["elements"]["timer"]["opacity"], 0.0)
        self.assertFalse(result["elements"]["timer"]["visible"])
        self.assertNotIn("notReal", result["elements"])

    def test_store_persists_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "presets", "overlay.json")
            store = OverlayStudioStore(path)
            store.set({"elements": {"blueName": {"x": 25}}}, persist=True)
            loaded = OverlayStudioStore(path).get()
            self.assertEqual(loaded["elements"]["blueName"]["x"], 25.0)

    def test_editor_and_runtime_include_live_edit_contract(self):
        editor = studio_html()
        runtime = runtime_js()
        self.assertIn('id="importFile"', editor)
        self.assertIn('id="snap"', editor)
        self.assertIn("i.oninput", editor)
        self.assertIn("window.__overlayStudioApply=apply", runtime)

    def test_http_api_updates_sse_state_and_persists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = BrowserOverlayServer(port, path_resolver=lambda path: os.path.join(temp_dir, path))
            self.assertTrue(server.start())
            try:
                with urlopen(server.studio_url, timeout=3) as response:
                    self.assertIn("OVERLAY STUDIO", response.read().decode("utf-8"))
                with urlopen(server.url, timeout=3) as response:
                    overlay_html = response.read().decode("utf-8")
                self.assertIn('/studio-runtime.js', overlay_html)
                self.assertIn("window.__overlayStudioApply", overlay_html)
                payload = json.dumps({"elements": {"timer": {"x": 42}}}).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{port}/api/studio/preset?persist=1",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    saved = json.loads(response.read().decode("utf-8"))
                self.assertEqual(saved["elements"]["timer"]["x"], 42.0)
                self.assertEqual(server.snapshot()["studioPreset"]["elements"]["timer"]["x"], 42.0)
                self.assertTrue(os.path.isfile(os.path.join(temp_dir, "presets", "overlay", "overlay_studio.json")))
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
