import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

from config_model import AppConfig
from spectator_log_watcher import SpectatorLogWatcher
from match_log_archive import MatchLogArchive


class LobbyReturnRestartTests(unittest.TestCase):
    def setUp(self):
        cfg = AppConfig()
        cfg.spectator_lobby_auto_start_enabled = True
        self.w = SpectatorLogWatcher(cfg)
        self.lobby = {'ready_to_start': True, 'slots': [
            {'slot': 1, 'type': 'Player', 'name': 'BLUE', 'ready': True, 'occupied': True},
            {'slot': 2, 'type': 'Player', 'name': 'RED', 'ready': True, 'occupied': True}]}
        self.sig = ((100, 10), (100, 5), (100, 20))

    def observe(self, now, state, lobby=True, match_sig=None, lobby_stamp=200):
        return self.w._observe_lobby_auto_start_cycle(
            self.lobby if lobby else {}, state=state,
            lobby_sig=(lobby_stamp, 200) if lobby else (0, 0),
            match_sig=match_sig or self.sig, now=now)

    def start(self):
        out = {}
        self.assertTrue(self.w._apply_lobby_auto_start_edge(self.lobby, out))
        request = out['spectator_lobby_auto_start']['requestId']
        self.w.lobby_auto_start_finished(request, True)
        return request

    def test_cancel_return_with_same_ready_players_rearms_once(self):
        old = self.start()
        self.observe(0, 'intro', lobby=False)
        self.observe(.9, 'fight', lobby=False)
        self.assertFalse(self.observe(2, 'cancel'))
        self.assertTrue(self.observe(3.1, 'cancel'))
        out = {}
        self.assertTrue(self.w._apply_lobby_auto_start_edge(self.lobby, out, state='cancel'))
        current = out['spectator_lobby_auto_start']['requestId']
        self.assertNotEqual(old, current)
        self.assertEqual(out['spectator_lobby_auto_start']['attempt'], 1)
        self.w.lobby_auto_start_finished(old, False)  # A late old worker cannot disturb the new cycle.
        self.assertEqual(self.w._lobby_auto_start_request_id, current)
        self.w.lobby_auto_start_finished(current, True)
        self.assertTrue(self.observe(5, 'cancel'))
        self.assertFalse(self.w._apply_lobby_auto_start_edge(self.lobby, {}, state='cancel'))

    def test_brief_lobby_file_during_live_match_does_not_rearm(self):
        self.start()
        self.observe(0, 'fight', lobby=False)
        self.observe(.2, 'fight')  # A short disappearance/rewrite is not departure.
        self.assertFalse(self.observe(2, 'fight'))
        self.assertFalse(self.w._apply_lobby_auto_start_edge(self.lobby, {}, state='fight'))
        self.assertTrue(self.w._lobby_ready_latched)

    def test_stale_fight_requires_departure_newer_lobby_and_quiet_match(self):
        self.start()
        self.observe(0, 'fight', lobby=False)
        self.observe(1, 'fight', lobby=False)
        self.assertFalse(self.observe(2, 'fight', lobby_stamp=50))
        self.assertFalse(self.observe(3.1, 'fight', lobby_stamp=50))  # Old lingering file.
        self.assertTrue(self.observe(3.2, 'fight', lobby_stamp=200))
        out = {}
        self.assertTrue(self.w._apply_lobby_auto_start_edge(self.lobby, out, state=''))
        self.w._lobby_start_match_signature = Mock(return_value=self.sig)
        self.assertEqual(self.w.lobby_auto_start_recovery_context('unused', self.lobby), 'ready')
        self.assertEqual(self.w.lobby_auto_start_recovery_context('unused', {}), 'waiting')
        self.lobby['slots'][1]['ready'] = False
        self.assertEqual(self.w.lobby_auto_start_recovery_context('unused', self.lobby), 'cancelled')
        new = ((300, 10), (300, 5), (300, 20))
        self.w._lobby_start_match_signature.return_value = new
        self.assertIsNone(self.w.lobby_auto_start_recovery_context('unused', self.lobby))
        self.assertFalse(self.observe(4, 'intro', match_sig=new))

    def test_progressing_match_or_missing_host_ready_flag_never_overrides_fight(self):
        self.start()
        self.observe(0, 'fight', lobby=False)
        self.observe(1, 'fight', lobby=False)
        self.observe(2, 'fight')
        self.assertFalse(self.observe(3.1, 'fight', match_sig=((250, 10), (250, 5), (250, 20)), lobby_stamp=300))
        self.lobby['ready_to_start'] = False
        self.assertFalse(self.observe(5, 'fight', lobby_stamp=300))

    def test_lobby_that_flashes_then_disappears_cannot_trigger_restart(self):
        self.start()
        self.observe(0, 'intro', lobby=False)
        self.observe(1, 'intro', lobby=False)
        self.assertFalse(self.observe(2, 'cancel'))
        self.assertFalse(self.observe(2.4, 'cancel', lobby=False))
        self.assertFalse(self.observe(4, 'cancel'))
        self.assertTrue(self.observe(5.1, 'cancel'))

    def test_read_update_emits_stable_return_even_when_duplicate_ui_updates_are_throttled(self):
        self.start()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'match').mkdir()
            self.w._match_archive = MatchLogArchive(str(root/'archive'))
            (root/'match'/'round_state.txt').write_text('MatchIntro',encoding='utf-8')
            (root/'match'/'round_number.txt').write_text('1',encoding='utf-8')
            self.w._read_update(folder)
            (root/'match'/'round_state.txt').write_text('Cancel',encoding='utf-8')
            (root/'lobby.txt').write_text(
                'slot_1: type=Player occupied=true name=BLUE ready=true\n'
                'slot_2: type=Player occupied=true name=RED ready=true\n'
                'ready_to_start: true\n',encoding='utf-8')
            first = self.w._read_update(folder)
            self.assertNotIn('spectator_lobby_auto_start',first)
            self.w._lobby_return_since -= 2
            self.w._last_log_info_emit_at = time.time()+1000
            returned = self.w._read_update(folder)
            self.assertEqual(returned['spectator_lobby_auto_start']['attempt'],1)


if __name__ == '__main__':
    unittest.main()
