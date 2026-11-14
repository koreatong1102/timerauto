"""Save final boards using the same HTML renderer, outside the live UI thread."""
import base64
import copy
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from diagnostics import diagnostics as DIAG


def safe_name(value):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value or '')).strip(' .')
    return (text[:48].rstrip(' .') or 'UNKNOWN')


def image_metadata(report, events, folder):
    """Number exactly as the chapter's result summary, including resumed journals."""
    if report.get('_reportImageTest'):
        return None
    key = str(report.get('matchSessionId') or '')
    order = []
    results = {}
    for event in events:
        if event.get('source') != 'match_result_summary':
            continue
        session = str(event.get('match_session_id') or '')
        if session and session not in results:
            order.append(session)
            results[session] = event
    if not key or key not in results:
        return None  # Never guess a match number if the journal write failed.
    event = results[key]
    stamp = str(event.get('wall_time') or '')
    for entry in events:
        if (entry.get('source') in ('spectatorlog_vs_intro', 'match_archive_recovery')
                and entry.get('match_session_id') == key):
            stamp = str(entry.get('wall_time') or stamp)
            break
    try:
        date = datetime.fromisoformat(stamp).strftime('%Y-%m-%d_%H-%M-%S')
    except (TypeError, ValueError):
        return None
    number = order.index(key) + 1
    blue = safe_name(event.get('blue_name') or (report.get('blue') or {}).get('name') or 'BLUE')
    red = safe_name(event.get('red_name') or (report.get('red') or {}).get('name') or 'RED')
    return dict(folder=str(folder), filename=f'{date}_제{number:03d}경기_{blue}_vs_{red}.png')


def browser_executable():
    for root in (os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', ''),
                 os.environ.get('LOCALAPPDATA', '')):
        if not root:
            continue
        for suffix in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
            path = Path(root) / suffix
            if path.is_file():
                return str(path)
    return shutil.which('msedge') or shutil.which('google-chrome') or shutil.which('chromium')


def save_png(source, target, token):
    """Use the app's existing Qt PNG codec, not an optional Pillow install."""
    from PyQt6.QtGui import QImage
    image = QImage(source)
    if image.isNull() or (image.width(), image.height()) != (1920, 1080):
        raise RuntimeError(f'리포트 PNG 크기/읽기 오류: {image.width()}x{image.height()}')
    staging = target + '.' + token + '.tmp'
    try:
        if not image.save(staging, 'PNG'):
            raise OSError('리포트 PNG를 저장하지 못했습니다. 폴더 권한·남은 용량을 확인해 주세요.')
        os.replace(staging, target)
    finally:
        if os.path.isfile(staging):
            os.unlink(staging)


def render_html(html, report, state, images):
    report = copy.deepcopy(report)
    report.pop('_reportImage', None)
    report.update(showDelayMs=0, displayMs=600000)
    data = json.dumps([report, state, images], ensure_ascii=True).replace('<', '\\u003c')
    # No polling, event stream, video, audio, or studio interaction in the export page.
    html = html.replace('startStateStream();', '')
    html = html.replace('<script src="/studio-runtime.js"></script>', '')
    script = '''<style>
html,body{margin:0!important;width:100vw!important;height:100vh!important;overflow:hidden!important;background:#080d18!important}
body>*:not(#roundReport){display:none!important}
#roundReport,#roundReport *{animation:none!important;transition:none!important}
#roundReport{display:block!important;opacity:1!important;filter:none!important;transform:none!important}
#roundReport .rrV4::before,#roundReport .rrV4::after{display:none!important}
</style><script>
const exportData=__DATA__;
showRoundReport(exportData[0],exportData[1]);
document.body.replaceChildren(document.getElementById('roundReport'));
for(const img of document.querySelectorAll('#roundReport img')){
 const src=img.getAttribute('src')||'';
 for(const [prefix,data] of Object.entries(exportData[2]))if(src.startsWith(prefix))img.src=data;
}
Promise.all([document.fonts.ready,...Array.from(document.querySelectorAll('#roundReport img')).filter(img=>img.getAttribute('src')).map(img=>img.decode())])
 .then(()=>{fetch('/report-image-ready/__TOKEN__')})
 .catch(e=>fetch('/report-image-error/__TOKEN__?error='+encodeURIComponent(String(e))));
</script>'''.replace('__DATA__', data)
    errors = "<script>window.addEventListener('error',e=>fetch('/report-image-error/__TOKEN__?error='+encodeURIComponent(e.message+' @'+e.lineno)));</script>"
    return html.replace('<head>', '<head>' + errors).replace('</body>', script + '</body>')


class ReportImageExporter:
    def __init__(self, overlay):
        self.overlay = overlay
        self.jobs = {}
        self.pending = set()
        self.ready = set()
        self.lock = threading.Lock()
        self.queue = queue.Queue(maxsize=4)
        self.worker = None

    def page(self, token):
        with self.lock:
            return self.jobs.get(token)

    def mark_ready(self, token):
        with self.lock:
            if token not in self.jobs:
                return False
            self.ready.add(token)
            return True

    def enqueue(self, report):
        meta = report.get('_reportImage')
        if not report.get('isFinal') or not isinstance(meta, dict):
            return False
        folder = str(meta.get('folder') or '')
        name = str(meta.get('filename') or '')
        if not folder or not name.endswith('.png') or os.path.basename(name) != name or '/' in name or '\\' in name:
            return False
        target = os.path.abspath(os.path.join(folder, name))
        with self.lock:
            if target in self.pending or os.path.isfile(target):
                return False
            self.pending.add(target)
        try:
            state = copy.deepcopy(self.overlay.snapshot())
            # Freeze portraits now; the next match may replace their shared cache files.
            images = {}
            for side in ('blue', 'red'):
                path = self.overlay.image_path(side)
                if path and os.path.isfile(path):
                    images['/image/' + side] = 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii')
            state['events'] = []
            self.queue.put_nowait((copy.deepcopy(report), state, images, target))
            with self.lock:
                if self.worker is None or not self.worker.is_alive():
                    self.worker = threading.Thread(target=self._work, name='report-image-export', daemon=True)
                    self.worker.start()
            return True
        except Exception:
            with self.lock:
                self.pending.discard(target)
            logging.exception('REPORT_IMAGE_QUEUE_FAILED')
            return False

    def _work(self):
        # One worker per overlay, blocking on its small queue; never blocks UI shutdown.
        while True:
            report, state, images, target = self.queue.get()
            token = uuid.uuid4().hex
            try:
                browser = browser_executable()
                if not browser:
                    raise RuntimeError('PNG 저장용 Microsoft Edge 또는 Chrome을 찾지 못했습니다.')
                page = render_html(self.overlay._html(), report, state, images).replace('__TOKEN__', token)
                with self.lock:
                    self.jobs[token] = page
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='timerauto_report_', ignore_cleanup_errors=True) as temp:
                    shot = os.path.join(temp, 'report.png')
                    args = [browser, '--headless=new', '--no-first-run', '--no-default-browser-check',
                            '--disable-extensions', '--hide-scrollbars', '--mute-audio',
                            '--force-device-scale-factor=1', '--window-size=1920,1080',
                            '--run-all-compositor-stages-before-draw', '--virtual-time-budget=5000',
                            '--user-data-dir=' + os.path.join(temp, 'profile'), '--screenshot=' + shot,
                            f'http://127.0.0.1:{self.overlay.port}/report-image/{token}']
                    result = subprocess.run(args, capture_output=True, timeout=35,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    # Edge's Windows launcher can exit before its isolated child finishes.
                    deadline = time.monotonic() + 25
                    while result.returncode == 0 and not os.path.isfile(shot) and time.monotonic() < deadline:
                        time.sleep(.1)
                    if result.returncode != 0 or not os.path.isfile(shot):
                        raise RuntimeError('리포트 PNG 렌더링 실패: ' + str(result.returncode) + ' ' + result.stderr.decode('utf-8', 'replace')[-1800:])
                    with self.lock:
                        if token not in self.ready:
                            raise RuntimeError('리포트 글꼴·초상화 렌더링 완료를 확인하지 못했습니다.')
                    save_png(shot, target, token)
                DIAG.record('report_image_saved', path=target, width=1920, height=1080)
                logging.info('REPORT_IMAGE_SAVED path=%s', target)
            except Exception as exc:
                DIAG.record('report_image_failed', path=target, error=str(exc))
                logging.exception('REPORT_IMAGE_FAILED path=%s', target)
            finally:
                with self.lock:
                    self.jobs.pop(token, None)
                    self.ready.discard(token)
                    self.pending.discard(target)
                self.queue.task_done()


def create_settings_panel(cfg, parent, changed, test_callback):
    from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QCheckBox, QLineEdit, QPushButton, QFileDialog, QLabel, QHBoxLayout
    panel = QGroupBox('경기 종료리포트 이미지 저장', parent)
    layout = QVBoxLayout(panel)
    enabled = QCheckBox('경기 전체리포트를 PNG로 자동저장')
    enabled.setChecked(bool(getattr(cfg, 'report_image_enabled', True)))
    folder = QLineEdit(str(getattr(cfg, 'report_image_dir', '') or ''))
    folder.setPlaceholderText('비워 두면 프로그램 폴더의 ReportImages에 저장')
    browse = QPushButton('폴더 선택')
    row = QHBoxLayout(); row.addWidget(folder); row.addWidget(browse)
    layout.addWidget(enabled); layout.addLayout(row)
    hint = QLabel('1920×1080 PNG · 날짜/시간_제001경기_블루닉네임_vs_레드닉네임.png\n'
                  '경기 번호는 방송 챕터의 경기 결과 요약과 같습니다. 재시작해도 챕터 기록을 이어 쓰면 번호도 이어집니다.\n'
                  '실제 종료리포트가 나올 때 별도 작업으로 저장합니다. Edge/Chrome이 필요하며 방송 화면은 건드리지 않습니다.')
    hint.setWordWrap(True); layout.addWidget(hint)
    test = QPushButton('마지막 종료리포트 이미지 저장 테스트')
    test.clicked.connect(test_callback); layout.addWidget(test)
    def save(*_):
        cfg.report_image_enabled = enabled.isChecked()
        cfg.report_image_dir = folder.text().strip()
        changed()
    def choose():
        value = QFileDialog.getExistingDirectory(panel, '리포트 PNG 저장 폴더', folder.text())
        if value:
            folder.setText(value)
    browse.clicked.connect(choose); enabled.toggled.connect(save); folder.textChanged.connect(save)
    return panel
