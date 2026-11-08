import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ShutdownTests(unittest.TestCase):
    def run_qt(self, code):
        result = subprocess.run([sys.executable, '-u', '-X', 'faulthandler', '-c', code], cwd=ROOT,
                                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_slow_and_failed_cleanup_keeps_event_loop_alive_and_has_deadline(self):
        self.run_qt('''
import threading,time
from PyQt6.QtCore import QCoreApplication,QTimer
from shutdown_runtime import finish_shutdown
app=QCoreApplication([])
ticks=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
release=threading.Event()
def fail():raise RuntimeError('intentional cleanup failure')
started=time.monotonic()
pending=finish_shutdown([('blocked',lambda:release.wait(2)),('failed',fail)],timeout=.15)
release.set()
assert pending==['blocked'],pending
assert time.monotonic()-started<1
assert len(ticks)>=3,ticks
assert finish_shutdown([],timeout=.1)==[]
''')

    def test_real_settings_save_only_and_quit_signal_never_restart_services(self):
        self.run_qt('''
import os,tempfile,time,threading,logging,sys,traceback
logging.basicConfig(level=logging.INFO)
sys.excepthook=lambda t,v,tb:traceback.print_exception(t,v,tb,file=sys.__stderr__)
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject,QTimer
from timerauto import MainApp,SettingsDialog
from config_model import AppConfig
app=QApplication([])
with tempfile.TemporaryDirectory() as root,chdir(root):
 cfg=AppConfig();cfg_path=os.path.join(root,'config.json')
 dlg=SettingsDialog(None,cfg,None,None,cfg_path=cfg_path)
 dlg.chk_spectatorlog_enabled.setChecked(True)
 dlg._apply_timer.stop()
 dlg._log_running=lambda:False
 dlg._log_detection_start=Mock();dlg._log_detection_stop=Mock()
 dlg._obs_reconfigure=Mock();dlg._idle_highlight_refresh=Mock()
 dlg.controller=SimpleNamespace(ui_update=Mock(),timer_win=Mock())
 dlg.apply_only(silent=True,save_only=True)
 dlg._log_detection_start.assert_not_called();dlg._obs_reconfigure.assert_not_called()
 dlg._idle_highlight_refresh.assert_not_called();dlg.controller.ui_update.emit.assert_not_called()
 main=MainApp.__new__(MainApp);QObject.__init__(main)
 main.cfg=cfg;main.cfg_path=cfg_path;main.settings_dlg=dlg
 main._global_hotkeys_enabled=False
 calls=[];ui_thread=threading.get_ident()
 def disable():
  assert threading.get_ident()!=ui_thread
  calls.append('disable');time.sleep(.15)
 def disconnect():calls.append('disconnect')
 main._shutdown_source_record_with_timer=disable
 main.obs_integration=SimpleNamespace(stop=disconnect)
 main.browser_overlay=SimpleNamespace(stop=lambda:calls.append('browser'))
 main.watcher=SimpleNamespace(stop=lambda:calls.append('screen'))
 main.spectator_watcher=SimpleNamespace(stop=lambda:calls.append('logs'))
 main._export_chapter_txt=lambda:Path(root,'chapters.txt').write_text('retained',encoding='utf-8')
 ticks=[];heartbeat=QTimer();heartbeat.setInterval(5);heartbeat.timeout.connect(lambda:ticks.append(1));heartbeat.start()
 app.aboutToQuit.connect(main.on_app_quit)
 with patch('timerauto.DIAG.close'):
  QTimer.singleShot(10,app.quit)
  app.exec()
 assert len(ticks)>=5,ticks
 assert calls.index('disable')<calls.index('disconnect'),calls
 assert main._shutting_down and not main._log_detector_start_pending
 assert Path(cfg_path).exists() and Path(root,'chapters.txt').read_text()=='retained'
 assert dlg._quitting
 dlg._log_detection_start.assert_not_called();dlg._obs_reconfigure.assert_not_called()
 before=list(calls);main.on_app_quit();assert calls==before
 main._start_log_detector();main._start_spectator_watcher_if_enabled();main._reconfigure_obs_integration()
 main.apply_ui_update({'overlay_hud_y':500});assert cfg.overlay_hud_y==0
 dlg._apply_timer.stop();dlg.deleteLater()
''')


if __name__ == '__main__':
    unittest.main()
