import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import timerauto


@unittest.skipUnless(os.name=='nt','Windows window activation')
class WindowActivationTests(unittest.TestCase):
    def user(self,*,iconic=False,visible=True,maximized=False):
        user=Mock()
        user.GetForegroundWindow.side_effect=[100,200]
        user.GetWindowThreadProcessId.return_value=20
        user.AttachThreadInput.return_value=True
        user.IsIconic.return_value=iconic
        user.IsWindowVisible.return_value=visible
        user.IsZoomed.return_value=maximized
        return user

    def activate(self,user,restore=True):
        kernel=Mock();kernel.GetCurrentThreadId.return_value=10
        with patch.object(timerauto.ctypes,'windll',SimpleNamespace(user32=user,kernel32=kernel)), \
             patch('timerauto.time.sleep'),patch('timerauto._window_title',return_value='test'):
            return timerauto._activate_window_reliably(200,restore=restore)

    def test_visible_normal_and_maximized_windows_keep_their_original_placement(self):
        for maximized in (False,True):
            for restore in (False,True):
                with self.subTest(maximized=maximized,restore=restore):
                    user=self.user(maximized=maximized)
                    self.assertTrue(self.activate(user,restore=restore)[0])
                    user.ShowWindow.assert_not_called()
                    user.SetWindowPos.assert_not_called()
                    user.MoveWindow.assert_not_called()
                    user.SetForegroundWindow.assert_called_once()

    def test_minimized_window_is_still_restored_before_focus(self):
        user=self.user(iconic=True)
        self.assertTrue(self.activate(user)[0])
        user.ShowWindow.assert_called_once()
        self.assertEqual(user.ShowWindow.call_args.args[1],9)

    def test_hidden_nonminimized_window_is_shown_without_restore(self):
        user=self.user(visible=False)
        self.assertTrue(self.activate(user)[0])
        user.ShowWindow.assert_called_once()
        self.assertEqual(user.ShowWindow.call_args.args[1],5)

    def test_activation_error_still_detaches_input_threads(self):
        user=self.user(maximized=True)
        user.SetForegroundWindow.side_effect=RuntimeError('foreground failure')
        self.assertFalse(self.activate(user)[0])
        user.ShowWindow.assert_not_called()
        self.assertFalse(user.AttachThreadInput.call_args.args[2])
