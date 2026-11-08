import math
import unittest
from camera_view_safety import ActiveViewSafety


class ActiveViewSafetyTests(unittest.TestCase):
    def setUp(self):
        self.guard=ActiveViewSafety()

    def check(self,t,reason='view_ready',distance=1.2,age=.1,output='0 1 0 0 0 0 1 75'):
        return self.guard.evaluate(t,reason in ('view_ready','glove_obstruction'),reason,
            {'distance':distance,'head_age':age},output)

    def test_entry_limits_are_not_active_exit_limits(self):
        for t in (0,.3,.6,.9,1.5,2.5):
            self.assertEqual(self.check(t,'too_close',distance=.55),'')
            self.assertEqual(self.check(t,'rapid_motion'),'')
            self.assertEqual(self.check(t,'glove_obstruction'),'')

    def test_partial_rewrite_tolerated_then_persistent_loss_exits(self):
        self.assertEqual(self.check(0,'partial_pose'),'')
        self.assertEqual(self.check(.3,'partial_pose'),'')
        self.assertEqual(self.check(.4),'')
        self.assertEqual(self.check(.5,'partial_pose'),'')
        self.assertEqual(self.check(1.16,'partial_pose'),'tracking_partial')

    def test_stale_source_requires_real_loss_not_a_short_update_gap(self):
        for t in (0,.2,.4,.6):self.assertEqual(self.check(t,'head_log_stale',age=.6),'')
        self.assertEqual(self.check(.7,'head_log_stale',age=1.1),'')
        self.assertEqual(self.check(.86,'head_log_stale',age=1.26),'tracking_stale')

    def test_severe_distance_has_grace_and_recovers(self):
        self.assertEqual(self.check(0,'too_close',distance=.2),'')
        self.assertEqual(self.check(.2),'')
        self.assertEqual(self.check(.3,'too_close',distance=.2),'')
        self.assertEqual(self.check(.56,'too_close',distance=.2),'distance_close')
        self.assertEqual(self.guard.metrics['distance'],.2)

    def test_far_distance_is_not_a_single_frame_cut(self):
        self.assertEqual(self.check(0,'too_far',distance=5),'')
        self.assertEqual(self.check(.6,'too_far',distance=5),'')
        self.assertEqual(self.check(.71,'too_far',distance=5),'distance_far')

    def test_published_motion_not_raw_warning_controls_cut(self):
        self.check(0)
        self.assertEqual(self.check(.1,output='1 1 0 0 0 0 1 75'),'')
        self.assertEqual(self.check(.2),'')  # Fast return is also a transient burst.
        self.assertEqual(self.check(.3),'')
        self.assertEqual(self.check(.4),'')
        for i in range(5,12):
            result=self.check(i/10,output=f'{(i-4)*.7} 1 0 0 0 0 1 75')
        self.assertEqual(result,'camera_motion')
        self.assertGreater(self.guard.metrics['output_speed'],5)

    def test_quaternion_sign_flip_is_not_a_camera_spin(self):
        self.check(0)
        for i in range(1,15):
            self.assertEqual(self.check(i/20,output=f'0 1 0 0 0 0 {(-1)**i} 75'),'')

    def test_large_published_jump_exits_even_after_stationary_period(self):
        self.check(0)
        self.assertEqual(self.check(2,output='2 1 0 0 0 0 1 75'),'tracking_jump')
        self.assertEqual(self.guard.metrics['output_jump'],2)

    def test_continuous_high_angular_motion_exits(self):
        for i in range(8):
            yaw=math.radians(i*35)/2
            result=self.check(i*.1,output=f'0 1 0 0 {math.sin(yaw)} 0 {math.cos(yaw)} 75')
        self.assertEqual(result,'camera_motion')

    def test_unchanged_samples_do_not_shorten_motion_interval(self):
        for t in (0,.05,.1,.15,.2):self.check(t)
        self.check(.25,output='.25 1 0 0 0 0 1 75')
        self.assertAlmostEqual(self.guard.metrics['output_speed'],1)

    def test_bad_published_output_and_unknown_errors_fail_closed(self):
        self.assertEqual(self.check(0,output='half-written'),'')
        self.assertEqual(self.check(.36,output='half-written'),'tracking_output')
        self.assertEqual(self.check(.5,'new_unknown_error'),'')
        self.assertEqual(self.check(1.16,'new_unknown_error'),'view_unknown')
