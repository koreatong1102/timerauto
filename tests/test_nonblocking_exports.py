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

from ai_project_snapshot import build_code_index, build_file_manifest, export_project_snapshot
from diagnostic_context import prepare_diagnostic_export
from export_jobs import BackgroundExportJob


class NonblockingExportsTests(unittest.TestCase):
    def test_preparation_never_queries_native_audio_or_discovers_folders(self):
        class BrokenAudio:
            def __getattr__(self,name):
                raise AssertionError('native audio query: '+name)
        owner=SimpleNamespace(cfg=SimpleNamespace(app_audio_output_device='VB'),
            _potm_bgm_player=BrokenAudio(),_potm_bgm_audio_out=BrokenAudio(),
            _commentary_players={'caster':BrokenAudio()},_commentary_audio_outs={'caster':BrokenAudio()},
            _diagnostic_folder=lambda:'output',_diagnostic_app_state=lambda:{},_diagnostic_spectator_root=lambda:'')
        with patch.object(Path,'iterdir',side_effect=AssertionError('UI directory scan')):
            result=prepare_diagnostic_export(owner)
        audio=result['context']['runtime']['audio']
        self.assertEqual(audio['requested_common_device'],'VB')
        self.assertIn('omitted',audio['commentary']['caster']['backend_query'])
        self.assertIn('match_archive_base',result['context'])

    def test_dependency_model_and_generated_trees_are_pruned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'app.py').write_text('def main(): pass\n')
            for name in ('.venv-release','.venv-qwen','.runtime','.qwen_models',
                         'commentary_voice_packs','MatchLogArchive','SpectatorLogArchive','ReportImages'):
                folder=root/name;folder.mkdir();(folder/'large.py').write_text('not valid python!')
            index=build_code_index(td);manifest=build_file_manifest(td)
            self.assertEqual(set(index['files']),{'app.py'})
            self.assertEqual([row['path'] for row in manifest['files']],['app.py'])

    def test_walk_results_have_explicit_limits_without_large_fixtures(self):
        names=[f'f{i:05d}.py' for i in range(5002)]
        with patch('ai_project_snapshot.os.walk',return_value=[('root',[],names)]), \
             patch('ai_project_snapshot._read_text',return_value='x=1'), \
             patch('ai_project_snapshot.os.stat',return_value=SimpleNamespace(st_size=4*1024*1024,st_mtime=1)):
            index=build_code_index('root');manifest=build_file_manifest('root')
        self.assertEqual(len(index['files']),512)
        self.assertIn('truncated',index)
        self.assertEqual(manifest['count'],5000)
        self.assertIn('truncated',manifest)

    def test_failed_snapshot_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td,'diagnostics')
            with patch('ai_project_snapshot.collect_patch_note_heads',side_effect=RuntimeError('fixture')):
                with self.assertRaises(RuntimeError):export_project_snapshot(td,str(output))
            self.assertFalse(list(output.glob('*.zip*')))

    def test_worker_returns_immediately_and_propagates_failure(self):
        entered=threading.Event();release=threading.Event();caller=threading.get_ident()
        def exporter():
            self.assertNotEqual(caller,threading.get_ident())
            entered.set();release.wait(2);raise RuntimeError('fixture')
        job=BackgroundExportJob(exporter,{})
        self.assertTrue(entered.wait(1));self.assertFalse(job.done.is_set())
        release.set();self.assertTrue(job.done.wait(2));self.assertEqual(job.error,'fixture')

    def test_project_button_keeps_qt_alive_and_coalesces_clicks(self):
        code='''
import threading,time
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QWidget,QPushButton,QLabel
from timerauto import SettingsDialog
app=QApplication([]);main=threading.get_ident()
class Owner:
 def _project_snapshot_export_zip(self):raise AssertionError('synchronous exporter called')
 def _project_snapshot_prepare_export(self):return {}
owner=Owner();panel=QWidget()
panel._diagnostics_apply_options=lambda:None
panel._diagnostic_project_snapshot=owner._project_snapshot_export_zip
panel.btn_project_snapshot=QPushButton();panel.btn_diag_export=QPushButton();panel.lbl_diag_status=QLabel()
ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
def slow(**kwargs):
 assert threading.get_ident()!=main
 time.sleep(.25);return 'fixture.zip'
def completed(*args):assert threading.get_ident()==main
with patch('timerauto.export_project_snapshot',side_effect=slow) as export,patch('timerauto.QMessageBox.information',side_effect=completed):
 SettingsDialog._diagnostics_project_snapshot_clicked(panel)
 assert not panel.btn_project_snapshot.isEnabled()
 SettingsDialog._diagnostics_project_snapshot_clicked(panel)
 QTimer.singleShot(650,app.quit);app.exec()
 assert export.call_count==1,export.call_count
assert len(ticks)>20,len(ticks)
assert panel.btn_project_snapshot.isEnabled()
assert panel._project_snapshot_job is None
assert 'fixture.zip' in panel.lbl_diag_status.text()
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=15,env={**os.environ,'QT_QPA_PLATFORM':'offscreen'})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
