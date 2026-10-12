import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject

import timerauto
from match_event_ledger import MatchEventLedger
from spectator_log_watcher import SpectatorLogWatcher


def hit(clock, damage=40, effect="Hit"):
    return f"1\t{clock}\t{damage}\t1.00\tred\tleft\t.4\t.5\t1\t2\t3\tJab\t{effect}\tChin\n"


class DamageParseCacheTests(unittest.TestCase):
    def setUp(self):
        self.watcher = SpectatorLogWatcher(SimpleNamespace())

    def read(self, path):
        return self.watcher._read_damage_snapshot(str(path), self.watcher._file_sig(str(path)))

    def test_unchanged_hot_to_full_snapshot_needs_no_file_read_or_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100) + hit(99), encoding="utf-8")
            first = self.read(path)
            with patch("builtins.open", side_effect=AssertionError("duplicate read")), patch.object(
                self.watcher, "_parse_damage_event_parts", side_effect=AssertionError("duplicate parse")
            ):
                self.assertEqual(first, self.read(path))

    def test_append_reuses_old_rows_but_parses_new_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text("".join(hit(180 - i) for i in range(100)), encoding="utf-8")
            self.read(path)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(hit(79))
            with patch.object(self.watcher, "_parse_damage_event_parts", wraps=self.watcher._parse_damage_event_parts) as parse:
                rows = self.read(path)
            self.assertEqual(101, len(rows))
            self.assertEqual(1, parse.call_count)

    def test_derived_verdicts_cannot_pollute_cached_raw_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100), encoding="utf-8")
            first = self.read(path)
            first[0]["counter_mult"] = 8
            first[0]["_central_event"] = {"combo_hits": 8}
            second = self.read(path)
            self.assertEqual(1.0, second[0]["counter_mult"])
            self.assertNotIn("_central_event", second[0])

    def test_truncation_and_same_length_rewrite_are_not_treated_as_append(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100) + hit(99), encoding="utf-8")
            self.read(path)
            path.write_text(hit(88), encoding="utf-8")
            self.assertEqual([88.0], [r["time"] for r in self.read(path)])
            path.write_text(hit(77), encoding="utf-8")
            os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
            self.assertEqual([77.0], [r["time"] for r in self.read(path)])

    def test_partial_last_row_is_reparsed_when_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100) + "1\t99", encoding="utf-8")
            self.assertEqual(1, len(self.read(path)))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(hit(99)[len("1\t99"):])
            self.assertEqual([100.0, 99.0], [r["time"] for r in self.read(path)])

    def test_changed_during_read_is_not_cached_with_stale_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100), encoding="utf-8")
            signature = self.watcher._file_sig(str(path))
            with patch.object(self.watcher, "_file_sig", return_value=(signature[0] + 1, signature[1])):
                self.watcher._read_damage_snapshot(str(path), signature)
            self.assertIsNone(self.watcher._damage_parse_cache)


class FeedbackPriorityTests(unittest.TestCase):
    def test_fast_pass_publishes_classified_hit_before_disk_commit(self):
        watcher = SpectatorLogWatcher(SimpleNamespace())
        watcher._last_fight_round_no = 1
        emitted = []
        watcher._safe_emit_update = lambda data: emitted.append(data) or True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damage_events.txt"
            path.write_text(hit(100), encoding="utf-8")
            watcher._read_damage_update(str(path))
            archive = Mock()
            archive.active.return_value = True

            def persist(*args, **kwargs):
                self.assertTrue(any(p.get("spectator_hit_effect_events") for p in emitted))

            archive.record_classified.side_effect = persist
            watcher._match_archive = archive
            path.write_text(hit(100) + hit(99, effect="Knockdown"), encoding="utf-8")
            with patch.object(watcher, "_parse_damage_event_parts", wraps=watcher._parse_damage_event_parts) as parse:
                hot = watcher._read_damage_update(str(path), fast_only=True)
                hot_calls = parse.call_count
                full = watcher._read_damage_update(str(path))
                self.assertEqual(hot_calls, parse.call_count)
            archive.record_classified.assert_called_once()
            self.assertTrue(hot["spectator_hit_effect_events"][0]["event_tags"])
            self.assertTrue(hot["_hitfx_already_emitted"])
            fx = hot["spectator_hit_effect_events"][0]
            self.assertLessEqual(fx["hitfx_detect_perf_ms"], fx["hitfx_ready_perf_ms"])
            self.assertGreater(fx["hitfx_source_mtime_ns"], 0)
            self.assertIn("spectator_event_engine", full)

    def test_early_combat_and_impact_are_not_duplicated_by_later_update(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        QObject.__init__(app)
        app.cfg = SimpleNamespace(browser_overlay_output_only=True, spectator_hit_effect_fast_emit=True, spectator_hit_effect_latency_log=False)
        app.browser_overlay = Mock()
        app.browser_overlay.snapshot.return_value = {}
        data = {"spectator_hit_effect_events": [{
            "side": "red", "attacker_side": "blue", "damage": 61,
            "screen_x": .4, "screen_y": .5, "event_time": 99,
            "hitfx_key": "one-hit", "event_id": "one-hit", "combo_hits": 2,
            "event_tags": ["hit", "combo"],
        }]}
        app._emit_urgent_spectator_effects(data)
        app.browser_overlay.snapshot.assert_not_called()
        app.browser_overlay.update.assert_not_called()
        app._apply_browser_overlay_direct_update(data, impacts_only=True)
        kinds = [call.args[0] for call in app.browser_overlay.push_event.call_args_list]
        self.assertEqual(["combat_event", "impact"], kinds)

    def test_late_bookkeeping_does_not_replay_fx_after_dedupe_expiry(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        QObject.__init__(app)
        app.cfg = SimpleNamespace(browser_overlay_output_only=True, spectator_hit_effect_fast_emit=True, spectator_hit_effect_latency_log=False)
        app.browser_overlay = Mock()
        app.browser_overlay.snapshot.return_value = {}
        data = {"spectator_hit_effect_events": [{
            "side": "red", "attacker_side": "blue", "damage": 61,
            "screen_x": .4, "screen_y": .5, "hitfx_key": "late-hit",
            "combo_hits": 2, "event_tags": ["hit", "combo"],
        }]}
        app._emit_urgent_spectator_effects(data)
        self.assertTrue(data["_browser_impacts_published_early"])
        with patch("timerauto.time.perf_counter", return_value=10**12):
            app._apply_browser_overlay_direct_update(data, impacts_only=True, skip_impact_push=True)
        self.assertEqual(2, app.browser_overlay.push_event.call_count)
        # A new later hit is not suppressed by another payload's marker.
        new_data = {"spectator_hit_effect_events": [dict(data["spectator_hit_effect_events"][0], hitfx_key="new-hit")]}
        app._emit_urgent_spectator_effects(new_data)
        self.assertEqual(4, app.browser_overlay.push_event.call_count)

    def test_already_emitted_hot_payload_skips_second_publication(self):
        app = timerauto.MainApp.__new__(timerauto.MainApp)
        QObject.__init__(app)
        app.cfg = SimpleNamespace(browser_overlay_output_only=True, spectator_hit_effect_fast_emit=True)
        app._apply_browser_overlay_direct_update = Mock()
        app._emit_urgent_spectator_effects({
            "spectator_hit_effect_events": [{"side": "red", "damage": 60}],
            "_hitfx_already_emitted": True,
        })
        app._apply_browser_overlay_direct_update.assert_not_called()

    def test_same_audio_device_does_not_restart_output_binding(self):
        player = Mock()
        device = object()
        player.audioOutput.return_value.device.return_value = device
        with patch.object(timerauto, "QMediaDevices") as devices:
            devices.defaultAudioOutput.return_value = device
            timerauto._refresh_default_audio_device(player)
            player.audioOutput.return_value.setDevice.assert_not_called()
            devices.defaultAudioOutput.return_value = object()
            timerauto._refresh_default_audio_device(player)
            player.audioOutput.return_value.setDevice.assert_called_once()


class LedgerWriteOptimizationTests(unittest.TestCase):
    def test_unchanged_rows_do_not_write_but_verdict_revision_still_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "match.db")
            ledger = MatchEventLedger(path)
            event = {"time": 99, "damage": 40, "attacker_side": "blue", "receiver_side": "red"}
            with patch("match_event_ledger.time.time", return_value=1000):
                ledger.upsert_events(1, "damage", [event])
            statements = []
            connect = ledger._connect

            def traced_connect():
                db = connect()
                db.set_trace_callback(statements.append)
                return db

            with patch.object(ledger, "_connect", side_effect=traced_connect), patch("match_event_ledger.time.time", return_value=2000):
                ledger.upsert_events(1, "damage", [event])
            self.assertFalse(any(s.startswith("UPDATE events") for s in statements))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(1000, db.execute("SELECT updated_at FROM events").fetchone()[0])
            revised = dict(event, _central_event={"primary": "combo", "combo_hits": 2})
            ledger.upsert_events(1, "damage", [revised], ruleset_version="rules-new")
            row = ledger.records()[1]["events"][0]
            self.assertEqual(2, row["_central_event"]["combo_hits"])
            self.assertEqual({"total": 1, "classified": 1}, ledger.classification_counts("rules-new"))


if __name__ == "__main__":
    unittest.main()
