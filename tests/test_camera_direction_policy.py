import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from camera_direction_policy import DirectorFeed, camera_settings, direction_selftest
from config_model import AppConfig


def event(key, hits, side='blue', **extra):
    return dict(event_id=key,side=side,combo_hits=hits,**extra)


class CameraPolicyTests(unittest.TestCase):
    def update(self, feed, now, *events):
        feed.update({'spectator_event_engine':list(events)},now=now)
        return feed.snapshot(now)[1]

    def test_counter_requires_distinct_real_followup_not_duplicate_delivery(self):
        feed=DirectorFeed()
        counter=event('c',1,counter=True)
        self.assertIsNone(self.update(feed,0,counter))
        self.assertIsNone(self.update(feed,.3,counter))
        candidate=self.update(feed,.5,event('follow',2))
        self.assertEqual(candidate['kind'],'counter_followup')
        self.assertIsNone(feed.snapshot(1.41)[1])

    def test_late_or_broken_chain_cannot_inherit_counter(self):
        feed=DirectorFeed()
        self.update(feed,0,event('c',1,counter=True))
        self.assertIsNone(self.update(feed,1.1,event('late',2)))
        self.update(feed,2,event('c2',1,counter=True))
        self.update(feed,2.1,event('reply',1,side='red'))
        self.assertIsNone(self.update(feed,2.2,event('not-follow',2)))

    def test_pressure_is_one_flow_and_opponent_reply_cancels_it(self):
        feed=DirectorFeed()
        a=self.update(feed,0,event('a',3))
        b=self.update(feed,.3,event('b',4))
        self.assertEqual(a['flow'],b['flow'])
        self.assertIsNone(self.update(feed,.4,event('reply',1,side='red')))
        c=self.update(feed,.6,event('c',3))
        self.assertNotEqual(a['flow'],c['flow'])

    def test_types_can_be_selected_independently(self):
        feed=DirectorFeed(pressure=False,counter=False)
        self.assertIsNone(self.update(feed,0,event('a',10,counter=True)))
        self.assertIsNone(self.update(feed,.2,event('b',11)))
        feed=DirectorFeed(pressure=False,counter=True)
        self.assertIsNone(self.update(feed,0,event('a',4)))
        self.assertIsNone(self.update(feed,.1,event('c',1,counter=True)))
        self.assertEqual(self.update(feed,.3,event('d',2))['kind'],'counter_followup')

    def test_terminal_batch_and_reports_cannot_leave_an_enterable_candidate(self):
        feed=DirectorFeed()
        feed.update({'spectator_event_engine':[event('kd',4,effect_kind='knockdown'),event('combo',5)]},now=0)
        self.assertIsNone(feed.snapshot(0)[1])
        self.assertFalse(feed.snapshot(0)[0])
        self.update(feed,6,event('live',3))
        feed.update({'spectator_round_report':{'round':1}},now=6.1)
        self.assertIsNone(feed.snapshot(6.1)[1])

    def test_configuration_roundtrip_and_invalid_values(self):
        self.assertEqual(camera_settings({'camera_director_cooldown':0})['camera_director_cooldown'],0)
        value=camera_settings({'camera_director_profile':'bad','camera_director_duration':2.5,
                               'camera_director_max_duration':1,'camera_director_min_hits':2})
        self.assertEqual(value['camera_director_profile'],'balanced')
        self.assertEqual(value['camera_director_max_duration'],2.5)
        self.assertEqual(value['camera_director_min_hits'],3)
        with tempfile.TemporaryDirectory() as folder:
            cfg=AppConfig();cfg.camera_director_profile='cautious';cfg.camera_director_cooldown=0
            cfg.camera_director_pressure_enabled=False
            path=str(Path(folder)/'config.json');cfg.to_json(path)
            self.assertEqual(camera_settings(AppConfig.from_json(path)),camera_settings(cfg))

    def test_rehearsal_never_uses_actual_camera_or_input(self):
        self.assertEqual(len(direction_selftest()),9)

    def test_delayed_delivery_cannot_turn_old_hits_into_a_new_shot(self):
        feed=DirectorFeed()
        old=event('old',5)
        feed.update({'spectator_event_engine':[old],'commentary_tts_observed_at':1},now=3)
        self.assertIsNone(feed.snapshot(3)[1])
        self.assertIsNone(self.update(feed,3.1,old))
        self.assertEqual(self.update(feed,3.2,event('fresh',3))['kind'],'pressure')

    def test_priority_diagnostics_distinguish_down_presentation_and_missing_signal(self):
        feed=DirectorFeed()
        feed.update({'spectator_effect_events':[{'kind':'knockdown'}]},now=1)
        self.assertEqual(feed.status(1.2)['priority_cause'],'effect_knockdown')
        feed.update({},busy=True,now=1.3)
        self.assertEqual(feed.status(1.4)['priority_cause'],'presentation_busy')
        feed.update({},now=7)
        self.assertEqual(feed.status(9)['priority_cause'],'stale_signal')

    def test_qt_controls_persist_and_rehearsal_does_not_arm_camera(self):
        code='''
from PyQt6.QtWidgets import QApplication,QComboBox,QDoubleSpinBox,QCheckBox,QPushButton
from unittest.mock import patch
from config_model import AppConfig
from spectator_camera import create_camera_panel
app=QApplication([]);cfg=AppConfig();panel=create_camera_panel(cfg,toggle=lambda:(True,'test'))
panel.findChild(QComboBox,'cameraDirectorProfile').setCurrentIndex(0)
panel.findChild(QDoubleSpinBox,'cameraDirector_cooldown').setValue(0)
panel.findChild(QCheckBox,'cameraDirectorPressure').setChecked(False)
panel.findChild(QCheckBox,'cameraDirectorBroadcast').setChecked(False)
panel.findChild(QDoubleSpinBox,'cameraDirector_target_pct').setValue(22)
panel.findChild(QDoubleSpinBox,'cameraDirector_idle_sec').setValue(10)
assert cfg.camera_director_profile=='cautious' and cfg.camera_director_cooldown==0
assert not cfg.camera_director_pressure_enabled
assert not cfg.camera_director_broadcast_enabled
assert cfg.camera_director_target_pct==22 and cfg.camera_director_idle_sec==10
with patch('PyQt6.QtWidgets.QMessageBox.information') as shown:
 panel.findChild(QPushButton,'cameraDirectorSelfTest').click()
 assert shown.called
service=app._rfc_head_camera
assert not service.director.thread and not service.timer.isActive()
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
