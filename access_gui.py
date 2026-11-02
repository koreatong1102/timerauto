"""Approval gate before MainApp starts any OBS, watchers, audio or hotkeys."""
import logging
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox

from access_client import AccessClient, AccessError, start_monitor
from access_policy import AUTH_SERVER_URL, POLL_SECONDS, CONNECTION_GRACE_SECONDS


class ApprovalDialog(QDialog):
    result_ready = pyqtSignal(object)

    def __init__(self, client):
        super().__init__()
        self.client,self.busy = client,False
        self.setWindowTitle("TimerAuto · 사용 승인")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        info = QLabel("운영자가 승인한 PC에서만 사용할 수 있습니다.\n이름을 입력하고 요청한 뒤 운영자에게 알려주세요.\n승인되면 자동으로 시작합니다. 인터넷 연결이 필요합니다.")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addWidget(QLabel("PC 등록번호: "+client.identity["device_id"][:12]))
        self.name = QLineEdit()
        self.name.setPlaceholderText("운영자가 알아볼 이름 또는 닉네임")
        self.name.setMaxLength(40)
        layout.addWidget(self.name)
        self.button = QPushButton("사용 승인 요청")
        self.button.clicked.connect(self.register)
        layout.addWidget(self.button)
        retry = QPushButton("승인 상태 다시 확인")
        retry.clicked.connect(self.check)
        layout.addWidget(retry)
        self.status = QLabel("승인 상태를 확인합니다…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.result_ready.connect(self.finished_request)
        self.poll = QTimer(self)
        self.poll.setInterval(POLL_SECONDS*1000)
        self.poll.timeout.connect(self.check)
        self.poll.start()
        QTimer.singleShot(0,self.check)

    def register(self):
        name = self.name.text().strip()
        if not name:
            self.status.setText("운영자가 알아볼 이름을 입력하세요.")
            return
        self.send("/api/register",name)

    def check(self):
        self.send("/api/check")

    def send(self, route, name=None):
        if self.busy:
            return
        self.busy = True
        self.button.setEnabled(False)
        def run():
            try:
                result = self.client.request(route,name)
            except Exception:
                result = "connection_error"
            try:
                self.result_ready.emit(result)
            except RuntimeError:
                pass  # The user may close the dialog during the bounded request.
        threading.Thread(target=run,daemon=True,name="AccessApprovalRequest").start()

    def finished_request(self, status):
        self.busy = False
        self.button.setEnabled(status in ("unknown","connection_error"))
        self.status.setText({"pending":"요청 완료 · 운영자의 승인을 기다립니다. 승인되면 자동 시작합니다.",
                             "revoked":"사용 권한이 중지되었거나 등록정보가 일치하지 않습니다. 운영자에게 문의하세요.",
                             "unknown":"아직 등록되지 않은 PC입니다. 이름을 입력하고 승인 요청을 누르세요.",
                             "connection_error":"인증 서버에 연결하지 못했습니다. 인터넷을 확인하세요. 자동으로 다시 확인합니다."}.get(status,"승인되었습니다."))
        if status == "approved":
            self.poll.stop()
            self.accept()

    def done(self, result):
        self.poll.stop()
        super().done(result)


def authorize(app):
    try:
        client = AccessClient(AUTH_SERVER_URL)
    except (AccessError,OSError,ValueError) as exc:
        QMessageBox.warning(None,"사용 인증 준비 필요",str(exc))
        return None
    dialog = ApprovalDialog(client)
    return client if dialog.exec() == QDialog.DialogCode.Accepted else None


class AccessGuard(QObject):
    denied = pyqtSignal(str)

    def __init__(self, app, client):
        super().__init__(app)
        self.denied.connect(self.stop_app)
        self.cancel = start_monitor(client,self.denied.emit,interval=POLL_SECONDS,grace=CONNECTION_GRACE_SECONDS)
        app.aboutToQuit.connect(self.cancel.set)

    def stop_app(self, reason):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        # Exit the APP, not OBS. Shutdown must not delete recordings or send
        # OBS stop-recording requests merely because approval was revoked.
        app.setProperty("access_revoked",True)
        logging.warning("ACCESS_STOP reason=%s",reason)
        app.quit()
