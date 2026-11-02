import io
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from access_client import AccessClient, AccessError, Lease, credentials, protect, validate_server, start_monitor, validate_access_configuration
import threading

ROOT = Path(__file__).resolve().parents[1]


class OnlineAccessTests(unittest.TestCase):
    def test_suspended_policy_skips_release_validation_but_enabled_policy_fails_closed(self):
        import access_policy
        self.assertFalse(access_policy.ONLINE_ACCESS_ENABLED)
        with patch('access_policy.ONLINE_ACCESS_ENABLED',False),patch('access_client.validate_server') as check:
            validate_access_configuration()
            check.assert_not_called()
        with patch('access_policy.ONLINE_ACCESS_ENABLED',True),patch('access_policy.AUTH_SERVER_URL',''):
            with self.assertRaises(AccessError):
                validate_access_configuration()

    def test_suspended_startup_runs_without_authorization_monitor_or_credentials(self):
        # Execute only main's AST with fake app objects, never the real app's
        # imports/watchers/OBS. Authentication entry points must be untouched.
        tree=ast.parse((ROOT/'timerauto.py').read_text(encoding='utf8'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        app=MagicMock();app.exec.return_value=0
        main_app=MagicMock()
        scope={'_suppress_qt_window_warnings':MagicMock(),'_ensure_std_streams':MagicMock(),
               'resolve_config_path':lambda:'test-only-config','_setup_logging':MagicMock(),
               'QApplication':MagicMock(return_value=app),'MainApp':MagicMock(return_value=main_app),
               'sys':SimpleNamespace(argv=[],exit=MagicMock())}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'isolated-main','exec'),scope)
        with patch('access_policy.ONLINE_ACCESS_ENABLED',False),patch('access_gui.authorize') as auth,patch('access_gui.AccessGuard') as guard,patch('access_client.credentials') as creds:
            scope['main']()
            auth.assert_not_called();guard.assert_not_called();creds.assert_not_called()
        main_app.show.assert_called_once()
        app.exec.assert_called_once()

    def test_configuration_is_https_origin_only_and_missing_is_not_a_bypass(self):
        self.assertEqual(validate_server('https://auth.example/'),'https://auth.example')
        for value in ('','http://auth.example','https://user:password@auth.example','https://auth.example/path','https://auth.example?token=x','https://auth.example#x','https://auth.example:123'):
            with self.assertRaises((AccessError,ValueError)):
                validate_server(value)

    def test_lease_never_starts_offline_and_errors_never_extend_it(self):
        now=[100]
        lease=Lease(45,lambda:now[0])
        self.assertFalse(lease.observe(None))
        self.assertTrue(lease.observe('approved'))
        now[0]=144
        self.assertTrue(lease.observe(None))
        now[0]=145
        self.assertFalse(lease.observe(None))
        self.assertTrue(lease.observe('approved'))
        self.assertFalse(lease.observe('revoked'))
        self.assertFalse(lease.observe(None))

    def test_pending_unknown_and_revoked_do_not_grant_authority(self):
        for status in ('pending','unknown','revoked'):
            lease=Lease()
            lease.observe('approved')
            self.assertFalse(lease.observe(status))

    def test_running_monitor_immediately_reports_explicit_denial(self):
        client=MagicMock();client.request.return_value='revoked'
        denied=threading.Event()
        reasons=[]
        def stop(reason):
            reasons.append(reason)
            denied.set()
        cancel=start_monitor(client,stop,interval=.01,grace=1)
        self.addCleanup(cancel.set)
        self.assertTrue(denied.wait(1))
        self.assertIn('중지',reasons[0])

    def test_gui_monitor_exits_app_on_revocation_without_obs_or_deleting_files(self):
        script='''
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import access_gui
class Client:
 def request(self,*args):return 'revoked'
app=QApplication([])
app.setQuitOnLastWindowClosed(False)
access_gui.POLL_SECONDS=.01
guard=access_gui.AccessGuard(app,Client())
QTimer.singleShot(2000,app.quit)
app.exec()
assert app.property('access_revoked') is True
assert guard.cancel.is_set()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_https_request_uses_only_pc_id_and_credential_and_bounded_timeout(self):
        client=AccessClient('https://auth.example',{'device_id':'a'*64,'token':'b'*64})
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"status":"approved"}'
        client.opener.open=MagicMock(return_value=response)
        self.assertEqual(client.request('/api/check'),'approved')
        args,kwargs=client.opener.open.call_args
        self.assertEqual(kwargs['timeout'],5)
        self.assertEqual(json.loads(args[0].data),{'device_id':'a'*64})
        self.assertEqual(args[0].get_header('Authorization'),'Bearer '+'b'*64)

    def test_denial_and_malformed_response_fail_closed(self):
        client=AccessClient('https://auth.example',{'device_id':'a'*64,'token':'b'*64})
        for code in (401,403,409):
            client.opener.open=MagicMock(side_effect=HTTPError(client.server,code,'denied',{},io.BytesIO(b'')))
            self.assertEqual(client.request('/api/check'),'revoked')
        client.opener.open=MagicMock(side_effect=OSError('network error with sensitive raw context'))
        with self.assertRaisesRegex(AccessError,'인증 서버') as caught:
            client.request('/api/check')
        self.assertNotIn('sensitive',str(caught.exception))
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"status":"allow-anyone"}'
        client.opener.open=MagicMock(return_value=response)
        with self.assertRaises(AccessError):
            client.request('/api/check')

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_credentials_are_encrypted_stable_and_not_in_project(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.bin'
            with patch('access_client.credential_path',return_value=path),patch('access_client.device_id',return_value='a'*64):
                first=credentials('https://auth.example')
                self.assertNotIn(first['token'].encode(),path.read_bytes())
                self.assertEqual(credentials('https://auth.example'),first)
                with patch('access_client.device_id',return_value='c'*64):
                    with self.assertRaises(AccessError):
                        credentials('https://auth.example')
                self.assertEqual(json.loads(protect(path.read_bytes(),decrypt=True)),first)

    def test_gate_precedes_mainapp_and_release_preflight_does_not_run_app(self):
        source=(ROOT/'timerauto.py').read_text(encoding='utf8')
        main=source[source.index('def main():'):]
        self.assertLess(main.index('authorize(app)'),main.index('MainApp(cfg_path)'))
        self.assertIn('if access_client is None:',main)
        self.assertIn('property("access_revoked")',source)
        self.assertIn('validate_access_configuration()',(ROOT/'build_release.ps1').read_text(encoding='utf8'))

    def test_approval_dialog_waits_for_authority_without_live_app_or_network(self):
        script='''
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import QTimer
from access_gui import ApprovalDialog
class Client:
 identity={'device_id':'a'*64}
 def request(self,*args):return 'approved'
app=QApplication([])
dialog=ApprovalDialog(Client())
QTimer.singleShot(3000,dialog.reject)
assert dialog.exec()==QDialog.DialogCode.Accepted
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node is not installed; server tests require Node 22.13+ / 24')
    def test_cloudflare_protocol_with_real_sqlite(self):
        supported=subprocess.run(['node','-e',"require('node:sqlite')"],capture_output=True,timeout=10)
        if supported.returncode:
            self.skipTest('Node SQLite unavailable; use Node 24 for server tests')
        result=subprocess.run(['node','--test',str(ROOT/'access_server/test_worker.mjs')],cwd=ROOT,
                              capture_output=True,text=True,timeout=30,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
