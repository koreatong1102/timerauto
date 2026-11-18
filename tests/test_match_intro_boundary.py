"""MatchIntro starts a bout; RoundIntro must preserve that bout's state."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from spectator_log_watcher import SpectatorLogWatcher


class MatchIntroBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ('blue', 'red', 'match'):
            (self.root / folder).mkdir()
        self.write('blue/name.txt', 'BLUE')
        self.write('red/name.txt', 'RED')
        self.write('match/round_total.txt', '3')
        self.cfg = SimpleNamespace(players={}, spectatorlog_sync_timer=True,
                                   spectator_match_archive_dir=str(self.root / 'archive'))
        self.watcher = self.make_watcher()
        self.watcher._runtime_baseline_ready = True

    def make_watcher(self):
        watcher = SpectatorLogWatcher(self.cfg)
        self.addCleanup(lambda: watcher._match_archive.close())
        return watcher

    def write(self, relative, text):
        (self.root / relative).write_text(text, encoding='utf-8')

    def update(self, state, round_no=1, *, watcher=None):
        self.write('match/round_state.txt', state)
        self.write('match/round_number.txt', str(round_no))
        self.write('match/round_time.txt', '180' if 'Fight' in state else '2')
        return (watcher or self.watcher)._read_update(str(self.root))

    def assert_not_new_match(self, update):
        for key in ('vs_intro_event', 'spectator_match_session', 'spectator_match_stats_reset', 'spectator_sp_reset'):
            self.assertNotIn(key, update)
        self.assertNotEqual(update.get('commentary_tts_stop_reason'), 'new_match')

    def test_three_rounds_have_one_vs_one_session_and_no_per_round_match_reset(self):
        watcher = self.watcher
        with patch.object(watcher, '_begin_match_session', wraps=watcher._begin_match_session) as begin, \
             patch.object(watcher, '_reset_damage_session', wraps=watcher._reset_damage_session) as reset:
            first = self.update('MatchIntro')
            self.assertIn('vs_intro_event', first)
            session = watcher._match_session_id
            self.assert_not_new_match(self.update('MatchIntro'))
            for round_no in (1, 2, 3):
                if round_no > 1:
                    self.update('RoundBreak', round_no - 1)
                watcher._sp_activity_spent = {'blue': 17., 'red': 23.}
                intro = self.update('RoundIntro', round_no)
                self.assert_not_new_match(intro)
                self.assertEqual(intro['spectator_intro_kind'], 'round')
                self.assertEqual(watcher._sp_activity_spent, {'blue': 17., 'red': 23.})
                self.assertEqual(watcher._match_session_id, session)
                fight = self.update('RoundFight', round_no)
                self.assertEqual(fight['round_intro_event']['round'], round_no)
                self.assert_not_new_match(fight)
            self.assertEqual(begin.call_count, 1)
            self.assertEqual(reset.call_count, 1)

    def test_round_intro_does_not_reset_engine_or_commentary_match_context(self):
        self.update('MatchIntro')
        self.update('RoundFight')
        self.update('RoundBreak')
        with patch.object(self.watcher._event_engine, 'reset') as engine_reset, \
             patch.object(self.watcher._commentary_director, 'reset_match') as commentary_reset, \
             patch.object(self.watcher._bgrade_commentary, 'reset_match') as style_reset:
            self.assert_not_new_match(self.update('RoundIntro', 2))
            engine_reset.assert_not_called()
            commentary_reset.assert_not_called()
            style_reset.assert_not_called()

    def test_same_fighters_rematch_gets_new_session_and_vs_even_if_old_archive_incomplete(self):
        first = self.update('MatchIntro')
        old_id = first['vs_intro_event']['matchSessionId']
        old_dir = self.watcher._match_archive.session_dir
        self.update('RoundFight')
        # Explicit new-bout intro is evidence of a new match even if a missing
        # winner file left the old archive marked resumable.
        self.update('Cancel')
        second = self.update('MatchIntro')
        self.assertIn('vs_intro_event', second)
        self.assertNotEqual(second['vs_intro_event']['matchSessionId'], old_id)
        self.assertNotEqual(self.watcher._match_archive.session_dir, old_dir)
        self.assertFalse(second['spectator_match_session']['resumed'])
        self.assertTrue(second['spectator_match_stats_reset'])
        self.assertEqual(self.update('RoundFight')['round_intro_event']['round'], 1)
        self.assert_not_new_match(self.update('RoundIntro', 2))

    def test_new_fighters_get_new_match_intro(self):
        old = self.update('MatchIntro')['vs_intro_event']['matchSessionId']
        self.update('RoundFight')
        self.write('blue/name.txt', 'NEXT_BLUE')
        self.write('red/name.txt', 'NEXT_RED')
        update = self.update('MatchIntro')
        self.assertNotEqual(update['vs_intro_event']['matchSessionId'], old)
        self.assertEqual(update['blue_name'], 'NEXT_BLUE')

    def test_restart_in_round_two_intro_restores_same_session_without_vs(self):
        self.update('MatchIntro')
        self.update('RoundFight')
        self.update('RoundBreak')
        session = self.watcher._match_session_id
        self.watcher._match_archive.close()
        resumed = self.make_watcher()
        first = self.update('RoundIntro', 2, watcher=resumed)
        self.assertEqual(resumed._match_session_id, session)
        self.assertTrue(first['spectator_match_session']['resumed'])
        self.assertNotIn('vs_intro_event', first)
        self.assertNotIn('spectator_sp_reset', first)
        self.assert_not_new_match(self.update('RoundIntro', 2, watcher=resumed))
        self.assert_not_new_match(self.update('RoundIntro', 3, watcher=resumed))

    def test_restart_in_round_two_fight_does_not_show_vs_in_next_round(self):
        self.update('MatchIntro')
        self.update('RoundFight', 2)
        session = self.watcher._match_session_id
        self.watcher._match_archive.close()
        resumed = self.make_watcher()
        self.assertNotIn('vs_intro_event', self.update('RoundFight', 2, watcher=resumed))
        self.assertEqual(resumed._match_session_id, session)
        self.update('RoundBreak', 2, watcher=resumed)
        self.assert_not_new_match(self.update('RoundIntro', 3, watcher=resumed))

    def test_first_round_fallback_handles_missed_match_intro_after_terminal(self):
        old = self.update('MatchIntro')['vs_intro_event']['matchSessionId']
        self.update('RoundFight')
        self.update('Cancel')
        update = self.update('RoundIntro')
        self.assertNotEqual(update['spectator_match_session']['id'], old)
        self.assertIn('vs_intro_event', update)
        self.assert_not_new_match(self.update('RoundIntro'))

    def test_legacy_intro_alias_cannot_create_match_in_round_two(self):
        self.update('MatchIntro')
        self.update('RoundFight')
        self.update('RoundBreak')
        self.assert_not_new_match(self.update('intro', 2))

    def test_temporary_empty_state_between_rounds_does_not_retrigger_vs(self):
        self.update('MatchIntro')
        self.update('RoundFight')
        self.update('RoundBreak')
        self.update('', 2)
        self.assert_not_new_match(self.update('RoundIntro', 2))
        self.assert_not_new_match(self.update('RoundIntro', 2))


if __name__ == '__main__':
    unittest.main()
