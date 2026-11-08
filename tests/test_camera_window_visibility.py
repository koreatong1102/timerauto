import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import timerauto
from spectator_camera import auto_camera_keeps_window_open


@unittest.skipUnless(os.name=='nt','Windows window controls')
class CameraWindowVisibilityTests(unittest.TestCase):
    def test_runtime_policy_tracks_running_worker_including_ordered_exit(self):
        thread=Mock();thread.is_alive.return_value=True
        app=SimpleNamespace(_rfc_head_camera=SimpleNamespace(director=SimpleNamespace(thread=thread)))
        with patch('PyQt6.QtWidgets.QApplication.instance',return_value=app):
            self.assertTrue(auto_camera_keeps_window_open())
            thread.is_alive.return_value=False
            self.assertFalse(auto_camera_keeps_window_open())

    def test_absent_camera_does_not_disable_normal_minimize(self):
        with patch('PyQt6.QtWidgets.QApplication.instance',return_value=None):
            self.assertFalse(auto_camera_keeps_window_open())

    def test_minimize_is_suppressed_only_while_director_is_running(self):
        user=Mock()
        with patch.object(timerauto.ctypes,'windll',SimpleNamespace(user32=user)), \
             patch('timerauto.auto_camera_keeps_window_open',side_effect=[True,False]):
            self.assertFalse(timerauto._minimize_spectator_window(200))
            user.ShowWindow.assert_not_called()
            self.assertTrue(timerauto._minimize_spectator_window(200))
        self.assertEqual(user.ShowWindow.call_args.args[1],6)

    def test_visibility_restore_does_not_activate_or_touch_already_visible_window(self):
        user=Mock();user.IsIconic.side_effect=[True,False]
        with patch.object(timerauto.ctypes,'windll',SimpleNamespace(user32=user)), \
             patch('timerauto._find_window_by_title_contains',return_value=200), \
             patch('timerauto._activate_window_reliably') as activate:
            self.assertTrue(timerauto.keep_spectator_window_visible('spectator'))
            self.assertTrue(timerauto.keep_spectator_window_visible('spectator'))
        user.ShowWindow.assert_called_once()
        self.assertEqual(user.ShowWindow.call_args.args[1],4)
        activate.assert_not_called()

    def test_f6_and_f4_never_reminimize_when_auto_camera_is_running(self):
        for vk in (0x75,0x73):
            with self.subTest(vk=vk):
                user=Mock();user.GetForegroundWindow.side_effect=[100,200];user.IsIconic.return_value=True
                with patch.object(timerauto.ctypes,'windll',SimpleNamespace(user32=user)), \
                     patch('timerauto._find_window_by_title_contains',return_value=200), \
                     patch('timerauto._activate_window_reliably',return_value=(True,'ok')) as activate, \
                     patch('timerauto.auto_camera_keeps_window_open',return_value=True), \
                     patch('timerauto._press_vk_sendinput_held',return_value=(True,'ok')) as press, \
                     patch('timerauto.time.sleep'):
                    self.assertTrue(timerauto.toggle_file_camera_once('spectator',vk=vk)[0])
                press.assert_called_once_with(vk,hold_sec=.08)
                user.ShowWindow.assert_not_called()
                self.assertEqual(activate.call_count,2)
