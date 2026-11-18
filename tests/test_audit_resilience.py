"""Regression cases reproduced by the 2026-11-18 audit; no live OBS or files."""
import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from config_model import AppConfig, number_setting
from match_log_archive import MatchLogArchive
from report_images import ReportImageExporter
from spectator_log_watcher import SpectatorLogWatcher
from tests import test_chapter_resume


class AuditSettingsTests(unittest.TestCase):
    def test_explicit_zero_survives_save_and_reload(self):
        keys = ('spectator_commentary_volume', 'obs_highlight_cooldown_sec',
                'overlay_vs_bg_opacity', 'spectator_hit_effect_fill_opacity')
        with tempfile.TemporaryDirectory() as temp:
            cfg = AppConfig()
            for key in keys:
                setattr(cfg, key, 0.0)
            path = str(Path(temp, 'config.json'))
            cfg.to_json(path)
            restored = AppConfig.from_json(path)
            saved = json.loads(Path(path).read_text(encoding='utf-8'))
            for key in keys:
                with self.subTest(key=key):
                    self.assertEqual(saved[key], 0.0)
                    self.assertEqual(getattr(restored, key), 0.0)

    def test_number_setting_keeps_zero_but_rejects_missing_invalid_and_nonfinite(self):
        self.assertEqual(number_setting(0, 100), 0)
        self.assertEqual(number_setting('0', 100), 0)
        for value in (None, '', 'invalid', float('nan'), float('inf')):
            self.assertEqual(number_setting(value, 100), 100)

    def test_preview_and_live_handoff_both_use_zero_volume(self):
        from timerauto import MainApp, SettingsDialog
        app = SimpleNamespace(cfg=SimpleNamespace(spectator_commentary_volume=0.0))
        self.assertEqual(SettingsDialog._commentary_tts_volume(app), 0.0)
        with patch('timerauto.pack_prepare_dialogue', return_value=None), patch('timerauto.pack_usage_voice', return_value='test'):
            self.assertEqual(MainApp._handoff_voice_settings(app, 'caster', {})[2], 0.0)

    def test_legacy_qml_to_browser_sync_keeps_transparent_vs_background(self):
        from browser_overlay_sync import BrowserOverlaySync
        overlay = Mock()
        cfg = AppConfig(); cfg.browser_overlay_output_only = False
        timer = SimpleNamespace(_backend=SimpleNamespace(_overlay_vs_bg_opacity=0.0), _provider=Mock())
        BrowserOverlaySync(cfg, timer, overlay).publish()
        self.assertEqual(overlay.update.call_args.kwargs['vsBgOpacity'], 0.0)


class AuditWriteRetryTests(unittest.TestCase):
    def test_chapter_failed_write_can_retry_without_memory_or_signature_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            app = test_chapter_resume.ChapterResumeTests()._app(temp)
            report = dict(isFinal=True, matchSessionId='retry', winner='blue',
                          blue={'name': 'BLUE'}, red={'name': 'RED'})
            with patch('builtins.open', side_effect=PermissionError('denied')), patch('timerauto.logging.exception'):
                self.assertFalse(app._record_chapter_match_result(report))
            self.assertEqual(app._chapter_events, [])
            self.assertEqual(app._chapter_result_signatures, {})
            self.assertTrue(app._record_chapter_match_result(report))
            self.assertFalse(app._record_chapter_match_result(report))
            rows = Path(app._chapter_jsonl_path).read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])['match_session_id'], 'retry')

    def test_score_write_failure_does_not_poison_dedupe_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = MatchLogArchive(temp)
            archive.start('retry-scores', ('BLUE', 'RED'))
            source = Path(temp, 'official.csv')
            source.write_bytes(b'official scores')
            with patch.object(Path, 'write_bytes', side_effect=OSError('disk full')):
                archive.snapshot_scores(1, str(source), final=True)
            self.assertNotIn('1:final', archive._score_hashes)
            archive.snapshot_scores(1, str(source), final=True)
            self.assertEqual(Path(archive.session_dir, 'scores_final.csv').read_bytes(), source.read_bytes())
            self.assertIn('1:final', archive._score_hashes)

    def test_ledger_failure_after_score_copy_is_also_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = MatchLogArchive(temp)
            archive.start('retry-ledger', ('BLUE', 'RED'))
            source = Path(temp, 'official.csv'); source.write_bytes(b'official scores')
            with patch.object(archive._ledger, 'snapshot_official', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    archive.snapshot_scores(1, str(source))
            self.assertNotIn('1:round', archive._score_hashes)
            with patch.object(archive._ledger, 'snapshot_official') as save:
                archive.snapshot_scores(1, str(source))
            save.assert_called_once()


@unittest.skipUnless(os.name == 'nt', 'Windows notification handles')
class AuditNotifierTests(unittest.TestCase):
    def test_real_windows_notifier_stops_and_restarts_in_temporary_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            watcher = SpectatorLogWatcher(SimpleNamespace())
            for index in range(3):
                stop = threading.Event()
                try:
                    watcher._ensure_change_notifier(temp, stop)
                    thread = watcher._change_thread
                    deadline = time.monotonic() + 2
                    while not watcher._change_handle and thread.is_alive() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertIsNotNone(watcher._change_handle)
                    watcher._change_event.clear()
                    Path(temp, f'{index}.txt').write_text('notification test', encoding='utf-8')
                    self.assertTrue(watcher._change_event.wait(2))
                finally:
                    stop.set()
                    watcher._stop_change_notifier()
                    watcher._change_thread.join(2)
                self.assertFalse(thread.is_alive(), 'old Windows reader did not stop')

    def run_notifier(self, action):
        watcher = SpectatorLogWatcher(SimpleNamespace())
        watcher._change_root = 'root'
        stop = threading.Event()
        kernel = Mock()
        kernel.CreateFileW.return_value = 111
        kernel.ReadDirectoryChangesW.side_effect = lambda *args: action(watcher, stop)
        with patch('spectator_log_watcher.ctypes.windll.kernel32', kernel):
            watcher._watch_log_directory_changes('root', stop)
        closed = [call.args[0].value for call in kernel.CloseHandle.call_args_list]
        return watcher, closed

    def test_old_notifier_never_closes_new_handle_even_if_number_is_reused(self):
        for new_handle in (222, 111):
            def replace(watcher, stop):
                watcher._stop_change_notifier()
                watcher._change_root = 'root'
                watcher._change_handle = new_handle
                stop.set()
                return 0
            watcher, closed = self.run_notifier(replace)
            self.assertEqual(closed, [111])  # Only stop() closes the OLD generation.
            self.assertEqual(watcher._change_handle, new_handle)

    def test_natural_exit_closes_local_handle_once_and_clears_pointer(self):
        watcher, closed = self.run_notifier(lambda *_: 0)
        self.assertEqual(closed, [111])
        self.assertIsNone(watcher._change_handle)

    def test_handle_created_after_stop_is_closed_without_publishing(self):
        watcher = SpectatorLogWatcher(SimpleNamespace())
        watcher._change_root = 'root'
        kernel = Mock()
        def create(*args):
            watcher._stop_change_notifier()
            return 111
        kernel.CreateFileW.side_effect = create
        with patch('spectator_log_watcher.ctypes.windll.kernel32', kernel):
            watcher._watch_log_directory_changes('root', threading.Event())
        kernel.ReadDirectoryChangesW.assert_not_called()
        self.assertEqual(kernel.CloseHandle.call_args.args[0].value, 111)
        self.assertIsNone(watcher._change_handle)


class AuditReportImageTests(unittest.TestCase):
    def worker(self):
        overlay = Mock()
        overlay.snapshot.return_value = {'blueName': 'original', 'events': []}
        overlay.image_path.return_value = ''
        worker = ReportImageExporter(overlay)
        worker.worker = Mock(); worker.worker.is_alive.return_value = True
        return worker

    def report(self, temp, revision=0, damage=100):
        return dict(isFinal=True, matchSessionId='match', reportRevision=revision,
                    blue={'damage': damage}, _reportImage=dict(folder=temp, filename='final.png'))

    def test_pending_correction_coalesces_without_duplicate_queue_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker()
            self.assertTrue(worker.enqueue(self.report(temp)))
            worker.overlay.snapshot.return_value = {'blueName': 'next match'}
            self.assertTrue(worker.enqueue(self.report(temp, 1, 200)))
            self.assertFalse(worker.enqueue(self.report(temp)))
            self.assertEqual(worker.queue.qsize(), 1)
            target = worker.queue.get_nowait()
            self.assertEqual(worker.latest[target]['report']['blue']['damage'], 200)
            self.assertEqual(worker.latest[target]['state']['blueName'], 'original')
            with patch.object(worker, '_render', return_value=True):
                worker._process_target(target)
            self.assertNotIn(target, worker.pending)

    def test_completed_correction_keeps_frozen_match_and_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp))
            target = worker.queue.get_nowait()
            with patch.object(worker, '_render', return_value=True):
                worker._process_target(target)
            Path(target).write_bytes(b'old image')
            worker.overlay.snapshot.return_value = {'blueName': 'next match'}
            self.assertTrue(worker.enqueue(self.report(temp, 2, 200)))
            self.assertEqual(worker.latest[target]['state']['blueName'], 'original')
            self.assertFalse(worker.enqueue(self.report(temp, 1, 150)))
            with patch.object(worker, '_render', return_value=True):
                worker._process_target(target)
            self.assertEqual(worker.completed[target]['revision'], 2)
            self.assertFalse(worker.enqueue(self.report(temp, 1, 150)))

    def test_new_revision_during_render_is_processed_before_finishing(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp))
            target = worker.queue.get_nowait(); rendered = []
            def render(job):
                rendered.append(job['revision'])
                if job['revision'] == 0:
                    worker.enqueue(self.report(temp, 1, 200))
                    return False
                return True
            with patch.object(worker, '_render', side_effect=render):
                worker._process_target(target)
            self.assertEqual(rendered, [0, 1])
            self.assertEqual(worker.completed[target]['report']['blue']['damage'], 200)

    def test_equal_content_higher_revision_still_blocks_older_corrections(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp))
            target = worker.queue.get_nowait()
            self.assertFalse(worker.enqueue(self.report(temp, 3, 100)))
            self.assertFalse(worker.enqueue(self.report(temp, 2, 50)))
            self.assertEqual(worker.latest[target]['revision'], 3)

    def test_queue_full_does_not_leave_an_unserviceable_pending_job(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker()
            for index in range(worker.queue.maxsize):
                report = self.report(temp)
                report['_reportImage']['filename'] = f'{index}.png'
                self.assertTrue(worker.enqueue(report))
            with patch('report_images.logging.exception'):
                self.assertFalse(worker.enqueue(self.report(temp)))
            target = str(Path(temp, 'final.png'))
            self.assertNotIn(target, worker.pending)
            self.assertNotIn(target, worker.latest)
            worker.queue.get_nowait()
            self.assertTrue(worker.enqueue(self.report(temp)))

    def test_transient_failure_retries_then_completes(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp))
            target = worker.queue.get_nowait()
            with patch.object(worker, '_render', side_effect=[TimeoutError('browser'), True]) as render, patch('report_images.time.sleep'):
                worker._process_target(target)
            self.assertEqual(render.call_count, 2)
            self.assertIn(target, worker.completed)
            self.assertNotIn(target, worker.failures)

    def test_permanent_failure_is_bounded_retained_and_manually_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); report = self.report(temp); worker.enqueue(report)
            target = worker.queue.get_nowait()
            with patch.object(worker, '_render', side_effect=OSError('denied')) as render, patch('report_images.time.sleep'), patch('report_images.logging.exception'):
                worker._process_target(target)
            self.assertEqual(render.call_count, 3)
            self.assertNotIn(target, worker.pending)
            self.assertEqual(worker.failures[target]['attempts'], 3)
            self.assertTrue(worker.enqueue(report))
            with patch.object(worker, '_render', return_value=True):
                worker._process_target(worker.queue.get_nowait())
            self.assertNotIn(target, worker.failures)

    def test_failed_new_revision_cannot_be_replaced_by_an_older_update(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp, 3, 300))
            target = worker.queue.get_nowait()
            with patch.object(worker, '_render', side_effect=OSError('denied')), patch('report_images.time.sleep'), patch('report_images.logging.exception'):
                worker._process_target(target)
            self.assertFalse(worker.enqueue(self.report(temp, 2, 200)))
            self.assertEqual(worker.failures[target]['revision'], 3)
            self.assertTrue(worker.enqueue(self.report(temp, 3, 300)))

    def test_stale_render_cannot_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = self.worker(); worker.enqueue(self.report(temp))
            target = worker.queue.get_nowait(); job = worker.latest[target]
            Path(target).write_bytes(b'keep existing')
            def browser_run(*args, **kwargs):
                token = next(iter(worker.jobs))
                worker.mark_ready(token)
                return SimpleNamespace(returncode=0, stderr=b'')
            def save(source, candidate, token):
                Path(candidate).write_bytes(b'stale render')
                worker.enqueue(self.report(temp, 1, 200))
            with patch('report_images.browser_executable', return_value='browser'), patch('report_images.render_html', return_value='html'), patch('report_images.subprocess.run', side_effect=browser_run), patch('report_images.os.path.isfile', return_value=True), patch('report_images.save_png', side_effect=save):
                self.assertFalse(worker._render(job))
            self.assertEqual(Path(target).read_bytes(), b'keep existing')
            self.assertEqual(list(Path(temp).glob('*.render.png')), [])

    def test_late_potm_revision_updates_only_export_not_live_presentation(self):
        # Exercise the actual nested dispatch function, isolating the already-played
        # guard from the rest of MainApp (no QApplication/OBS/player is started).
        source = Path(__file__).resolve().parents[1] / 'timerauto.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        dispatch = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == '_push_report')
        dispatch = copy.deepcopy(dispatch)
        dispatch.args.defaults = []
        overlay = Mock()
        namespace = dict(self=SimpleNamespace(_potm_played=True), overlay=overlay,
                         DIAG=Mock(), logging=Mock())
        exec(compile(ast.fix_missing_locations(ast.Module(body=[dispatch], type_ignores=[])), str(source), 'exec'), namespace)
        payload = dict(isFinal=True, reportRevision=1)
        namespace['_push_report'](payload, 0)
        overlay.report_images.enqueue.assert_called_once_with(payload)
        overlay.push_event.assert_not_called()
        overlay.report_images.enqueue.reset_mock()
        namespace['_push_report'](dict(isFinal=True, reportRevision=0), 0)
        overlay.report_images.enqueue.assert_not_called()

