"""Round-local replay selection and break presentation; no combat rejudging."""
import os
import copy
import re
import time
import uuid
from diagnostics import diagnostics as DIAG


DEFAULTS={'round_highlights_enabled':True,'round_highlights_report_sec':15,
          'round_highlights_clip_sec':8,'round_highlights_max_clips':5,
          'round_highlights_reserve_sec':5,'round_highlights_capture_source':'auto'}


def settings(raw):
    get=raw.get if isinstance(raw,dict) else lambda k,d:getattr(raw,k,d)
    out={k:get(k,v) for k,v in DEFAULTS.items()}
    out['round_highlights_enabled']=out['round_highlights_enabled'] is True
    for key,lo,hi in (('report_sec',5,20),('clip_sec',4,12),('max_clips',1,5),('reserve_sec',4,10)):
        name='round_highlights_'+key
        try:out[name]=max(lo,min(hi,int(out[name])))
        except (ValueError,TypeError,OverflowError):out[name]=DEFAULTS[name]
    if out['round_highlights_capture_source'] not in ('auto','source_record','replay_buffer'):
        out['round_highlights_capture_source']='auto'
    return out


class RoundHighlights:
    def __init__(self,cfg,overlay,schedule,busy,clock=time.monotonic,release=None):
        self.cfg,self.overlay,self.schedule,self.busy,self.clock=cfg,overlay,schedule,busy,clock
        self.pool={};self.seen=set();self.mode='';self.until=0;self.terminal=False
        self.generation=0;self.active=False;self.token='';self.pending=None;self.planned=set()
        self.last_capture=-100;self.started=0;self.remaining=[]
        self.release=release or (lambda paths:None)
        self.wait_reason=''
        self.last_report=None;self.played=False;self.report_restored=False

    def reset(self):
        files=[x['file'] for rows in self.pool.values() for x in rows if x['file']]
        self.cancel();self.pool.clear();self.seen.clear();self.planned.clear()
        self.last_capture=-100;self.terminal=False;self.mode=''
        self.last_report=None;self.played=False;self.report_restored=False
        self.release(files)

    def observe(self,data):
        state=str(data.get('spectator_round_state') or '').lower()
        if data.get('vs_intro_event') or data.get('spectator_match_clear'):
            self.reset()
        if state:self.mode=state
        reports=list(data.get('spectator_round_reports') or [])
        if isinstance(data.get('spectator_round_report'),dict):reports.append(data['spectator_round_report'])
        if any(isinstance(x,dict) and x.get('isFinal') for x in reports):self.terminal=True
        if data.get('spectator_match_terminal') or state in ('results','end','knockout','disqualified','cancel'):
            self.terminal=True
        if any(str(x.get('kind') or '').lower() in ('knockdown','ko','tko','stun') for x in data.get('spectator_effect_events') or []):
            self.cancel()
        if self.terminal or (state and state!='break') or data.get('round_intro_event'):
            self.cancel()
        if state=='fight':self.terminal=False
        if self.mode=='break':
            now=self.clock()
            seconds=data.get('seconds_left')
            if seconds is not None:
                try:deadline=now+max(0,float(seconds))
                except (ValueError,TypeError,OverflowError):return
                self.until=deadline if self.until<now or state=='break' and not self.pending and not self.active else min(self.until,deadline)
        else:self.until=0

    def consider(self,event,round_no,names):
        if not settings(self.cfg())['round_highlights_enabled'] or not round_no:return None
        key=str(event.get('event_id') or '')
        if not key or key in self.seen:return None
        self.seen.add(key)
        if len(self.seen)>2048:self.seen={key}
        hits=int(event.get('combo_hits') or 0);counter=bool(event.get('is_counter'))
        effect=str(event.get('effect_kind') or '').lower()
        down=effect in ('knockdown','down','ko','tko')
        if not (down or hits>=3 or counter and hits>=2):return None
        side=str(event.get('attacker_side') or '')
        if side not in ('blue','red'):return None
        now=self.clock()
        # Reuse down captures. Keep a bounded top ten so five non-overlapping
        # scenes can survive pending/failed saves and nearby down events.
        score=min(40,(20 if counter else 0)+hits*5)+(35 if down else 0)
        score+=min(20,max(0,float(event.get('combo_damage') or event.get('damage') or 0))/10)
        rows=self.pool.setdefault(int(round_no),[])
        if now-self.last_capture<8 and not down:return None
        if len(rows)>=10 and score<=min(x['score'] for x in rows):return None
        self.last_capture=now
        cfg=self.cfg();source=settings(cfg)['round_highlights_capture_source']
        if source=='auto':
            source=str(getattr(cfg,'potm_capture_source',getattr(cfg,'obs_auto_replay_source','source_record')) or 'source_record')
            if source=='source_record' and not getattr(cfg,'obs_source_record_enabled',False) and getattr(cfg,'obs_replay_buffer_enabled',False):source='replay_buffer'
            if source=='replay_buffer' and not getattr(cfg,'obs_replay_buffer_enabled',False) and getattr(cfg,'obs_source_record_enabled',False):source='source_record'
        row=dict(id=uuid.uuid4().hex,round=int(round_no),side=side,score=score,at=now,
                 label=('COUNTER COMBO' if counter else 'CLEAN COMBO' if hits>=3 else 'KNOCKDOWN')+(' · DOWN' if down and hits>=3 else ''),
                 nickname=str(names.get(side) or side.upper()),file='',source=source)
        rows.append(row)
        DIAG.record('replay_round_candidate',round=round_no,candidate_id=row['id'],label=row['label'],score=score)
        retired=[]
        if len(rows)>10:
            lowest=min(range(len(rows)),key=lambda index:rows[index]['score'])
            retired.append(rows.pop(lowest)['file'])
        for old in list(self.pool):
            if old<int(round_no)-1:retired.extend(x['file'] for x in self.pool.pop(old,[]))
        self.release(retired)
        return row

    def attach(self,path,context,source):
        key=context.get('round_highlight_id')
        if not key or not os.path.isfile(path):return
        for rows in self.pool.values():
            for row in rows:
                if row['id']==key and row['source']==source:
                    row['file']=path
                    DIAG.record('replay_round_file_attached',candidate_id=key,round=row['round'],path=path)

    def compact_summary(self,text):
        """Only shorten a recap when this break actually has a reserved clip.

        Preserve complete existing sentences and their original numbers. The
        normal final report and breaks without footage retain their full text.
        """
        if not self.pending or not settings(self.cfg())['round_highlights_enabled']:
            return text
        if not self.ready(self.pending[0]) and not any(not x['file'] for x in self.pool.get(self.pending[0],[])):return text
        cfg=settings(self.cfg())
        available=self.until-self.clock()-cfg['round_highlights_clip_sec']-cfg['round_highlights_reserve_sec']-12
        budget=max(5,min(18,available))
        sentences=re.split(r'(?<=[.!?])\s+',str(text or '').strip())
        selected=[];used=0
        for sentence in sentences:
            estimate=len(re.sub(r'\s+','',sentence))/5.2+1.4
            if selected and (used+estimate>budget or len(selected)>=3):break
            selected.append(sentence);used+=estimate
        result=' '.join(selected)
        DIAG.record('replay_round_recap_budget',round=self.pending[0],budget_sec=budget,
                    original_chars=len(text),selected_chars=len(result))
        return result

    def pins(self,path):
        # Archive pruning runs in a worker; take bounded snapshots of UI data.
        return bool(path) and any(x['file']==path for rows in list(self.pool.values()) for x in list(rows))

    def ready(self,round_no):
        rows=sorted(self.pool.get(int(round_no or 0),[]),key=lambda x:x['score'],reverse=True)
        chosen=[]
        for row in rows:
            try:available=bool(row['file']) and os.path.getsize(row['file'])>0
            except OSError:available=False
            if available and all(abs(row['at']-x['at'])>=8 for x in chosen):
                chosen.append(dict(row))
        return chosen

    def report(self,payload):
        cfg=settings(self.cfg());r=int(payload.get('round') or 0)
        if payload.get('isFinal') or self.terminal or self.mode!='break' or not cfg['round_highlights_enabled']:return False
        if self.last_report and r<int(self.last_report.get('round') or 0):return True
        self.last_report=copy.deepcopy(payload)
        if r in self.planned:return self.active or self.pending is None and not self.report_restored
        # Keep corrected report numbers visible while awaiting the same due
        # time. A last-second capture may finish after the report arrives.
        if not self.ready(r) and not any(not x['file'] for x in self.pool.get(r,[])):
            DIAG.record('replay_round_skip',round=r,reason='no_candidate_file');return False
        if self.until-self.clock()<cfg['round_highlights_report_sec']+cfg['round_highlights_clip_sec']+cfg['round_highlights_reserve_sec']:
            DIAG.record('replay_round_skip',round=r,reason='short_break',remaining_sec=self.until-self.clock());return False
        self.planned.add(r);self.pending=(r,self.clock()+cfg['round_highlights_report_sec'])
        self.played=False;self.report_restored=False
        DIAG.record('replay_round_plan',round=r,ready=len(self.ready(r)),remaining_sec=self.until-self.clock())
        self._arm()
        return False

    def _arm(self):
        generation=self.generation
        self.schedule(200,lambda:self.tick() if generation==self.generation else None)

    def tick(self):
        cfg=settings(self.cfg());now=self.clock();overlay=self.overlay()
        if not overlay or not cfg['round_highlights_enabled'] or self.terminal or self.mode!='break':
            self.cancel();return
        if self.until-now<=cfg['round_highlights_reserve_sec']:
            if self.pending or self.active:DIAG.record('replay_round_skip',reason='reserve_reached',waiting_for=self.wait_reason)
            self.cancel();self._restore_report();return
        if self.active:
            if now-self.started>cfg['round_highlights_clip_sec']+3:
                token=self.token
                self.active=False;self.token=''
                overlay.stop_obs_replay(token);overlay.update(roundHighlightActive=False)
                self._play()
        elif self.pending and now>=self.pending[1]:
            busy=self.busy();replaying=overlay.snapshot().get('obsReplayActive')
            if busy or replaying:
                reason='commentary' if busy else 'other_replay'
                if reason!=self.wait_reason:
                    self.wait_reason=reason
                    DIAG.record('replay_round_wait',reason=reason,round=self.pending[0],remaining_sec=self.until-now)
                self._arm();return
            r=self.pending[0];self.pending=None
            self.remaining=self.ready(r)[:cfg['round_highlights_max_clips']]
            if not self.remaining:DIAG.record('replay_round_skip',round=r,reason='capture_not_ready_at_due')
            self._play()
        if self.active or self.pending:self._arm()

    def _play(self):
        cfg=settings(self.cfg());overlay=self.overlay()
        if not self.remaining or self.until-self.clock()<cfg['round_highlights_clip_sec']+cfg['round_highlights_reserve_sec']:
            if self.remaining:DIAG.record('replay_round_skip',reason='not_enough_time_after_commentary',remaining_sec=self.until-self.clock())
            self.remaining=[];self._restore_report();return
        row=self.remaining.pop(0)
        caption=f"ROUND {row['round']} HIGHLIGHT · {row['nickname']} · {row['label']}"
        self.token=overlay.play_obs_replay(row['file'],muted=False,volume=100,replay_kind='round_highlight',
                                          replay_caption=caption,start_from_end_sec=cfg['round_highlights_clip_sec'],fade_ms=160)
        self.active=bool(self.token);self.started=self.clock()
        if self.active:self.played=True
        DIAG.record('replay_round_start',candidate_id=row['id'],round=row['round'],token=self.token)
        overlay.update(roundHighlightActive=self.active)
        if not self.active:
            if self.remaining:self._play()
            else:self._restore_report()

    def _restore_report(self):
        overlay=self.overlay()
        if (not overlay or not self.played or self.report_restored or not self.last_report
                or self.active or self.pending or self.terminal or self.mode!='break'
                or self.until<=self.clock()):return
        if overlay.snapshot().get('obsReplayActive'):return
        payload=copy.deepcopy(self.last_report)
        if payload.get('isFinal'):return
        payload['showDelayMs']=0
        self.report_restored=True
        overlay.push_event('round_report',**payload)
        DIAG.record('replay_round_report_restored',round=payload.get('round'),remaining_sec=self.until-self.clock())

    def ended(self,token):
        if not self.active or token!=self.token:return False
        self.active=False;self.token=''
        self.overlay().update(roundHighlightActive=False)
        self._play()
        return True

    def cancel(self):
        self.generation+=1;self.pending=None;self.remaining=[]
        self.wait_reason=''
        token=self.token;self.token='';self.active=False
        overlay=self.overlay()
        if overlay and token:
            overlay.stop_obs_replay(token);overlay.update(roundHighlightActive=False)


def create_settings_panel(cfg,parent,changed):
    from PyQt6.QtWidgets import QGroupBox,QFormLayout,QCheckBox,QSpinBox,QComboBox,QLabel
    panel=QGroupBox('휴식시간 · 방금 라운드 하이라이트',parent);layout=QFormLayout(panel)
    saved=settings(cfg)
    enabled=QCheckBox('라운드리포트 다음에 방금 라운드의 좋은 장면 재생')
    enabled.setObjectName('roundHighlightsEnabled');enabled.setChecked(saved['round_highlights_enabled'])
    layout.addRow(enabled)
    note=QLabel('카운터 후속 콤보·연속 공격·다운 중 라운드별 후보를 따로 고릅니다.\n'
                'OBS 연결과 아래 선택한 저장 방식이 준비돼 있어야 합니다. POTM을 꺼도 사용할 수 있습니다.\n'
                '기존 KD/POTM과 같은 이벤트는 저장 요청을 합칩니다. 추가 후보 저장은 최소 8초 간격입니다.\n'
                '해설이 끝나고 시간이 충분할 때만 재생합니다. 영상이 없으면 리포트를 유지합니다.\n'
                '영상이 모두 끝나면 남은 휴식시간 동안 방금 라운드리포트를 다시 표시합니다.\n'
                '마지막 라운드는 기존 POTM 순서를 유지하며, 다음 라운드가 시작되면 즉시 종료합니다.')
    note.setWordWrap(True);layout.addRow(note)
    controls={}
    source=QComboBox();source.addItem('자동 · 현재 리플레이/POTM 설정 사용','auto');source.addItem('Source Record · 게임 전용 저장','source_record');source.addItem('OBS 기본 리플레이 버퍼','replay_buffer')
    source.setObjectName('roundHighlightsSource');source.setCurrentIndex(max(0,source.findData(saved['round_highlights_capture_source'])))
    layout.addRow('영상 저장 방식',source)
    for key,label,lo,hi in [('report_sec','리포트 최소 표시(초)',5,20),('clip_sec','영상당 최대 재생(초)',4,12),
                          ('max_clips','라운드당 최대 재생 개수',1,5),('reserve_sec','다음 라운드 준비 여유(초)',4,10)]:
        spin=QSpinBox();spin.setObjectName('roundHighlights_'+key);spin.setRange(lo,hi);spin.setValue(saved['round_highlights_'+key])
        controls[key]=spin;layout.addRow(label,spin)
    def save(*_):
        cfg.round_highlights_enabled=enabled.isChecked();cfg.round_highlights_capture_source=source.currentData()
        for key,spin in controls.items():setattr(cfg,'round_highlights_'+key,spin.value())
        changed()
    enabled.toggled.connect(save);source.currentIndexChanged.connect(save)
    for spin in controls.values():spin.valueChanged.connect(save)
    return panel
