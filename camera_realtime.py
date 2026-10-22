"""Latest-only camera collection/publication, independently paced from the UI."""
import collections
import ctypes
import math
import os
from pathlib import Path
import threading
import time
import logging


class FramePacer:
    def __init__(self, hz=60):
        self.period = 1/float(hz)
        self.deadline = time.monotonic()
        self.handle = None
        if os.name == "nt":
            try:
                kernel = ctypes.WinDLL("kernel32",use_last_error=True)
                kernel.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong]
                kernel.CreateWaitableTimerExW.restype = ctypes.c_void_p
                kernel.SetWaitableTimer.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_longlong),ctypes.c_long,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p,ctypes.c_ulong]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                self.kernel = kernel
                self.handle = kernel.CreateWaitableTimerExW(None,None,2,0x1F0003)
            except (AttributeError,OSError):
                self.handle = None

    def remaining(self, now):
        self.deadline += self.period
        if now >= self.deadline:
            # Late work does not incur an additional full-frame sleep, and no
            # queued old frames are replayed in a catch-up loop.
            self.deadline = now
            return 0
        return self.deadline-now

    def wait(self, cancel):
        delay = self.remaining(time.monotonic())
        if delay <= 0 or cancel.is_set():
            return
        if self.handle:
            due = ctypes.c_longlong(-max(1,int(delay*10_000_000)))
            if self.kernel.SetWaitableTimer(self.handle,ctypes.byref(due),0,None,None,False):
                self.kernel.WaitForSingleObject(self.handle,int(delay*1000)+20)
                return
        cancel.wait(delay)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class CameraPipeline:
    """One collector + one publisher, one immutable latest packet, no queue."""
    def __init__(self, camera):
        self.camera = camera
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.packet = None
        self.error = None
        self.ready = threading.Event()
        self.collector = threading.Thread(target=self._collect,daemon=True,name="CameraPoseCollector")
        self.publisher = threading.Thread(target=self._publish,daemon=True,name="CameraPosePublisher")
        self.output_gaps = collections.deque(maxlen=600)
        self.frame_ticks = 0
        self.started = time.monotonic()
        self.last_success = None
        self.initial_writes = camera.writes
        self.timer_backend = "starting"
        self.write_failures = 0
        self.same_frames = 0
        self.last_write_error = ""

    def start(self):
        self.collector.start()
        self.publisher.start()

    def stop(self):
        self.cancel.set()
        for thread in (self.collector,self.publisher):
            if thread is not threading.current_thread():
                thread.join(timeout=.5)
                if thread.is_alive():
                    raise RuntimeError("카메라 수집/출력 작업이 종료되는 중입니다. 잠시 후 다시 시도하세요.")
        logging.info("SPECTATOR_CAMERA_PIPELINE_SUMMARY side=%s metrics=%s",self.camera.side,self.metrics())

    def _fail(self, error):
        self.error = error
        self.cancel.set()

    def _collect(self):
        from spectator_camera import pose_to_camera
        pacer = FramePacer(120)
        last_stamp = None
        last_timeline = None
        replay_previous = None
        failed_at = None
        timeline_checked, timeline = 0, ("",None)
        replay_jump = False
        epoch = 0
        try:
            while not self.cancel.is_set():
                try:
                    now = time.monotonic()
                    c = self.camera
                    options = dict(c.options)
                    side, root = c.side, c.root
                    source = root/side/"head_position.txt"
                    stat = source.stat()
                    oldest = stat.st_mtime
                    other_stamp, other_text = None,None
                    other = None
                    if options.get("look_opponent"):
                        other = root/("red" if side == "blue" else "blue")/"head_position.txt"
                        other_stat = other.stat()
                        other_stamp = other_stat.st_mtime_ns
                        oldest = min(oldest,other_stat.st_mtime)
                    if time.time()-oldest > 3:
                        raise RuntimeError("머리 로그가 3초 이상 갱신되지 않아 전달을 중지합니다.")
                    if now-timeline_checked >= .05:
                        round_file, replay_file = root/"match/round_number.txt",root/"match/replay_state.txt"
                        round_value = round_file.read_text().strip() if round_file.exists() else ""
                        replay = replay_file.read_text().split() if replay_file.exists() else []
                        # Ignore transient truncation rather than inventing a
                        # round/seek transition on an empty sample.
                        if not round_file.exists() or round_value:
                            timeline = (round_value,replay[6] if len(replay) >= 7 else timeline[1])
                        if len(replay) >= 2:
                            replay_time = float(replay[1])
                            if not math.isfinite(replay_time):
                                raise ValueError("리플레이 시간이 올바르지 않습니다.")
                            if replay_previous:
                                delta = replay_time-replay_previous[0]
                                replay_jump |= delta < -.05 or delta > max(.5,(now-replay_previous[1])*4+.25)
                            replay_previous = (replay_time,now)
                        timeline_checked = now
                    stamp = (stat.st_mtime_ns,other_stamp,tuple(sorted(options.items())),timeline)
                    if stamp != last_stamp or replay_jump:
                        params = {k:v for k,v in options.items() if k not in ("look_opponent","position_ms","rotation_ms","comfort")}
                        if other is not None:
                            params["target_text"] = other.read_text(encoding="utf-8-sig")
                        output = pose_to_camera(source.read_text(encoding="utf-8-sig"),side,**params)
                        fields = output.split("\t")
                        pose = tuple(float(v) for v in (fields[0]+" "+fields[1]).split())
                        reset = timeline != last_timeline or replay_jump
                        if reset:
                            epoch += 1
                        # Keep discontinuity generation in every later packet;
                        # latest-only delivery must not lose a one-frame reset.
                        stamp = stamp+(epoch,)
                        packet = (stamp,pose,now,oldest,options,reset)
                        with self.lock:
                            self.packet = packet
                        if c.last_input_at is not None:
                            gap = (now-c.last_input_at)*1000
                            c.input_gap_sum_ms += gap
                            c.max_input_gap_ms = max(c.max_input_gap_ms,gap)
                        c.samples += 1
                        c.last_input_at = now
                        last_stamp, last_timeline, replay_jump = stamp[:-1],timeline,False
                        self.ready.set()
                    failed_at = None
                except (OSError,ValueError):
                    now = time.monotonic()
                    if failed_at is None:
                        failed_at = now
                    if now-failed_at > 1:
                        raise
                pacer.wait(self.cancel)
        except Exception as exc:
            self._fail(exc)
        finally:
            pacer.close()

    def _publish(self):
        from spectator_camera import CameraMotion
        motion = CameraMotion()
        pacer = FramePacer(60)
        self.timer_backend = "windows_high_resolution" if pacer.handle else "event_wait"
        last_stamp, failed_at, target_checked = None,None,0
        try:
            while not self.cancel.is_set():
                with self.lock:
                    packet = self.packet
                if packet is not None:
                    stamp,pose,arrived_at,source_at,options,reset = packet
                    now = time.monotonic()
                    if time.time()-source_at > 3:
                        raise RuntimeError("유효한 머리 데이터가 오래되어 출력을 중지합니다.")
                    if stamp != last_stamp:
                        motion.aim(pose,arrived_at,reset=reset or (last_stamp is not None and stamp[-1] != last_stamp[-1]),comfort=options.get("comfort",False))
                        last_stamp = stamp
                    current = motion.sample(now,options.get("position_ms",20),options.get("rotation_ms",40),comfort=options.get("comfort",False))
                    c = self.camera
                    output = c.separator.join((" ".join(f"{v:.3f}" for v in current[:3]),
                                               " ".join(f"{v:.6f}" for v in current[3:7]),
                                               f"{float(options.get('fov',75)):.2f}",str(c.side == "blue"),str(c.side == "red")))
                    force = False
                    # Don't stat the output and re-open timeline files every
                    # publication. Periodically detect an external game reset.
                    if now-target_checked >= .25:
                        force = (c.root/"match/camera_input.txt").stat().st_mtime_ns != getattr(c,"last_target_stamp",None)
                        target_checked = now
                    try:
                        if force or output != c.last_output:
                            c._write_output(output,timeout=.002)
                            at = time.monotonic()
                            if self.last_success is not None:
                                self.output_gaps.append((at-self.last_success)*1000)
                            self.last_success = at
                        else:
                            self.same_frames += 1
                        failed_at = None
                    except (OSError,ValueError) as exc:
                        self.write_failures += 1
                        self.last_write_error = repr(exc)
                        # Drop this frame, not the newest target. Never spend
                        # 150ms retrying an obsolete publication.
                        if failed_at is None:
                            failed_at = now
                        if now-failed_at > 1:
                            raise
                    self.frame_ticks += 1
                    c.last_sample_age_ms = max(0,(time.time()-source_at)*1000)
                pacer.wait(self.cancel)
        except Exception as exc:
            self._fail(exc)
        finally:
            pacer.close()

    def metrics(self):
        elapsed = max(.001,time.monotonic()-self.started)
        gaps = sorted(self.output_gaps)
        return {"tick_hz":self.frame_ticks/elapsed,"write_hz":(self.camera.writes-self.initial_writes)/elapsed,"timer_backend":self.timer_backend,
                "write_failures":self.write_failures,"unchanged_frames":self.same_frames,"last_write_error":self.last_write_error,
                "gap_max_ms":max(gaps,default=0),"gap_p95_ms":gaps[min(len(gaps)-1,int(len(gaps)*.95))] if gaps else 0}
