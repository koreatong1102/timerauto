import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from camera_director import DirectorFeed, AutoCameraDirector, pose_matches


class DirectorFeedTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows input wrapper")
    def test_f6_wrapper_sends_once_and_never_falls_back(self):
        import timerauto
        user = Mock()
        user.GetForegroundWindow.side_effect = [100,200]
        user.IsIconic.return_value = False
        with patch.object(timerauto.ctypes,"windll",SimpleNamespace(user32=user)), \
             patch("timerauto._find_window_by_title_contains",return_value=200), \
             patch("timerauto._activate_window_reliably",return_value=(True,"ok")) as activate, \
             patch("timerauto._press_vk_sendinput_held",return_value=(False,"test failure")) as press, \
             patch("timerauto.press_vk_once",side_effect=AssertionError("no toggle fallback")), \
             patch("timerauto.time.sleep"):
            ok,_ = timerauto.toggle_file_camera_once("spectator")
        self.assertFalse(ok)
        press.assert_called_once_with(0x75,hold_sec=.08)
        self.assertEqual(activate.call_count,2)

    def test_central_events_only_latest_deduped_and_expire(self):
        feed = DirectorFeed()
        event = {"event_id":"one","side":"blue","combo_hits":3}
        feed.update({"spectator_event_engine":[event]},now=10)
        self.assertEqual(feed.snapshot(10.1)[1]["id"],"one")
        feed.update({"spectator_event_engine":[event]},now=10.5)
        self.assertIsNone(feed.snapshot(10.95)[1])
        feed.update({"spectator_event_engine":[dict(event,event_id="two",side="red")]},now=11)
        self.assertEqual(feed.snapshot(11)[1]["side"],"red")
        self.assertFalse(feed.snapshot(12.1)[0])

    def test_down_report_and_busy_block_even_with_combo_event(self):
        feed = DirectorFeed()
        feed.update({"spectator_effect_events":[{"kind":"knockdown"}],"spectator_event_engine":[{"event_id":"one","side":"blue","combo_hits":8}]},now=10)
        self.assertFalse(feed.snapshot(10)[0])
        feed.update({},busy=True,now=20)
        self.assertFalse(feed.snapshot(20)[0])
        feed.update({"spectator_round_report":{"round":1}},now=30)
        self.assertFalse(feed.snapshot(30)[0])

    def test_quaternion_equivalence_does_not_look_like_a_mode_change(self):
        self.assertTrue(pose_matches("0 1 0\t0 0 0 1\t75","0 1 0\t0 0 0 -1\t75\tTrue\tFalse"))
        self.assertFalse(pose_matches("0 3 -5\t0 0 0 1\t75","0 1 0\t0 0 0 1\t75"))


class DirectorStateTests(unittest.TestCase):
    normal = "0 3 -4\t0 0 0 1\t75"
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("blue","red","match"):
            (self.root/folder).mkdir()
        (self.root/"blue/head_position.txt").write_text("0 0 0 1.7 0 0 0 0 1")
        (self.root/"red/head_position.txt").write_text("0 0 0 1.7 1.5 0 0 0 1")
        (self.root/"match/round_state.txt").write_text("RoundFight")
        (self.root/"match/camera_input.txt").write_text(self.normal+"\tFalse\tFalse")
        self.camera_file = self.root/"match/camera.txt"
        self.camera_file.write_text(self.normal)
        self.calls = []
        self.actual_on = False
        def toggle():
            self.calls.append(self.director.state)
            self.actual_on = not self.actual_on
            return True,"fake single toggle"
        self.director = AutoCameraDirector(lambda message:None,toggle)
        self.director.realtime = False  # Deterministic step/ack tests use synthetic time.
        with patch("camera_director.threading.Thread"):
            self.director.start(self.root,{"fov":75,"position_ms":20,"rotation_ms":40})
        self.director.feed.update({"spectator_event_engine":[{"event_id":"one","side":"blue","combo_hits":3}]},now=0)

    def step(self, now, *, busy=False):
        self.director.feed.update({},busy=busy,now=now)
        output = self.director.camera.last_output if self.actual_on else self.normal
        self.camera_file.write_text(output or self.normal)
        os.utime(self.camera_file,ns=(time.time_ns(),time.time_ns()+int(now*10000)))
        with patch("camera_director.time.monotonic",return_value=now):
            return self.director.step(now)

    def active(self):
        self.step(0)
        self.step(.26)
        self.assertEqual(self.director.state,"probe")
        self.step(.6)
        self.assertEqual(self.director.state,"enter")
        self.step(.62)
        self.step(.64)
        self.assertEqual(self.director.state,"active")

    def test_complete_cut_release_then_single_exit_and_cooldown(self):
        self.active()
        self.step(2.7)
        self.assertEqual(self.director.state,"release")
        self.assertTrue((self.root/"match/camera_input.txt").read_text().endswith("False\tFalse"))
        self.step(2.83)
        self.step(2.85)
        self.assertEqual(self.director.state,"off_wait")
        self.step(2.87); self.step(2.89)
        self.assertEqual(self.director.state,"idle")
        self.assertEqual(self.calls,["probe","release"])
        self.assertGreater(self.director.next_cut,14)
        self.director.feed.update({"spectator_event_engine":[{"event_id":"two","side":"red","combo_hits":5}]},now=3)
        self.step(3)
        self.assertEqual(self.director.state,"idle")

    def test_cancel_and_priority_content_exit_instead_of_finishing_duration(self):
        self.active()
        self.step(.7,busy=True)
        self.assertEqual(self.director.state,"release")

    def test_entry_failure_never_retries_toggle(self):
        self.director.toggle = lambda: (self.calls.append("one") or True,"fake no effect")
        self.step(0); self.step(.26); self.step(.6)
        with self.assertRaisesRegex(ValueError,"전환 확인 실패"):
            self.step(2.2)
        self.assertEqual(self.calls,["one"])

    def test_already_on_is_detected_before_sending_a_toggle(self):
        self.step(0); self.step(.26)
        self.actual_on = True
        self.step(.3)
        with self.assertRaisesRegex(ValueError,"이미 켜진"):
            self.step(.32)
        self.assertFalse(self.calls)

    def test_close_distance_rejects_cut(self):
        (self.root/"red/head_position.txt").write_text("0 0 0 1.7 .3 0 0 0 1")
        self.step(0); self.step(.26)
        self.assertEqual(self.director.state,"idle")
        self.assertFalse(self.calls)

    def test_manual_override_does_not_get_an_extra_blind_toggle(self):
        self.active()
        self.actual_on = False
        self.step(.7); self.step(.72)
        with self.assertRaisesRegex(ValueError,"수동 카메라 변경"):
            self.step(.74)
        self.assertEqual(len(self.calls),1)

    def test_cancel_before_a_cut_never_sends_key(self):
        self.director.stop()
        self.assertFalse(self.step(0))
        self.assertFalse(self.calls)

    def test_finished_exchange_aborts_preparation_without_toggle(self):
        self.step(0); self.step(.26)
        self.step(1.1)
        self.assertEqual(self.director.state,"idle")
        self.assertFalse(self.calls)

    def test_priority_during_preparation_aborts_cut_but_stays_armed(self):
        self.step(0); self.step(.26)
        self.step(.4,busy=True)
        self.assertEqual(self.director.state,"idle")
        self.assertFalse(self.calls)

    def test_return_timeout_never_repeats_exit_toggle(self):
        self.active()
        self.step(2.7); self.step(2.83); self.step(2.85)
        self.actual_on = True  # Simulate native input accepted but not acted on.
        with self.assertRaisesRegex(ValueError,"복귀를 확인하지"):
            self.step(4.5)
        self.assertEqual(len(self.calls),2)

    def test_quick_cancel_active_releases_heads_before_exit_input(self):
        self.active()
        self.director.stop()
        self.step(.7)
        self.assertEqual(self.director.state,"release")
        self.assertTrue((self.root/"match/camera_input.txt").read_text().endswith("False\tFalse"))
        self.assertEqual(len(self.calls),1)

    def test_release_file_lock_does_not_disarm_or_send_exit_early(self):
        self.active()
        with patch("camera_director.restore_head_flags",side_effect=PermissionError(13,"reader lock")):
            self.step(.7,busy=True)
        self.assertEqual(self.director.state,"release_write")
        self.assertEqual(len(self.calls),1)
        self.step(.8)
        self.assertEqual(self.director.state,"release")
        self.assertTrue((self.root/"match/camera_input.txt").read_text().endswith("False\tFalse"))
        self.assertEqual(len(self.calls),1)

    def test_two_hit_combo_enters_without_waiting_for_a_third_hit(self):
        self.director.feed.update({"spectator_event_engine":[{"event_id":"two-hit","side":"blue","combo_hits":2}]},now=0)
        self.step(0); self.step(.09)
        self.assertEqual(self.director.state,"probe")
        self.step(.22)
        self.assertEqual(self.director.state,"enter")
        self.step(.24); self.step(.26)
        self.assertEqual(self.director.state,"active")

    def test_viewer_comfort_skips_very_close_exchange(self):
        (self.root/"red/head_position.txt").write_text("0 0 0 1.7 .55 0 0 0 1")
        self.step(0); self.step(.09)
        self.assertEqual(self.director.state,"idle")
        self.assertEqual(self.director.last_reason,"too_close")

    def test_wait_reason_is_readable_without_inspecting_logs(self):
        self.step(0)
        self.director.last_reason = "too_close"
        self.assertIn("너무 가까움",self.director.describe())
        self.director.last_reason = "no_fresh_combo"
        self.assertIn("2연타",self.director.describe())

    def test_zero_cooldown_is_preserved_and_return_f4_runs_once_after_exit(self):
        self.director.cooldown = 0
        callback = Mock(return_value=(True,"F4 test"))
        self.director.on_return = callback
        self.active()
        self.step(2.7); self.step(2.83); self.step(2.85)
        callback.assert_not_called()
        self.step(2.87); self.step(2.89)
        callback.assert_called_once()
        self.assertEqual(self.director.next_cut,2.89)
        self.assertEqual(self.director.state,"idle")
        self.step(2.91)
        callback.assert_called_once()

    def test_start_accepts_zero_and_sub_ten_second_intervals(self):
        for seconds in (0,1,5,9):
            self.director.thread = None  # The fixture never starts a real worker.
            with patch("camera_director.threading.Thread"):
                self.director.start(self.root,{},cooldown=seconds)
            self.assertEqual(self.director.cooldown,seconds)

    def test_failed_return_confirmation_does_not_send_f4(self):
        self.director.on_return = Mock(return_value=(True,"unused"))
        self.active()
        self.step(2.7); self.step(2.83); self.step(2.85)
        self.actual_on = True
        with self.assertRaises(ValueError):
            self.step(4.5)
        self.director.on_return.assert_not_called()
