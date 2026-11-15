import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

from browser_overlay import BrowserOverlayServer
from diagnostics import DiagnosticRecorder
from video_formats import VIDEO_EXTENSIONS, VIDEO_FILE_FILTER


class IdleVideoFormatTests(unittest.TestCase):
    def scan(self, path):
        from timerauto import MainApp
        return MainApp._idle_highlight_files(SimpleNamespace(cfg=SimpleNamespace(idle_highlight_path=str(path))))

    def test_mkv_under_player_and_nested_ko_folder_reaches_browser_playlist(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp,'선수 영상');nested=root/'선수'/'KO_REPLAY';nested.mkdir(parents=True)
            one=root/'Replay 2026-11-14 23-00-56.mkv'
            two=nested/'두번째.MKV'
            for path in (one,two):path.write_bytes(b'video fixture')
            (root/'empty.mkv').touch();(root/'notes.txt').write_text('ignore',encoding='utf-8')
            paths=self.scan(root)
            self.assertEqual(set(paths),{str(one),str(two)})
            overlay=BrowserOverlayServer();overlay.set_highlight_playlist(paths)
            self.assertEqual(overlay.snapshot()['idleHighlightCount'],2)
            self.assertEqual({overlay.highlight_path(0),overlay.highlight_path(1)},{str(one),str(two)})

    def test_direct_uppercase_mkv_and_legacy_video_formats_are_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            for suffix in VIDEO_EXTENSIONS:
                path=Path(temp,'video'+suffix.upper());path.write_bytes(b'fixture')
                self.assertEqual(self.scan(path),[str(path)])
            self.assertEqual(len(self.scan(temp)),len(VIDEO_EXTENSIONS))

    def test_file_picker_exposes_same_extensions_as_scanner_and_browser(self):
        from timerauto import SettingsDialog
        fake=SimpleNamespace(le_idle_highlight_path=Mock(),_schedule_apply=Mock())
        fake.le_idle_highlight_path.text.return_value=''
        with patch('timerauto.QFileDialog.getOpenFileName',return_value=('clip.mkv','')) as picker:
            SettingsDialog._pick_idle_highlight_file(fake)
        self.assertEqual(picker.call_args.args[-1],VIDEO_FILE_FILTER)
        for suffix in VIDEO_EXTENSIONS:self.assertIn('*'+suffix,VIDEO_FILE_FILTER)
        fake.le_idle_highlight_path.setText.assert_called_once_with('clip.mkv')
        fake._schedule_apply.assert_called_once()

    def test_mkv_stream_uses_matroska_type_and_supports_range_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp,'한글 영상.mkv');path.write_bytes(b'0123456789abcdef')
            overlay=BrowserOverlayServer();overlay.port=0
            self.assertTrue(overlay.start());overlay.port=overlay._server.server_address[1]
            try:
                overlay.set_highlight_playlist([str(path)])
                with urlopen(f'http://127.0.0.1:{overlay.port}/highlight/0',timeout=3) as response:
                    self.assertEqual(response.headers['Content-Type'],'video/x-matroska')
                    self.assertEqual(response.read(),path.read_bytes())
                request=Request(f'http://127.0.0.1:{overlay.port}/highlight/0',headers={'Range':'bytes=3-7'})
                with urlopen(request,timeout=3) as response:
                    self.assertEqual(response.status,206)
                    self.assertEqual(response.headers['Content-Range'],'bytes 3-7/16')
                    self.assertEqual(response.read(),b'34567')
            finally:overlay.stop()

    def test_diagnostics_reports_empty_playlist_and_zero_volume_separately(self):
        findings=DiagnosticRecorder._findings({},[],{},overlay={
            'idleHighlightEnabled':True,'idleHighlightCount':0,
            'idleHighlightMuted':False,'idleHighlightVolume':0})
        self.assertTrue(any(item['evidence']=='overlay_snapshot.json:idleHighlightCount' for item in findings))
        self.assertTrue(any(item['evidence']=='overlay_snapshot.json:idleHighlightVolume' for item in findings))
        self.assertFalse(any('코덱 오류' in item['message'] or '성능 문제' in item['message'] for item in findings))
        findings=DiagnosticRecorder._findings({},[],{},overlay={'idleHighlightEnabled':False,'idleHighlightCount':0})
        self.assertFalse(any(item['evidence'].startswith('overlay_snapshot.json:idle') for item in findings))

    def test_browser_records_actual_idle_play_and_media_errors(self):
        html=BrowserOverlayServer()._html()
        self.assertIn("overlayBeacon('idle_video_playing'",html)
        self.assertIn("idleVideoErrorBeacon('idle_video_error')",html)
        self.assertIn("idleVideoErrorBeacon('idle_play_rejected'",html)
        self.assertIn('now-idleVideoErrorAt<5000',html)
