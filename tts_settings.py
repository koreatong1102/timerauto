"""Optional local TTS controls; probing uses a worker, never Qt's UI thread."""
import copy
import threading
import json
import time
import logging
import uuid
from pathlib import Path
from PyQt6.QtCore import pyqtSignal, QUrl, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QFormLayout, QHBoxLayout,
                            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton, QLabel, QCheckBox,
                            QMessageBox)
from app_paths import app_path
from local_tts import SPEAKERS, check_server, commentary_voice
from qwen_duo_setup import DuoSetupJob, PROFILE_ID, profile_ready, profile_revision


def _close_duo_job(holder):
    """Release only this control's worker; controller cleanup is non-blocking."""
    job = holder.pop("job", None)
    if job is not None:
        try:
            job.close()
        except Exception:
            logging.exception("QWEN_DUO_CLOSE_FAIL")


class TtsEngineControls(QGroupBox):
    changed = pyqtSignal()
    probe_finished = pyqtSignal(int, str)
    pack_progress = pyqtSignal(int, int, str)
    pack_finished = pyqtSignal(str)
    preview_requested = pyqtSignal(str)
    rehearsal_requested = pyqtSignal(list)
    rehearsal_stop_requested = pyqtSignal()
    duo_completed = pyqtSignal()

    def __init__(self, cfg, parent=None):
        super().__init__("해설 음성 엔진 · 선택 설치", parent)
        self.cfg = cfg
        self._probe_token = 0
        self._duo_job = None
        self._duo_applying = False
        self._duo_revision = ""
        self._selected_profile = ""
        self._duo_holder = {}
        self._duo_timer = QTimer(self)
        self._duo_timer.setInterval(400)
        self._duo_timer.timeout.connect(self._poll_duo)
        outer = QVBoxLayout(self)
        self.duo_build = QPushButton("한국어 남성 2인 해설팩 · 원클릭 완성")
        self.duo_build.setToolTip("목소리 설계 → 한국어 남성 캐스터/해설 팩 전체 제작 → 완료 후 자동 선택. 기존 팩은 보존합니다.")
        duo_buttons = QHBoxLayout()
        duo_buttons.addWidget(self.duo_build)
        self.duo_stop = QPushButton("자동 제작 중지")
        self.duo_stop.setEnabled(False)
        self.duo_stop.clicked.connect(self.stop_pack)
        duo_buttons.addWidget(self.duo_stop)
        outer.addLayout(duo_buttons)
        duo_note = QLabel("또렷하고 힘 있는 남성 캐스터 + 묵직하고 재치 있는 남성 해설자를 자동으로 준비합니다.\n"
            "실존 인물의 목소리를 복제하지 않는 독창적인 2인 음성입니다. 녹음·프롬프트 입력·서버 실행은 필요 없습니다.\n"
            "최초에는 수 GB 모델 다운로드와 긴 제작 시간이 필요합니다. 방송을 끈 뒤 시작하세요.\n"
            "중지/실패 시 기존 팩을 유지하며, 다시 누르면 완성한 문장부터 이어 만듭니다.")
        duo_note.setWordWrap(True)
        outer.addWidget(duo_note)
        self.duo_status = QLabel("완료되기 전에는 현재 사용 중인 목소리와 팩을 바꾸지 않습니다.")
        self.duo_status.setWordWrap(True)
        outer.addWidget(self.duo_status)
        self.engine = QComboBox()
        self.engine.addItem("Edge TTS · 기존 온라인 음성", "edge")
        self.engine.addItem("Qwen3-TTS · 내 컴퓨터에서 생성", "qwen3")
        outer.addWidget(self.engine)
        self.details = QWidget()
        layout = QFormLayout(self.details)
        self._voice_form = layout
        self.voice_profile = QComboBox()
        self.voice_profile.addItem("기존 Qwen 기본 목소리 · 수동 설정", "")
        self.voice_profile.addItem("한국어 남성 2인 · 원클릭 완성팩", PROFILE_ID)
        layout.addRow("사용할 음성팩", self.voice_profile)
        self.model = QComboBox()
        self.model.addItem("1.7B · 감정/말투 지시 지원", "1.7B")
        self.model.addItem("0.6B · 작은 모델, 감정 지시 미지원", "0.6B")
        layout.addRow("서버와 맞출 모델", self.model)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        layout.addRow("로컬 포트 · 기본 8768", self.port)
        self.language = QComboBox()
        for label, value in (("한국어", "Korean"), ("영어", "English"), ("자동", "Auto")):
            self.language.addItem(label, value)
        layout.addRow("읽을 언어", self.language)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(.7, 1.5)
        self.speed.setSingleStep(.05)
        self.speed.setDecimals(2)
        self.speed.setSuffix(" 배")
        layout.addRow("Qwen 읽는 배속", self.speed)
        self.speakers, self.instructions = {}, {}
        for role, label in (("caster", "캐스터"), ("analyst", "해설")):
            combo = QComboBox()
            for speaker in SPEAKERS:
                combo.addItem(speaker + (" · 한국어 여성" if speaker == "Sohee" else ""), speaker)
            layout.addRow(label + " 목소리", combo)
            instruction = QLineEdit()
            instruction.setMaxLength(500)
            instruction.setPlaceholderText("1.7B에서만 적용. 영어 또는 한국어로 말투를 지시")
            layout.addRow(label + " 말투", instruction)
            self.speakers[role], self.instructions[role] = combo, instruction
        note = QLabel("Qwen은 별도 설치가 필요합니다. 최초 모델 다운로드는 수 GB가 될 수 있습니다.\n"
            "① Qwen_환경설치.bat → ② Qwen_서버실행.bat → ③ 연결 확인 → ④ 위의 자동해설 TTS/듀오 테스트\n"
            "Sohee는 한국어 여성 기본 음성입니다. 남성 후보는 한국어 억양을 직접 들어보세요.\n"
            "위쪽 Edge 목소리·wpm·피치는 Qwen에 적용되지 않습니다. 해설 볼륨은 공통입니다.\n"
            "느린 생성은 지난 콜을 생략할 수 있습니다. 서버 중단 시 Edge로 자동 전환하지 않습니다.")
        note.setWordWrap(True)
        self.manual_note = note
        layout.addRow(note)
        buttons = QHBoxLayout()
        self.check = QPushButton("Qwen 연결 확인 · 소리 없음")
        help_button = QPushButton("설치·사용 설명")
        buttons.addWidget(self.check)
        buttons.addWidget(help_button)
        layout.addRow(buttons)
        self.status = QLabel("서버를 실행한 뒤 연결 확인을 눌러 주세요.")
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.pack_enabled = QCheckBox("실시간 해설은 준비된 해설팩만 재생 · 없는 멘트는 생략")
        self.pack_auto_names = QCheckBox("자동 닉네임 준비 · 경기 중 호명 생략으로 현재 사용 안 함")
        self.pack_auto_names.setEnabled(False)
        layout.addRow(self.pack_enabled)
        layout.addRow(self.pack_auto_names)
        self.pack_scope = QComboBox()
        for label, value in (("대표 시험팩 · 짧은 콜/코너명부터", "sample"),
                             ("기본 콜 팩 · 연타/급소/다운", "calls"),
                             ("전체 B급 팩 · 기본 콜+후속 멘트+듀오", "full"),
                             ("닉네임만 준비", "names")):
            self.pack_scope.addItem(label, value)
        layout.addRow("만들 해설팩", self.pack_scope)
        self.pack_names = QLineEdit()
        self.pack_names.setPlaceholderText("미리 만들 닉네임을 쉼표로 구분 · 예: 통, 현선호")
        layout.addRow("닉네임 미리 준비", self.pack_names)
        pack_buttons = QHBoxLayout()
        self.pack_build = QPushButton("팩 생성 / 이어 만들기")
        self.pack_stop = QPushButton("제작 중지")
        self.pack_preview = QPushButton("팩 즉시재생 · 캐스터+해설")
        self.pack_stop.setEnabled(False)
        for button in (self.pack_build, self.pack_stop, self.pack_preview):
            pack_buttons.addWidget(button)
        layout.addRow(pack_buttons)
        test_buttons = QHBoxLayout()
        self.pack_rehearsal = QPushButton("해설팩 종합 테스트 · 합성 없음")
        self.pack_rehearsal_stop = QPushButton("팩 테스트 중지")
        test_buttons.addWidget(self.pack_rehearsal)
        test_buttons.addWidget(self.pack_rehearsal_stop)
        layout.addRow(test_buttons)
        self.pack_rehearsal.clicked.connect(self.rehearse_pack)
        self.pack_rehearsal_stop.clicked.connect(self.rehearsal_stop_requested.emit)
        self.pack_status = QLabel("전체 팩은 수백 문장이라 수 시간이 걸릴 수 있습니다. 대표 시험팩부터 확인하세요.\n"
            "방송이 아닐 때 제작하세요. 완료된 파일은 재사용하며 중지는 현재 한 문장 완료 후 반영됩니다.\n"
            "팩 사용 체크는 직접 켜세요. 대표 시험팩에는 모든 멘트가 없어서 생략되는 콜이 많습니다.\n"
            "이 기능은 B급 고정 멘트용입니다. 수치 리포트/VS/POTM 안내와 위의 일반 TTS 테스트는 동적 합성입니다.")
        self.pack_status.setWordWrap(True)
        layout.addRow(self.pack_status)
        self._pack_cancel = threading.Event()
        self._pack_running = False
        self.pack_build.clicked.connect(self.build_pack)
        self.pack_stop.clicked.connect(self.stop_pack)
        self.pack_preview.clicked.connect(self.preview_pack)
        self.pack_progress.connect(self._pack_progress)
        self.pack_finished.connect(self._pack_finished)
        self.destroyed.connect(lambda *_args, event=self._pack_cancel: event.set())
        self.destroyed.connect(lambda *_args, holder=self._duo_holder: _close_duo_job(holder))
        self.duo_build.clicked.connect(self.build_duo)
        outer.addWidget(self.details)
        self.load(cfg)
        for widget in (self.engine, self.model, self.language, self.voice_profile, *self.speakers.values()):
            widget.currentIndexChanged.connect(self._changed)
        self.port.valueChanged.connect(self._changed)
        self.speed.valueChanged.connect(self._changed)
        self.pack_enabled.stateChanged.connect(self._changed)
        self.pack_auto_names.stateChanged.connect(self._changed)
        for widget in self.instructions.values():
            widget.textChanged.connect(self._changed)
        self.check.clicked.connect(self.probe)
        self.probe_finished.connect(self._probe_result)
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(app_path("LOCAL_TTS.md"))))
        self._refresh()

    def load(self, cfg):
        previous = self._duo_applying
        self._duo_applying = True
        try:
            self._load_fields(cfg)
        finally:
            self._duo_applying = previous
        self._refresh()

    def _load_fields(self, cfg):
        selected = getattr(cfg, "spectator_qwen_duo_profile", "")
        revision = getattr(cfg, "spectator_qwen_duo_revision", "")
        complete = profile_ready(PROFILE_ID, revision=revision or None)
        self._duo_revision = revision or (profile_revision(PROFILE_ID) if complete else "")
        self.voice_profile.model().item(1).setEnabled(complete)
        # A damaged/missing file must not silently replace an already chosen
        # original voice with the old Sohee/Ryan presets when settings opens.
        self.voice_profile.setCurrentIndex(1 if selected == PROFILE_ID else 0)
        self._selected_profile = self.voice_profile.currentData()
        if selected == PROFILE_ID and not complete:
            self.duo_status.setText("선택한 남성 2인 팩이 완전하지 않습니다. 위의 원클릭 버튼으로 이어 제작하세요. 기존 팩은 삭제하지 않습니다.")
        self.pack_enabled.setChecked(selected == PROFILE_ID or bool(getattr(cfg, "spectator_tts_pack_enabled", False)))
        self.pack_auto_names.setChecked(False if selected == PROFILE_ID else bool(getattr(cfg, "spectator_tts_pack_auto_names", True)))
        self.engine.setCurrentIndex(max(0, self.engine.findData(getattr(cfg, "spectator_tts_engine", "edge"))))
        self.model.setCurrentIndex(max(0, self.model.findData(getattr(cfg, "spectator_qwen_model", "1.7B"))))
        self.port.setValue(getattr(cfg, "spectator_qwen_port", 8768))
        self.language.setCurrentIndex(max(0, self.language.findData(getattr(cfg, "spectator_qwen_language", "Korean"))))
        self.speed.setValue(getattr(cfg, "spectator_qwen_speed", 1.))
        for role in self.speakers:
            self.speakers[role].setCurrentIndex(max(0, self.speakers[role].findData(
                getattr(cfg, f"spectator_qwen_{role}_speaker", "Sohee" if role == "caster" else "Ryan"))))
            self.instructions[role].setText(getattr(cfg, f"spectator_qwen_{role}_instruction", ""))

    def write(self, cfg):
        cfg.spectator_qwen_duo_profile = self.voice_profile.currentData() or ""
        cfg.spectator_qwen_duo_revision = self._duo_revision if cfg.spectator_qwen_duo_profile else ""
        cfg.spectator_tts_pack_enabled = self.pack_enabled.isChecked()
        cfg.spectator_tts_pack_auto_names = self.pack_auto_names.isChecked()
        for key, value in (("engine", self.engine.currentData()), ("model", self.model.currentData()),
                           ("port", self.port.value()), ("language", self.language.currentData()), ("speed", self.speed.value())):
            setattr(cfg, "spectator_tts_engine" if key == "engine" else f"spectator_qwen_{key}", value)
        for role in self.speakers:
            setattr(cfg, f"spectator_qwen_{role}_speaker", self.speakers[role].currentData())
            setattr(cfg, f"spectator_qwen_{role}_instruction", self.instructions[role].text().strip())

    def snapshot(self):
        cfg = copy.copy(self.cfg)
        self.write(cfg)
        return cfg

    def voice(self, role, edge_voice):
        return commentary_voice(self.snapshot(), role, edge_voice)

    def _refresh(self):
        self.details.setVisible(self.engine.currentData() == "qwen3")
        duo = self.voice_profile.currentData() == PROFILE_ID
        running = self._duo_job is not None
        self.manual_note.setVisible(not duo)
        self.check.setText("남성 2인 팩 파일 확인 · 소리 없음" if duo else "Qwen 연결 확인 · 소리 없음")
        if duo:
            self.pack_scope.setCurrentIndex(self.pack_scope.findData("full"))
        for widget in (self.engine, self.voice_profile):
            widget.setEnabled(not running)
        for widget in (self.model, self.language, self.speed, *self.speakers.values()):
            widget.setEnabled(not duo and not running)
            self._voice_form.setRowVisible(widget, not duo)
        for instruction in self.instructions.values():
            instruction.setEnabled(not duo and not running and self.model.currentData() == "1.7B")
            self._voice_form.setRowVisible(instruction, not duo)
        self._voice_form.setRowVisible(self.port, not duo)
        self.port.setEnabled(not running)
        self.check.setEnabled(not running)
        self.pack_enabled.setEnabled(not running and not duo)
        self.duo_build.setEnabled(not running and not self._pack_running)
        self.pack_build.setEnabled(not running and not self._pack_running)
        self.pack_scope.setEnabled(not running and not duo)
        self.pack_names.setEnabled(not running and not duo)

    def _changed(self, *_):
        if self._duo_applying:
            return
        selected = self.voice_profile.currentData() or ""
        if selected == PROFILE_ID and selected != self._selected_profile:
            revision = (self._duo_revision if self._selected_profile == PROFILE_ID
                        else profile_revision(PROFILE_ID))
            if not revision or not profile_ready(PROFILE_ID, revision=revision):
                self._duo_applying = True
                try:
                    # Disabled Qt items can still be selected programmatically.
                    # Never let such a selection publish an incomplete pack.
                    previous = self._selected_profile if self._selected_profile != PROFILE_ID else ""
                    self.voice_profile.setCurrentIndex(max(0, self.voice_profile.findData(previous)))
                    self._selected_profile = previous
                finally:
                    self._duo_applying = False
                self.duo_status.setText("남성 2인 팩이 아직 완전하지 않습니다. 원클릭 완성으로 이어 제작한 뒤 선택할 수 있습니다.")
                self._refresh()
                return
        if selected != self._selected_profile:
            if selected == PROFILE_ID:
                self._duo_revision = profile_revision(PROFILE_ID)
                self._duo_applying = True
                try:
                    self.pack_enabled.setChecked(True)
                finally:
                    self._duo_applying = False
            self._selected_profile = selected
        if self._pack_running:
            self._pack_cancel.set()
        self._probe_token += 1
        self.status.setText("완성된 남성 2인 팩을 사용합니다. 경기 중에는 서버 없이 파일만 재생합니다."
                            if selected == PROFILE_ID else "설정이 바뀌었습니다. 서버와 모델/포트를 맞춘 뒤 다시 확인해 주세요.")
        self._refresh()
        self.changed.emit()

    def build_pack(self):
        if self._pack_running or self._duo_job is not None:
            return
        if self.voice_profile.currentData() == PROFILE_ID:
            self.build_duo()
            return
        from commentary_pack import build
        cfg, scope = self.snapshot(), self.pack_scope.currentData()
        names = [name.strip() for name in self.pack_names.text().split(",") if name.strip()]
        if scope == "names" and not names:
            self.pack_status.setText("미리 준비할 닉네임을 먼저 입력해 주세요.")
            return
        self._pack_cancel.clear()
        self._pack_running = True
        self.duo_build.setEnabled(False)
        self.pack_build.setEnabled(False)
        self.pack_stop.setEnabled(True)
        self.pack_status.setText("서버 확인 후 제작합니다. 이미 완성된 문장은 건너뜁니다. 방송 중에는 중지해 주세요.")
        def worker():
            try:
                check_server(cfg)
                def progress(done, total, role, text):
                    try:
                        self.pack_progress.emit(done, total, role + ": " + text)
                    except RuntimeError:
                        self._pack_cancel.set()
                result = build(cfg, scope, names=names, cancel=self._pack_cancel, progress=progress)
                message = ("완료" if result["complete"] else "중지") + f" · {result['done']}/{result['total']} · 새로 생성 {result['generated']}개"
                message += "\n준비된 팩은 즉시재생 테스트로 확인하세요. 실제 경기 사용은 위의 ‘실시간 해설팩’ 체크를 켜세요."
            except Exception as exc:
                message = "제작 중단: " + str(exc) + "\n완성된 파일은 유지됩니다. 원인을 해결한 뒤 이어 만들기를 누르세요."
            try:
                self.pack_finished.emit(message)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True, name="CommentaryPackBuild").start()

    def _pack_progress(self, done, total, text):
        self.pack_status.setText(f"제작 {done}/{total} · {text}\n현재 한 문장 완료 후 중지 가능 · 완성된 문장은 다음 제작에서 재사용합니다.")

    def _pack_finished(self, message):
        self._pack_running = False
        self.pack_build.setEnabled(True)
        self.pack_stop.setEnabled(False)
        self.pack_status.setText(message)
        self._refresh()

    def stop_pack(self):
        self._pack_cancel.set()
        if self._duo_job is not None:
            try:
                self._duo_job.cancel()
                self.duo_status.setText("중지 요청을 보냈습니다. 현재 문장/모델 작업이 정리되면 멈춥니다. 기존 팩은 유지됩니다.")
            except Exception as exc:
                self.duo_status.setText("중지 요청을 전달하지 못했습니다: " + str(exc))

    def build_duo(self):
        if self._pack_running or self._duo_job is not None:
            return
        answer = QMessageBox.question(self, "한국어 남성 2인 팩 자동 완성",
            "목소리 준비부터 전체 해설팩 제작까지 자동으로 진행합니다.\n\n"
            "최초 모델 다운로드는 수 GB이며, GPU/CPU를 많이 사용해 오래 걸릴 수 있습니다.\n"
            "방송과 무거운 작업을 끝낸 뒤 시작하세요. 기존 팩은 삭제하지 않습니다.\n\n"
            "지금 시작할까요?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        job = None
        try:
            job = DuoSetupJob(self.snapshot())
            job.start()
        except Exception as exc:
            _close_duo_job({"job": job})
            self.duo_status.setText("준비를 시작하지 못했습니다: " + str(exc))
            return
        self._duo_job = job
        self._duo_holder["job"] = job
        self.pack_stop.setEnabled(True)
        self.duo_stop.setEnabled(True)
        self.duo_status.setText("자동 준비 시작 · 모델 확인 → 남성 목소리 설계 → 전체 팩 제작. 기존 설정은 아직 그대로입니다.")
        self._refresh()
        self._duo_timer.start()

    def _poll_duo(self):
        job = self._duo_job
        if job is None:
            self._duo_timer.stop()
            return
        try:
            events = job.poll()
        except Exception as exc:
            try:
                job.cancel()
            except Exception:
                logging.exception("QWEN_DUO_CANCEL_FAIL")
            events = [{"status": "error", "message": str(exc)}]
        for event in events:
            status = event.get("status", "")
            message = str(event.get("message") or "")
            if status == "progress":
                done, total = event.get("done", 0), event.get("total", 0)
                self.duo_status.setText((f"자동 제작 {done}/{total} · " if total else "자동 준비 · ") + message)
            elif status in ("complete", "error", "cancelled"):
                self._duo_timer.stop()
                self._duo_job = None
                _close_duo_job(self._duo_holder)
                self.pack_stop.setEnabled(False)
                self.duo_stop.setEnabled(False)
                revision = str(event.get("revision") or "")
                if (status == "complete" and event.get("profile") == PROFILE_ID and revision
                        and profile_ready(PROFILE_ID, revision=revision)):
                    # Signals must not save half-applied voice settings.
                    self._duo_applying = True
                    try:
                        self.voice_profile.model().item(1).setEnabled(True)
                        self.voice_profile.setCurrentIndex(1)
                        self._duo_revision = revision
                        self._selected_profile = PROFILE_ID
                        self.engine.setCurrentIndex(self.engine.findData("qwen3"))
                        self.model.setCurrentIndex(self.model.findData("1.7B"))
                        self.language.setCurrentIndex(self.language.findData("Korean"))
                        self.speed.setValue(1.)
                        self.pack_enabled.setChecked(True)
                        self.pack_auto_names.setChecked(False)
                    finally:
                        self._duo_applying = False
                    self.duo_status.setText("한국어 남성 2인 해설팩 완성 · 새 팩을 선택했습니다. 아래 ‘팩 즉시재생’으로 두 목소리를 들어보세요. 기존 팩도 남아 있습니다.")
                    self.changed.emit()
                    self.duo_completed.emit()
                else:
                    reason = message or ("완성 파일 검증에 실패했습니다." if status == "complete" else "제작을 중지했습니다.")
                    self.duo_status.setText(reason + "\n현재 사용 설정과 기존 팩은 유지됩니다. 다시 누르면 이어 제작합니다.")
                self._refresh()
                break

    def rehearse_pack(self):
        from commentary_pack import rehearsal
        try:
            steps, missing = rehearsal(self.snapshot(), names=[n.strip() for n in self.pack_names.text().split(",") if n.strip()])
            self.pack_status.setText(f"팩 종합 테스트 · 재생 가능 {len(steps)}개 / 누락 {len(missing)}개 · 새 합성 없음\n"
                                    "캐스터 콜 → 남성 해설 응답 → 코너명/입력 닉네임 순서로 재생합니다.\n"
                                    + ("누락:\n" + "\n".join(missing) if missing else "검사 대상 파일이 모두 준비되었습니다."))
            if steps:
                self.rehearsal_requested.emit(steps)
        except Exception as exc:
            logging.exception("COMMENTARY_PACK_REHEARSAL_FAIL")
            self.pack_status.setText(str(exc))

    def preview_pack(self):
        from commentary_pack import usage_voice, prepare_dialogue, render
        from speech_runtime import commentary_cache_path
        cfg = self.snapshot()
        cfg.spectator_tts_pack_enabled = True
        name = next((name.strip() for name in self.pack_names.text().split(",") if name.strip()), "블루 선수")
        packet = prepare_dialogue(cfg, "caster", {"focus": {"name": name, "side": "blue", "named": True}})
        voice = usage_voice(cfg, "caster", "", {"kind": "live"}, packet)
        text = name + ", 카운터!"
        path = commentary_cache_path(text, "caster", voice, 200, 100, 0)
        # Qt/Windows may still hold a prior preview open. Never replace media
        # currently owned by a player, even when the requested call is identical.
        path = str(Path(path).with_name("pack_preview_" + uuid.uuid4().hex + ".wav"))
        started = time.monotonic()
        try:
            render(text, path, voice)
            self.pack_status.setText(f"준비된 팩 파일 연결 {round((time.monotonic()-started)*1000)}ms · 합성 서버 호출 없음\n"
                                     "닉네임이 없으면 블루 선수로 지칭합니다. 실제 음성 재생 시작 지연을 측정한 수치는 아닙니다.")
            from commentary_pack import rehearsal
            steps, _missing = rehearsal(cfg)
            reply = next((s for s in steps if s["role"] == "analyst" and s["label"] == "counter 응답"), None)
            if reply:
                self.rehearsal_requested.emit([
                    {"role": "caster", "text": text, "media_path": path, "label": "카운터", "post_ms": 350}, reply])
                self.pack_status.setText("캐스터 카운터 → 해설 응답 순서로 재생합니다. 새 합성 없음.")
            else:
                self.preview_requested.emit(path)
                self.pack_status.setText("캐스터만 재생합니다: 해설 응답 파일이 없습니다.\n대표 시험팩을 ‘생성 / 이어 만들기’ 하면 해설 응답 1개를 추가합니다.")
        except Exception as exc:
            logging.exception("COMMENTARY_PACK_PREVIEW_FAIL path=%s", path)
            self.pack_status.setText(str(exc))

    def probe(self):
        self._probe_token += 1
        token, cfg = self._probe_token, self.snapshot()
        self.check.setEnabled(False)
        self.status.setText("로컬 서버 연결 확인 중…")
        def worker():
            try:
                info = check_server(cfg)
                metrics = info.get("metrics") or {}
                message = f"연결 완료 · {info['model']} · {info.get('device')}"
                if metrics:
                    message += f" · 최근 생성 {metrics.get('generation_ms')}ms / 음성 {metrics.get('audio_seconds')}초"
                    seconds = float(metrics.get("audio_seconds") or 0)
                    elapsed = float(metrics.get("generation_ms") or 0) / 1000
                    if seconds > 0 and elapsed > seconds:
                        message += f"\n주의: 최근 생성은 음성 길이의 {elapsed/seconds:.1f}배가 걸렸습니다. 실시간 콜에 늦을 수 있습니다."
                message += "\n이제 위의 TTS/듀오 테스트로 발음과 실제 생성 속도를 확인해 주세요."
            except Exception as exc:
                message = str(exc)
            try:
                self.probe_finished.emit(token, message)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True, name="QwenProbe").start()

    def _probe_result(self, token, message):
        self.check.setEnabled(True)
        if token == self._probe_token:
            self.status.setText(message)
