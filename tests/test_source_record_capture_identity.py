"""Missing/coalesced saves must never shift the next clip's event identity."""
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from obs_auto_replay import ObsAutoReplayController
from source_record_capture import file_matches_capture
from tests import test_source_record_auto_replay as replay_tests


class SourceCaptureIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = replay_tests.SourceRecordAutoReplayTests()._app(self.temp.name, fallback=False)
        self.app._prune_source_record_archive = Mock()
        self.app._schedule_obs_auto_replay = Mock(return_value=True)
        self.app._register_potm_file = Mock()
        self.app._round_highlight_engine = Mock(return_value=Mock())
        self.clock = [100.0]
        self.patch_clock = patch('timerauto.time.monotonic', side_effect=lambda: self.clock[0])
        self.patch_clock.start()
        self.addCleanup(self.patch_clock.stop)

    def context(self, key, kind='', **extra):
        return dict(auto_replay_kind=kind, auto_replay_source='source_record',
                    auto_replay_source_wait_sec=5., event_key=key,
                    trigger_monotonic=self.clock[0] - 1.9,
                    replay_capture_delay_sec=1.9, replay_pre_event_sec=3.,
                    replay_post_event_sec=1.9, attacker_side='blue',
                    attacker_name='Original Nick', **extra)

    def request(self, reason, context):
        return self.app._request_source_record_capture(self.app.obs_integration, 'Scene 2', reason, context)

    def output(self, name='new.mp4'):
        path = Path(self.app.cfg.obs_source_record_incoming_dir, name)
        path.write_bytes(b'fixture for a newly produced clip')
        return path

    def scan(self):
        self.app._refresh_source_record_clip_organizer()
        self.app._refresh_source_record_clip_organizer()

    def test_reproduced_42_second_old_kd_does_not_claim_new_normal_hit(self):
        old = self.context('old-kd', 'kd', potm_candidate_id='wrong-best', round_highlight_id='wrong-round')
        self.assertTrue(self.request('knockdown', old))
        self.clock[0] += 42.
        normal = self.context('new-hit')
        self.assertTrue(self.request('hit-38.4', normal))
        self.output()
        self.scan()
        self.app._schedule_obs_auto_replay.assert_not_called()
        self.app._register_potm_file.assert_not_called()
        self.app._round_highlight_engine().attach.assert_not_called()
        saved = list(Path(self.app.cfg.obs_source_record_archive_dir).rglob('*.mp4'))
        self.assertEqual(len(saved), 1)
        self.assertIn('HIT-38.4', saved[0].name)
        self.assertNotIn('KO_REPLAY', str(saved[0]))
        self.assertEqual(len(self.app._source_record_pending), 0)

    def test_near_simultaneous_normal_saves_do_not_build_fifo(self):
        self.assertTrue(self.request('counter', self.context('first')))
        self.clock[0] += .4
        self.assertFalse(self.request('hit', self.context('overlap')))
        self.assertEqual(len(self.app.obs_integration.source_saves), 1)
        self.assertEqual(len(self.app._source_record_pending), 1)
        self.output('first.mp4')
        self.scan()
        self.assertEqual(len(self.app._source_record_pending), 0)
        self.clock[0] += 1
        self.assertTrue(self.request('knockdown', self.context('actual-kd', 'kd')))
        self.output('kd.mp4')
        self.scan()
        self.assertEqual(self.app._schedule_obs_auto_replay.call_count, 1)
        self.assertEqual(self.app._schedule_obs_auto_replay.call_args.args[2]['event_key'], 'actual-kd')

    def test_kd_waits_briefly_for_previous_file_and_adjusts_event_anchored_trim(self):
        self.request('counter', self.context('first'))
        self.clock[0] += .4
        kd = self.context('kd', 'kd')
        self.assertTrue(self.request('knockdown', kd))
        self.assertEqual(len(self.app.obs_integration.source_saves), 1)
        self.clock[0] += 1.0
        self.output('first.mp4')
        self.scan()
        self.assertEqual(len(self.app.obs_integration.source_saves), 2)
        sent = self.app.obs_integration.source_saves[-1][2]
        self.assertAlmostEqual(sent['replay_capture_delay_sec'], 2.9)
        self.output('kd.mp4')
        self.scan()
        play = self.app._schedule_obs_auto_replay.call_args.args[2]
        self.assertAlmostEqual(play['replay_start_from_end_sec'], 5.9)
        self.assertAlmostEqual(play['replay_end_from_end_sec'], 1.0)

    def test_expired_deferred_kd_is_not_captured_as_a_later_scene(self):
        self.request('counter', self.context('first'))
        self.request('knockdown', self.context('kd', 'kd'))
        self.clock[0] += 3.
        self.output('first.mp4')
        self.scan()
        self.assertEqual(len(self.app.obs_integration.source_saves), 1)
        self.assertIsNone(self.app._source_record_deferred)

    def test_tko_has_priority_over_deferred_kd(self):
        self.request('counter', self.context('first'))
        self.request('knockdown', self.context('kd', 'kd'))
        self.request('tko', self.context('tko', 'tko'))
        self.output('first.mp4')
        self.scan()
        self.assertEqual(self.app.obs_integration.source_saves[-1][2]['event_key'], 'tko')

    def test_expired_tko_does_not_block_a_new_decisive_event(self):
        self.request('counter', self.context('first'))
        self.request('tko', self.context('old-tko', 'tko'))
        self.clock[0] += 3.
        self.request('knockdown', self.context('new-kd', 'kd'))
        self.output('first.mp4')
        self.scan()
        self.assertEqual(self.app.obs_integration.source_saves[-1][2]['event_key'], 'new-kd')

    def test_changing_incoming_folder_does_not_transfer_old_event_ownership(self):
        self.request('knockdown', self.context('kd', 'kd'))
        other = Path(self.temp.name, 'other-incoming')
        other.mkdir()
        self.app.cfg.obs_source_record_incoming_dir = str(other)
        path = self.output('unrelated.mp4')
        self.scan()
        self.assertEqual(len(self.app._source_record_pending), 0)
        self.assertTrue(path.exists())
        self.app._schedule_obs_auto_replay.assert_not_called()

    def test_round_change_cancels_deferred_capture(self):
        self.request('counter', self.context('first'))
        self.request('knockdown', self.context('kd', 'kd'))
        self.app._obs_auto_replay = Mock()
        self.app._cancel_obs_auto_replay('next_round')
        self.output('first.mp4')
        self.scan()
        self.assertEqual(len(self.app.obs_integration.source_saves), 1)

    def test_failed_ack_does_not_remove_another_capture(self):
        self.request('counter', self.context('first'))
        failed = self.app.obs_integration.source_saves[-1][2]
        self.app._discard_failed_source_record_clip(failed)
        self.request('knockdown', self.context('kd', 'kd'))
        self.app._discard_failed_source_record_clip(failed)
        self.assertEqual(len(self.app._source_record_pending), 1)
        self.assertEqual(self.app._source_record_pending[0]['context']['event_key'], 'kd')

    def test_timeout_without_a_file_cannot_attach_late_output_to_potm(self):
        self.request('knockdown', self.context('kd', 'kd', potm_candidate_id='candidate'))
        self.clock[0] += 6.
        self.output('late.mp4')
        self.scan()
        self.assertEqual(len(self.app._source_record_pending), 0)
        self.app._register_potm_file.assert_not_called()
        self.app._schedule_obs_auto_replay.assert_not_called()

    def test_existing_incoming_recording_is_not_assigned_to_new_event(self):
        old = self.output('ongoing-recording.mp4')
        self.request('knockdown', self.context('kd', 'kd'))
        self.scan()
        self.assertTrue(old.exists())
        self.assertEqual(len(self.app._source_record_pending), 1)
        self.app._schedule_obs_auto_replay.assert_not_called()

    def test_one_correct_file_is_shared_by_kd_potm_and_round_candidate(self):
        context = self.context('kd', 'kd', potm_candidate_id='best', round_highlight_id='round')
        self.request('knockdown', context)
        self.app._source_record_names['blue'] = 'Wrong New Fighter'
        self.output()
        self.scan()
        path = self.app._schedule_obs_auto_replay.call_args.args[0]
        self.assertIn('Original Nick', path)
        self.app._register_potm_file.assert_called_once_with(path, 'best', managed=False, capture_source='source_record')
        self.assertEqual(self.app._round_highlight_engine().attach.call_args.args[0], path)
        self.assertEqual(len(list(Path(self.app.cfg.obs_source_record_archive_dir).rglob('*.mp4'))), 1)

    def test_locked_file_remains_bound_and_cannot_be_replaced_by_next_file(self):
        self.request('knockdown', self.context('kd', 'kd'))
        first = self.output('locked.mp4')
        self.app._refresh_source_record_clip_organizer()
        with self.assertLogs(level='ERROR'), patch('timerauto.shutil.move', side_effect=PermissionError('fixture lock')):
            self.app._refresh_source_record_clip_organizer()
        self.assertEqual(self.app._source_record_pending[0]['bound_file'], os.path.normcase(str(first)))
        second = self.output('unrelated.mp4')
        with self.assertLogs(level='WARNING'), patch('timerauto.shutil.move', side_effect=PermissionError('fixture lock')):
            self.scan()
        self.assertTrue(second.exists())
        self.app._schedule_obs_auto_replay.assert_not_called()
        self.scan()
        self.assertTrue(second.exists())
        self.assertEqual(self.app._schedule_obs_auto_replay.call_count, 1)

    def test_ack_success_alone_does_not_release_capture_slot(self):
        self.request('counter', self.context('first'))
        # Even after the vendor accepts, the active file receiver remains owned.
        self.assertFalse(self.request('counter', self.context('second')))
        self.assertEqual(len(self.app.obs_integration.source_saves), 1)

    def test_late_file_after_timeout_cannot_take_a_new_receiver_during_quarantine(self):
        self.request('knockdown', self.context('first-kd', 'kd'))
        self.clock[0] += 5.5
        self.assertFalse(self.request('hit', self.context('normal')))
        late = self.output('late-kd.mp4')
        self.scan()
        self.assertTrue(late.exists())
        self.app._schedule_obs_auto_replay.assert_not_called()
        self.clock[0] += 3.
        self.assertTrue(self.request('counter', self.context('fresh')))
        self.output('fresh.mp4')
        self.scan()
        self.assertTrue(late.exists())
        saved = list(Path(self.app.cfg.obs_source_record_archive_dir).rglob('*.mp4'))
        self.assertEqual(len(saved), 1)
        self.assertIn('COUNTER', saved[0].name)

    def test_reused_filename_is_not_permanently_hidden_after_previous_file_moved(self):
        self.request('counter', self.context('first'))
        self.output('reused.mp4')
        self.scan()
        self.clock[0] += 1.
        self.request('knockdown', self.context('kd', 'kd'))
        self.output('reused.mp4')
        self.scan()
        self.assertEqual(len(self.app._source_record_pending), 0)
        self.assertEqual(self.app._schedule_obs_auto_replay.call_count, 1)

    def test_superseded_kd_file_is_archived_but_not_played_after_new_terminal_event(self):
        self.request('knockdown', self.context('kd', 'kd'))
        self.app._obs_highlight_capture_generation += 1
        self.output('kd.mp4')
        self.scan()
        self.assertEqual(len(self.app._source_record_pending), 0)
        self.app._schedule_obs_auto_replay.assert_not_called()

    def test_receiver_rejects_second_metadata_even_if_admission_is_bypassed(self):
        self.request('counter', self.context('first'))
        with self.assertLogs(level='WARNING'):
            self.assertFalse(self.app._queue_source_record_clip('hit', self.context('second')))
        self.assertEqual(len(self.app._source_record_pending), 1)

    def test_birth_time_not_finalization_time_identifies_capture_window(self):
        meta = dict(requested_wall=100., context={'auto_replay_source_wait_sec': 5.})
        self.assertTrue(file_matches_capture(meta, SimpleNamespace(st_birthtime=102., st_mtime=110.)))
        self.assertFalse(file_matches_capture(meta, SimpleNamespace(st_birthtime=90., st_mtime=102.)))
        self.assertFalse(file_matches_capture(meta, SimpleNamespace(st_birthtime=142., st_mtime=142.)))

    def test_expired_source_file_cannot_bypass_live_playback_gate(self):
        target = self.output()
        context = self.context('kd', 'kd')
        self.clock[0] += 42
        self.assertFalse(self.app._play_source_record_auto_replay(str(target), {'event': 'KD', 'context': context}))
        self.app._schedule_obs_auto_replay.assert_not_called()


class LiveReplayExpiryTests(unittest.TestCase):
    def test_schedule_and_start_both_enforce_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, 'replay.mp4')
            path.write_bytes(b'fixture')
            cfg = SimpleNamespace(obs_auto_replay_enabled=True, obs_auto_replay_kd=True, obs_auto_replay_delay_sec=1.)
            clock, callbacks = [100.], []
            overlay = Mock()
            controller = ObsAutoReplayController(lambda: cfg, lambda: overlay,
                lambda ms, callback: callbacks.append(callback), clock=lambda: clock[0])
            context = dict(auto_replay_kind='kd', trigger_monotonic=100., auto_replay_deadline_monotonic=105.)
            self.assertTrue(controller.schedule(str(path), 'KD', context))
            clock[0] = 110.
            callbacks[0]()
            overlay.play_obs_replay.assert_not_called()
            self.assertFalse(controller.schedule(str(path), 'KD', context))


if __name__ == '__main__':
    unittest.main()
