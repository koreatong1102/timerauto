import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from camera_director import DirectorFeed, AutoCameraDirector, pose_matches


class DirectorFeedTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt','Windows input wrapper')
    def test_entry_guard_after_foreground_activation_prevents_key_and_restores_window(self):
        import timerauto
        user=Mock()
        user.GetForegroundWindow.side_effect=[100,200]
        user.IsIconic.return_value=False
        guard=Mock(return_value=False)
        with patch.object(timerauto.ctypes,'windll',SimpleNamespace(user32=user)), \
             patch('timerauto._find_window_by_title_contains',return_value=200), \
             patch('timerauto._activate_window_reliably',return_value=(True,'ok')) as activate, \
             patch('timerauto._press_vk_sendinput_held') as press,patch('timerauto.time.sleep'):
            ok,detail=timerauto.toggle_file_camera_once('spectator',guard=guard)
        self.assertFalse(ok)
        self.assertEqual(detail,'camera_entry_cancelled')
        guard.assert_called_once()
        press.assert_not_called()
        self.assertEqual(activate.call_count,2)

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

    def test_plain_two_hit_combo_cancels_old_flow_and_never_enters(self):
        self.director.feed.update({"spectator_event_engine":[{"event_id":"two-hit","side":"blue","combo_hits":2}]},now=0)
        self.step(0); self.step(.09)
        self.assertEqual(self.director.state,"idle")
        self.step(.22)
        self.assertEqual(self.director.state,"idle")
        self.step(.24); self.step(.26)
        self.assertEqual(self.director.state,"idle")
        self.assertFalse(self.calls)

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
        self.assertIn("3연타",self.director.describe())

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

    def test_ended_attack_keeps_configured_duration_from_confirmed_entry(self):
        self.director.duration=3
        self.director.max_duration=3
        self.active()
        entered=self.director.active_started
        for after in (.41,.81,1.5,2.5,2.99):
            self.step(entered+after)
            self.assertEqual(self.director.state,'active')
        self.step(entered+3.01)
        self.assertEqual(self.director.state,'release')
        self.assertEqual(self.director.last_reason,'duration_complete')

    def test_ordinary_opponent_reply_does_not_cut_short_confirmed_shot(self):
        self.active()
        self.director.feed.update({'spectator_event_engine':[{
            'event_id':'reply','side':'red','combo_hits':1}]},now=.8)
        self.step(.8);self.step(1.5)
        self.assertEqual(self.director.state,'active')

    def test_down_still_exits_before_configured_hold(self):
        self.director.duration=3
        self.active()
        self.director.feed.update({'spectator_effect_events':[{'kind':'knockdown'}]},now=.8)
        self.step(.8)
        self.assertEqual(self.director.state,'release')
        self.assertEqual(self.director.last_reason,'priority_or_signal')

    def test_down_arriving_while_window_is_activating_cancels_before_f6(self):
        def activate_and_check(guard):
            self.director.feed.update({'spectator_effect_events':[{'kind':'knockdown'}]},now=.6)
            self.assertFalse(guard())
            return False,'camera_entry_cancelled'
        self.director.toggle_guarded=activate_and_check
        self.step(0);self.step(.26);self.step(.6)
        self.assertEqual(self.director.state,'idle')
        self.assertEqual(self.director.last_reason,'entry_priority_cancelled')
        self.assertFalse(self.calls)
        self.assertIsNone(self.director.shot_budget.opened)

    def test_down_after_f6_returns_once_without_promoting_aborted_entry_to_active(self):
        self.step(0);self.step(.26);self.step(.6)
        self.assertEqual(self.director.state,'enter')
        self.director.feed.update({'spectator_effect_events':[{'kind':'knockdown'}]},now=.61)
        self.step(.62);self.step(.64)
        self.assertEqual(self.director.state,'release')
        self.assertIsNone(self.director.shot_budget.opened)
        self.assertEqual(len(self.director.history),0)
        self.assertEqual(self.director.last_cut_reason,'entry_priority_cancelled')
        self.step(.8);self.step(.82);self.step(.84);self.step(.86)
        self.assertEqual(self.calls,['probe','release'])
        self.assertEqual(self.director.state,'idle')

    def test_round_end_still_exits_before_configured_hold(self):
        self.active()
        (self.root/'match/round_state.txt').write_text('Results')
        self.step(.8)
        self.assertEqual(self.director.state,'release')

    def test_unsafe_view_still_exits_before_configured_hold(self):
        self.active()
        def close_view(*args):
            self.director.geometry_reason='too_close'
            self.director.geometry_metrics={'distance':.2}
            return False
        with patch.object(self.director,'_geometry',side_effect=close_view):
            self.step(.8);self.step(1.1)
        self.assertEqual(self.director.state,'release')
        self.assertEqual(self.director.last_reason,'view_distance_close')

    def test_entry_only_motion_and_glove_scores_do_not_cut_active_shot(self):
        self.director.duration=3
        self.active()
        def warning(*args):
            self.director.geometry_reason='glove_obstruction'
            self.director.geometry_score=1
            self.director.geometry_metrics={'distance':.6,'head_age':.1}
            return True
        with patch.object(self.director,'_geometry',side_effect=warning):
            for after in (.3,.6,.9,1.2,1.8,2.5):
                self.step(self.director.active_started+after)
                self.assertEqual(self.director.state,'active')

    def test_repeated_pose_reads_do_not_inflate_next_motion_speed(self):
        for t in (0,.05,.1,.15,.2):
            self.assertTrue(self.director._geometry('blue',t))
        # 0.25m / .25s = 1m/s, not 0.25m / .05s = 5m/s.
        (self.root/'blue/head_position.txt').write_text('0 0 .25 1.7 0 0 0 0 1')
        self.assertTrue(self.director._geometry('blue',.25))
        self.assertNotEqual(self.director.geometry_reason,'rapid_motion')

    def test_old_opponent_log_is_not_masked_by_slightly_delayed_self_log(self):
        now=time.time()
        os.utime(self.root/'blue/head_position.txt',(now-.5,now-.5))
        os.utime(self.root/'red/head_position.txt',(now-1.5,now-1.5))
        self.assertFalse(self.director._geometry('blue',0))
        self.assertGreater(self.director.geometry_metrics['head_age'],1.4)

    def test_fresh_stationary_pose_stamps_still_advance_motion_sample_time(self):
        self.assertTrue(self.director._geometry('blue',0))
        path=self.root/'blue/head_position.txt'
        path.write_text('0 0 0 1.7 0 0 0 0 1')
        self.assertTrue(self.director._geometry('blue',.2))
        self.assertEqual(self.director.previous['blue'][0],.2)

    def test_fresh_same_flow_extends_cut_but_never_past_hard_limit(self):
        self.active()
        for now,hits in ((.8,4),(1.5,5),(2.2,6),(3,7),(3.3,8)):
            self.director.feed.update({'spectator_event_engine':[{'event_id':str(hits),'side':'blue','combo_hits':hits}]},now=now)
            self.step(now)
            self.assertEqual(self.director.state,'active')
        self.assertLessEqual(self.director.active_until,self.director.hard_until)
        self.step(3.65)
        self.assertEqual(self.director.state,'release')

    def test_view_change_during_preparation_aborts_before_f6(self):
        self.step(0);self.step(.26)
        (self.root/'red/head_position.txt').write_text('0 0 0 1.7 .3 0 0 0 1')
        self.step(.6)
        self.assertEqual(self.director.state,'idle')
        self.assertFalse(self.calls)

    def test_gloves_near_view_ray_reduce_shot_quality(self):
        for hand in ('left','right'):
            (self.root/'blue'/f'glove_{hand}_position.txt').write_text('0 0 0 1.7 .2 0 0 0 1')
        self.step(0);self.step(.26)
        self.assertEqual(self.director.state,'idle')
        self.assertEqual(self.director.last_reason,'glove_obstruction')

    def test_counter_followup_can_enter_without_requiring_pressure_three_hits(self):
        self.director.feed=DirectorFeed()
        self.director.feed.update({'spectator_event_engine':[{'event_id':'counter','side':'blue','combo_hits':1,'counter':True}]},now=0)
        self.step(0);self.step(.26)
        self.assertFalse(self.calls)
        self.director.feed.update({'spectator_event_engine':[{'event_id':'follow','side':'blue','combo_hits':2}]},now=.3)
        self.step(.3);self.step(.46);self.step(.6);self.step(.62);self.step(.64)
        self.assertEqual(self.director.state,'active')
        self.assertEqual(self.director.prepared['kind'],'counter_followup')
        self.assertIn('카운터',self.director.describe())

    def test_geometry_collection_is_capped_without_slowing_the_state_loop(self):
        self.director.geometry_reason='view_ready'
        with patch.object(self.director,'_geometry_once',return_value=True) as collect:
            for now in (0,.005,.01,.04,.06):self.director._geometry('blue',now)
            self.assertEqual(collect.call_count,2)

    def test_auto_worker_restores_window_before_first_direction_step(self):
        restore=Mock()
        self.director.ensure_window_visible=restore
        with patch.object(self.director,'step',return_value=False) as step, \
             patch('camera_director.time.sleep'):
            self.director._run()
        restore.assert_called_once()
        step.assert_called_once()

    def test_broadcast_scenic_shot_enters_without_inventing_combat_event(self):
        self.director.broadcast_enabled=True
        self.director.feed.latest=None
        self.director.shot_budget.fight=12
        self.director.shot_budget.live=True
        self.step(0);self.step(.3)
        self.assertEqual(self.director.state,'probe')
        self.assertEqual(self.director.prepared['kind'],'scenic')
        self.assertEqual(self.director.prepared['hits'],0)
        self.step(.5);self.step(.52);self.step(.54)
        self.assertEqual(self.director.state,'active')
        self.assertIsNotNone(self.director.shot_budget.opened)

    def test_broadcast_scenic_preparation_cannot_bypass_priority(self):
        self.director.broadcast_enabled=True
        self.director.feed.latest=None
        self.director.shot_budget.fight=12
        self.director.shot_budget.live=True
        self.step(0);self.step(.3)
        self.assertEqual(self.director.state,'probe')
        self.step(.4,busy=True)
        self.assertEqual(self.director.state,'idle')
        self.assertFalse(self.calls)

    def test_broadcast_support_is_allowed_only_after_quiet_and_safe_entry(self):
        from camera_direction_policy import PROFILES
        self.director.broadcast_enabled=True
        self.director.profile=PROFILES['active']
        self.director.feed.support=True
        self.director.shot_budget.fight=6
        self.director.shot_budget.live=True
        self.director.feed.update({'spectator_event_engine':[{
            'event_id':'support','side':'blue','combo_hits':2}]},now=0)
        self.step(0);self.step(.26);self.step(.5);self.step(.52);self.step(.54)
        self.assertEqual(self.director.state,'active')
        self.assertEqual(self.director.prepared['kind'],'pressure_support')

    def test_coverage_budget_prevents_even_good_event_from_forcing_more_cuts(self):
        self.director.broadcast_enabled=True
        self.director.shot_budget.fight=30
        self.director.shot_budget.intervals.append((0,15))
        self.step(0);self.step(.3)
        self.assertEqual(self.director.state,'idle')
        self.assertEqual(self.director.last_reason,'coverage_budget')
        self.assertFalse(self.calls)

    def test_broadcast_gloves_are_soft_penalty_not_automatic_rejection(self):
        self.director.broadcast_enabled=True
        for hand in ('left','right'):
            (self.root/'blue'/f'glove_{hand}_position.txt').write_text('0 0 0 1.7 .2 0 0 0 1')
        self.step(0);self.step(.26);self.step(.6);self.step(.62);self.step(.64)
        self.assertEqual(self.director.state,'active')

    def test_quiet_fight_gets_periodic_bounded_scenic_shots_and_alternates_sides(self):
        self.director.broadcast_enabled=True
        self.director.cooldown=2
        self.director.feed.latest=None
        entered=[]
        for i in range(601):
            for side in ('blue','red'):os.utime(self.root/side/'head_position.txt',None)
            before=self.director.state
            self.step(i/10)
            if before!='active' and self.director.state=='active':
                entered.append((i/10,self.director.camera.side))
        self.assertGreaterEqual(len(entered),3)
        self.assertLessEqual(len(entered),5)
        for a,b in zip(entered,entered[1:]):self.assertNotEqual(a[1],b[1])
        self.assertLessEqual(self.director.shot_budget.snapshot()['coverage_pct'],23)

    def test_transient_initial_pose_read_waits_then_prepares_without_early_f6(self):
        with patch.object(self.director.camera,'_tick_once',side_effect=ValueError('half-written head row')):
            self.step(0);self.step(.26)
        self.assertEqual(self.director.state,'prepare')
        self.assertFalse(self.calls)
        self.step(.3)
        self.assertEqual(self.director.state,'probe')
        self.assertFalse(self.calls)
        self.step(.44);self.step(.46);self.step(.48)
        self.assertEqual(self.director.state,'active')
        self.assertEqual(len(self.calls),1)

    def test_transient_initial_camera_write_denial_is_retried(self):
        with patch.object(self.director.camera,'_write_output',side_effect=PermissionError('temporary camera input lock')):
            self.step(0);self.step(.26)
        self.assertEqual(self.director.state,'prepare')
        self.assertIsNone(self.director.camera.last_output)
        self.assertFalse(self.calls)
        self.step(.3)
        self.assertEqual(self.director.state,'probe')
        self.assertIsNotNone(self.director.camera.last_output)

    def test_input_file_open_failure_retries_start_before_any_toggle(self):
        with patch.object(self.director.camera,'start',side_effect=PermissionError('input held by game')):
            self.step(0);self.step(.26)
        self.assertEqual(self.director.state,'prepare')
        self.assertFalse(self.calls)
        self.step(.3)
        self.assertEqual(self.director.state,'probe')

    def test_prepare_timeout_reports_underlying_error_without_toggle(self):
        with patch.object(self.director.camera,'_tick_once',side_effect=ValueError('incomplete head row')):
            self.step(0);self.step(.26)
            with self.assertRaisesRegex(ValueError,'incomplete head row'):
                self.step(.88)
        self.assertFalse(self.calls)

    def test_priority_cancels_waiting_preparation_without_claiming_unwritten_file(self):
        with patch.object(self.director.camera,'_tick_once',side_effect=ValueError('incomplete head row')):
            self.step(0);self.step(.26)
        with patch('camera_director.restore_head_flags') as restore:
            self.step(.3,busy=True)
            restore.assert_not_called()
        self.assertEqual(self.director.state,'idle')
        self.assertFalse(self.calls)

    def test_failed_return_confirmation_does_not_send_f4(self):
        self.director.on_return = Mock(return_value=(True,"unused"))
        self.active()
        self.step(2.7); self.step(2.83); self.step(2.85)
        self.actual_on = True
        with self.assertRaises(ValueError):
            self.step(4.5)
        self.director.on_return.assert_not_called()
