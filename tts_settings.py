"""Optional local TTS controls; probing uses a worker, never Qt's UI thread."""
import copy
import threading
import json
import time
import logging
import uuid
from pathlib import Path
from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QFormLayout, QHBoxLayout,
                            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton, QLabel, QCheckBox)
from app_paths import app_path
from local_tts import SPEAKERS, check_server, commentary_voice


class TtsEngineControls(QGroupBox):
    changed = pyqtSignal()
    probe_finished = pyqtSignal(int, str)
    pack_progress = pyqtSignal(int, int, str)
    pack_finished = pyqtSignal(str)
    preview_requested = pyqtSignal(str)
    rehearsal_requested = pyqtSignal(list)
    rehearsal_stop_requested = pyqtSignal()

    def __init__(self, cfg, parent=None):
        super().__init__("해설 음성 엔진 · 선택 설치", parent)
        self.cfg = cfg
        self._probe_token = 0
        outer = QVBoxLayout(self)
        self.engine = QComboBox()
        self.engine.addItem("Edge TTS · 기존 온라인 음성", "edge")
        self.engine.addItem("Qwen3-TTS · 내 컴퓨터에서 생성", "qwen3")
        outer.addWidget(self.engine)
        self.details = QWidget()
        layout = QFormLayout(self.details)
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
        self.pack_stop.clicked.connect(self._pack_cancel.set)
        self.pack_preview.clicked.connect(self.preview_pack)
        self.pack_progress.connect(self._pack_progress)
        self.pack_finished.connect(self._pack_finished)
        self.destroyed.connect(lambda *_args, event=self._pack_cancel: event.set())
        outer.addWidget(self.details)
        self.load(cfg)
        for widget in (self.engine, self.model, self.language, *self.speakers.values()):
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
        self.pack_enabled.setChecked(bool(getattr(cfg, "spectator_tts_pack_enabled", False)))
        self.pack_auto_names.setChecked(bool(getattr(cfg, "spectator_tts_pack_auto_names", True)))
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
        for instruction in self.instructions.values():
            instruction.setEnabled(self.model.currentData() == "1.7B")

    def _changed(self, *_):
        if self._pack_running:
            self._pack_cancel.set()
        self._probe_token += 1
        self.status.setText("설정이 바뀌었습니다. 서버와 모델/포트를 맞춘 뒤 다시 확인해 주세요.")
        self._refresh()
        self.changed.emit()

    def build_pack(self):
        if self._pack_running:
            return
        from commentary_pack import build
        cfg, scope = self.snapshot(), self.pack_scope.currentData()
        names = [name.strip() for name in self.pack_names.text().split(",") if name.strip()]
        if scope == "names" and not names:
            self.pack_status.setText("미리 준비할 닉네임을 먼저 입력해 주세요.")
            return
        self._pack_cancel.clear()
        self._pack_running = True
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
