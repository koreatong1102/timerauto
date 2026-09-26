import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QUrl

import timerauto
from spectator_log_watcher import SpectatorLogWatcher


class SpectatorEffectLatencyTests(unittest.TestCase):
    def test_dead_file_notifier_uses_fast_fallback_poll(self):
        watcher = SpectatorLogWatcher(SimpleNamespace(spectatorlog_backup_poll_ms=1500))
        self.assertEqual(watcher._change_wait_seconds(True), 0.25)
        watcher._change_thread = Mock()
        watcher._change_thread.is_alive.return_value = True
        watcher._change_handle = 123
        self.assertEqual(watcher._change_wait_seconds(True), 0.5)

    def test_urgent_effect_is_pushed_and_played_once(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        app.cfg = SimpleNamespace(browser_overlay_output_only=True)
        app.browser_overlay = SimpleNamespace(push_event=Mock())
        app._play_spectator_sfx = Mock()
        played, pushed = app._emit_urgent_spectator_effects({
            "spectator_effect_events": [
                {"kind": "knockdown", "side": "blue"},
                {"kind": "knockdown", "side": "blue"},
            ]
        })
        self.assertTrue(pushed)
        self.assertEqual(played, {("knockdown", "blue")})
        self.assertEqual(app.browser_overlay.push_event.call_count, 2)
        app._play_spectator_sfx.assert_called_once_with("knockdown")

    def test_short_effect_reuses_loaded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ko.wav"
            path.write_bytes(b"RIFF")
            url = QUrl.fromLocalFile(str(path))
            player = Mock()
            player.source.return_value = url
            with patch.object(timerauto, "_refresh_default_audio_device"):
                self.assertTrue(timerauto._play_media_sfx(player, Mock(), str(path)))
            player.setSource.assert_not_called()
            player.play.assert_called_once()

    def test_knockdown_fast_pass_emits_before_full_pass_without_replay(self):
        watcher = SpectatorLogWatcher(SimpleNamespace())
        watcher._last_fight_round_no = 1
        emitted = []
        watcher._safe_emit_update = lambda payload: emitted.append(dict(payload)) or True
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "damage_events.txt")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("1\t100\t30\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tHead\n")
            watcher._read_damage_update(path)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("1\t99\t40\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tHook\tKnockdown\tChin\n")
            hot = watcher._read_damage_update(path, fast_only=True)
            full = watcher._read_damage_update(path)
        urgent = [item for item in emitted if item.get("_spectator_urgent_fast_emit")]
        self.assertEqual(len(urgent), 1)
        self.assertEqual(urgent[0]["spectator_effect_events"][0]["kind"], "knockdown")
        self.assertNotIn("spectator_effect_events", hot)
        self.assertNotIn("spectator_effect_events", full)

    def test_hud_uses_official_completed_rounds_plus_live_round_only(self):
        watcher = SpectatorLogWatcher(SimpleNamespace())
        watcher._last_fight_round_no = 2
        watcher._last_round_state = "fight"
        with tempfile.TemporaryDirectory() as root:
            damage_path = os.path.join(root, "damage_events.txt")
            scores_path = os.path.join(root, "scores.csv")
            with open(damage_path, "w", encoding="utf-8") as stream:
                stream.write("1\t100\t30\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tJab\tHit\tHead\n")
            with open(scores_path, "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,9,10,9,0,35,0,0\n")
            first = watcher._read_damage_update(damage_path)
            self.assertEqual(first["blue_damage_dealt"], 35)
            with open(damage_path, "a", encoding="utf-8") as stream:
                stream.write("2\t99\t20\t1.0\tred\tleft\t.4\t.5\t1\t2\t3\tHook\tHit\tChin\n")
            live = watcher._read_damage_update(damage_path)
            self.assertEqual(live["blue_damage_dealt"], 55)
            watcher._last_round_state = "break"
            with open(scores_path, "a", encoding="utf-8") as stream:
                stream.write("2,10,10,20,19,0,0,0,0\n")
            placeholder = watcher._project_hud_damage(scores_path, 2, {"blue": 20, "red": 0})
            self.assertEqual(placeholder["blue"], 55)
            with open(scores_path, "w", encoding="utf-8") as stream:
                stream.write("round,blue_score,red_score,blue_total,red_total,blue_damage_taken,red_damage_taken,blue_kds,red_kds\n")
                stream.write("1,10,9,10,9,0,35,0,0\n")
                stream.write("2,10,9,20,18,0,25,0,0\n")
            watcher._last_round_state = "fight"
            self.assertEqual(watcher._project_hud_damage(scores_path, 2, {"blue": 20, "red": 0})["blue"], 55)
            watcher._last_round_state = "break"
            official = watcher._project_hud_damage(scores_path, 2, {"blue": 20, "red": 0})
            self.assertEqual(official["blue"], 60)
            self.assertEqual(watcher._hud_official_round_damage(2)["blue"], 25)
            watcher._last_round_state = "results"
            watcher._total_damage_dealt["blue"] = 55
            self.assertEqual(watcher._project_hud_damage(scores_path, 2, {"blue": 25, "red": 0})["blue"], 60)

    def test_browser_round_damage_uses_official_display_without_changing_live_metric(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        timerauto.QObject.__init__(app)
        app.cfg = SimpleNamespace(timer_current_round=2, timer_total_rounds=3, timer_seconds_left=180)
        overlay = Mock()
        overlay.snapshot.return_value = {}
        app.browser_overlay = overlay
        app._apply_browser_overlay_direct_update({
            "blue_damage_dealt": 60,
            "blue_round_damage_dealt": 20,
            "blue_round_damage_display": 25,
        })
        self.assertEqual(overlay.update.call_args.kwargs["blueDamageText"], "DMG 25")


if __name__ == "__main__":
    unittest.main()
