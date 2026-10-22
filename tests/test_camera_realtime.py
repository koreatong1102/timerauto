import threading
import math
import time
import unittest
from unittest.mock import patch

from camera_realtime import FramePacer, CameraPipeline
from spectator_camera import HeadCamera, CameraMotion, restore_head_flags
from tests import test_spectator_camera as camera_tests


class PacerTests(unittest.TestCase):
    def test_comfort_limits_jumps_and_rotation_even_with_zero_smoothing(self):
        motion = CameraMotion()
        motion.aim((0,0,0,0,0,0,1),0,comfort=True)
        motion.aim((4,4,0,0,1,0,0),.01,reset=True,comfort=True)
        pose = motion.sample(1/60,0,0,comfort=True)
        self.assertLessEqual(math.dist(pose[:3],(0,0,0)),2/60+1e-9)
        self.assertLessEqual(abs(pose[1]),.8/60+1e-9)
        self.assertLessEqual(math.degrees(2*math.acos(pose[6])),120/60+1e-6)

    def test_comfort_damps_vertical_bob_more_than_horizontal(self):
        motion = CameraMotion()
        motion.aim((0,0,0,0,0,0,1),0,comfort=True)
        motion.aim((.01,.01,0,0,0,0,1),.01,comfort=True)
        pose = motion.sample(1/60,0,0,comfort=True)
        self.assertGreater(pose[0],pose[1])

    def test_overrun_does_not_sleep_an_extra_frame(self):
        with patch("camera_realtime.time.monotonic",return_value=10):
            pacer = FramePacer(60)
        self.addCleanup(pacer.close)
        self.assertEqual(pacer.remaining(10.025),0)
        self.assertAlmostEqual(pacer.remaining(10.026),1/60-.001)


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        # Reuse the fixture builder without inheriting/rerunning other tests.
        camera_tests.CameraTests.setUp(self)

    def wait_for(self, predicate, seconds=1):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            if predicate():
                return True
            time.sleep(.003)
        return False

    def test_collection_continues_when_publication_is_blocked(self):
        camera = HeadCamera()
        camera.start(self.root,"blue",position_ms=20,rotation_ms=40)
        original_write = camera._write_output
        entered,release = threading.Event(),threading.Event()
        def blocked(output,**kwargs):
            entered.set()
            release.wait(1)
            return original_write(output,**kwargs)
        self.addCleanup(camera.stop)
        self.addCleanup(release.set)
        with patch.object(camera,"_write_output",side_effect=blocked):
            camera.pipeline = CameraPipeline(camera)
            camera.pipeline.start()
            source = self.root/"blue/head_position.txt"
            source.write_text("0 0 1.2 2 3 0 0 0 1")
            self.assertTrue(entered.wait(1))
            source.write_text("0 0 1.4 2 3 0 0 0 1")
            self.assertTrue(self.wait_for(lambda: camera.pipeline.packet and camera.pipeline.packet[1][0] == 1.4))
            self.assertFalse(camera.pipeline.error)
            release.set()
            self.assertTrue(self.wait_for(lambda: camera.writes > 1))
            camera.freeze()

    def test_transient_write_denial_drops_frame_and_recovers(self):
        camera = HeadCamera()
        camera.start(self.root,"blue",position_ms=20,rotation_ms=40)
        self.addCleanup(camera.stop)
        original_write = camera._write_output
        attempts = []
        def write(output,**kwargs):
            attempts.append(1)
            if len(attempts) <= 2:
                raise PermissionError("simulated temporary sharing violation")
            return original_write(output,**kwargs)
        with patch.object(camera,"_write_output",side_effect=write):
            camera.pipeline = CameraPipeline(camera)
            camera.pipeline.start()
            (self.root/"blue/head_position.txt").write_text("0 0 1.4 2 3 0 0 0 1")
            self.assertTrue(self.wait_for(lambda: camera.writes > 1))
            self.assertGreaterEqual(camera.pipeline.write_failures,2)
            self.assertIsNone(camera.pipeline.error)
            camera.freeze()

    def test_freeze_joins_writers_before_head_restore(self):
        camera = HeadCamera()
        camera.start(self.root,"blue",realtime=True,position_ms=20,rotation_ms=40)
        self.addCleanup(camera.stop)
        (self.root/"blue/head_position.txt").write_text("0 0 1.4 2 3 0 0 0 1")
        self.assertTrue(self.wait_for(lambda: camera.writes > 1))
        camera.freeze()
        self.assertTrue(restore_head_flags(self.root,expected=camera.last_output))
        snapshot = self.target.read_bytes()
        time.sleep(.04)
        self.assertEqual(self.target.read_bytes(),snapshot)
        self.assertTrue(self.target.read_text().endswith("False\tFalse"))
