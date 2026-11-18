"""Pure timed rotation using temporary pose logs and simulated F6/F4 only."""
import unittest
from unittest.mock import Mock, patch

from tests import test_camera_director as fixtures


class CameraRotationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DirectorStateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.director = self.fixture.director
        self.director.thread = None
        with patch('camera_director.threading.Thread'):
            self.director.start(self.fixture.root, {'fov': 75, 'position_ms': 20, 'rotation_ms': 40},
                                profile='rotation', duration=1, max_duration=3, cooldown=120,
                                pressure=False, counter=False, broadcast_enabled=True, target_pct=5)
        self.director.on_return = Mock(return_value=(True, 'fake F4'))

    def step(self, at, **kwargs):
        return self.fixture.step(at, **kwargs)

    def enter(self, at):
        self.step(at)
        self.assertEqual(self.director.state, 'probe')
        self.step(at + .14)
        self.assertEqual(self.director.state, 'enter')
        self.step(at + .16); self.step(at + .18)
        self.assertEqual(self.director.state, 'active')
        self.assertEqual(self.director.camera.side, 'blue')

    def switch_red(self, at):
        self.step(at)
        self.assertEqual(self.director.state, 'rotation_switch')
        before = len(self.fixture.calls)
        self.step(at + .02); self.step(at + .04); self.step(at + .06)
        self.assertEqual(self.director.state, 'active')
        self.assertEqual(self.director.camera.side, 'red')
        self.assertEqual(len(self.fixture.calls), before, 'blue -> red must not toggle F6')
        self.assertTrue((self.fixture.root/'match/camera_input.txt').read_text().endswith('False\tTrue'))

    def leave(self, at):
        self.step(at)
        self.assertEqual(self.director.state, 'release')
        self.step(at + .13); self.step(at + .15)
        self.assertEqual(self.director.state, 'off_wait')
        self.step(at + .17); self.step(at + .19)
        self.assertEqual(self.director.state, 'idle')

    def test_timing_is_independent_of_combat_feed_geometry_score_and_budget(self):
        # No event, stale feed, replay/report busy and deliberately failing policy
        # methods must not prevent entry, interrupt a shot or postpone red.
        self.director.feed.update({'spectator_round_reports': [{'isFinal': True}],
                                   'spectator_effect_events': [{'kind': 'stun'}]}, busy=True, now=0)
        with patch.object(self.director.feed, 'snapshot', side_effect=AssertionError('no combat feed')), \
             patch.object(self.director, '_geometry', side_effect=AssertionError('no geometry gate')), \
             patch.object(self.director, '_candidate_score', side_effect=AssertionError('no scoring')), \
             patch.object(self.director.shot_budget, 'allows', side_effect=AssertionError('no budget')), \
             patch('camera_director.ActiveViewSafety', side_effect=AssertionError('no shot-policy cuts')):
            self.enter(0)
            self.step(5, busy=True)
            self.assertEqual(self.director.state, 'active')
            self.switch_red(10.19)
            self.step(15, busy=True)
            self.assertEqual(self.director.state, 'active')

    def test_two_cycles_have_direct_red_then_exact_ten_second_normal_phase(self):
        self.assertEqual((self.director.duration, self.director.max_duration), (10, 10))
        self.enter(0)  # Active at .18, not before actual observed entry.
        self.step(10.17)
        self.assertEqual(self.director.state, 'active')
        self.switch_red(10.19)  # Red active at 10.25.
        self.assertEqual(self.fixture.calls, ['probe'])
        self.director.on_return.assert_not_called()
        self.step(20.24)
        self.assertEqual(self.director.state, 'active')
        self.leave(20.26)  # Normal confirmed at 20.45, F4 once.
        self.assertAlmostEqual(self.director.next_cut, 30.45)
        self.step(30.44)
        self.assertEqual(self.director.state, 'idle')
        self.enter(30.46)
        self.switch_red(40.65)
        self.leave(50.72)
        self.assertAlmostEqual(self.director.next_cut, 60.91)
        self.assertEqual(self.director.rotation_sequence, 4)
        self.assertEqual(self.fixture.calls, ['probe', 'release'] * 2)
        self.assertEqual(self.director.on_return.call_count, 2)

    def test_independent_custom_durations_and_zero_normal_wait(self):
        for normal in (3.5, 0):
            with self.subTest(normal=normal):
                # Each iteration uses its own camera files/state and fake keys.
                case=CameraRotationTests();case.setUp()
                try:
                    d=case.director;d.thread=None
                    with patch('camera_director.threading.Thread'):
                        d.start(case.fixture.root,{'fov':75},profile='rotation',
                                rotation_blue_sec=2.5,rotation_red_sec=4.5,rotation_normal_sec=normal)
                    case.enter(0)
                    case.step(2.67);self.assertEqual(d.state,'active')
                    case.switch_red(2.69)
                    case.step(7.24);self.assertEqual(d.state,'active')
                    case.leave(7.26)
                    self.assertAlmostEqual(d.next_cut,7.45+normal)
                    if normal:
                        case.step(d.next_cut-.01);self.assertEqual(d.state,'idle')
                    case.enter(d.next_cut+.01)
                finally:
                    case.doCleanups()

    def test_rotation_times_persist_and_validate(self):
        import tempfile
        from pathlib import Path
        from config_model import AppConfig
        from camera_direction_policy import camera_settings
        with tempfile.TemporaryDirectory() as temp:
            cfg=AppConfig()
            for side,value in (('blue',2.5),('red',24),('normal',0)):
                setattr(cfg,'camera_director_rotation_'+side+'_sec',value)
            path=str(Path(temp,'config.json'));cfg.to_json(path)
            restored=AppConfig.from_json(path)
            for side,value in (('blue',2.5),('red',24),('normal',0)):
                self.assertEqual(getattr(restored,'camera_director_rotation_'+side+'_sec'),value)
        values=camera_settings(dict(camera_director_rotation_blue_sec=float('nan'),
                                    camera_director_rotation_red_sec=-5,camera_director_rotation_normal_sec=9999))
        self.assertEqual(values['camera_director_rotation_blue_sec'],10)
        self.assertEqual(values['camera_director_rotation_red_sec'],1)
        self.assertEqual(values['camera_director_rotation_normal_sec'],600)

    def test_stun_and_knockdown_do_not_shorten_blue_or_red(self):
        self.enter(0)
        self.director.feed.update({'spectator_effect_events': [{'kind': 'stun'}]}, now=1)
        self.step(1)
        self.assertEqual(self.director.state, 'active')
        (self.fixture.root/'match/round_state.txt').write_text('RoundKnockdown')
        self.director.feed.update({'spectator_round_state': 'knockdown',
                                   'spectator_effect_events': [{'kind': 'knockdown'}]}, busy=True, now=2)
        self.step(2, busy=True)
        self.assertEqual(self.director.state, 'active')
        self.switch_red(10.19)
        self.step(18, busy=True)
        self.assertEqual(self.director.state, 'active')

    def test_entry_guard_ignores_effects_and_presentation_busy(self):
        def guarded(guard):
            self.director.feed.update({'spectator_effect_events': [{'kind': 'knockdown'}]}, busy=True, now=.14)
            self.assertTrue(guard())
            return self.director.toggle()
        self.director.toggle_guarded = guarded
        self.enter(0)

    def test_close_distance_is_not_a_rotation_gate(self):
        (self.fixture.root/'red/head_position.txt').write_text('0 0 0 1.7 .3 0 0 0 1')
        self.enter(0)
        self.switch_red(10.19)

    def test_initial_preparation_does_not_consume_shot_before_confirmation(self):
        self.step(0)
        self.assertEqual(self.director.state, 'probe')
        self.assertIsNone(self.director.used)
        self.assertEqual(self.fixture.calls, [])

    def test_cancelled_guard_retries_same_slot_without_arbitrary_cooldown(self):
        self.director.toggle_guarded = lambda guard: (False, 'camera_entry_cancelled')
        self.step(0); self.step(.14)
        self.assertEqual(self.director.state, 'idle')
        self.assertEqual(self.director.rotation_index, 0)
        self.assertEqual(self.fixture.calls, [])
        self.director.toggle_guarded = None
        self.enter(.15)

    def test_partial_first_pose_waits_for_complete_frame_not_geometry_score(self):
        with patch.object(self.director.camera, 'start', return_value=None):
            self.step(0)
        self.assertEqual(self.director.state, 'prepare')
        self.director._prepare_started = False
        self.step(.02)
        self.assertEqual(self.director.state, 'probe')

    def test_round_break_returns_to_normal_and_waits_for_next_round(self):
        self.enter(0)
        (self.fixture.root/'match/round_state.txt').write_text('RoundBreak')
        self.leave(1)
        self.step(5)
        self.assertEqual(self.director.state, 'idle')
        self.assertEqual(self.fixture.calls, ['probe', 'release'])
        (self.fixture.root/'match/round_state.txt').write_text('RoundFight')
        self.enter(6)

    def test_user_stop_during_red_switch_restores_heads_and_exits_once(self):
        self.enter(0)
        self.step(10.19)
        self.assertEqual(self.director.state, 'rotation_switch')
        self.director.stop()
        self.leave(10.20)
        self.assertTrue((self.fixture.root/'match/camera_input.txt').read_text().endswith('False\tFalse'))
        self.assertFalse(self.step(11))
        self.assertEqual(self.fixture.calls, ['probe', 'release'])

    def test_manual_override_still_stops_without_blind_f6(self):
        self.enter(0)
        self.fixture.actual_on = False
        self.step(.3); self.step(.32)
        with self.assertRaisesRegex(ValueError, '수동 카메라 변경'):
            self.step(.34)
        self.assertEqual(self.fixture.calls, ['probe'])

    def test_entry_acknowledgement_failure_does_not_repeat_f6(self):
        self.director.toggle = lambda: (self.fixture.calls.append('one') or True, 'no effect')
        self.step(0); self.step(.14)
        with self.assertRaisesRegex(ValueError, '전환 확인 실패'):
            self.step(2)
        self.assertEqual(self.fixture.calls, ['one'])

    def test_already_enabled_file_camera_is_detected_before_any_toggle(self):
        self.step(0)
        self.fixture.actual_on = True
        self.step(.02)
        with self.assertRaisesRegex(ValueError, '이미 켜진'):
            self.step(.04)
        self.assertEqual(self.fixture.calls, [])

    def test_red_acknowledgement_failure_does_not_toggle_f6_again(self):
        self.enter(0)
        self.step(10.19)
        self.step(10.21)
        self.fixture.actual_on = False  # Simulate lost native file-camera ownership.
        with self.assertRaisesRegex(ValueError, '레드 선수 시점'):
            self.step(12)
        self.assertEqual(self.fixture.calls, ['probe'])

    def test_rotation_ui_disables_unrelated_policy_controls_without_erasing_values(self):
        import os, subprocess, sys
        code = '''
from PyQt6.QtWidgets import QApplication,QComboBox,QDoubleSpinBox,QCheckBox,QLabel
from config_model import AppConfig
from spectator_camera import create_camera_panel
app=QApplication([]);cfg=AppConfig();cfg.camera_director_profile='rotation'
cfg.camera_director_cooldown=42
panel=create_camera_panel(cfg,toggle=lambda:(True,'test'))
profile=panel.findChild(QComboBox,'cameraDirectorProfile')
cooldown=panel.findChild(QDoubleSpinBox,'cameraDirector_cooldown')
pressure=panel.findChild(QCheckBox,'cameraDirectorPressure')
assert not cooldown.isEnabled() and not pressure.isEnabled()
assert cfg.camera_director_cooldown==42
for side,value in (('blue',12.5),('red',4),('normal',0)):
 control=panel.findChild(QDoubleSpinBox,'cameraDirector_rotation_'+side+'_sec')
 assert control.isEnabled()
 control.setValue(value)
 assert getattr(cfg,'camera_director_rotation_'+side+'_sec')==value
assert any('단순 로테이션' in label.text() for label in panel.findChildren(QLabel))
profile.setCurrentIndex(profile.findData('balanced'))
assert cooldown.isEnabled() and pressure.isEnabled()
assert cfg.camera_director_cooldown==42
assert not panel.findChild(QDoubleSpinBox,'cameraDirector_rotation_blue_sec').isEnabled()
assert app._rfc_head_camera.director.thread is None
profile.setCurrentIndex(profile.findData('rotation'))
for check in panel.findChildren(QCheckBox):
 if check.text().startswith('F6 파일 카메라'):check.setChecked(True)
from PyQt6.QtWidgets import QPushButton
from unittest.mock import patch
service=app._rfc_head_camera
with patch.object(service.director,'start') as start,patch.object(service.timer,'start'):
 for button in panel.findChildren(QPushButton):
  if button.text()=='자동 연출 시작':button.click()
 assert start.call_count==1
 assert start.call_args.kwargs['rotation_blue_sec']==12.5
 assert start.call_args.kwargs['rotation_red_sec']==4
 assert start.call_args.kwargs['rotation_normal_sec']==0
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=20,
                                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONUTF8': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
