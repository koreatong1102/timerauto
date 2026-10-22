import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import subprocess
import sys
from spectator_camera import HeadCamera, pose_to_camera, CameraMotion, CameraWorker, restore_head_flags, replace_camera_file


class CameraTests(unittest.TestCase):
    def test_controls_share_one_inactive_service_and_do_not_touch_live_logs(self):
        script = '''
from types import SimpleNamespace
from PyQt6.QtWidgets import QApplication, QPushButton
from spectator_camera import create_camera_panel
import time
app = QApplication([])
cfg = SimpleNamespace(spectatorlog_path='Z:/missing/rfc-test-path')
a = create_camera_panel(cfg)
service = app._rfc_head_camera
b = create_camera_panel(cfg)
assert service is app._rfc_head_camera
assert not service.timer.isActive()
next(x for x in a.findChildren(QPushButton) if x.text() == '블루 시점 추적').click()
service.worker.thread.join(timeout=2)
service.tick()
assert not service.timer.isActive() and service.camera.side is None
assert '추적 중지' in service.message
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("blue", "red", "match"):
            (self.root / folder).mkdir()
        for side in ("blue", "red"):
            (self.root / side / "head_position.txt").write_text(".2 .3 1 2 3 0 0 0 1")
        self.target = self.root / "match" / "camera_input.txt"
        self.target.write_text("0 0 0\t0 0 0 1\t60\tFalse\tFalse")

    def test_world_coordinates_not_screen_coordinates_and_selected_head_only(self):
        text = pose_to_camera(".2 .3 1 2 3 0 0 0 1", "blue")
        self.assertEqual(text.split("\t"), ["1.000 2.000 3.000", "0.000000 0.000000 0.000000 1.000000", "75.00", "True", "False"])
        self.assertTrue(pose_to_camera(".2 .3 1 2 3 0 0 0 1", "red").endswith("False\tTrue"))

    def test_yaw_and_local_forward_offset(self):
        text = pose_to_camera("0 0 1 2 3 0 0 0 1", "blue", forward_cm=10, yaw=90)
        self.assertEqual(text.split("\t")[0], "1.100 2.000 3.000")

    def test_invalid_pose_or_parameters_never_pass(self):
        for text in ("0 0 1", "0 0 nan 2 3 0 0 0 1", "0 0 1 2 3 0 0 0 0"):
            with self.assertRaises(ValueError):
                pose_to_camera(text, "blue")
        for options in ({"fov": 0}, {"yaw": 181}, {"forward_cm": float("inf")}):
            with self.assertRaises(ValueError):
                pose_to_camera("0 0 1 2 3 0 0 0 1", "red", **options)

    def test_start_is_opt_in_and_writes_only_changed_samples(self):
        camera = HeadCamera()
        self.assertFalse(camera.tick())
        camera.start(self.root, "blue")
        self.assertEqual(camera.writes, 1)
        self.assertFalse(camera.tick())
        head = self.root / "blue" / "head_position.txt"
        head.write_text("0 0 4 5 6 0 0 0 1")
        os.utime(head, ns=(time.time_ns(), time.time_ns()+1000000))
        self.assertTrue(camera.tick())
        self.assertTrue(self.target.read_text().startswith("4.000 5.000 6.000"))
        camera.stop()
        original = self.target.read_bytes()
        self.assertFalse(camera.tick())
        self.assertEqual(original, self.target.read_bytes())

    def test_literal_tab_serialization_is_preserved(self):
        self.target.write_text("0 0 0\\t0 0 0 1\\t60\\tFalse\\tFalse")
        camera = HeadCamera()
        camera.start(self.root, "red")
        self.assertIn("\\t", self.target.read_text())
        self.assertNotIn("\t", self.target.read_text())

    def test_stale_or_partial_head_never_overwrites_camera(self):
        camera = HeadCamera()
        source = self.root / "blue" / "head_position.txt"
        original = self.target.read_bytes()
        os.utime(source, (time.time()-10, time.time()-10))
        with self.assertRaises(ValueError):
            camera.start(self.root, "blue")
        self.assertIsNone(camera.side)
        self.assertEqual(original, self.target.read_bytes())
        source.write_text("0 0 1")
        with patch("spectator_camera.time.monotonic", return_value=100):
            camera.start(self.root, "blue")
        self.assertEqual(camera.side, "blue")
        with patch("spectator_camera.time.monotonic", return_value=101.1):
            with self.assertRaises(ValueError):
                camera.tick()
        self.assertEqual(original, self.target.read_bytes())

    def test_partial_read_recovers_without_stopping_or_overwriting_valid_frame(self):
        camera = HeadCamera()
        camera.start(self.root, "blue")
        original = self.target.read_bytes()
        source = self.root / "blue" / "head_position.txt"
        source.write_text("")
        self.assertFalse(camera.tick())
        self.assertEqual(camera.side, "blue")
        self.assertEqual(original, self.target.read_bytes())
        source.write_text("0 0 4 5 6 0 0 0 1")
        self.assertTrue(camera.tick())
        self.assertIsNone(camera.invalid_since)
        self.assertTrue(self.target.read_text().startswith("4.000 5.000 6.000"))

    def test_opponent_direction_is_upright_independent_of_bone_rotation(self):
        source = "0 0 1 2 3 .7071 0 0 .7071"
        target = "0 0 1 2 5 0 0 0 1"
        output = pose_to_camera(source, "blue", target_text=target)
        self.assertEqual(output.split("\t")[1], "0.000000 0.000000 0.000000 1.000000")

    def test_opponent_movement_updates_camera_even_if_own_head_is_unchanged(self):
        other = self.root / "red" / "head_position.txt"
        other.write_text("0 0 1 2 5 0 0 0 1")
        camera = HeadCamera()
        camera.start(self.root, "blue", look_opponent=True)
        original = self.target.read_text()
        other.write_text("0 0 3 2 3 0 0 0 1")
        os.utime(other, ns=(time.time_ns(), time.time_ns()+1000000))
        self.assertTrue(camera.tick())
        self.assertNotEqual(original, self.target.read_text())

    def test_camera_reset_is_replaced_with_current_head(self):
        camera = HeadCamera()
        camera.start(self.root / "match", "red")
        self.target.write_text("ring centre reset")
        os.utime(self.target, ns=(time.time_ns(), time.time_ns()+1000000))
        self.assertTrue(camera.tick())
        self.assertTrue(self.target.read_text().endswith("False\tTrue"))

    def test_missing_camera_or_invalid_side_does_not_create_files(self):
        self.target.unlink()
        with self.assertRaises(ValueError):
            HeadCamera().start(self.root, "blue")
        self.assertFalse(self.target.exists())
        with self.assertRaises(ValueError):
            pose_to_camera("0 0 1 2 3 0 0 0 1", "other")

    def test_motion_follows_latest_goal_without_overshoot_or_queued_samples(self):
        motion = CameraMotion()
        motion.aim([0,0,0,0,0,0,1], 0)
        motion.aim([.1,0,0,0,0,0,1], .01)
        motion.aim([.2,0,0,0,0,0,1], .02)
        first = motion.sample(.02, 20, 40)[0]
        self.assertGreater(first, 0)
        self.assertLess(first, .2)
        self.assertLessEqual(motion.sample(.1,20,40)[0], .2)
        self.assertEqual(motion.goal[0], .2)

    def test_quaternion_sign_flip_does_not_spin_and_rotation_stays_normalized(self):
        motion = CameraMotion()
        motion.aim([0,0,0,0,0,0,1], 0)
        motion.aim([0,0,0,0,0,0,-1], .01)
        self.assertAlmostEqual(motion.sample(.02)[-1], 1)
        motion.aim([0,0,0,0,1,0,0], .03)
        q = motion.sample(.04)[3:]
        self.assertAlmostEqual(sum(v*v for v in q),1)

    def test_large_jump_timeline_reset_or_long_gap_snaps_without_flying(self):
        for goal, at, reset in (([5,0,0,0,0,0,1],.02,False), ([.2,0,0,0,0,0,1],.4,False), ([.2,0,0,0,0,0,1],.02,True)):
            motion = CameraMotion()
            motion.aim([0,0,0,0,0,0,1], 0)
            motion.aim(goal,at,reset=reset)
            self.assertEqual(motion.sample(at), goal)

    def test_smoothing_keeps_emitting_between_source_updates_then_converges(self):
        camera = HeadCamera()
        with patch("spectator_camera.time.monotonic", return_value=10):
            camera.start(self.root,"blue",position_ms=20,rotation_ms=40)
        source = self.root / "blue" / "head_position.txt"
        source.write_text("0 0 1.2 2 3 0 0 0 1")
        with patch("spectator_camera.time.monotonic", return_value=10.016):
            camera.tick()
        first = self.target.read_text()
        with patch("spectator_camera.time.monotonic", return_value=10.032):
            self.assertTrue(camera.tick())
        self.assertNotEqual(first,self.target.read_text())

    def test_worker_runs_without_gui_events_and_stops_before_restart(self):
        messages = []
        camera = HeadCamera()
        worker = CameraWorker(camera,messages.append)
        self.addCleanup(worker.stop)
        worker.start(self.root,"blue",position_ms=20,rotation_ms=40)
        time.sleep(.06)
        source = self.root / "blue" / "head_position.txt"
        source.write_text("0 0 1.2 2 3 0 0 0 1")
        time.sleep(.1)
        self.assertGreater(camera.writes,1)
        first_thread = worker.thread
        worker.start(self.root,"red")
        self.assertFalse(first_thread.is_alive())
        worker.stop()
        original = self.target.read_bytes()
        time.sleep(.03)
        self.assertEqual(original,self.target.read_bytes())

    def test_native_replay_seek_resets_motion_even_without_new_command_number(self):
        camera = HeadCamera()
        replay = self.root / "match" / "replay_state.txt"
        replay.write_text("playing 20 120 1 1 0 session.zip")
        with patch("spectator_camera.time.monotonic",return_value=10):
            camera.start(self.root,"blue",position_ms=100)
        (self.root / "blue" / "head_position.txt").write_text("0 0 1.2 2 3 0 0 0 1")
        with patch("spectator_camera.time.monotonic",return_value=10.016):
            camera.tick()
        replay.write_text("paused 5 120 1 1 0 session.zip")
        with patch("spectator_camera.time.monotonic",return_value=10.032):
            camera.tick()
        self.assertTrue(self.target.read_text().startswith("1.200 2.000 3.000"))

    def test_restore_heads_preserves_pose_and_separator(self):
        for separator in ("\t", "\\t"):
            original = separator.join(("1 2 3", "0 0 0 1", "75", "True", "False"))
            self.target.write_text(original)
            self.assertTrue(restore_head_flags(self.root,expected=original))
            self.assertEqual(self.target.read_text(),separator.join(("1 2 3", "0 0 0 1", "75", "False", "False")))

    def test_restore_does_not_overwrite_another_controller(self):
        original = self.target.read_bytes()
        self.assertFalse(restore_head_flags(self.root,expected="old unrelated camera"))
        self.assertEqual(original,self.target.read_bytes())

    def test_worker_stop_releases_head_hiding(self):
        worker = CameraWorker(HeadCamera(),lambda text:None)
        self.addCleanup(worker.stop)
        worker.start(self.root,"blue")
        time.sleep(.06)
        worker.stop()
        self.assertTrue(self.target.read_text().endswith("False\tFalse"))

    def test_short_windows_file_lock_retries_atomic_replace(self):
        staged = self.root/"match/staged.tmp"
        staged.write_text("replacement")
        original_replace = os.replace
        calls = []
        def replacement(src,dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13,"simulated Windows reader lock")
            return original_replace(src,dst)
        with patch("spectator_camera.os.replace",side_effect=replacement):
            replace_camera_file(staged,self.target)
        self.assertEqual(len(calls),3)
        self.assertEqual(self.target.read_text(),"replacement")

    def test_persistent_denial_is_bounded_and_live_file_is_not_truncated(self):
        staged = self.root/"match/staged.tmp"
        staged.write_text("replacement")
        original = self.target.read_bytes()
        with patch("spectator_camera.os.replace",side_effect=PermissionError(13,"permanent denial")):
            with self.assertRaises(PermissionError):
                replace_camera_file(staged,self.target,timeout=.01)
        self.assertEqual(original,self.target.read_bytes())

    def test_unrelated_io_error_is_not_hidden_as_a_reader_lock(self):
        with patch("spectator_camera.os.replace",side_effect=FileNotFoundError("removed file")) as replace:
            with self.assertRaises(FileNotFoundError):
                replace_camera_file("unused","unused")
        self.assertEqual(replace.call_count,1)
