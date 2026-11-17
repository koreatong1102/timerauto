import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from portrait_identity import PortraitOwnership
from spectator_log_watcher import SpectatorLogWatcher
from timerauto import MainApp


class PortraitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'blue').mkdir()
        self.archive = self.root / 'archive'
        self.archive.mkdir()
        self.name = self.root / 'blue' / 'name.txt'
        self.image = self.root / 'blue' / 'portrait.png'
        self.name.write_text('CURRENT_PLAYER', encoding='utf-8')
        self.pixels = np.full((8, 8, 4), 255, dtype=np.uint8)
        self.image.write_bytes(cv2.imencode('.png', self.pixels)[1].tobytes())
        os.utime(self.name, (100, 100))
        os.utime(self.image, (101, 101))

    def watcher(self, *, session='match-current', directory=None):
        watcher = SpectatorLogWatcher(SimpleNamespace(players={}))
        watcher._match_archive = SimpleNamespace(
            session_dir=str(directory or self.archive), session_id=session)
        return watcher

    def accept(self, watcher):
        changed, image = watcher._read_image_if_changed('blue', str(self.image))
        self.assertTrue(changed)
        np.testing.assert_array_equal(image, self.pixels)

    def test_same_fighter_name_rewrite_keeps_ui_portrait_and_can_reemit_after_reset(self):
        watcher = self.watcher()
        self.accept(watcher)
        self.name.write_text('CURRENT_PLAYER', encoding='utf-8')
        os.utime(self.name, (200, 200))
        with patch('spectator_log_watcher._safe_cv2_imread') as decode:
            self.assertEqual(watcher._read_image_if_changed('blue', str(self.image)), (False, None))
            decode.assert_not_called()
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), str(self.image))
        app = SimpleNamespace(cfg=SimpleNamespace(spectatorlog_path=str(self.root)),
                              spectator_watcher=watcher)
        self.assertEqual(MainApp._log_portrait_path_for_side(app, 'blue'), str(self.image))
        watcher._reset_portrait_locks()
        self.accept(watcher)

    def test_same_match_restart_restores_verified_identity_not_name_mtime(self):
        self.accept(self.watcher())
        os.utime(self.name, (200, 200))
        resumed = self.watcher()
        self.accept(resumed)
        receipt = json.loads((self.archive / 'portrait_owners.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['session_id'], 'match-current')
        self.assertEqual(receipt['portraits']['blue']['name'], 'current_player')

    def test_full_watcher_round_transition_and_restart_keep_both_portraits(self):
        (self.root / 'red').mkdir()
        (self.root / 'red' / 'name.txt').write_text('RED_PLAYER', encoding='utf-8')
        (self.root / 'red' / 'portrait.png').write_bytes(self.image.read_bytes())
        os.utime(self.root / 'red' / 'name.txt', (100, 100))
        os.utime(self.root / 'red' / 'portrait.png', (101, 101))
        match = self.root / 'match'
        match.mkdir()
        for key, value in dict(round_number='1', round_total='3', round_time='180',
                               round_state='MatchIntro').items():
            (match / (key + '.txt')).write_text(value, encoding='utf-8')
        cfg = SimpleNamespace(players={}, spectator_match_archive_dir=str(self.archive))
        watcher = SpectatorLogWatcher(cfg)
        self.addCleanup(lambda: watcher._match_archive.close())
        first = watcher._read_update(str(self.root))
        self.assertIsNotNone(first.get('blue_player_img'))
        self.assertIsNotNone(first.get('red_player_img'))
        session = watcher._match_session_id
        (match / 'round_state.txt').write_text('RoundFight', encoding='utf-8')
        watcher._read_update(str(self.root))
        (match / 'round_state.txt').write_text('RoundBreak', encoding='utf-8')
        watcher._read_update(str(self.root))
        for side in ('blue', 'red'):
            path = self.root / side / 'name.txt'
            path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
            os.utime(path, (200, 200))
        (match / 'round_number.txt').write_text('2', encoding='utf-8')
        (match / 'round_state.txt').write_text('RoundIntro', encoding='utf-8')
        watcher._read_update(str(self.root))
        self.assertEqual(watcher._match_session_id, session)
        for side in ('blue', 'red'):
            self.assertTrue(watcher._portrait_locked[side])
            self.assertTrue(watcher.portrait_path_for_side(str(self.root), side))
        watcher._match_archive.close()
        resumed = SpectatorLogWatcher(cfg)
        self.addCleanup(lambda: resumed._match_archive.close())
        (match / 'round_state.txt').write_text('RoundFight', encoding='utf-8')
        update = resumed._read_update(str(self.root))
        self.assertEqual(resumed._match_session_id, session)
        self.assertIsNotNone(update.get('blue_player_img'))
        self.assertIsNotNone(update.get('red_player_img'))

    def test_different_fighter_cannot_reuse_receipt_then_new_capture_is_accepted(self):
        watcher = self.watcher()
        self.accept(watcher)
        self.name.write_text('NEXT_PLAYER', encoding='utf-8')
        os.utime(self.name, (200, 200))
        watcher._reset_portrait_locks()
        with patch('spectator_log_watcher._safe_cv2_imread') as decode:
            self.assertEqual(watcher._read_image_if_changed('blue', str(self.image)), (False, None))
            decode.assert_not_called()
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), '')
        os.utime(self.image, (201, 201))
        self.accept(watcher)
        os.utime(self.name, (300, 300))
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), str(self.image))

    def test_new_match_with_same_fighter_does_not_inherit_previous_match_receipt(self):
        self.accept(self.watcher())
        os.utime(self.name, (200, 200))
        other = self.watcher(session='match-next')
        with patch('spectator_log_watcher._safe_cv2_imread') as decode:
            self.assertEqual(other._read_image_if_changed('blue', str(self.image)), (False, None))
            decode.assert_not_called()
        self.assertEqual(other.portrait_path_for_side(str(self.root), 'blue'), '')

    def test_replaced_or_changed_file_cannot_use_old_receipt(self):
        watcher = self.watcher()
        self.accept(watcher)
        os.utime(self.name, (200, 200))
        replacement = self.image.with_suffix('.new')
        replacement.write_bytes(self.image.read_bytes())
        os.utime(replacement, (101, 101))
        os.replace(replacement, self.image)
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), '')

    def test_invalid_image_never_creates_a_receipt(self):
        self.image.write_bytes(b'partial png')
        os.utime(self.image, (101, 101))
        watcher = self.watcher()
        self.assertEqual(watcher._read_image_if_changed('blue', str(self.image)), (False, None))
        self.assertFalse((self.archive / 'portrait_owners.json').exists())
        os.utime(self.name, (200, 200))
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), '')

    def test_identity_changed_during_decode_cannot_be_confirmed(self):
        watcher = self.watcher()
        def decode(*args):
            self.name.write_text('NEXT_PLAYER', encoding='utf-8')
            os.utime(self.name, (200, 200))
            return self.pixels
        with patch('spectator_log_watcher._safe_cv2_imread', side_effect=decode):
            self.assertEqual(watcher._read_image_if_changed('blue', str(self.image)), (False, None))
        self.assertFalse((self.archive / 'portrait_owners.json').exists())

    def test_winner_replacement_is_emitted_and_retained_after_another_name_write(self):
        watcher = self.watcher()
        self.accept(watcher)
        self.pixels[:, :, :3] = 120
        self.image.write_bytes(cv2.imencode('.png', self.pixels)[1].tobytes())
        os.utime(self.image, (201, 201))
        self.accept(watcher)
        os.utime(self.name, (300, 300))
        self.assertEqual(watcher.portrait_path_for_side(str(self.root), 'blue'), str(self.image))

    def test_invalid_receipt_is_ignored_but_fresh_photo_still_works(self):
        (self.archive / 'portrait_owners.json').write_text('{incomplete', encoding='utf-8')
        self.accept(self.watcher())

    def test_file_changed_after_candidate_is_not_confirmed(self):
        owners = PortraitOwnership()
        owners.bind(str(self.archive), 'match-current')
        candidate = owners.candidate('blue', str(self.image))
        os.utime(self.image, (102, 102))
        self.assertFalse(owners.confirm('blue', candidate))

    def test_match_changed_during_decode_does_not_bind_photo_to_the_other_match(self):
        owners = PortraitOwnership()
        owners.bind(str(self.archive), 'match-current')
        candidate = owners.candidate('blue', str(self.image))
        owners.bind(str(self.archive), 'match-next')
        self.assertFalse(owners.confirm('blue', candidate))
        self.assertFalse((self.archive / 'portrait_owners.json').exists())


if __name__ == '__main__':
    unittest.main()
