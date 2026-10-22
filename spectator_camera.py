"""Opt-in head-follow file camera. Never injects keys or alters match verdicts."""
import math
import logging
import os
from pathlib import Path
import tempfile
import time
import threading


def replace_camera_file(staged, target, *, timeout=.15):
    """Windows readers can deny FILE_SHARE_DELETE for a frame. Retry rename,
    never truncate the live input and never retry forever on real ACL denial.
    """
    deadline = time.monotonic()+timeout
    attempts = 0
    while True:
        try:
            os.replace(staged,target)
            if attempts:
                logging.debug("CAMERA_FILE_LOCK_RECOVERED attempts=%s path=%s",attempts,target)
            return
        except OSError as exc:
            shared = isinstance(exc,PermissionError) or getattr(exc,"winerror",None) in (5,32,33)
            if not shared or time.monotonic() >= deadline:
                raise
            attempts += 1
            time.sleep(.003)


class CameraMotion:
    """Latest-goal damping, no backlog and no extrapolation of stale samples."""
    def __init__(self):
        self.current = None
        self.goal = None
        self.last_step = None
        self.last_input = None

    def aim(self, pose, now, *, reset=False, comfort=False):
        distance = math.dist(pose[:3], self.goal[:3]) if self.goal else 0
        if self.current is None or (not comfort and (reset or distance > 1.0 or (self.last_input is not None and now-self.last_input > .25))):
            self.current = list(pose)
            self.last_step = now
        self.goal = list(pose)
        self.last_input = now

    def sample(self, now, position_ms=20, rotation_ms=40, *, comfort=False):
        if self.current is None:
            return None
        dt = min(.1, max(0, now - self.last_step))
        self.last_step = now
        def alpha(ms):
            return 1.0 if ms <= 0 else 1-math.exp(-dt/(ms/1000))
        p, r = alpha(max(60,position_ms) if comfort else position_ms), alpha(max(100,rotation_ms) if comfort else rotation_ms)
        displacement = [(self.goal[i]-self.current[i])*(alpha(max(140,position_ms)) if comfort and i == 1 else p) for i in range(3)]
        if comfort:
            # Bound movement even when a log sample jumps; never catch up in a
            # single frame after a stall. Vertical bob gets stronger damping.
            length = math.sqrt(sum(v*v for v in displacement))
            scale = min(1,2*dt/max(length,1e-12))
            displacement = [v*scale for v in displacement]
            displacement[1] = max(-.8*dt,min(.8*dt,displacement[1]))
        for i in range(3):
            self.current[i] += displacement[i]
        a, b = self.current[3:7], self.goal[3:7]
        dot = sum(x*y for x, y in zip(a, b))
        if dot < 0:
            b = [-v for v in b]
            dot = -dot
        if comfort:
            angle = 2*math.acos(max(-1,min(1,dot)))
            r = min(r,math.radians(120)*dt/max(angle,1e-12))
        if dot > .9995:
            q = [x+(y-x)*r for x,y in zip(a,b)]
        else:
            angle = math.acos(max(-1, min(1, dot)))
            q = [(math.sin((1-r)*angle)*x+math.sin(r*angle)*y)/math.sin(angle) for x,y in zip(a,b)]
        norm = math.sqrt(sum(v*v for v in q))
        self.current[3:7] = [v/norm for v in q]
        return self.current


def pose_to_camera(text, side, fov=75.0, forward_cm=0.0, yaw=0.0, pitch=0.0, separator="\t", target_text=None):
    if side not in ("blue", "red"):
        raise ValueError("선수는 blue 또는 red여야 합니다.")
    values = [float(v) for v in text.split()]
    if len(values) != 9 or not all(math.isfinite(v) for v in values):
        raise ValueError("머리 위치 파일이 완전하지 않습니다.")
    x, y, z = values[2:5]
    q = values[5:9]
    norm = math.sqrt(sum(v*v for v in q))
    if norm < .5 or norm > 1.5:
        raise ValueError("머리 회전값이 올바르지 않습니다.")
    q = tuple(v/norm for v in q)
    if target_text is not None:
        target = [float(v) for v in target_text.split()]
        if len(target) != 9 or not all(math.isfinite(v) for v in target):
            raise ValueError("상대 머리 위치 파일이 완전하지 않습니다.")
        dx, dy, dz = (target[i+2] - values[i+2] for i in range(3))
        horizontal = math.hypot(dx, dz)
        if horizontal < .01:
            raise ValueError("상대와 카메라 위치가 겹칩니다.")
        # Camera +Z looks toward opponent, +Y stays upright. This deliberately
        # does not pretend the skeletal head quaternion is headset gaze.
        a = math.atan2(dx, dz)/2
        b = -math.atan2(dy, horizontal)/2
        q = (math.cos(a)*math.sin(b), math.sin(a)*math.cos(b),
             -math.sin(a)*math.sin(b), math.cos(a)*math.cos(b))
    fov, forward_cm, yaw, pitch = map(float, (fov, forward_cm, yaw, pitch))
    if not all(math.isfinite(v) for v in (fov, forward_cm, yaw, pitch)) or not 30 <= fov <= 120 or abs(forward_cm) > 30 or abs(yaw) > 180 or abs(pitch) > 90:
        raise ValueError("카메라 보정 범위를 벗어났습니다.")
    def mul(a, b):
        ax, ay, az, aw = a; bx, by, bz, bw = b
        return (aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz)
    a, b = math.radians(yaw)/2, math.radians(pitch)/2
    q = mul(q, mul((0, math.sin(a), 0, math.cos(a)), (math.sin(b), 0, 0, math.cos(b))))
    qx, qy, qz, qw = q
    distance = forward_cm / 100.0
    x += 2*(qx*qz+qw*qy)*distance
    y += 2*(qy*qz-qw*qx)*distance
    z += (1-2*(qx*qx+qy*qy))*distance
    return separator.join((f"{x:.3f} {y:.3f} {z:.3f}", " ".join(f"{v:.6f}" for v in q),
                           f"{fov:.2f}", str(side == "blue"), str(side == "red")))


class HeadCamera:
    def __init__(self):
        self.pipeline = None
        self.staging_path = None
        self.side = None
        self.root = None
        self.last_stamp = None
        self.writes = 0
        self.options = {}
        self.separator = "\t"
        self.invalid_since = None
        self.motion = CameraMotion()
        self.last_output = None
        self.timeline = None
        self.samples = 0
        self.max_input_gap_ms = 0
        self.input_gap_sum_ms = 0
        self.last_input_at = None
        self.last_sample_age_ms = 0
        self.last_write_ms = 0
        self.replay_previous = None
        self.pending_reset = False

    def start(self, root, side, *, realtime=False, **options):
        self.stop()
        root = Path(root).resolve()
        if root.name.lower() == "match":
            root = root.parent
        if side not in ("blue", "red") or not (root / "match" / "camera_input.txt").is_file():
            raise ValueError("현재 경기의 camera_input.txt가 없습니다. 로그 경로를 확인하고 경기/리플레이를 여세요.")
        text = (root / "match" / "camera_input.txt").read_text(encoding="utf-8-sig")
        # Some spectator builds serialize literal backslash-t separators.
        self.separator = "\\t" if "\\t" in text and "\t" not in text else "\t"
        self.root, self.side, self.options = root, side, dict(options)
        try:
            self.tick()
            if realtime:
                from camera_realtime import CameraPipeline
                self.pipeline = CameraPipeline(self)
                self.pipeline.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        # Stop writing, not the game's mode. F6 returns to normal cameras.
        self.freeze()
        self.side = None
        self.last_stamp = None
        self.writes = 0
        self.invalid_since = None
        self.motion = CameraMotion()
        self.last_output = None
        self.timeline = None
        self.samples = 0
        self.max_input_gap_ms = 0
        self.input_gap_sum_ms = 0
        self.last_input_at = None
        self.replay_previous = None
        self.pending_reset = False

    def freeze(self):
        """Join publishers before releasing head flags or handing off ownership."""
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
        if self.staging_path:
            try:
                Path(self.staging_path).unlink(missing_ok=True)
            except OSError:
                logging.debug("CAMERA_STAGE_CLEANUP_PENDING path=%s",self.staging_path)
            self.staging_path = None

    def tick(self):
        if self.pipeline is not None:
            if self.pipeline.error is not None:
                raise self.pipeline.error
            return False  # Publication is independently paced, not caller-paced.
        try:
            result = self._tick_once()
            self.invalid_since = None
            return result
        except StaleCameraLog:
            raise
        except (OSError, ValueError) as exc:
            # The game truncates/re-writes its output files. Retain the last
            # complete camera frame while a transient partial read is retried.
            now = time.monotonic()
            if self.invalid_since is None:
                self.invalid_since = now
            if now - self.invalid_since < 1.0:
                return False
            raise ValueError("로그 읽기/카메라 저장 실패가 1초 이상 지속됩니다: " + str(exc)) from exc

    def _tick_once(self):
        if not self.side:
            return False
        source = self.root / self.side / "head_position.txt"
        stat = source.stat()
        if time.time() - stat.st_mtime > 3.0:
            raise StaleCameraLog("머리 로그가 3초 이상 갱신되지 않아 추적을 중지합니다.")
        # Re-send after a game reset of camera_input.txt, even with a static head.
        target = self.root / "match" / "camera_input.txt"
        options = dict(self.options)
        position_ms = options.pop("position_ms", 0)
        rotation_ms = options.pop("rotation_ms", 0)
        look_opponent = options.pop("look_opponent", False)
        comfort = options.pop("comfort", False)
        other_stamp = None
        if look_opponent:
            opponent = self.root / ("red" if self.side == "blue" else "blue") / "head_position.txt"
            other = opponent.stat()
            if time.time() - other.st_mtime > 3.0:
                raise StaleCameraLog("상대 머리 로그가 3초 이상 갱신되지 않았습니다.")
            other_stamp = other.st_mtime_ns
            options["target_text"] = opponent.read_text(encoding="utf-8-sig")
        target_stamp = target.stat().st_mtime_ns
        stamp = (stat.st_mtime_ns, other_stamp, tuple(sorted(self.options.items())))
        now = time.monotonic()
        # Round/replay command changes invalidate the previous smoothing goal.
        round_file = self.root / "match" / "round_number.txt"
        replay_file = self.root / "match" / "replay_state.txt"
        round_value = round_file.read_text().strip() if round_file.exists() else ""
        replay = replay_file.read_text().split() if replay_file.exists() else []
        timeline = (round_value, replay[6] if len(replay) >= 7 else None)
        if len(replay) >= 2:
            replay_time = float(replay[1])
            if not math.isfinite(replay_time):
                raise ValueError("리플레이 시간이 올바르지 않습니다.")
            if self.replay_previous:
                previous_time, previous_at = self.replay_previous
                delta = replay_time-previous_time
                if delta < -.05 or delta > max(.5, (now-previous_at)*4+.25):
                    self.pending_reset = True
            self.replay_previous = (replay_time,now)
        else:
            self.replay_previous = None
        if stamp != self.last_stamp or timeline != self.timeline or self.pending_reset:
            output = pose_to_camera(source.read_text(encoding="utf-8-sig"), self.side,
                                    separator=self.separator, **options)
            fields = output.replace("\\t", "\t").split("\t")
            pose = [float(v) for v in (fields[0]+" "+fields[1]).split()]
            self.motion.aim(pose, now, reset=timeline != self.timeline or self.pending_reset, comfort=comfort)
            self.pending_reset = False
            if self.last_input_at is not None:
                gap = (now-self.last_input_at)*1000
                self.max_input_gap_ms = max(self.max_input_gap_ms, gap)
                self.input_gap_sum_ms += gap
            self.samples += 1
            self.last_input_at = now
            self.last_stamp, self.timeline = stamp, timeline
        pose = self.motion.sample(now, position_ms, rotation_ms, comfort=comfort)
        output = self.separator.join((" ".join(f"{v:.3f}" for v in pose[:3]),
                                      " ".join(f"{v:.6f}" for v in pose[3:7]),
                                      f"{float(options.get('fov',75)):.2f}", str(self.side == "blue"), str(self.side == "red")))
        self.last_sample_age_ms = max(0, (time.time()-stat.st_mtime)*1000)
        if output == self.last_output and target_stamp == getattr(self, "last_target_stamp", None):
            return False
        self._write_output(output)
        return True

    def _write_output(self, output, *, timeout=.15):
        target = self.root/"match/camera_input.txt"
        write_started = time.monotonic()
        if self.staging_path is None:
            fd,self.staging_path = tempfile.mkstemp(prefix="rfc_camera_",suffix=".tmp",dir=target.parent)
            os.close(fd)
        # Reuse our private staging pathname instead of generating/scanning a
        # brand-new pathname every frame. The live target is never truncated.
        with open(self.staging_path,"w",encoding="utf-8",newline="") as stream:
            stream.write(output)
        replace_camera_file(self.staging_path,target,timeout=timeout)
        self.last_write_ms = (time.monotonic()-write_started)*1000
        self.last_target_stamp = target.stat().st_mtime_ns
        self.last_output = output
        self.writes += 1


class StaleCameraLog(ValueError):
    pass


def restore_head_flags(root, *, expected=None):
    """Preserve the camera pose, explicitly release both head-hide flags."""
    root = Path(root).resolve()
    if root.name.lower() == "match":
        root = root.parent
    target = root / "match" / "camera_input.txt"
    text = target.read_text(encoding="utf-8-sig")
    if expected is not None and text != expected:
        return False  # Game reset/another controller owns this input now.
    separator = "\\t" if "\\t" in text and "\t" not in text else "\t"
    fields = text.replace("\\t", "\t").split("\t")
    if len(fields) < 3:
        raise ValueError("카메라 입력 형식을 확인할 수 없어 머리 복구값을 쓰지 않았습니다.")
    numbers = [float(v) for v in (fields[0]+" "+fields[1]+" "+fields[2]).split()]
    if len(numbers) != 8 or not all(math.isfinite(v) for v in numbers):
        raise ValueError("카메라 위치/회전값이 올바르지 않습니다.")
    output = separator.join(fields[:3]+["False", "False"])
    staged = None
    try:
        fd, staged = tempfile.mkstemp(prefix="rfc_camera_", suffix=".tmp", dir=target.parent)
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as stream:
            stream.write(output)
        replace_camera_file(staged,target)
        staged = None
    finally:
        if staged:
            os.unlink(staged)
    return True


class CameraWorker:
    """One bounded 60Hz file worker, independent of Qt's GUI event loop."""
    def __init__(self, camera, notify):
        self.camera, self.notify = camera, notify
        self.thread = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.options = {}

    def configure(self, **options):
        with self.lock:
            self.options.update(options)

    def stop(self):
        self.cancel.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=.5)
            if self.thread.is_alive():
                raise RuntimeError("카메라 파일 작업이 끝나는 중입니다. 잠시 후 다시 시도하세요.")

    def start(self, root, side, **options):
        self.stop()
        with self.lock:
            self.options = dict(options)
        self.cancel = threading.Event()
        cancel = self.cancel
        def run():
            try:
                if cancel.is_set():
                    return
                self.camera.start(root, side, realtime=True, **options)
                if cancel.is_set():
                    return
                self.notify(("블루" if side == "blue" else "레드") + " 추적 중 · 독립 60Hz 목표 출력 · F6 상태는 관전툴에서 확인하세요.")
                logging.info("SPECTATOR_HEAD_CAMERA_START side=%s root=%s options=%s", side, root, options)
                metrics_at = time.monotonic()
                started = metrics_at
                while not cancel.is_set():
                    with self.lock:
                        self.camera.options = dict(self.options)
                    self.camera.tick()
                    now = time.monotonic()
                    if now-metrics_at >= 10:
                        pipeline = self.camera.pipeline
                        metrics = pipeline.metrics() if pipeline else {}
                        logging.info("SPECTATOR_HEAD_CAMERA_METRICS samples=%s writes=%s input_gap_avg_ms=%.1f input_gap_max_ms=%.1f source_age_ms=%.1f write_ms=%.2f output_hz=%.1f tick_hz=%.1f gap_p95_ms=%.1f gap_max_ms=%.1f",
                                     self.camera.samples, self.camera.writes,
                                     self.camera.input_gap_sum_ms/max(1,self.camera.samples-1), self.camera.max_input_gap_ms,
                                     self.camera.last_sample_age_ms, self.camera.last_write_ms,
                                     metrics.get("write_hz",self.camera.writes/max(.001,now-started)),metrics.get("tick_hz",0),metrics.get("gap_p95_ms",0),metrics.get("gap_max_ms",0))
                        metrics_at = now
                    cancel.wait(.05)  # Supervisor only; cannot pace or block publication.
            except Exception as exc:
                logging.warning("SPECTATOR_HEAD_CAMERA_STOP detail=%s", exc)
                self.notify("추적 중지: " + str(exc) + " · F6으로 파일 카메라를 꺼주세요.")
            finally:
                self.camera.freeze()
                if self.camera.last_output is not None:
                    try:
                        restored = restore_head_flags(self.camera.root, expected=self.camera.last_output)
                        logging.info("SPECTATOR_HEAD_CAMERA_RELEASE_HEADS restored=%s", restored)
                    except Exception as exc:
                        logging.warning("SPECTATOR_HEAD_CAMERA_RELEASE_FAIL detail=%s",exc)
                        self.notify("머리 숨김 해제 파일 저장 실패: " + str(exc) + " · 머리 표시 복구 버튼으로 다시 시도하세요.")
                self.camera.stop()
        self.thread = threading.Thread(target=run, daemon=True, name="SpectatorHeadCamera")
        self.thread.start()


def create_camera_panel(cfg, parent=None, toggle=None, on_return=None):
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QWidget, QFormLayout, QLabel, QDoubleSpinBox, QPushButton, QHBoxLayout, QComboBox, QCheckBox
    app = QApplication.instance()
    # One writer per app; it survives closing/reopening Settings.
    service = getattr(app, "_rfc_head_camera", None)
    if service is None:
        class Service(QObject):
            status = pyqtSignal(str)
            def __init__(self):
                super().__init__(app)
                self.camera = HeadCamera()
                self.worker = CameraWorker(self.camera, self.report)
                self.director = None
                self.message = "중지 상태 · 파일 카메라를 아직 제어하지 않습니다."
                self.timer = QTimer(self)
                self.timer.setInterval(500)  # UI status only, no file I/O.
                self.timer.timeout.connect(self.tick)
                app.aboutToQuit.connect(self.shutdown)
            def report(self, text):
                self.message = text
                self.status.emit(text)
            def stop(self):
                self.timer.stop()
                if self.director and self.director.thread and self.director.thread.is_alive():
                    self.director.stop()
                    self.report("자동 연출 복귀 중 · 일반 카메라 복귀 확인까지 잠시 기다려주세요.")
                    return
                try:
                    self.worker.stop()
                except RuntimeError as exc:
                    self.report(str(exc))
                    return
                self.report("추적 중지 · 파일 카메라가 켜진 상태에서 머리 표시를 확인한 뒤 F6을 끄세요. 이미 껐다면 잠깐 켰다가 다시 꺼주세요.")
            def tick(self):
                if self.director and self.director.thread and self.director.thread.is_alive():
                    text = self.director.describe()
                    pipeline = self.director.camera.pipeline
                    if pipeline is not None:
                        text += f" · 파일 갱신 {pipeline.metrics()['write_hz']:.1f}Hz"
                    self.report(text)
                    return
                if self.director and self.director.thread:
                    self.timer.stop()
                if self.worker.thread and not self.worker.thread.is_alive():
                    self.timer.stop()
                elif self.camera.pipeline is not None:
                    metrics = self.camera.pipeline.metrics()
                    self.report(("블루" if self.camera.side == "blue" else "레드") +
                                f" 추적 · 출력 루프 {metrics['tick_hz']:.1f}Hz / 파일 갱신 {metrics['write_hz']:.1f}Hz · 같은 값은 저장 생략")
            def shutdown(self):
                self.timer.stop()
                if self.director:
                    self.director.stop()
                    if self.director.thread:
                        self.director.thread.join(timeout=4.5)
                try:
                    self.worker.stop()
                except RuntimeError:
                    logging.warning("SPECTATOR_CAMERA_SHUTDOWN_PENDING")
        service = Service()
        app._rfc_head_camera = service
    panel = QWidget(parent)
    layout = QFormLayout(panel)
    from camera_director import AutoCameraDirector
    if service.director is None and toggle is not None:
        service.director = AutoCameraDirector(service.report,toggle,on_return=on_return)
    note = QLabel("① 경기 또는 관전툴 세션 리플레이 열기 → ② 블루/레드 추적 시작 → ③ 관전툴 창에서 F6으로 파일 카메라 켜기\n"
                  "종료: 먼저 추적 중지 → 머리 표시 복구 확인 → F6 끄기. 이미 일반 카메라로 돌아왔다면 ‘머리 표시 복구’ 후 F6을 잠깐 켰다가 끄세요.\n"
                  "설정창을 닫아도 추적은 계속됩니다. 타이머를 종료하면 값 전달이 중지됩니다.\n"
                  "머리 모델의 회전과 실제 시선이 다를 수 있습니다. 우선 녹화된 경기에서 시험하고 아래 보정값을 조절하세요.")
    note.setWordWrap(True)
    layout.addRow(note)
    mode = QComboBox()
    mode.addItem("상대 바라보기 · 수평 유지 (기본)", True)
    mode.addItem("머리 회전 원본 · 방향 보정 필요할 수 있음", False)
    mode.setCurrentIndex(0 if service.worker.options.get("look_opponent", True) else 1)
    mode.currentIndexChanged.connect(lambda _: service.worker.configure(look_opponent=mode.currentData()))
    layout.addRow("시선 방식", mode)
    explanation = QLabel("기본 모드는 내 머리 위치에서 상대 머리를 바라봅니다. 실제 헤드셋 시선 복제는 아닙니다.\n"
                         "시청자 안정화 적용: 상하 흔들림 완화 · 이동/회전 속도 제한. 빠른 움직임에는 약간의 추적 지연이 생깁니다.\n"
                         "파일을 쓰는 순간 잠깐 비면 마지막 정상 화면을 유지하며 재시도합니다. 초기 값이 없으면 로그를 기다립니다.")
    explanation.setWordWrap(True)
    layout.addRow(explanation)
    controls = {}
    for key, label, lo, hi, default in (("fov", "시야각", 30, 120, 75), ("forward_cm", "눈 방향 앞뒤 보정(cm)", -30, 30, 0),
                                       ("yaw", "좌우 방향 보정(도)", -180, 180, 0), ("pitch", "위아래 방향 보정(도)", -90, 90, 0),
                                       ("position_ms", "위치 부드러움(ms) · 낮을수록 빠른 반응", 0, 100, 20),
                                       ("rotation_ms", "회전 부드러움(ms) · 낮을수록 빠른 반응", 0, 150, 40)):
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(service.worker.options.get(key, default))
        controls[key] = spin
        layout.addRow(label, spin)
        spin.valueChanged.connect(lambda value, k=key: service.worker.configure(**{k: value}))
    buttons = QHBoxLayout()
    status = QLabel(service.message)
    status.setWordWrap(True)
    service.status.connect(status.setText)
    def start(side):
        service.stop()
        if service.director and service.director.thread and service.director.thread.is_alive():
            return
        try:
            service.worker.start(getattr(cfg, "spectatorlog_path", ""), side,
                                 look_opponent=mode.currentData(), comfort=True,
                                 **{k: v.value() for k, v in controls.items()})
            service.timer.start()
        except Exception as exc:
            service.report("시작 실패: " + str(exc))
    for label, callback in (("블루 시점 추적", lambda: start("blue")), ("레드 시점 추적", lambda: start("red")), ("추적 중지", service.stop)):
        button = QPushButton(label)
        button.clicked.connect(callback)
        buttons.addWidget(button)
    def restore():
        service.stop()
        if service.director and service.director.thread and service.director.thread.is_alive():
            return
        if service.worker.thread and service.worker.thread.is_alive():
            return
        def run_restore():
            try:
                restore_head_flags(getattr(cfg,"spectatorlog_path",""))
                service.report("양쪽 머리 숨김 해제값 전달 완료 · F6이 꺼져 있었다면 잠깐 켰다가 머리가 복구된 뒤 다시 끄세요.")
            except Exception as exc:
                service.report("머리 표시 복구 실패: " + str(exc))
        # Same worker slot: a subsequent Start must wait for this write too.
        service.worker.thread = threading.Thread(target=run_restore,daemon=True,name="SpectatorHeadRestore")
        service.worker.thread.start()
    restore_button = QPushButton("머리 표시 복구")
    restore_button.clicked.connect(restore)
    layout.addRow(restore_button)
    layout.addRow(buttons)
    auto_note = QLabel("자동 연출(시험): F6 파일 카메라를 먼저 끄고 시작하세요. 연타 중 안정된 거리/방향에서만 잠깐 선수 시점으로 전환합니다.\n"
                       "일반 카메라 복귀가 관측되면 F4를 한 번 누릅니다. F4는 토글이며 켜짐 상태를 직접 확인할 수는 없습니다.\n"
                       "F6 기본 키가 관전툴에 설정되어 있어야 합니다. 전환 때 관전툴 창을 잠깐 활성화하고 원래 창으로 돌아옵니다.\n"
                       "자동 연출 중 F6/카메라를 수동 변경하지 마세요. 실제 카메라 로그로 전환을 관측하지만 내부 모드의 확정 신호는 아닙니다.\n"
                       "확인 실패 시 토글을 반복하지 않고 중지합니다. 머리 표시/F6 상태를 직접 확인해야 할 수 있습니다. 앱 재시작 시 자동으로 켜지지 않습니다.")
    auto_note.setWordWrap(True)
    layout.addRow(auto_note)
    auto_controls = {}
    for key,label,lo,hi,default in (("duration","1인칭 유지(초)",1,3,2), ("cooldown","복귀 후 최소 간격(초) · 0은 대기 없음",0,120,12), ("min_hits","발동 최소 연타 수",2,10,2)):
        spin = QDoubleSpinBox()
        spin.setDecimals(1 if key == "duration" else 0)
        spin.setRange(lo,hi); spin.setValue(default)
        auto_controls[key] = spin
        layout.addRow(label,spin)
    confirmation = QCheckBox("F6 파일 카메라가 꺼져 있고 일반 카메라인 것을 확인했습니다")
    layout.addRow(confirmation)
    auto_buttons = QHBoxLayout()
    arm = QPushButton("자동 연출 시작")
    disarm = QPushButton("자동 연출 중지 / 복귀")
    def arm_auto():
        if not confirmation.isChecked():
            service.report("먼저 관전툴 F6 파일 카메라를 끄고 확인 체크를 켜주세요.")
            return
        if service.director is None:
            service.report("관전툴 단축키 연결이 없어 자동 연출을 사용할 수 없습니다.")
            return
        if service.director.thread and service.director.thread.is_alive():
            service.report("이미 자동 연출 중입니다. 먼저 중지/복귀하세요.")
            return
        try:
            service.worker.stop()
            service.director.start(getattr(cfg,"spectatorlog_path",""),
                                   {k:v.value() for k,v in controls.items()},
                                   **{k:v.value() for k,v in auto_controls.items()})
            service.timer.start()
            confirmation.setChecked(False)
        except Exception as exc:
            service.report("자동 연출 시작 실패: "+str(exc))
    arm.clicked.connect(arm_auto)
    disarm.clicked.connect(service.stop)
    auto_buttons.addWidget(arm); auto_buttons.addWidget(disarm)
    layout.addRow(auto_buttons)
    layout.addRow(status)
    return panel
