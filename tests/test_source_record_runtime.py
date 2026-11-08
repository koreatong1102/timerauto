import time
import unittest

from source_record_runtime import SourceRecordRuntime
from obs_integration import ObsIntegration
from config_model import AppConfig


class SourceRecordRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent, self.events = [], []
        async def send(ws, kind, **kwargs):
            self.sent.append((kind, kwargs))
        self.runtime = SourceRecordRuntime(send, self.events.append)

    async def reply(self, response, ok=True, index=-1):
        await self.runtime.response(None, {
            'requestId': self.sent[index][1]['request_id'],
            'requestStatus': {'result': ok}, 'responseData': response})

    async def test_vendor_save_exact_target_and_no_hotkey_duplicate(self):
        await self.runtime.save(None, '장면 2', {'event_key': 'kd-1'}, 'KD')
        kind, args = self.sent[0]
        self.assertEqual(kind, 'CallVendorRequest')
        self.assertEqual(args['request_data'], {
            'vendorName': 'source-record', 'requestType': 'replay_buffer_save',
            'requestData': {'source': '장면 2', 'filter': 'Source Record'}})
        await self.reply({'responseData': {'success': True}})
        self.assertTrue(self.events[0]['ok'])
        self.assertEqual(self.events[0]['context']['event_key'], 'kd-1')
        self.assertEqual(len(self.sent), 1)

    async def test_nested_failure_not_reported_as_save_success(self):
        await self.runtime.save(None, '장면 2', {'event_key': 'kd-1'}, 'KD')
        await self.reply({'responseData': {'success': False}})
        self.assertFalse(self.events[0]['ok'])
        self.assertEqual(self.sent[-1][0], 'SetSourceFilterSettings')
        self.assertEqual(self.sent[-1][1]['request_data'], {
            'sourceName': '장면 2', 'filterName': 'Source Record', 'overlay': True,
            'filterSettings': {'replay_buffer': False}})

    async def test_enabled_checkbox_without_active_output_repairs_and_warms(self):
        await self.runtime.health(None, '장면 2')
        await self.reply({'filterEnabled': True, 'filterSettings': {
            'replay_buffer': True, 'replay_duration': 10}})
        await self.reply({'outputs': []})
        await self.reply({})  # OFF ACK; ON must be deferred, not coalesced.
        count = len(self.sent)
        await self.runtime.service(None)
        self.assertEqual(len(self.sent), count)
        self.runtime.restart_due['장면 2'] = 0
        await self.runtime.service(None)
        self.assertTrue(self.sent[-1][1]['request_data']['filterSettings']['replay_buffer'])
        await self.reply({})
        self.runtime.verify_due['장면 2'] = 0
        await self.runtime.service(None)
        await self.reply({'outputs': [{'outputName': '장면 2 - Source Record',
                                     'outputKind': 'replay_buffer', 'outputActive': True}]})
        self.assertEqual(self.events[-1]['warmup_sec'], 10)
        count = len(self.sent)
        await self.runtime.save(None, '장면 2', {'event_key': 'early'}, 'KD')
        self.assertEqual(len(self.sent), count)
        self.assertFalse(self.events[-1]['ok'])
        await self.runtime.repair(None, '장면 2')
        self.assertEqual(len(self.sent), count)  # No destructive watchdog loop.

    async def test_outer_rpc_failure_does_not_restart_unknown_source(self):
        await self.runtime.save(None, 'missing', {}, '')
        await self.reply({}, ok=False)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.events[-1]['ok'])

    async def test_timeout_is_uncertain_and_never_resaved(self):
        await self.runtime.save(None, '장면 2', {'event_key': 'kd'}, 'KD')
        next(iter(self.runtime.pending.values()))['sent_at'] = time.monotonic() - 9
        self.runtime.expire()
        self.assertTrue(self.events[-1]['uncertain'])
        self.assertEqual(len(self.sent), 1)

    async def test_shutdown_invalidates_late_reply_without_restart(self):
        await self.runtime.health(None, '장면 2')
        self.runtime.reset()
        await self.reply({'filterEnabled': True, 'filterSettings': {'replay_buffer': False}})
        self.assertEqual(len(self.sent), 1)

    async def test_shutdown_cancels_deferred_reenable(self):
        await self.runtime.repair(None, '장면 2')
        await self.reply({})
        self.runtime.restart_due['장면 2'] = 0
        self.runtime.reset()
        await self.runtime.service(None)
        self.assertEqual(len(self.sent), 1)

    async def test_active_output_does_not_mask_vendor_save_failure(self):
        await self.runtime.health(None, '장면 2')
        await self.reply({'filterEnabled': True, 'filterSettings': {'replay_buffer': True}})
        await self.reply({'outputs': [{'outputName': '장면 2 - Source Record',
                                     'outputKind': 'replay_buffer', 'outputActive': True}]})
        await self.runtime.save(None, '장면 2', {}, 'KD')
        await self.reply({'responseData': {'success': False}})
        self.assertEqual(self.sent[-1][0], 'SetSourceFilterSettings')

    async def test_healthy_target_without_hotkey_never_restarted(self):
        await self.runtime.health(None, '장면 2')
        await self.reply({'filterEnabled': True, 'filterSettings': {'replay_buffer': True}})
        await self.reply({'outputs': [{'outputName': '장면 2 - Source Record',
                                     'outputKind': 'replay_buffer', 'outputActive': True}]})
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.runtime.repaired_at, {})

    async def test_other_sources_active_output_is_not_target_health(self):
        await self.runtime.health(None, '장면 2')
        await self.reply({'filterEnabled': True, 'filterSettings': {'replay_buffer': True}})
        await self.reply({'outputs': [{'outputName': '다른 소스 - Source Record',
                                     'outputKind': 'replay_buffer', 'outputActive': True}]})
        self.assertEqual(self.sent[-1][0], 'SetSourceFilterSettings')


class SourceRecordQueueTests(unittest.TestCase):
    def test_public_save_uses_normalized_source(self):
        cfg = AppConfig()
        cfg.obs_integration_enabled = True
        client = ObsIntegration(cfg)
        client.save_source_record_replay('장면 2 - Source Record', 'KD', context={'event_key': 'a'})
        item = client._commands.get_nowait()
        self.assertEqual(item['type'], 'source_record_save')
        self.assertEqual(item['source'], '장면 2')

    def test_failed_capture_removes_only_matching_metadata(self):
        from collections import deque
        from types import SimpleNamespace
        from timerauto import MainApp
        app = SimpleNamespace(_source_record_pending=deque([
            {'context': {'event_key': 'first'}}, {'context': {'event_key': 'failed'}},
            {'context': {'event_key': 'third'}}]))
        MainApp._discard_failed_source_record_clip(app, {'event_key': 'failed'})
        self.assertEqual([x['context']['event_key'] for x in app._source_record_pending], ['first', 'third'])
