import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from camera_hybrid import HybridView,multiply,upright,needs_opponent
from spectator_camera import HeadCamera
from config_model import AppConfig


def text(q,position=(0,1.7,0)):
    return ' '.join(map(str,(.5,.5,*position,*q)))


def angles(pose_text):
    row=[float(v) for v in pose_text.split()]
    x,y,z,w=row[5:]
    fx,fy,fz=2*(x*z+w*y),2*(y*z-w*x),1-2*(x*x+y*y)
    return math.degrees(math.atan2(fx,fz)),math.degrees(math.atan2(fy,math.hypot(fx,fz)))


class HybridViewTests(unittest.TestCase):
    raw=(.6111,-.6504,.0333,-.45)
    target=text((0,0,0,1),(0,1.7,2))

    def test_bone_axis_tilt_is_calibrated_and_camera_horizon_is_level(self):
        hybrid=HybridView()
        pose=hybrid.pose(text(self.raw),self.target)
        yaw,pitch=angles(pose)
        self.assertAlmostEqual(yaw,0,places=5);self.assertAlmostEqual(pitch,0,places=5)
        x,y,z,w=[float(v) for v in pose.split()][5:]
        self.assertAlmostEqual(2*(x*y+w*z),0,places=5)

    def test_twenty_degree_head_turn_and_pitch_receive_twenty_percent_assist(self):
        for yaw,pitch in ((20,0),(0,20)):
            hybrid=HybridView();hybrid.pose(text(self.raw),self.target)
            moved=multiply(upright(math.radians(yaw),math.radians(pitch)),self.raw)
            result=angles(hybrid.pose(text(moved),self.target,80))
            self.assertAlmostEqual(result[0],yaw*.8,places=4)
            self.assertAlmostEqual(result[1],pitch*.8,places=4)

    def test_deliberate_look_away_is_not_pulled_back_to_opponent(self):
        hybrid=HybridView();hybrid.pose(text(self.raw),self.target)
        moved=multiply(upright(math.radians(100),0),self.raw)
        self.assertAlmostEqual(angles(hybrid.pose(text(moved),self.target))[0],100,places=4)

    def test_weight_endpoints_and_recalibration(self):
        hybrid=HybridView();hybrid.pose(text(self.raw),self.target)
        moved=multiply(upright(math.radians(30),0),self.raw)
        self.assertAlmostEqual(angles(hybrid.pose(text(moved),self.target,0))[0],0,places=4)
        self.assertAlmostEqual(angles(hybrid.pose(text(moved),self.target,100))[0],30,places=4)
        hybrid.reset()
        self.assertAlmostEqual(angles(hybrid.pose(text(moved),self.target,100))[0],0,places=4)

    def test_roll_is_removed_pitch_is_bounded_and_sign_flip_does_not_spin(self):
        hybrid=HybridView();hybrid.pose(text(self.raw),self.target)
        moved=multiply(upright(.3,math.radians(80)),self.raw)
        first=hybrid.pose(text(moved),self.target,100)
        second=hybrid.pose(text(tuple(-v for v in moved)),self.target,100)
        self.assertAlmostEqual(angles(first)[1],60,places=4)
        self.assertEqual(first,second)
        x,y,z,w=[float(v) for v in first.split()][5:]
        self.assertAlmostEqual(2*(x*y+w*z),0,places=5)

    def test_invalid_samples_never_establish_reference(self):
        for source,target in (('0 0 nan 0 0 0 0 0 1',self.target),
                              (text(self.raw),None),(text(self.raw),text((0,0,0,1)))):
            hybrid=HybridView()
            with self.assertRaises(ValueError):hybrid.pose(source,target)
            self.assertIsNone(hybrid.correction)

    def test_legacy_modes_and_explicit_modes_resolve_consistently(self):
        self.assertFalse(needs_opponent({'look_opponent':False}))
        self.assertTrue(needs_opponent({'view_mode':'hybrid','look_opponent':False}))
        self.assertFalse(needs_opponent({'view_mode':'raw','look_opponent':True}))

    def test_head_camera_hybrid_uses_both_logs_and_recalibration_nonce(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('blue','red','match'):(root/name).mkdir()
            own=root/'blue/head_position.txt';other=root/'red/head_position.txt'
            own.write_text(text(self.raw));other.write_text(self.target)
            (root/'match/camera_input.txt').write_text('0 0 0\t0 0 0 1\t75')
            camera=HeadCamera();camera.start(root,'blue',view_mode='hybrid',hybrid_player_pct=80)
            try:
                first=(root/'match/camera_input.txt').read_text()
                other.write_text(text((0,0,0,1),(1,1.7,2)))
                os.utime(other,ns=(time.time_ns(),time.time_ns()+1000000))
                self.assertTrue(camera.tick())
                self.assertNotEqual(first,(root/'match/camera_input.txt').read_text())
                old=camera.hybrid.correction
                camera.options['hybrid_recalibrate']=1
                self.assertTrue(camera.tick())
                self.assertNotEqual(old,camera.hybrid.correction)
            finally:camera.stop()

    def test_real_time_hybrid_pipeline_has_no_unsupported_options_or_live_log_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('blue','red','match'):(root/name).mkdir()
            (root/'blue/head_position.txt').write_text(text(self.raw))
            (root/'red/head_position.txt').write_text(self.target)
            (root/'match/camera_input.txt').write_text('0 0 0\t0 0 0 1\t75')
            camera=HeadCamera();camera.start(root,'blue',realtime=True,view_mode='hybrid',hybrid_player_pct=80,comfort=True)
            try:
                self.assertTrue(camera.pipeline.ready.wait(1))
                self.assertIsNone(camera.pipeline.error)
                self.assertGreaterEqual(camera.samples,2)
            finally:camera.stop()

    def test_config_and_settings_panel_preserve_mixed_mode_without_starting_camera(self):
        code='''
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QComboBox,QDoubleSpinBox
from config_model import AppConfig
from spectator_camera import create_camera_panel
app=QApplication([]);cfg=AppConfig();panel=create_camera_panel(cfg)
mode=panel.findChild(QComboBox,'cameraViewMode');mode.setCurrentIndex(mode.findData('hybrid'))
mix=panel.findChild(QDoubleSpinBox,'cameraHybridPlayerPct');mix.setValue(75)
assert cfg.camera_view_mode=='hybrid' and cfg.camera_hybrid_player_pct==75
assert app._rfc_head_camera.camera.side is None and app._rfc_head_camera.worker.thread is None
with tempfile.TemporaryDirectory() as temp:
 path=str(Path(temp,'config.json'));cfg.to_json(path);saved=AppConfig.from_json(path)
 assert saved.camera_view_mode=='hybrid' and saved.camera_hybrid_player_pct==75
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
