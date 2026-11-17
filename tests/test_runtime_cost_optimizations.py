import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from config_model import AppConfig
from idle_video_library import IdleVideoScanner, VideoLibrarySnapshot, scan_video_library
from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher


class RuntimeCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def watcher_and_throws(self):
        watcher = SpectatorLogWatcher(AppConfig())
        archive = MatchLogArchive(str(self.root / 'archive'))
        archive.start('cost-test', ('BLUE', 'RED'))
        self.addCleanup(archive.close)
        watcher._match_archive = archive
        path = self.root / 'punches_thrown.txt'
        path.write_text('1\t100.0\tblue\tleft\tJab\n', encoding='utf-8')
        return watcher, archive, path

    def test_unchanged_throws_skip_merge_but_same_size_rewrite_is_read(self):
        w, archive, path = self.watcher_and_throws()
        with patch.object(archive, 'record_throws', wraps=archive.record_throws) as record:
            w._archive_thrown_snapshot(str(path), 1)
            w._archive_thrown_snapshot(str(path), 1)
            self.assertEqual(record.call_count, 1)
            path.write_text('1\t099.0\tblue\tleft\tJab\n', encoding='utf-8')
            st = path.stat(); os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000))
            w._archive_thrown_snapshot(str(path), 1)
            self.assertEqual(record.call_count, 2)
        self.assertEqual(len(archive.round_records()[1]['throws']), 2)

    def test_replacement_deletion_round_and_archive_invalidate_throw_cache(self):
        w, archive, path = self.watcher_and_throws()
        w._archive_thrown_snapshot(str(path), 1)
        st = path.stat()
        replacement = path.with_suffix('.new')
        replacement.write_text('1\t099.0\tblue\tleft\tJab\n', encoding='utf-8')
        os.utime(replacement, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(replacement, path)
        w._archive_thrown_snapshot(str(path), 1)
        self.assertEqual(len(archive.round_records()[1]['throws']), 2)
        with patch.object(archive, 'record_throws', wraps=archive.record_throws) as record:
            w._archive_thrown_snapshot(str(path), 2)
            self.assertEqual(record.call_count, 1)
            path.unlink(); w._archive_thrown_snapshot(str(path), 2)
            path.write_text('1\t099.0\tblue\tleft\tJab\n', encoding='utf-8')
            w._archive_thrown_snapshot(str(path), 2)
            self.assertEqual(record.call_count, 2)
        other = MatchLogArchive(str(self.root / 'other'))
        other.start('next-match', ('BLUE', 'RED')); self.addCleanup(other.close)
        w._match_archive = other
        w._archive_thrown_snapshot(str(path), 2)
        self.assertEqual(len(other.round_records()[1]['throws']), 1)

    def test_failed_or_mid_write_snapshot_is_retried(self):
        w, archive, path = self.watcher_and_throws()
        with patch.object(archive, 'record_throws', return_value=False):
            w._archive_thrown_snapshot(str(path), 1)
        self.assertIsNone(w.__dict__.get('_archived_throws_snapshot'))
        original = archive.record_throws
        def changes_during_merge(*args):
            result = original(*args)
            path.write_text('1\t098.0\tblue\tleft\tJab\n', encoding='utf-8')
            return result
        with patch.object(archive, 'record_throws', side_effect=changes_during_merge):
            w._archive_thrown_snapshot(str(path), 1)
        self.assertIsNone(w.__dict__.get('_archived_throws_snapshot'))
        w._archive_thrown_snapshot(str(path), 1)
        self.assertEqual(len(archive.round_records()[1]['throws']), 2)

    def test_mirror_write_failure_does_not_latch_seen_or_snapshot(self):
        w, archive, path = self.watcher_and_throws()
        with patch.object(Path, 'open', side_effect=PermissionError('fixture')):
            w._archive_thrown_snapshot(str(path), 1)
        self.assertFalse(archive._seen_throws)
        self.assertIsNone(w.__dict__.get('_archived_throws_snapshot'))
        w._archive_thrown_snapshot(str(path), 1)
        self.assertEqual(len((Path(archive.session_dir) / 'punches_thrown.jsonl').read_text().splitlines()), 1)

    def test_interrupted_mirror_recovers_complete_rows_without_duplicates(self):
        _w, archive, _path = self.watcher_and_throws()
        one = {'time': 100., 'side': 'blue', 'hand': 'left', 'punch': 'Jab'}
        two = {**one, 'time': 99.}
        target = Path(archive.session_dir) / 'punches_thrown.jsonl'
        target.write_text(json.dumps({'round': 1, 'event': one}) + '\n{"round":', encoding='utf-8')
        archive._append_retry_files = {'punches_thrown.jsonl'}
        self.assertTrue(archive.record_throws(1, [one, two]))
        valid = []
        for line in target.read_text().splitlines():
            try: valid.append(json.loads(line))
            except ValueError: pass
        self.assertEqual([row['event']['time'] for row in valid], [100., 99.])

    def test_report_cache_is_build_scoped_and_matches_uncached_output(self):
        w, archive, throws = self.watcher_and_throws()
        damage = self.root / 'damage_events.txt'; damage.write_text('')
        (self.root / 'scores.csv').write_text('round,blue_score,red_score\n1,10,9\n')
        event = {'time': 100., 'attacker_side': 'blue', 'receiver_side': 'red',
                 'damage': 35., 'punch': 'Jab', 'hand': 'left', 'counter_mult': 1.2,
                 'damage_type': 'Hit', 'weak_point': 'Nose'}
        archive.record_damage(1, [event]); w._archive_thrown_snapshot(str(throws), 1)
        w._last_round_state = 'break'
        w._rebuild_archive_classifications(force=True)
        args = (str(damage), 1, ('BLUE', 'RED'))
        w._last_round_report_key = None
        baseline = w._compute_round_report_payload(*args, force_final=False)
        w._last_round_report_key = None
        with patch.object(archive, 'reconcile', wraps=archive.reconcile) as reconcile, \
             patch.object(w, '_compute_report_scorecard_rounds', wraps=w._compute_report_scorecard_rounds) as stats:
            report = w._build_round_report_payload(*args, force_final=False)
        self.assertTrue(report)
        self.assertEqual(report, baseline)
        self.assertEqual(reconcile.call_count, 1)
        self.assertEqual(stats.call_count, 1)
        self.assertIsNone(w._report_build_cache)
        archive.record_damage(1, [{**event, 'time': 99., 'damage': 70.}])
        w._last_round_report_key = None
        updated = w._build_round_report_payload(*args, force_final=False)
        self.assertNotEqual(updated['blue'], report['blue'])
        with patch.object(w, '_compute_round_report_payload', side_effect=ValueError('fixture')):
            with self.assertRaises(ValueError):w._build_round_report_payload(*args)
        self.assertIsNone(w._report_build_cache)

    def test_library_single_pass_preserves_paths_and_metadata(self):
        from timerauto import MainApp
        child = self.root / '선수' / 'KO_REPLAY'; child.mkdir(parents=True)
        for path in (self.root / 'one.MKV', child / 'two.mp4'):path.write_bytes(b'fixture')
        (child / 'empty.mp4').touch(); (child / 'notes.txt').write_text('ignore')
        result = scan_video_library(str(self.root))
        self.assertEqual(len(result.files), 2)
        self.assertEqual(result.signature, MainApp._idle_highlight_playlist_signature_for(list(result.files)))
        self.assertEqual(scan_video_library(str(child / 'empty.mp4')).files, ())
        self.assertEqual(scan_video_library(str(child / 'missing')).files, ())

    def test_failed_report_verification_is_not_cached_as_success(self):
        w, archive, _path = self.watcher_and_throws()
        w._report_build_cache = {}
        w._event_ruleset_version = lambda:'fixture-rules'
        with patch.object(archive, 'classification_counts', return_value={'total':0, 'classified':0}), \
             patch.object(archive, 'reconcile', side_effect=[{'ok':False}, {'ok':True}]) as reconcile:
            w._rebuild_archive_classifications()
            self.assertNotIn('classification', w._report_build_cache)
            w._rebuild_archive_classifications()
            w._rebuild_archive_classifications()
            self.assertEqual(reconcile.call_count, 2)
        w._report_build_cache = {}
        with patch.object(w, '_compute_report_scorecard_rounds', return_value={}) as compute:
            w._report_scorecard_rounds(); w._report_scorecard_rounds()
            self.assertEqual(compute.call_count, 2)

    def test_worker_coalesces_and_discards_old_path_and_stops_after_one_scan(self):
        entered = threading.Event(); release = threading.Event(); done = threading.Event()
        calls = []; delivered = []
        def scan(path):
            calls.append(path)
            if path == 'A':entered.set(); release.wait(2)
            return VideoLibrarySnapshot(path, (), ())
        def receive(result):delivered.append(result); done.set()
        worker = IdleVideoScanner(receive); self.addCleanup(worker.close); self.addCleanup(release.set)
        with patch('idle_video_library.scan_video_library', side_effect=scan):
            self.assertTrue(worker.request('A')); self.assertTrue(entered.wait(1))
            for _ in range(10):self.assertFalse(worker.request('B'))
            release.set(); self.assertTrue(done.wait(2))
            self.assertEqual(calls, ['A', 'B'])
            self.assertEqual([r.path for r in delivered], ['B'])
            self.assertTrue(worker.is_current(delivered[0]))
            worker.close()
            self.assertFalse(worker.is_current(delivered[0]))
            self.assertFalse(worker.request('C'))

    def test_scanner_error_preserves_playlist_and_trusted_publish_does_no_stat(self):
        from timerauto import MainApp
        from browser_overlay import BrowserOverlayServer
        server = BrowserOverlayServer()
        with patch('browser_overlay.os.path.isfile', side_effect=AssertionError('UI stat')):
            server.set_highlight_playlist([str(self.root / 'known.mp4')], validated=True)
        self.assertEqual(server.snapshot()['idleHighlightCount'], 1)
        cfg = AppConfig(); cfg.idle_highlight_enabled = True; cfg.idle_highlight_path = str(self.root)
        fake = SimpleNamespace(cfg=cfg, _idle_highlight_library=SimpleNamespace(is_current=lambda r:True),
            _sync_idle_highlight_playlist=Mock())
        MainApp._idle_highlight_scan_finished(fake, VideoLibrarySnapshot(str(self.root), (), (), error='denied'))
        fake._sync_idle_highlight_playlist.assert_not_called()

    def test_qt_remains_responsive_and_result_is_committed_on_ui_thread(self):
        code = '''
import tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QCoreApplication,QObject,QTimer,Qt
from timerauto import MainApp
from browser_overlay import BrowserOverlayServer
from config_model import AppConfig
from idle_video_library import IdleVideoScanner,scan_video_library
qt=QCoreApplication([])
with tempfile.TemporaryDirectory() as td:
 Path(td,'video.mp4').write_bytes(b'fixture')
 app=MainApp.__new__(MainApp);QObject.__init__(app)
 app.cfg=AppConfig();app.cfg.idle_highlight_path=td;app.cfg.idle_highlight_enabled=True
 app.browser_overlay=BrowserOverlayServer();app._idle_highlight_playlist_signature=None
 app._idle_highlight_library=IdleVideoScanner(app._idle_highlight_scan_ready.emit)
 seen=[];main=threading.get_ident()
 def finished(result):
  assert threading.get_ident()==main
  app._idle_highlight_scan_finished(result);seen.append(result)
 app._idle_highlight_scan_ready.connect(finished,Qt.ConnectionType.QueuedConnection)
 ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
 def slow(path):
  assert threading.get_ident()!=main
  time.sleep(.2);return scan_video_library(path)
 with patch('idle_video_library.scan_video_library',side_effect=slow):
  started=time.monotonic();app._refresh_idle_highlight_playlist()
  assert time.monotonic()-started<.1
  QTimer.singleShot(450,qt.quit);qt.exec()
 app._idle_highlight_library.close()
 assert len(ticks)>15,len(ticks)
 assert len(seen)==1,len(seen)
 assert app.browser_overlay.snapshot()['idleHighlightCount']==1
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
            cwd=Path(__file__).resolve().parents[1], env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
