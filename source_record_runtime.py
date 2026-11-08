"""Targeted Source Record vendor requests; never operate the program output.

An enabled filter is not proof that its replay output was created. A missing
ReplayBuffer.Save hotkey is not proof of failure either: inspect actual outputs.
"""
import time
import uuid
from diagnostics import diagnostics as DIAG


class SourceRecordRuntime:
    def __init__(self, send, emit):
        self.send = send
        self.emit = emit
        self.pending = {}
        self.ready_at = {}
        self.repaired_at = {}
        self.duration = {}
        self.restart_due = {}
        self.verify_due = {}

    def reset(self):
        for item in self.pending.values():
            if item['action'] == 'save':
                self.result(item, False, 'OBS 연결이 종료되어 저장 결과를 확인할 수 없습니다', uncertain=True)
        self.pending.clear()
        self.ready_at.clear()
        self.repaired_at.clear()
        self.restart_due.clear()
        self.verify_due.clear()

    def result(self, item, ok, message='', uncertain=False):
        DIAG.record('source_record_save_result', source=item['source'], ok=bool(ok),
                    context=item.get('context', {}), request_id=item.get('request_id', ''),
                    message=message, uncertain=uncertain, accepted_only=True)
        self.emit({'type': 'source_record_replay_saved', 'ok': bool(ok),
                   'message': message, 'context': item.get('context', {}),
                   'reason': item.get('reason', ''), 'source': item['source'],
                   'request_id': item.get('request_id', ''), 'accepted_only': True,
                   'uncertain': uncertain})

    async def request(self, ws, action, source, context=None, reason=''):
        rid = 'sr-runtime-' + uuid.uuid4().hex
        item = dict(action=action, source=source, context=dict(context or {}),
                    reason=reason, sent_at=time.monotonic(), request_id=rid)
        self.pending[rid] = item
        DIAG.record('source_record_runtime_request', action=action, source=source,
                    request_id=rid, context=item['context'])
        if action == 'health':
            kind, payload = 'GetSourceFilter', {'sourceName': source, 'filterName': 'Source Record'}
        elif action == 'outputs':
            kind, payload = 'GetOutputList', {}
        elif action in ('repair_off', 'repair_on'):
            kind, payload = 'SetSourceFilterSettings', {
                'sourceName': source, 'filterName': 'Source Record', 'overlay': True,
                'filterSettings': {'replay_buffer': action == 'repair_on'},
            }
        else:
            args = {'source': source, 'filter': 'Source Record'}
            kind, payload = 'CallVendorRequest', {
                'vendorName': 'source-record',
                'requestType': 'replay_buffer_save' if action == 'save' else 'replay_buffer_start',
                'requestData': args,
            }
        await self.send(ws, kind, request_id=rid, request_data=payload)

    async def save(self, ws, source, context, reason):
        if time.monotonic() < self.ready_at.get(source, 0):
            self.result(dict(source=source, context=context, reason=reason), False,
                        'Source Record 버퍼 복구 후 영상 축적 중입니다. 이번 이벤트는 저장하지 못했습니다')
            return
        await self.request(ws, 'save', source, context, reason)

    async def health(self, ws, source):
        if not any(x['source'] == source and x['action'] != 'save' for x in self.pending.values()):
            await self.request(ws, 'health', source)

    async def repair(self, ws, source):
        now = time.monotonic()
        if now - self.repaired_at.get(source, -1e9) < 60:
            return
        self.repaired_at[source] = now
        DIAG.record('source_record_buffer_repair', source=source)
        # Gate saves immediately, including while waiting for the restart ACK.
        self.ready_at[source] = now + 15
        # The plugin's vendor start(stop_existing=True) sends two source updates
        # in one callback. OBS can coalesce them, so replayBuffer never sees false.
        # ACK + a deferred second request makes the state transition observable.
        await self.request(ws, 'repair_off', source)

    async def response(self, ws, data):
        item = self.pending.pop(str(data.get('requestId') or ''), None)
        if item is None:
            return  # A shutdown/reconnect invalidated this request.
        status = data.get('requestStatus') or {}
        outer_ok = bool(status.get('result'))
        response = data.get('responseData') or {}
        source, action = item['source'], item['action']
        if action in ('repair_off', 'repair_on'):
            if outer_ok and action == 'repair_off':
                self.restart_due[source] = time.monotonic() + 0.5
            elif outer_ok:
                self.ready_at[source] = time.monotonic() + self.duration.get(source, 10)
                self.verify_due[source] = time.monotonic() + 1
            else:
                self.emit({'type': 'source_record_buffer_recovered', 'ok': False,
                           'source': source, 'message': str(status.get('comment') or '버퍼 설정 실패')})
            return
        if action == 'health':
            if outer_ok and response.get('filterEnabled'):
                settings = response.get('filterSettings') or {}
                self.duration[source] = max(1, min(120, float(settings.get('replay_duration') or 10)))
                if not settings.get('replay_buffer', False):
                    await self.repair(ws, source)
                else:
                    await self.request(ws, 'outputs', source)
            return
        if action == 'outputs':
            if outer_ok:
                registered = any(
                    x.get('outputKind') == 'replay_buffer' and x.get('outputActive')
                    and x.get('outputName') == source + ' - Source Record'
                    for x in response.get('outputs') or [])
                if item.get('verify'):
                    self.emit({'type': 'source_record_buffer_recovered', 'ok': registered,
                               'source': source, 'warmup_sec': self.duration.get(source, 10),
                               'message': '' if registered else 'Source Record 버퍼 출력이 실행되지 않았습니다'})
                elif not registered:
                    await self.repair(ws, source)
            return
        nested = response.get('responseData') or {}
        ok = outer_ok and nested.get('success') is True
        message = str(nested.get('error') or status.get('comment') or '')
        if action == 'save':
            self.result(item, ok, message or ('' if ok else 'Source Record 리플레이 출력이 준비되지 않았습니다'))
            # An outer RPC error might be a missing plugin/source: do not reset
            # arbitrary OBS outputs. A vendor-declared failure is target-local.
            if outer_ok and not ok:
                await self.repair(ws, source)

    async def service(self, ws):
        now = time.monotonic()
        for source, due in list(self.restart_due.items()):
            if now >= due:
                self.restart_due.pop(source, None)
                await self.request(ws, 'repair_on', source)
        for source, due in list(self.verify_due.items()):
            if now >= due:
                self.verify_due.pop(source, None)
                await self.request(ws, 'outputs', source)
                # Mark only this verification request, not periodic checks.
                for item in self.pending.values():
                    if item['source'] == source and item['action'] == 'outputs':
                        item['verify'] = True

    def expire(self):
        now = time.monotonic()
        for rid, item in list(self.pending.items()):
            if now - item['sent_at'] > 8:
                self.pending.pop(rid, None)
                if item['action'] == 'save':
                    # Never resubmit an ambiguous save: it could create duplicates.
                    self.result(item, False, 'OBS 저장 응답 시간 초과: 중복 방지를 위해 재저장하지 않습니다', uncertain=True)
