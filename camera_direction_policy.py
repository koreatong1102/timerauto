"""Broadcast shot selection, consuming central verdicts without reclassifying hits."""
import collections
import math
import threading
import time

CAMERA_DEFAULTS = {
    'camera_director_profile':'balanced', 'camera_director_pressure_enabled':True,
    'camera_director_counter_enabled':True, 'camera_director_duration':2.0,
    'camera_director_max_duration':3.0, 'camera_director_cooldown':12.0,
    'camera_director_min_hits':3,
    'camera_director_broadcast_enabled':True,
    'camera_director_target_pct':18.0,'camera_director_idle_sec':12.0,
}
PROFILES = {
    'cautious':dict(hits=4, score=82, stability=.22, speed=2, turn=100, near=.8, far=2.8),
    'balanced':dict(hits=3, score=72, stability=.15, speed=2.5, turn=120, near=.7, far=3.2),
    'active':dict(hits=3, score=65, stability=.10, speed=3, turn=150, near=.65, far=3.5),
}


def camera_settings(source):
    out = {}
    limits = {'duration':(1,3), 'max_duration':(1,3), 'cooldown':(0,120), 'min_hits':(3,10),
              'target_pct':(5,35),'idle_sec':(6,60)}
    for key, default in CAMERA_DEFAULTS.items():
        value = source.get(key, default) if isinstance(source,dict) else getattr(source,key,default)
        if key.endswith('_profile'):
            value = value if isinstance(value,str) and value in PROFILES else default
        elif key.endswith('_enabled'):
            value = value if isinstance(value,bool) else default
        else:
            try:
                value = float(value)
                if not math.isfinite(value):raise ValueError()
                lo,hi = limits[key.removeprefix('camera_director_')]
                value = max(lo,min(hi,value))
                if key.endswith('_min_hits'):value=int(value)
            except (ValueError,TypeError,OverflowError):value=default
        out[key] = value
    out['camera_director_max_duration'] = max(out['camera_director_duration'],out['camera_director_max_duration'])
    return out


class DirectorFeed:
    """Latest live flow only. Repeated deliveries never refresh opportunity age."""
    def __init__(self, *, min_hits=3, pressure=True, counter=True, support=False):
        self.lock = threading.Lock()
        self.min_hits, self.pressure, self.counter = max(3,min_hits), pressure, counter
        self.support=support
        self.latest = None
        self.blocked_until = self.at = 0
        self.busy = False
        self.seen = collections.OrderedDict()
        self.flows = {}
        self.serial = 0
        self.reason = 'no_fresh_combo'
        self.last_event_at=-100
        self.block_reason=''

    def update(self, data, busy=False, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self.at,self.busy = now,busy
            try:
                observed=float(data.get('commentary_tts_observed_at',now))
                late=math.isfinite(observed) and now-observed>.9
            except (ValueError,TypeError):late=False
            priority = any(data.get(k) for k in ('spectator_round_report','spectator_round_reports',
                'spectator_winner','spectator_scorecard','vs_intro_event','round_intro_event'))
            if priority or busy:
                self.latest = None
                self.flows.clear()
                self.reason = 'priority_or_signal'
            if priority:
                self.blocked_until=max(self.blocked_until,now+2)
                self.block_reason='report_or_round_priority'
            for event in data.get('spectator_effect_events') or []:
                if str(event.get('kind') or '').lower() in ('stun','knockdown','tko','ko'):
                    self.blocked_until=max(self.blocked_until,now+5)
                    self.block_reason='effect_'+str(event.get('kind') or '').lower()
                    self.latest=None;self.flows.clear()
            for event in data.get('spectator_event_engine') or []:
                key=str(event.get('event_id') or '')
                if not key or key in self.seen:continue
                self.seen[key]=now
                while len(self.seen)>256:self.seen.popitem(last=False)
                if late:continue
                self.last_event_at=now
                if str(event.get('effect_kind') or '').lower() in ('stun','knockdown','tko','ko'):
                    self.blocked_until=max(self.blocked_until,now+5)
                    self.block_reason='effect_'+str(event.get('effect_kind') or '').lower()
                    self.latest=None;self.flows.clear()
                    continue
                if busy or priority or now<self.blocked_until:continue
                side=event.get('side')
                if side not in ('blue','red'):continue
                hits=max(0,int(event.get('combo_hits') or 0))
                if not hits and not event.get('counter'):continue
                other='red' if side=='blue' else 'blue'
                # An opponent's centrally-qualified reply ends uncontested pressure.
                if self.latest and self.latest['side']!=side:
                    self.latest=None;self.reason='opponent_reply'
                self.flows.pop(other,None)
                flow=self.flows.get(side)
                if not flow or now-flow['at']>.9 or hits<=flow['hits']:
                    self.serial+=1
                    flow={'key':f'{side}-{self.serial}','counter_at':-100,'counter_hits':0}
                    self.latest=None
                followed = (now-flow['counter_at']<=.9 and hits>flow['counter_hits'] and hits>=2)
                kind='counter_followup' if followed and self.counter else 'pressure' if hits>=self.min_hits and self.pressure else 'pressure_support' if self.support and self.pressure and hits>=2 else ''
                flow.update(at=now,hits=hits)
                if event.get('counter'):flow.update(counter_at=now,counter_hits=hits)
                self.flows[side]=flow
                if kind:
                    score=64+min(4,max(0,hits-2))*3 if kind=='counter_followup' else 46+min(5,max(0,hits-2))*5 if kind=='pressure_support' else 52+min(5,max(0,hits-3))*5
                    self.latest=dict(side=side,at=now,id=key,hits=hits,kind=kind,score=score,flow=flow['key'])
                    self.reason=kind
                else:self.reason='counter_wait_followup' if event.get('counter') else 'no_fresh_combo'

    def snapshot(self,now):
        with self.lock:
            valid=now-self.at<=1 and not self.busy and now>=self.blocked_until
            candidate=dict(self.latest) if self.latest and now-self.latest['at']<=.9 else None
            if candidate is None and now-self.last_event_at>.9:self.reason='no_fresh_combo'
            return valid,candidate

    def status(self,now):
        with self.lock:
            return {'feed_age_sec':round(max(0,now-self.at),3),
                    'presentation_busy':self.busy,
                    'priority_remaining_sec':round(max(0,self.blocked_until-now),3),
                    'priority_cause':'presentation_busy' if self.busy else self.block_reason if now<self.blocked_until else 'stale_signal' if now-self.at>1 else ''}


def direction_selftest():
    """Deterministic rehearsal; never reads/writes camera files or sends keys."""
    feed=DirectorFeed()
    feed.update({'spectator_event_engine':[dict(event_id='a',side='blue',combo_hits=2)]},now=0)
    assert feed.snapshot(0)[1] is None
    feed.update({'spectator_event_engine':[dict(event_id='b',side='blue',combo_hits=3)]},now=.2)
    assert feed.snapshot(.2)[1]['kind']=='pressure'
    feed=DirectorFeed()
    feed.update({'spectator_event_engine':[dict(event_id='c',side='red',combo_hits=1,counter=True)]},now=1)
    assert feed.snapshot(1)[1] is None
    feed.update({'spectator_event_engine':[dict(event_id='d',side='red',combo_hits=2)]},now=1.3)
    assert feed.snapshot(1.3)[1]['kind']=='counter_followup'
    assert feed.snapshot(2.3)[1] is None
    feed.update({'spectator_effect_events':[dict(kind='knockdown')]},now=3)
    assert not feed.snapshot(3)[0]
    support=DirectorFeed(support=True)
    support.update({'spectator_event_engine':[dict(event_id='support',side='blue',combo_hits=2)]},now=0)
    assert support.snapshot(0)[1]['kind']=='pressure_support'
    from camera_broadcast_policy import ShotBudget
    budget=ShotBudget()
    for now in range(13):budget.observe(now,True)
    assert budget.scenic_ready() and budget.allows(2)
    return ['기본 모드 2연타: 전환 안 함','3연타 공격 흐름: 후보 선정',
            '단발 카운터: 후속타 대기','카운터 후속타: 후보 선정',
            '지난 공격 후보: 만료','다운: 전환 차단',
            '방송 모드 2연타: 보조 후보 선정','방송 모드: 구도 대기·목표 비중 검사',
            '이 시험은 F6·F4와 실제 카메라를 건드리지 않습니다.']
