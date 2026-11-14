import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from config_model import AppConfig
from report_images import ReportImageExporter, browser_executable, image_metadata, render_html, safe_name, save_png


class ReportImagesTests(unittest.TestCase):
    def test_png_save_without_pillow_in_unicode_directory(self):
        import builtins
        from PyQt6.QtGui import QImage,QColor
        original_import=builtins.__import__
        def without_pillow(name,*args,**kwargs):
            if name=='PIL' or name.startswith('PIL.'):
                raise ModuleNotFoundError("No module named 'PIL'")
            return original_import(name,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp:
            source=str(Path(temp,'원본.png'));target=str(Path(temp,'경기 리포트.png'))
            image=QImage(1920,1080,QImage.Format.Format_RGB32);image.fill(QColor(20,220,180))
            self.assertTrue(image.save(source,'PNG'))
            with patch('builtins.__import__',side_effect=without_pillow):
                save_png(source,target,'test')
            result=QImage(target)
            self.assertEqual((result.width(),result.height()),(1920,1080))
            self.assertEqual(result.pixelColor(100,100).getRgb()[:3],(20,220,180))
            self.assertFalse(Path(target+'.test.tmp').exists())

    def test_invalid_png_does_not_overwrite_existing_target(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp,'bad.png');source.write_bytes(b'bad')
            target=Path(temp,'saved.png');target.write_bytes(b'keep original')
            with self.assertRaises(RuntimeError):save_png(str(source),str(target),'test')
            self.assertEqual(target.read_bytes(),b'keep original')

    def journal(self):
        return [
            dict(source='spectatorlog_vs_intro', match_session_id='one', wall_time='2026-11-14T20:00:00'),
            dict(source='match_result_summary', match_session_id='one', wall_time='2026-11-14T20:05:00', blue_name='통', red_name='선수'),
            dict(source='spectatorlog_vs_intro', match_session_id='two', wall_time='2026-11-14T20:06:00'),
            dict(source='match_result_summary', match_session_id='two', wall_time='2026-11-14T20:10:00', blue_name='통', red_name='선수'),
            dict(source='match_result_summary', match_session_id='two', wall_time='2026-11-14T20:10:10', blue_name='통', red_name='선수'),
        ]

    def test_date_time_and_number_are_chapter_result_order_not_player_names(self):
        meta = image_metadata({'matchSessionId':'two'}, self.journal(), 'exports')
        self.assertEqual(meta['filename'], '2026-11-14_20-06-00_제002경기_통_vs_선수.png')
        self.assertEqual(meta, image_metadata({'matchSessionId':'two'}, json.loads(json.dumps(self.journal())), 'exports'))

    def test_new_broadcast_journal_restarts_number(self):
        rows = [x for x in self.journal() if x['match_session_id']=='two']
        self.assertIn('제001경기', image_metadata({'matchSessionId':'two'}, rows, 'x')['filename'])

    def test_unknown_match_or_invalid_date_does_not_guess_number(self):
        self.assertIsNone(image_metadata({'matchSessionId':'missing'}, self.journal(), 'x'))
        rows = [dict(source='match_result_summary',match_session_id='x',wall_time='bad')]
        self.assertIsNone(image_metadata({'matchSessionId':'x'}, rows, 'x'))

    def test_no_intro_repeated_result_retains_first_filename_and_test_is_excluded(self):
        rows=[x for x in self.journal() if x['source']=='match_result_summary']
        first=image_metadata({'matchSessionId':'two'},rows[:2],'x')
        corrected=image_metadata({'matchSessionId':'two'},rows,'x')
        self.assertEqual(first,corrected)
        self.assertIsNone(image_metadata({'matchSessionId':'two','_reportImageTest':True},rows,'x'))

    def test_settings_panel_updates_cfg_without_saving_or_changing_broadcast(self):
        import subprocess,sys
        code='''
from PyQt6.QtWidgets import QApplication,QCheckBox,QLineEdit,QPushButton
from unittest.mock import Mock
from config_model import AppConfig
from report_images import create_settings_panel
app=QApplication([]);cfg=AppConfig();changed=Mock();test=Mock()
panel=create_settings_panel(cfg,None,changed,test)
panel.findChild(QCheckBox).setChecked(False)
panel.findChild(QLineEdit).setText('report-output')
assert cfg.report_image_enabled is False and cfg.report_image_dir=='report-output'
assert changed.called and not test.called
for button in panel.findChildren(QPushButton):
 if button.text().startswith('마지막'):button.click()
assert test.call_count==1
'''
        run=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                           env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_filename_sanitization(self):
        self.assertEqual(safe_name('A/B:C?*<>|"\\'), 'A_B_C_______')
        self.assertLessEqual(len(safe_name('가'*200)),48)

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            config=AppConfig();config.report_image_enabled=False;config.report_image_dir='리포트 PNG'
            path=os.path.join(temp,'config.json');config.to_json(path)
            restored=AppConfig.from_json(path)
            self.assertFalse(restored.report_image_enabled)
            self.assertEqual(restored.report_image_dir,'리포트 PNG')

    def test_export_html_isolated_from_live_polling_and_script_injection(self):
        html=render_html('<body><script>startStateStream();</script><script src="/studio-runtime.js"></script></body>',
                         {'isFinal':True,'blue':{'name':'</script><script>alert(1)</script>'}}, {}, {})
        self.assertNotIn('startStateStream();',html)
        self.assertNotIn('src="/studio-runtime.js"',html)
        self.assertNotIn('</script><script>alert(1)',html)
        self.assertIn('document.fonts.ready',html)
        self.assertIn('img.decode()',html)
        self.assertIn('animation:none',html)

    def test_round_and_synthetic_final_without_metadata_never_save(self):
        worker=ReportImageExporter(Mock())
        self.assertFalse(worker.enqueue({'isFinal':True}))
        self.assertFalse(worker.enqueue({'isFinal':False,'_reportImage':{'folder':'x','filename':'x.png'}}))

    def test_invalid_path_and_existing_file_do_not_enqueue(self):
        worker=ReportImageExporter(Mock())
        self.assertFalse(worker.enqueue({'isFinal':True,'_reportImage':{'folder':'x','filename':'../x.png'}}))
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,'done.png').write_bytes(b'original')
            self.assertFalse(worker.enqueue({'isFinal':True,'_reportImage':{'folder':temp,'filename':'done.png'}}))
            self.assertEqual(Path(temp,'done.png').read_bytes(),b'original')

    def test_same_report_queues_once_and_freezes_state(self):
        overlay=Mock();overlay.snapshot.return_value={'blueName':'original','events':[{'kind':'ko'}]};overlay.image_path.return_value=''
        worker=ReportImageExporter(overlay);worker.worker=Mock();worker.worker.is_alive.return_value=True
        with tempfile.TemporaryDirectory() as temp:
            report={'isFinal':True,'_reportImage':{'folder':temp,'filename':'report.png'}}
            self.assertTrue(worker.enqueue(report));self.assertFalse(worker.enqueue(report))
            overlay.snapshot.return_value['blueName']='next match'
            queued=worker.queue.get_nowait()
            self.assertEqual(queued[1]['blueName'],'original')
            self.assertEqual(queued[1]['events'],[])

    def test_server_only_requests_export_for_final_event(self):
        from browser_overlay import BrowserOverlayServer
        overlay=BrowserOverlayServer();overlay.report_images=Mock()
        overlay.push_event('round_report',isFinal=False,round=1)
        overlay.report_images.enqueue.assert_not_called()
        overlay.push_event('round_report',isFinal=True,round=3)
        overlay.report_images.enqueue.assert_called_once()

    @unittest.skipUnless(os.environ.get('RFC_TEST_REPORT_BROWSER')=='1' and browser_executable(), 'explicit real browser render test')
    def test_real_headless_report_png(self):
        from browser_overlay import BrowserOverlayServer
        from PyQt6.QtGui import QImage,QColor
        overlay=BrowserOverlayServer(port=0)
        overlay.port=0  # Constructor's public 0 means default; tests need an OS-assigned port.
        self.assertTrue(overlay.start());overlay.port=overlay._server.server_address[1]
        try:
            with tempfile.TemporaryDirectory() as temp:
                overlay.update(blueName='통',redName='현선호',reportWeakPointParts=[])
                blue_image=Path(temp,'blue.png');red_image=Path(temp,'red.png')
                for path,color in ((blue_image,(20,220,180)),(red_image,(220,40,180))):
                    fixture=QImage(260,300,QImage.Format.Format_RGB32);fixture.fill(QColor(*color));fixture.save(str(path),'PNG')
                overlay._image_paths={'blue':str(blue_image),'red':str(red_image)}
                overlay.update(blueHasImage=True,redHasImage=True,blueImageRev=1,redImageRev=1)
                report={'isFinal':True,'round':3,'winner':'blue',
                    'blue':dict(name='통',officialScore=30,damage=1245,landed=52,thrown=88,maxComboHits=4,maxComboDamage=151,averageDamage=23.9,healthPct=61,staminaPct=54,maxComboSequence=['JAB','CROSS','HOOK','HOOK'],maxComboRound=2,maxComboStartTimeText='1:23'),
                    'red':dict(name='현선호',officialScore=27,damage=1040,landed=40,thrown=90,maxComboHits=3,maxComboDamage=100,averageDamage=26,healthPct=50,staminaPct=43),
                    '_reportImage':dict(folder=temp,filename='real_report.png')}
                self.assertTrue(overlay.report_images.enqueue(report))
                end=time.monotonic()+40
                while overlay.report_images.pending and time.monotonic()<end:
                    time.sleep(.1)
                target=Path(temp,'real_report.png')
                self.assertTrue(target.is_file(),'renderer failed; inspect REPORT_IMAGE_FAILED')
                image=QImage(str(target))
                self.assertEqual((image.width(),image.height()),(1920,1080))
                self.assertEqual(image.pixelColor(100,150).getRgb()[:3],(20,220,180))
                self.assertEqual(image.pixelColor(1750,150).getRgb()[:3],(220,40,180))
                # Keep an explicitly requested visual QA artifact outside temp cleanup.
                if os.environ.get('RFC_REPORT_QA_PATH'):
                    import shutil
                    shutil.copyfile(target,os.environ['RFC_REPORT_QA_PATH'])
        finally:
            overlay.stop()
