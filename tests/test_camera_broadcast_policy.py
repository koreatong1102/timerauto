import unittest
from camera_broadcast_policy import ShotBudget
from camera_direction_policy import DirectorFeed, camera_settings


class ShotBudgetTests(unittest.TestCase):
    def advance(self,budget,seconds,live=True):
        for i in range(seconds+1):budget.observe(i,live)

    def test_only_live_fight_time_counts_and_long_stalls_do_not_create_opportunities(self):
        budget=ShotBudget()
        self.advance(budget,5)
        budget.observe(50,False);budget.observe(80,False);budget.observe(100,True)
        self.assertEqual(budget.fight,5)
        self.assertEqual(budget.quiet,0)
        budget.observe(101,True)
        self.assertEqual(budget.fight,6)
        self.assertFalse(budget.scenic_ready())

    def test_support_then_scenic_gradually_become_available(self):
        budget=ShotBudget(idle_sec=12)
        self.advance(budget,5);self.assertFalse(budget.support_ready())
        budget.observe(6,True);self.assertTrue(budget.support_ready())
        self.assertFalse(budget.scenic_ready())
        for now in range(7,13):budget.observe(now,True)
        self.assertTrue(budget.scenic_ready())
        self.assertEqual(budget.relaxation(),0)
        for now in range(13,30):budget.observe(now,True)
        self.assertEqual(budget.relaxation(),8)

    def test_coverage_limits_bursts_then_recovers_with_time(self):
        budget=ShotBudget(target_pct=18)
        self.advance(budget,3)
        self.assertTrue(budget.allows(3));budget.started()
        self.assertFalse(budget.allows(3))
        for now in range(4,7):budget.observe(now,True)
        budget.ended()
        self.assertTrue(budget.allows(3));budget.started()
        for now in range(7,10):budget.observe(now,True)
        budget.ended()
        self.assertFalse(budget.allows(3))
        for now in range(10,71):budget.observe(now,True)
        self.assertTrue(budget.allows(3))
        self.assertEqual(budget.used_seconds(),0)

    def test_support_events_are_explicit_and_never_refresh_duplicates(self):
        feed=DirectorFeed(support=True)
        row={'event_id':'two','side':'blue','combo_hits':2}
        feed.update({'spectator_event_engine':[row]},now=0)
        self.assertEqual(feed.snapshot(0)[1]['kind'],'pressure_support')
        feed.update({'spectator_event_engine':[row]},now=.8)
        self.assertIsNone(feed.snapshot(1)[1])
        feed.update({'spectator_effect_events':[{'kind':'knockdown'}]},now=2)
        self.assertFalse(feed.snapshot(2)[0])
        self.assertIsNone(feed.snapshot(2)[1])

    def test_broadcast_configuration_has_safe_limits_and_opt_out(self):
        value=camera_settings({'camera_director_broadcast_enabled':False,
                               'camera_director_target_pct':999,'camera_director_idle_sec':0})
        self.assertFalse(value['camera_director_broadcast_enabled'])
        self.assertEqual(value['camera_director_target_pct'],35)
        self.assertEqual(value['camera_director_idle_sec'],6)
