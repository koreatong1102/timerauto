"""Save final boards using the same HTML renderer, outside the live UI thread."""
import base64
import copy
import hashlib
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from diagnostics import diagnostics as DIAG


def image_metadata(report, events, folder):
    """Use the recorded match date, independent of the active broadcast."""
    if report.get('_reportImageTest'):
        return None
    key = str(report.get('matchSessionId') or '')
    if not key:
        return None
    event = next((entry for entry in events if entry.get('source') == 'match_result_summary'
                  and str(entry.get('match_session_id') or '') == key), None)
    if event is None:
        return None
    stamp = str(event.get('wall_time') or '')
    for entry in events:
        if (entry.get('source') in ('spectatorlog_vs_intro', 'match_archive_recovery')
                and str(entry.get('match_session_id') or '') == key):
            stamp = str(entry.get('wall_time') or stamp)
            break
    try:
        date = datetime.fromisoformat(stamp).date().isoformat()
    except (TypeError, ValueError):
        return None
    return dict(folder=str(Path(folder) / date), dailyMatchId=key)


def daily_report_target(folder, match_id):
    """Reserve one stable filename per match, even across application restarts."""
    folder = Path(folder).absolute()
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / '.report-index.sqlite3', timeout=0.25)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS reports '
                       '(match_id TEXT PRIMARY KEY, number INTEGER NOT NULL UNIQUE)')
            reserved = db.execute('SELECT number FROM reports WHERE match_id = ?', (match_id,)).fetchone()
            if reserved:
                number = reserved[0]
            else:
                last = db.execute('SELECT COALESCE(MAX(number), 0) FROM reports').fetchone()[0]
                for path in folder.iterdir():
                    match = re.fullmatch(r'([0-9]{1,18})\.png', path.name, flags=re.IGNORECASE)
                    if match:
                        last = max(last, int(match[1]))
                number = last + 1
                db.execute('INSERT INTO reports VALUES (?, ?)', (match_id, number))
    finally:
        db.close()
    return str(folder / f'{number:03d}.png')


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
        self.latest = {}
        self.completed = {}
        self.failures = {}
        self.max_attempts = 3

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
        if not folder:
            return False
        try:
            daily_match = meta.get('dailyMatchId')
            if daily_match:
                if daily_match != str(report.get('matchSessionId') or '') or report.get('_reportImageTest'):
                    return False
                target = daily_report_target(folder, daily_match)
            elif name.endswith('.png') and os.path.basename(name) == name and '/' not in name and '\\' not in name:
                target = os.path.abspath(os.path.join(folder, name))
            else:
                return False
            revision = max(0, int(report.get('reportRevision') or 0))
            frozen = copy.deepcopy(report)
            semantic = {key: value for key, value in frozen.items()
                        if key not in ('id', 'timestamp', 'reportRevision', 'showDelayMs', 'displayMs', '_reportImage')}
            signature = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
            with self.lock:
                previous = self.latest.get(target) or self.failures.get(target) or self.completed.get(target)
                if previous:
                    if revision < previous['revision']:
                        return False
                    if signature == previous['signature'] and previous is not self.failures.get(target):
                        previous['revision'] = max(revision, previous['revision'])
                        return False
                # An unversioned request must not overwrite an unrelated existing image.
                # A late official revision can replace the first image after a restart.
                if not previous and os.path.isfile(target) and not (revision > 0 and report.get('matchSessionId')):
                    return False
                original = self.latest.get(target) or self.failures.get(target) or self.completed.get(target)
                if original:
                    # A late correction must keep THIS match's frozen portraits, not
                    # the next match's shared image cache or HUD state.
                    state, images = original['state'], original['images']
                else:
                    state = copy.deepcopy(self.overlay.snapshot())
                    images = {}
                    for side in ('blue', 'red'):
                        path = self.overlay.image_path(side)
                        if path and os.path.isfile(path):
                            images['/image/' + side] = 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii')
                    state['events'] = []
                job = dict(report=frozen, state=state, images=images, target=target,
                           revision=revision, signature=signature)
                if target not in self.pending:
                    self.queue.put_nowait(target)
                    self.pending.add(target)
                self.latest[target] = job
                self.failures.pop(target, None)
                if self.worker is None or not self.worker.is_alive():
                    self.worker = threading.Thread(target=self._work, name='report-image-export', daemon=True)
                    self.worker.start()
            return True
        except Exception:
            logging.exception('REPORT_IMAGE_QUEUE_FAILED')
            return False

    def _work(self):
        # One worker per overlay, blocking on its small queue; never blocks UI shutdown.
        while True:
            target = self.queue.get()
            try:
                self._process_target(target)
            except Exception:
                logging.exception('REPORT_IMAGE_WORKER_FAILED path=%s', target)
                with self.lock:
                    self.latest.pop(target, None)
                    self.pending.discard(target)
            finally:
                self.queue.task_done()

    def _process_target(self, target):
        active = None
        attempts = 0
        while True:
            with self.lock:
                job = self.latest.get(target)
            if job is None:
                return
            if job is not active:
                active, attempts = job, 0
            attempts += 1
            try:
                saved = self._render(job)
            except Exception as exc:
                with self.lock:
                    if self.latest.get(target) is not job:
                        continue
                    if attempts >= self.max_attempts:
                        self.failures[target] = dict(job, error=str(exc), attempts=attempts)
                        self.latest.pop(target, None)
                        self.pending.discard(target)
                        while len(self.failures) > 16:
                            self.failures.pop(next(iter(self.failures)))
                        DIAG.record('report_image_failed', path=target, error=str(exc), attempts=attempts)
                        logging.exception('REPORT_IMAGE_FAILED path=%s attempts=%s', target, attempts)
                        return
                DIAG.record('report_image_retry', path=target, attempt=attempts, error=str(exc))
                logging.warning('REPORT_IMAGE_RETRY path=%s attempt=%s error=%s', target, attempts, exc)
                time.sleep(0.5 * attempts)  # Only the export worker waits, never the UI.
                continue
            with self.lock:
                if self.latest.get(target) is not job:
                    continue  # Coalesce to the newest revision instead of dropping it.
                if not saved:
                    raise RuntimeError('Report image was not committed')
                # Keep a small recent cache (including frozen portraits for corrections).
                self.completed[target] = job
                while len(self.completed) > 16:
                    self.completed.pop(next(iter(self.completed)))
                self.latest.pop(target, None)
                self.pending.discard(target)
                self.failures.pop(target, None)
            DIAG.record('report_image_saved', path=target, width=1920, height=1080, revision=job['revision'])
            logging.info('REPORT_IMAGE_SAVED path=%s revision=%s', target, job['revision'])
            return

    def _render(self, job):
        report, state, images, target = (job[key] for key in ('report', 'state', 'images', 'target'))
        token = uuid.uuid4().hex
        candidate = target + '.' + token + '.render.png'
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
                deadline = time.monotonic() + 25
                while result.returncode == 0 and not os.path.isfile(shot) and time.monotonic() < deadline:
                    time.sleep(.1)
                if result.returncode != 0 or not os.path.isfile(shot):
                    raise RuntimeError('리포트 PNG 렌더링 실패: ' + str(result.returncode) + ' ' + result.stderr.decode('utf-8', 'replace')[-1800:])
                with self.lock:
                    if token not in self.ready:
                        raise RuntimeError('리포트 글꼴·초상화 렌더링 완료를 확인하지 못했습니다.')
                save_png(shot, candidate, token)
                with self.lock:
                    if self.latest.get(target) is not job:
                        return False
                    os.replace(candidate, target)
                return True
        finally:
            with self.lock:
                self.jobs.pop(token, None)
                self.ready.discard(token)
            if os.path.isfile(candidate):
                os.unlink(candidate)


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
    hint = QLabel('1920×1080 PNG · 날짜별 폴더에 001.png, 002.png 순서로 저장합니다.\n'
                  '같은 날에는 앱이나 방송을 다시 시작해도 번호가 이어집니다.\n'
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
