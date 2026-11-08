"""Opt-in live camera direction. Canonical events in, bounded camera cuts out.

No native mode acknowledgement exists. Fresh camera pose comparisons are only
an observation-based check, not proof of the game's internal toggle state.
"""
import collections
import logging
import math
from pathlib import Path
import threading
import time

from spectator_camera import HeadCamera, pose_to_camera, restore_head_flags
from camera_direction_policy import DirectorFeed, PROFILES
from camera_view_safety import ActiveViewSafety
from camera_broadcast_policy import ShotBudget
from diagnostics import diagnostics as DIAG


class CameraReadPending(ValueError):
    pass


def camera_pose(text):
    fields = text.replace("\\t", "\t").split()
    values = [float(v) for v in fields[:8]]
    if len(values) != 8 or not all(math.isfinite(v) for v in values):
        raise ValueError("카메라 출력이 완전하지 않습니다.")
    return values


def pose_matches(actual, requested):
    a, b = camera_pose(actual), camera_pose(requested)
    na = math.sqrt(sum(v*v for v in a[3:7])); nb = math.sqrt(sum(v*v for v in b[3:7]))
    return bool(na > .5 and nb > .5 and math.dist(a[:3],b[:3]) < .30
                and abs(sum(x*y for x,y in zip(a[3:7],b[3:7]))/(na*nb)) > .97)


class AutoCameraDirector:
    def __init__(self, notify, toggle, on_return=None, toggle_guarded=None, ensure_window_visible=None):
        self.notify, self.toggle = notify, toggle
        self.on_return = on_return
        self.toggle_guarded=toggle_guarded
        self.ensure_window_visible=ensure_window_visible
        self.feed = DirectorFeed()
        self.cancel = threading.Event()
        self.thread = None
        self.state = "idle"
        self.camera = HeadCamera()
        self.confirmed_on = False
        self.used = None
        self.realtime = True

    def start(self, root, options, duration=2, cooldown=12, min_hits=3, *,
              profile='balanced', pressure=True, counter=True, max_duration=3,
              broadcast_enabled=False,target_pct=18,idle_sec=12):
        if self.thread and self.thread.is_alive():
            raise ValueError("자동 연출을 먼저 중지하세요.")
        self.root = Path(root).resolve()
        if self.root.name.lower() == "match":
            self.root = self.root.parent
        self.options = dict(options,look_opponent=True)
        # Off-camera axes offsets are disabled for the geometry-safe auto view.
        self.options.update(yaw=0,pitch=0,comfort=True)
        self.duration = max(1,min(3,float(duration)))
        self.cooldown = max(0,min(120,float(cooldown)))
        self.profile = PROFILES.get(profile,PROFILES['balanced'])
        self.min_hits = max(self.profile['hits'],min(10,int(min_hits)))
        self.max_duration = max(self.duration,min(3,float(max_duration)))
        self.broadcast_enabled=bool(broadcast_enabled)
        self.shot_budget=ShotBudget(target_pct,idle_sec)
        self.scenic_candidate=None
        self.selection_reason=''
        self.history=collections.deque(maxlen=8)
        self.used_flow=None
        self.geometry_score=25
        self.geometry_cache={}
        self.geometry_metrics={}
        self.cancel = threading.Event()
        self.state, self.confirmed_on, self.used = "idle", False, None
        self.mismatch = 0
        self.last_round_value, self.last_round_at = "", 0
        self.next_cut, self.stable_at, self.previous = 0, None, {}
        self.last_reason = "waiting"
        self.candidate_kind=''
        self._last_decision_signature=None
        self._last_decision_at=-100
        self.last_cut_reason=''
        self.observed_stamp, self.matches = None, 0
        self.feed = DirectorFeed(min_hits=self.min_hits,pressure=pressure,counter=counter,
                                 support=self.broadcast_enabled and pressure)
        self.thread = threading.Thread(target=self._run,daemon=True,name="AutoCameraDirector")
        self.thread.start()

    def stop(self):
        self.cancel.set()  # Worker performs its own ordered release/exit.

    def _state(self, value, now):
        logging.info("CAMERA_DIRECTOR_STATE from=%s to=%s",self.state,value)
        DIAG.record('camera_director_state',previous=self.state,state=value)
        self.state, self.since = value, now
        self.observed_stamp, self.matches = None, 0

    def _decision(self,reason,candidate=None):
        self.last_reason=reason
        self.candidate_kind=(candidate or {}).get('kind','')
        signature=(reason,self.candidate_kind,(candidate or {}).get('side'))
        now=time.monotonic()
        if signature!=self._last_decision_signature and now-self._last_decision_at>=.25:
            self._last_decision_signature,self._last_decision_at=signature,now
            logging.info('CAMERA_DIRECTOR_DECISION reason=%s kind=%s side=%s',*signature)

    def _candidate_score(self,candidate,now):
        score=candidate['score']+self.geometry_score
        if self.history:
            previous=self.history[-1]
            if self.broadcast_enabled:
                # Never silently impose another 12–15s wait on top of cooldown.
                if now-previous['at']<max(4,self.cooldown):
                    if previous['kind']==candidate['kind']:score-=2
                    if previous['side']==candidate['side']:score-=1
            else:
                if now-previous['at']<12 and previous['kind']==candidate['kind']:score-=8
                if now-previous['at']<15 and previous['side']==candidate['side']:score-=5
        return score

    def _score_floor(self):
        return self.profile['score']-(self.shot_budget.relaxation() if self.broadcast_enabled else 0)

    def _entry_allowed(self):
        """Recheck after slow window activation, immediately before F6 key-down."""
        now=time.monotonic()
        valid,candidate=self.feed.snapshot(now)
        self.entry_block_reason=''
        if self.cancel.is_set() or not valid:
            self.entry_block_reason='cancelled' if self.cancel.is_set() else self.feed.status(now)['priority_cause'] or 'signal_invalid'
            return False
        try:
            live=(self.root/'match/round_state.txt').read_text().strip().lower() in ('roundfight','fight')
        except OSError:
            self.entry_block_reason='round_unavailable'
            return False
        if not live:
            self.entry_block_reason='not_fight'
            return False
        if self.prepared['kind']!='scenic' and (not candidate or candidate['flow']!=self.prepared['flow']):
            self.entry_block_reason='candidate_expired_or_changed'
            return False
        return True

    def _opportunity(self,now,valid,live,candidate):
        self.selection_reason=''
        if not self.broadcast_enabled or self.state not in ('idle','prepare','probe'):
            return candidate
        if not valid or not live or now<self.next_cut:return None
        if not self.shot_budget.allows(self.duration):
            self.selection_reason='coverage_budget'
            return None
        if candidate:
            support=candidate['kind']=='pressure_support'
            if not support or (self.shot_budget.support_ready() and
                               (self.profile is not PROFILES['cautious'] or candidate['hits']>=3)):
                return candidate
        if not self.shot_budget.scenic_ready():
            self.selection_reason='broadcast_wait'
            return None
        if self.scenic_candidate:
            return dict(self.scenic_candidate)
        last=self.history[-1]['side'] if self.history else 'red'
        for side in (('red','blue') if last=='blue' else ('blue','red')):
            if not self._geometry(side,now):continue
            distance=self.geometry_metrics.get('distance',0)
            if not max(.8,self.profile['near'])<=distance<=min(2.5,self.profile['far']):continue
            key=f'scenic-{self.shot_budget.serial}-{side}'
            self.scenic_candidate=dict(side=side,at=now,id=key,hits=0,kind='scenic',score=60,flow=key)
            return dict(self.scenic_candidate)
        self.selection_reason='scenic_view_wait'
        return None

    def _cancel_preparation(self,now,reason):
        self._decision(reason)
        if reason=='entry_priority_cancelled':
            DIAG.record('camera_director_entry_abort',stage='before_key',
                        cause=getattr(self,'entry_block_reason',''),**self.feed.status(now))
        self.camera.freeze()
        if self.camera.last_output is not None:
            restore_head_flags(self.root,expected=self.camera.last_output)
        self.camera.stop()
        self.next_cut,self.stable_at=now+3,None
        self.scenic_candidate=None
        self.shot_budget.serial+=1
        self._state('idle',now)

    def _prepare(self,now,valid,live,candidate):
        if self.cancel.is_set() or not valid or not live or not candidate or candidate['flow']!=self.prepared['flow']:
            self._cancel_preparation(now,'prepare_cancelled')
            return not self.cancel.is_set()
        if not self._geometry(candidate['side'],now) or self._candidate_score(candidate,now)<self._score_floor():
            self._cancel_preparation(now,'prepare_cancelled')
            return True
        try:
            if not self._prepare_started:
                self.camera.start(self.root,candidate['side'],realtime=self.realtime,**self.options)
                self._prepare_started=True
            else:
                self.camera.tick()
        except OSError as exc:
            # camera_input.txt itself may be held by Unity for a short rewrite.
            self._prepare_error=repr(exc)
        if self.camera.last_output is not None:
            # Initial atomic write can briefly wait on Unity's file handle;
            # start the probe clock only after that write actually succeeded.
            self._state('probe',time.monotonic())
            return True
        pipeline=self.camera.pipeline
        detail=(getattr(pipeline,'last_write_error','') or getattr(pipeline,'last_read_error','')
                or self.camera.last_prepare_error or self._prepare_error)
        self._decision('prepare_wait')
        if now-self.since>=.6:
            DIAG.record('camera_director_prepare_timeout',detail=detail or 'no complete first frame')
            raise ValueError('시점 준비 시간 초과 · F6은 누르지 않았습니다. '+
                             (detail or '완전한 첫 머리 좌표 또는 카메라 파일 저장을 확인하지 못했습니다.'))
        return True

    def _observe(self):
        try:
            path = self.root / "match" / "camera.txt"
            stat = path.stat()
            if time.time()-stat.st_mtime > .5:
                raise ValueError("실제 카메라 로그가 오래되어 전환을 확인할 수 없습니다.")
            text = path.read_text(encoding="utf-8-sig")
            camera_pose(text)
        except (OSError,ValueError) as exc:
            raise CameraReadPending(str(exc)) from exc
        fresh = stat.st_mtime_ns != self.observed_stamp
        self.observed_stamp = stat.st_mtime_ns
        return text, fresh

    def _geometry(self, side, now):
        cached=self.geometry_cache.get(side)
        if cached and 0<=now-cached[0]<.05:
            self.geometry_score,self.geometry_reason=cached[2:4]
            self.geometry_metrics=dict(cached[4])
            return cached[1]
        self.geometry_metrics={}
        try:
            result=self._geometry_once(side,now)
        except (OSError,ValueError):
            self.geometry_reason = "partial_pose"
            result=False
        self.geometry_cache[side]=(now,result,self.geometry_score,self.geometry_reason,dict(self.geometry_metrics))
        return result

    def _geometry_once(self, side, now):
        values = []
        self.geometry_metrics = {}
        paths=[self.root/corner/'head_position.txt' for corner in
               (side,'red' if side=='blue' else 'blue')]
        stats=[path.stat() for path in paths]
        stamps=[stat.st_mtime_ns for stat in stats]
        self.geometry_metrics['head_age']=max(max(0,time.time()-stat.st_mtime) for stat in stats)
        if self.geometry_metrics['head_age'] > .4:
            self.geometry_reason = "head_log_stale"
            return False
        for path in paths:
            row = [float(v) for v in path.read_text().split()]
            if len(row) != 9 or not all(math.isfinite(v) for v in row):
                self.geometry_reason = "partial_pose"
                return False
            values.append(row)
        distance = math.dist(values[0][2:5],values[1][2:5])
        self.geometry_metrics['distance']=distance
        self.geometry_score=25
        self.geometry_reason='view_ready'
        if not self.profile['near'] <= distance <= self.profile['far']:
            self.geometry_reason = "too_close" if distance < self.profile['near'] else "too_far"
            return False
        # Reject fast translation and sudden look-direction changes.
        opts = {k:v for k,v in self.options.items() if k not in ("look_opponent","position_ms","rotation_ms","comfort")}
        view = camera_pose(pose_to_camera(" ".join(map(str,values[0])),side,
                          target_text=" ".join(map(str,values[1])),**opts))
        previous = self.previous.get(side)
        fresh=not previous or tuple(stamps)!=previous[2]
        if fresh:
            self.previous[side] = (now,view,tuple(stamps))
        if previous and fresh:
            dt = now-previous[0]
            if 0 < dt < .3:
                dot = min(1,abs(sum(x*y for x,y in zip(view[3:7],previous[1][3:7]))))
                if math.dist(view[:3],previous[1][:3])/dt > self.profile['speed'] or math.degrees(2*math.acos(dot))/dt > self.profile['turn']:
                    self.geometry_reason = "rapid_motion"
                    return False
        # Optional glove proximity is only a visibility estimate, never a game verdict.
        direction=[values[1][i+2]-view[i] for i in range(3)]
        length=math.sqrt(sum(v*v for v in direction))
        direction=[v/max(.001,length) for v in direction]
        for hand in ('left','right'):
            path=self.root/side/f'glove_{hand}_position.txt'
            try:
                if time.time()-path.stat().st_mtime>.4:continue
                glove=[float(v) for v in path.read_text().split()]
                if len(glove)!=9 or not all(math.isfinite(v) for v in glove):continue
                delta=[glove[i+2]-view[i] for i in range(3)]
                along=sum(a*b for a,b in zip(delta,direction))
                across=math.sqrt(max(0,sum(v*v for v in delta)-along*along))
                if .06<along<min(.6,length) and across<.12:
                    self.geometry_score-=1.5 if self.broadcast_enabled else 12
            except (OSError,ValueError):pass
        if self.geometry_score<10:self.geometry_reason='glove_obstruction'
        return True

    def _begin_exit(self, now):
        self.camera.freeze()
        self.exit_pose = self.camera.last_output
        if not self.exit_pose:
            raise ValueError("복구할 카메라 위치가 없습니다.")
        self._state("release_write",now)
        self._release_write(now)

    def _release_write(self, now):
        try:
            restored = restore_head_flags(self.root,expected=self.exit_pose)
        except OSError as exc:
            if isinstance(exc,PermissionError) or getattr(exc,"winerror",None) in (5,32,33):
                if now-self.since <= 1:
                    return  # Retry on the next tick; no F6 before flags clear.
                raise ValueError("카메라 입력 파일 잠금이 지속되어 머리 복구를 저장하지 못했습니다. F6 상태와 머리 표시를 직접 확인하세요.") from exc
            raise
        if not restored:
            raise ValueError("카메라 입력 소유권이 바뀌어 자동 복귀를 중지합니다.")
        self._state("release",now)
        self.notify("자동 연출: 머리 숨김 해제 후 일반 카메라로 복귀 중")

    def step(self, now):
        valid, candidate = self.feed.snapshot(now)
        state_file = self.root / "match" / "round_state.txt"
        try:
            state_value = state_file.read_text().strip().lower()
        except OSError:
            state_value = ""
        if state_value:
            self.last_round_value, self.last_round_at = state_value,now
        elif now-self.last_round_at <= .2:
            state_value = self.last_round_value
        live = state_value in ("roundfight","fight")
        self.shot_budget.observe(now,live and valid)
        candidate=self._opportunity(now,valid,live,candidate)
        if self.state == "idle":
            if self.cancel.is_set():
                return False
            if not valid or not live or now < self.next_cut or not candidate or candidate["id"] == self.used or candidate['flow']==self.used_flow:
                reason='priority_or_signal' if not valid else 'not_fight' if not live else 'cooldown' if now<self.next_cut else 'same_flow' if candidate and candidate['flow']==self.used_flow else self.selection_reason or self.feed.reason
                if candidate is None and reason in ('pressure','counter_followup'):reason='no_fresh_combo'
                self._decision(reason,candidate)
                self.stable_at = None
                return True
            if not self._geometry(candidate["side"],now):
                self._decision(getattr(self,"geometry_reason","unsafe_or_stale_view"),candidate)
                self.stable_at = None
                return True
            if self._candidate_score(candidate,now)<self._score_floor():
                self._decision('glove_obstruction' if self.geometry_reason=='glove_obstruction' else 'shot_score_low',candidate)
                self.stable_at=None
                return True
            if self.stable_at is None or self.stable_at[:2] != (candidate['side'],candidate['flow']):
                self.stable_at = (candidate['side'],candidate['flow'],now)
                self._decision('stability_check',candidate)
                return True
            if now-self.stable_at[2] < max(self.profile['stability'],.25 if candidate['kind']=='scenic' else 0):
                self._decision('stability_check',candidate)
                return True
            self.used = candidate["id"]
            self.prepared=dict(candidate)
            self._prepare_started=False
            self._prepare_error=''
            self._state('prepare',now)
            return self._prepare(now,valid,live,candidate)
        if self.state=='prepare':
            return self._prepare(now,valid,live,candidate)
        if self.state in ("probe","enter","active"):
            self.camera.tick()
            actual,fresh = self._observe()
            match = pose_matches(actual,self.camera.last_output)
            if fresh:
                self.matches = self.matches+1 if match else 0
            if self.state == "probe":
                if self.matches >= 2:
                    raise ValueError("파일 카메라가 이미 켜진 것으로 보여 자동 연출을 중지합니다. F6을 끄고 다시 켜세요.")
                if self.cancel.is_set() or not valid or not live:
                    if self.cancel.is_set():
                        return False
                    self._cancel_preparation(now,'prepare_cancelled')
                    return True
                if now-self.since >= .12 and fresh:
                    if (not candidate or candidate['flow']!=self.prepared['flow']
                            or not self._geometry(candidate['side'],now)
                            or self._candidate_score(candidate,now)<self._score_floor()):
                        self._decision('prepare_cancelled',candidate)
                        self._cancel_preparation(now,'prepare_cancelled')
                        return True
                    if not self._entry_allowed():
                        self._cancel_preparation(time.monotonic(),'entry_priority_cancelled')
                        return True
                    ok,detail = (self.toggle_guarded(self._entry_allowed) if self.toggle_guarded else self.toggle())
                    logging.info("CAMERA_DIRECTOR_TOGGLE direction=enter ok=%s detail=%s",ok,detail)
                    if not ok:
                        if detail=='camera_entry_cancelled':
                            self._cancel_preparation(time.monotonic(),'entry_priority_cancelled')
                            return True
                        raise ValueError("F6 입력 실패: "+str(detail))
                    self._state("enter",time.monotonic())
            elif self.state == "enter":
                if self.matches >= 2:
                    self.confirmed_on = True
                    if self.cancel.is_set() or not valid or not live:
                        # The key may already have been sent when KD arrived.
                        # Confirm its effect, then exit once; never promote this
                        # transition to a normal active shot or blindly toggle.
                        self.last_cut_reason='entry_priority_cancelled'
                        self._decision('entry_priority_cancelled')
                        DIAG.record('camera_director_entry_abort',stage='confirmed_after_key',
                                    kind=self.prepared['kind'],side=self.camera.side,
                                    **self.feed.status(now))
                        self._begin_exit(now)
                        return True
                    self.mismatch = 0
                    self.bad_geometry_at = None
                    self.view_safety=ActiveViewSafety()
                    self.view_safety.evaluate(now,True,'view_ready',{},self.camera.last_output)
                    self.bad_flow_at=None
                    self._state("active",now)
                    self.active_started=now
                    self.shot_budget.started()
                    self.active_until=now+self.duration
                    self.hard_until=now+self.max_duration
                    self.used_flow=self.prepared['flow']
                    self.history.append(dict(at=now,side=self.camera.side,kind=self.prepared['kind']))
                    self._decision('shot_entered',self.prepared)
                    names={'counter_followup':'카운터 후속 공격','pressure_support':'짧은 연타 공방','scenic':'좋은 구도 · 공방 시점','pressure':'공격 흐름'}
                    self.notify('자동 연출: '+names[self.prepared['kind']]+' · 선수 시점')
                elif now-self.since > 1.5:
                    raise ValueError("파일 카메라 전환 확인 실패. F6을 재입력하지 않습니다. 직접 일반 카메라/머리 표시를 확인하세요.")
            elif self.state == "active":
                if not match and fresh:
                    self.mismatch = getattr(self,"mismatch",0)+1
                elif match:
                    self.mismatch = 0
                if getattr(self,"mismatch",0) >= 3:
                    self.confirmed_on = False
                    raise ValueError("수동 카메라 변경 또는 추적 이탈 감지. 추가 F6 입력 없이 중지합니다.")
                geometry_ok=self._geometry(self.camera.side,now)
                unsafe_reason=self.view_safety.evaluate(now,geometry_ok,self.geometry_reason,
                    self.geometry_metrics,self.camera.last_output)
                same_flow=bool(candidate and candidate['side']==self.camera.side and candidate['flow']==self.used_flow)
                if same_flow:
                    self.active_until=min(self.hard_until,max(self.active_until,now+.45))
                # Candidate freshness gates entry/extension, not the minimum
                # viewing time. A 0.9s gap between punches must not cancel a
                # confirmed shot configured to last 2–3 seconds.
                unsafe=bool(unsafe_reason)
                if self.cancel.is_set() or not valid or not live or now>=self.hard_until or now>=self.active_until or unsafe:
                    reason='priority_or_signal' if not valid or not live or self.cancel.is_set() else 'view_'+unsafe_reason if unsafe else 'duration_complete'
                    self.last_cut_reason=reason
                    detail=dict(self.view_safety.metrics,geometry_reason=self.geometry_reason,
                                held_sec=round(now-self.active_started,3),reason=reason,
                                side=self.camera.side,kind=self.prepared['kind'])
                    detail.update(self.shot_budget.snapshot())
                    detail.update(self.feed.status(now))
                    detail['round_state']=state_value
                    detail['broadcast_mode']=self.broadcast_enabled
                    logging.info('CAMERA_DIRECTOR_CUT %s',detail)
                    DIAG.record('camera_director_cut',**detail)
                    self._decision(reason,candidate)
                    self._begin_exit(now)
            return True
        if self.state == "release":
            _actual,fresh = self._observe()
            if fresh:
                self.matches += 1
            if self.matches >= 2 and now-self.since >= .12:
                self.confirmed_on = False  # Once-only exit: never repeat on failure.
                ok,detail = self.toggle()
                logging.info("CAMERA_DIRECTOR_TOGGLE direction=exit ok=%s detail=%s",ok,detail)
                if not ok:
                    raise ValueError("복귀 F6 입력 실패. 머리 숨김은 해제했지만 파일 카메라는 직접 확인하세요.")
                self._state("off_wait",time.monotonic())
            elif now-self.since > 1:
                raise ValueError("머리 복구 후 카메라 갱신 확인 실패. F6 상태를 직접 확인하세요.")
            return True
        if self.state == "release_write":
            self._release_write(now)
            return True
        if self.state == "off_wait":
            actual,fresh = self._observe()
            if fresh:
                self.matches = self.matches+1 if not pose_matches(actual,self.exit_pose) else 0
            if self.matches >= 2:
                self.camera.stop()
                self.shot_budget.ended()
                self.scenic_candidate=None
                self._state("post_return",now)
                if self.on_return is not None:
                    ok,detail = self.on_return()
                    logging.info("CAMERA_DIRECTOR_RETURN_F4 ok=%s detail=%s",ok,detail)
                    if not ok:
                        raise ValueError("일반 카메라 복귀 후 F4 입력 실패. 재시도하지 않습니다: "+str(detail))
                now = time.monotonic()
                self.next_cut, self.stable_at = now+self.cooldown, None
                self._state("idle",now)
                self.notify("자동 연출 대기 · 일반 카메라 복귀 관측 완료" + (" · F4 한 번 전달" if self.on_return is not None else ""))
            elif now-self.since > 1.5:
                raise ValueError("일반 카메라 복귀를 확인하지 못했습니다. F6을 재입력하지 않고 자동 연출을 중지합니다.")
            return True
        return False

    def _run(self):
        self.notify("자동 연출 대기 · 중앙 판정의 연속 공격과 안전한 시점을 기다립니다.")
        read_failed_at = None
        metrics_at = time.monotonic()
        visible_at=-100.0
        try:
            for filename in ("camera.txt","camera_input.txt","round_state.txt"):
                if not (self.root/"match"/filename).is_file():
                    raise ValueError("경기/세션 리플레이와 로그 경로를 확인하세요. 없는 파일: "+filename)
            while True:
                try:
                    if self.ensure_window_visible and time.monotonic()-visible_at>=.5:
                        visible_at=time.monotonic()
                        self.ensure_window_visible()
                    if not self.step(time.monotonic()):
                        break
                    read_failed_at = None
                except CameraReadPending:
                    now = time.monotonic()
                    if read_failed_at is None:
                        read_failed_at = now
                    if now-read_failed_at > .4:
                        raise
                if time.monotonic()-metrics_at >= 10:
                    logging.info("CAMERA_DIRECTOR_HEARTBEAT state=%s reason=%s candidate_used=%s",self.state,self.last_reason,self.used)
                    metrics_at = time.monotonic()
                # Cancellation still needs bounded release/exit observations.
                time.sleep(1/60)
        except Exception as exc:
            logging.warning("CAMERA_DIRECTOR_FAULT state=%s detail=%s",self.state,exc)
            DIAG.record('camera_director_fault',state=self.state,detail=str(exc))
            self.notify("자동 연출 중지: "+str(exc))
        finally:
            self.camera.freeze()
            if self.camera.last_output is not None:
                try:
                    restore_head_flags(self.root,expected=self.camera.last_output)
                except Exception:
                    logging.exception("CAMERA_DIRECTOR_HEAD_RESTORE_FAIL")
            self.camera.stop()

    def describe(self):
        labels = {"waiting":"대기", "priority_or_signal":"다운·리포트·리플레이 우선 또는 감지 신호 대기",
                  "not_fight":"경기 중 아님", "cooldown":"다음 연출까지 간격 유지",
                  "no_fresh_combo":f"새 {self.min_hits}연타 이상 공격 흐름 대기", "partial_pose":"머리 로그 갱신 중",
                  "head_log_stale":"머리 로그 지연", "too_close":"선수 사이가 너무 가까움",
                  "too_far":"선수 사이가 너무 멂", "rapid_motion":"급격한 움직임 진정 대기",
                  "stability_check":"시점 안정 확인 중", 'counter_wait_followup':'카운터 후 실제 후속타 대기',
                  'shot_score_low':'시야·반복 컷 점수 부족', 'same_flow':'같은 공격 흐름 재전환 방지',
                  'opponent_reply':'상대 반격으로 후보 취소', 'prepare_cancelled':'준비 중 흐름·시야 변화로 취소',
                  'glove_obstruction':'글러브가 시야를 가릴 가능성', 'flow_ended':'공격 흐름 종료',
                  'unsafe_view_exit':'불안정한 시야로 복귀',
                  'view_tracking_partial':'좌표 불완전 상태 지속으로 복귀',
                  'view_tracking_stale':'머리 좌표 갱신 중단으로 복귀',
                  'view_tracking_output':'카메라 출력 이상 지속으로 복귀',
                  'view_tracking_jump':'카메라 좌표의 큰 도약으로 복귀',
                  'view_distance_close':'선수 시점이 지나치게 밀착되어 복귀',
                  'view_distance_far':'선수 간격이 크게 벌어져 복귀',
                  'view_camera_motion':'실제 카메라의 심한 움직임 지속으로 복귀',
                  'view_view_unknown':'시야 검사 불확실 상태 지속으로 복귀',
                  'coverage_budget':'선수 시점 비중 조절 · 일반 화면 유지',
                  'entry_priority_cancelled':'전환 중 다운·우선 상황 발생으로 취소',
                  'broadcast_wait':'좋은 사건·구도 대기',
                  'scenic_view_wait':'공방 시점에 적합한 구도 대기',
                  'duration_complete':'설정 유지시간 완료'}
        states = {'prepare':'첫 정상 좌표·카메라 저장 대기 · 아직 F6 입력 전',
                  "probe":"시점 준비 / 기존 파일 카메라 여부 확인", "enter":"F6 전환 확인 중",
                  "active":"선수 시점 재생 중", "release_write":"머리 숨김 해제 저장 중",
                  "release":"머리 복구 후 복귀 준비", "off_wait":"일반 카메라 복귀 확인 중"}
        if self.state == "idle":
            wait = max(0, self.next_cut-time.monotonic())
            previous=(' · 이전 복귀: '+labels.get(self.last_cut_reason,self.last_cut_reason)) if self.last_cut_reason else ''
            return "자동 연출 대기 · "+labels.get(self.last_reason,self.last_reason)+(f" · {wait:.0f}초" if wait > 0 else "")+previous
        kind={'counter_followup':'카운터 후속타','pressure_support':'짧은 연타 공방','scenic':'좋은 구도 · 공방 시점'}.get(getattr(self,'prepared',{}).get('kind'),'공격 흐름')
        return "자동 연출 · "+states.get(self.state,self.state)+(' · '+kind if self.state=='active' else '')


def feed_camera_director(app, data):
    """Nonblocking MainApp hook; no I/O or input injection on the UI thread."""
    from PyQt6.QtWidgets import QApplication
    qapp = QApplication.instance()
    service = getattr(qapp,"_rfc_head_camera",None)
    director = getattr(service,"director",None)
    if not director or not director.thread or not director.thread.is_alive():
        return
    overlay = app.__dict__.get("browser_overlay")
    state = getattr(overlay,"_state",{}) if overlay is not None else {}
    busy = bool(app.__dict__.get("_potm_presentation_active") or state.get("obsReplayActive")
                or state.get("roundReport") or state.get("matchReport"))
    director.feed.update(data,busy=busy)
