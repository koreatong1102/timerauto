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


class DirectorFeed:
    """Latest opportunity only; dedupe fast/full UI passes without replaying history."""
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None
        self.blocked_until = 0
        self.busy = False
        self.at = 0
        self.seen = collections.OrderedDict()

    def update(self, data, busy=False, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self.at, self.busy = now, busy
            if any(data.get(k) for k in ("spectator_round_report", "spectator_round_reports", "spectator_winner", "spectator_scorecard", "vs_intro_event", "round_intro_event")):
                self.blocked_until = max(self.blocked_until,now+2)
            for event in data.get("spectator_effect_events") or []:
                if str(event.get("kind") or "").lower() in ("stun","knockdown","tko","ko"):
                    self.blocked_until = max(self.blocked_until,now+5)
                    self.latest = None
            for event in data.get("spectator_event_engine") or []:
                effect = str(event.get("effect_kind") or "").lower()
                if effect in ("stun","knockdown","tko","ko"):
                    self.blocked_until = max(self.blocked_until,now+5)
                    self.latest = None
                    continue
                key = str(event.get("event_id") or "")
                if not key or key in self.seen:
                    continue
                self.seen[key] = now
                while len(self.seen) > 256:
                    self.seen.popitem(last=False)
                side = event.get("side")
                if side in ("blue","red") and int(event.get("combo_hits") or 0) >= 2:
                    self.latest = {"side":side,"at":now,"id":key,"hits":int(event["combo_hits"])}

    def snapshot(self, now):
        with self.lock:
            valid = now-self.at <= 1 and not self.busy and now >= self.blocked_until
            candidate = dict(self.latest) if self.latest and now-self.latest["at"] <= .9 else None
            return valid, candidate


class AutoCameraDirector:
    def __init__(self, notify, toggle, on_return=None):
        self.notify, self.toggle = notify, toggle
        self.on_return = on_return
        self.feed = DirectorFeed()
        self.cancel = threading.Event()
        self.thread = None
        self.state = "idle"
        self.camera = HeadCamera()
        self.confirmed_on = False
        self.used = None
        self.realtime = True

    def start(self, root, options, duration=2, cooldown=12, min_hits=2):
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
        self.min_hits = max(2,min(10,int(min_hits)))
        self.cancel = threading.Event()
        self.state, self.confirmed_on, self.used = "idle", False, None
        self.mismatch = 0
        self.last_round_value, self.last_round_at = "", 0
        self.next_cut, self.stable_at, self.previous = 0, None, {}
        self.last_reason = "waiting"
        self.observed_stamp, self.matches = None, 0
        self.feed = DirectorFeed()
        self.thread = threading.Thread(target=self._run,daemon=True,name="AutoCameraDirector")
        self.thread.start()

    def stop(self):
        self.cancel.set()  # Worker performs its own ordered release/exit.

    def _state(self, value, now):
        logging.info("CAMERA_DIRECTOR_STATE from=%s to=%s",self.state,value)
        self.state, self.since = value, now
        self.observed_stamp, self.matches = None, 0

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
        try:
            return self._geometry_once(side,now)
        except (OSError,ValueError):
            self.geometry_reason = "partial_pose"
            return False

    def _geometry_once(self, side, now):
        values = []
        for corner in (side,"red" if side == "blue" else "blue"):
            path = self.root / corner / "head_position.txt"
            if time.time()-path.stat().st_mtime > .4:
                self.geometry_reason = "head_log_stale"
                return False
            row = [float(v) for v in path.read_text().split()]
            if len(row) != 9 or not all(math.isfinite(v) for v in row):
                self.geometry_reason = "partial_pose"
                return False
            values.append(row)
        distance = math.dist(values[0][2:5],values[1][2:5])
        if not .65 <= distance <= 4:
            self.geometry_reason = "too_close" if distance < .65 else "too_far"
            return False
        # Reject fast translation and sudden look-direction changes.
        opts = {k:v for k,v in self.options.items() if k not in ("look_opponent","position_ms","rotation_ms","comfort")}
        view = camera_pose(pose_to_camera(" ".join(map(str,values[0])),side,
                          target_text=" ".join(map(str,values[1])),**opts))
        previous = self.previous.get(side)
        self.previous[side] = (now,view)
        if previous:
            dt = now-previous[0]
            if 0 < dt < .3:
                dot = min(1,abs(sum(x*y for x,y in zip(view[3:7],previous[1][3:7]))))
                if math.dist(view[:3],previous[1][:3])/dt > 3 or math.degrees(2*math.acos(dot))/dt > 150:
                    self.geometry_reason = "rapid_motion"
                    return False
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
        if self.state == "idle":
            if self.cancel.is_set():
                return False
            if not valid or not live or now < self.next_cut or not candidate or candidate["id"] == self.used or candidate["hits"] < self.min_hits:
                self.last_reason = "priority_or_signal" if not valid else "not_fight" if not live else "cooldown" if now < self.next_cut else "no_fresh_combo"
                self.stable_at = None
                return True
            if not self._geometry(candidate["side"],now):
                self.last_reason = getattr(self,"geometry_reason","unsafe_or_stale_view")
                self.stable_at = None
                return True
            if self.stable_at is None or self.stable_at[0] != candidate["side"]:
                self.stable_at = (candidate["side"],now)
                return True
            if now-self.stable_at[1] < .08:
                self.last_reason = "stability_check"
                return True
            self.used = candidate["id"]
            self.camera.start(self.root,candidate["side"],realtime=self.realtime,**self.options)
            if not self.camera.last_output:
                raise ValueError("시점 준비에 실패했습니다.")
            self._state("probe",now)
            return True
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
                    self.camera.freeze()
                    restore_head_flags(self.root,expected=self.camera.last_output)
                    self.camera.stop()
                    self.next_cut, self.stable_at = now+3,None
                    self._state("idle",now)
                    return True
                if now-self.since >= .12 and fresh:
                    if not candidate or candidate["side"] != self.camera.side:
                        self.camera.freeze()
                        restore_head_flags(self.root,expected=self.camera.last_output)
                        self.camera.stop()
                        self.next_cut, self.stable_at = now+3,None
                        self._state("idle",now)
                        return True
                    ok,detail = self.toggle()
                    logging.info("CAMERA_DIRECTOR_TOGGLE direction=enter ok=%s detail=%s",ok,detail)
                    if not ok:
                        raise ValueError("F6 입력 실패: "+str(detail))
                    self._state("enter",time.monotonic())
            elif self.state == "enter":
                if self.matches >= 2:
                    self.confirmed_on = True
                    self.mismatch = 0
                    self.bad_geometry_at = None
                    entered_at = self.since
                    self._state("active",now)
                    self.active_until = max(now,entered_at+self.duration)
                    self.notify("자동 연출: 선수 시점 · 유지 후 자동 복귀")
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
                if self._geometry(self.camera.side,now):
                    self.bad_geometry_at = None
                elif self.bad_geometry_at is None:
                    self.bad_geometry_at = now
                if self.cancel.is_set() or not valid or not live or now >= self.active_until or (self.bad_geometry_at is not None and now-self.bad_geometry_at > .12):
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
        try:
            for filename in ("camera.txt","camera_input.txt","round_state.txt"):
                if not (self.root/"match"/filename).is_file():
                    raise ValueError("경기/세션 리플레이와 로그 경로를 확인하세요. 없는 파일: "+filename)
            while True:
                try:
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
                  "no_fresh_combo":f"새 {self.min_hits}연타 이상 대기", "partial_pose":"머리 로그 갱신 중",
                  "head_log_stale":"머리 로그 지연", "too_close":"선수 사이가 너무 가까움",
                  "too_far":"선수 사이가 너무 멂", "rapid_motion":"급격한 움직임 진정 대기",
                  "stability_check":"시점 안정 확인 중"}
        states = {"probe":"시점 준비 / 기존 파일 카메라 여부 확인", "enter":"F6 전환 확인 중",
                  "active":"선수 시점 재생 중", "release_write":"머리 숨김 해제 저장 중",
                  "release":"머리 복구 후 복귀 준비", "off_wait":"일반 카메라 복귀 확인 중"}
        if self.state == "idle":
            wait = max(0, self.next_cut-time.monotonic())
            return "자동 연출 대기 · "+labels.get(self.last_reason,self.last_reason)+(f" · {wait:.0f}초" if wait > 0 else "")
        return "자동 연출 · "+states.get(self.state,self.state)


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
