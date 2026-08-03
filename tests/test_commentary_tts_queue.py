import unittest
from collections import deque

from timerauto import MainApp


class CommentaryTtsQueueTests(unittest.TestCase):
    def _app(self):
        app = MainApp.__new__(MainApp)
        app._commentary_tts_queue = deque()
        app._commentary_tts_queue_draining = False
        app._commentary_tts_busy = {"analyst": True, "caster": False}
        return app

    def test_urgent_line_moves_ahead_of_live_punch_line(self):
        app = self._app()
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        MainApp._enqueue_commentary_tts(app, "레드 선수, 다운입니다!", "caster")

        self.assertEqual("레드 선수, 다운입니다!", app._commentary_tts_queue[0]["text"])
        self.assertEqual("정확한 카운터입니다.", app._commentary_tts_queue[1]["text"])

    def test_queued_line_is_played_when_shared_channel_is_free(self):
        app = self._app()
        played = []
        app._speak_commentary_tts = lambda text, role, **kwargs: played.append((text, role, kwargs))
        MainApp._enqueue_commentary_tts(app, "레드 선수, 다운입니다!", "caster")

        app._commentary_tts_busy = {"analyst": False, "caster": False}
        MainApp._drain_commentary_tts_queue(app)

        self.assertEqual([("레드 선수, 다운입니다!", "caster", {"_from_queue": True})], played)
        self.assertFalse(app._commentary_tts_queue)

    def test_duplicate_snapshot_line_is_queued_once(self):
        app = self._app()
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        MainApp._enqueue_commentary_tts(app, "정확한 카운터입니다.", "analyst")
        self.assertEqual(1, len(app._commentary_tts_queue))


if __name__ == "__main__":
    unittest.main()
