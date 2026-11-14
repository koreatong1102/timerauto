import os
import tempfile
import unittest
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
from round_highlights import RoundHighlights,settings
from config_model import AppConfig
from browser_overlay import BrowserOverlayServer


class RoundHighlightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'clip.mp4');Path(self.path).write_bytes(b'capture')
        self.now=0;self.jobs=[];self.cfg=SimpleNamespace(round_highlights_report_sec=9,round_highlights_max_clips=1);self.busy=False
        self.overlay=Mock();self.overlay.snapshot.return_value={};self.overlay.play_obs_replay.return_value='clip-token'
        self.engine=RoundHighlights(lambda:self.cfg,lambda:self.overlay,
                                    lambda ms,fn:self.jobs.append(fn),lambda:self.busy,clock=lambda:self.now)

    def event(self,key,round_no=1,**extra):
        return self.engine.consider(dict(event_id=key,combo_hits=3,attacker_side='blue',damage=30,**extra),round_no,{'blue':'PLAYER'})

    def ready(self,round_no=1):
        candidate=self.event('first'+str(round_no),round_no)
        self.engine.attach(self.path,{'round_highlight_id':candidate['id']},'source_record')
        return candidate

    def start(self):
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':1});self.now=9.1;self.engine.tick()

    def test_only_ready_current_round_is_selected_not_prior_round_winner(self):
        self.ready(1);self.now=10;self.ready(2)
        self.assertEqual([r['round'] for r in self.engine.ready(2)],[2])
        self.assertEqual(self.engine.ready(3),[])

    def test_unqualified_single_hit_does_not_request_capture(self):
        row=self.engine.consider({'event_id':'one','combo_hits':1,'attacker_side':'red','damage':99},1,{})
        self.assertIsNone(row)

    def test_duplicate_delivery_and_overlapping_scenes_do_not_play_twice(self):
        first=self.ready()
        self.assertIsNone(self.event('first1'))
        self.now=1
        later=self.event('down',effect_kind='knockdown')
        self.engine.attach(self.path,{'round_highlight_id':later['id']},'source_record')
        self.assertEqual(len(self.engine.ready(1)),1)
        self.assertEqual(self.engine.ready(1)[0]['id'],later['id'])

    def test_report_minimum_then_video_and_caption(self):
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.assertFalse(self.engine.report({'round':1}))
        self.now=8;self.engine.tick();self.overlay.play_obs_replay.assert_not_called()
        self.now=9.1;self.engine.tick()
        self.assertTrue(self.engine.active)
        kwargs=self.overlay.play_obs_replay.call_args.kwargs
        self.assertEqual(kwargs['replay_kind'],'round_highlight')
        self.assertIn('PLAYER',kwargs['replay_caption'])
        self.assertEqual(kwargs['start_from_end_sec'],8)

    def test_final_round_never_schedules_break_highlight(self):
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.assertFalse(self.engine.report({'round':1,'isFinal':True}))
        self.assertIsNone(self.engine.pending)

    def test_final_report_alone_cancels_running_video(self):
        self.start();self.engine.observe({'spectator_round_report':{'isFinal':True}})
        self.assertFalse(self.engine.active)
        self.overlay.stop_obs_replay.assert_called_once_with('clip-token')

    def test_short_break_or_missing_clip_keeps_existing_report(self):
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':15})
        self.assertFalse(self.engine.report({'round':1}));self.assertIsNone(self.engine.pending)
        self.engine.until=60;os.remove(self.path)
        self.assertFalse(self.engine.report({'round':1}));self.assertIsNone(self.engine.pending)

    def test_commentary_and_existing_replay_are_not_interrupted(self):
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':1});self.now=10;self.busy=True;self.engine.tick()
        self.overlay.play_obs_replay.assert_not_called()
        self.busy=False;self.overlay.snapshot.return_value={'obsReplayActive':True};self.engine.tick()
        self.overlay.play_obs_replay.assert_not_called()
        self.overlay.snapshot.return_value={};self.engine.tick();self.assertTrue(self.engine.active)

    def test_recap_leaves_time_for_highlight_preserving_sentences_and_numbers(self):
        text=('1라운드, 숫자보다 차이가 난 대목을 봅시다. 공식 점수는 망고링 10, 솜방망이 9입니다. '
              '유효타는 망고링 66번, 솜방망이 52번. 다운을 만든 횟수는 망고링 2, 솜방망이 2입니다. '
              '솜방망이 쪽 최고 펀치는 스트레이트, 111.37 데미지였습니다. '
              '최대 콤보는 망고링 5연타에 162 데미지, 솜방망이 6연타에 302 데미지.')
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':54})
        self.engine.report({'round':1})
        short=self.engine.compact_summary(text)
        self.assertLess(len(short),len(text));self.assertTrue(short.endswith('.'))
        self.assertIn('10, 솜방망이 9입니다.',short)
        self.assertTrue(text.startswith(short))
        estimate=sum(len(''.join(s.split()))/5.2+1.4 for s in short.split('. ') if s)
        self.assertLess(estimate,19)
        self.now=10;self.busy=True;self.engine.tick();self.assertFalse(self.engine.active)
        self.now=27;self.busy=False;self.engine.tick();self.assertTrue(self.engine.active)

    def test_no_highlight_reservation_keeps_full_report_commentary(self):
        text='전체 리포트입니다. 자세한 해설을 그대로 유지합니다.'
        self.assertEqual(self.engine.compact_summary(text),text)
        self.ready();self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':1,'isFinal':True})
        self.assertEqual(self.engine.compact_summary(text),text)

    def test_late_capture_also_reserves_commentary_time_and_skip_reason_is_recorded(self):
        self.event('pending-file');self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':1})
        text='라운드 정리입니다. 공식 점수는 블루 10, 레드 9입니다. '+('추가 설명입니다. '*20)
        self.assertLess(len(self.engine.compact_summary(text)),len(text))
        with patch('round_highlights.DIAG.record') as record:
            self.now=10;self.engine.tick()
        self.assertTrue(any(call.args[0]=='replay_round_skip' and call.kwargs['reason']=='capture_not_ready_at_due' for call in record.call_args_list))

    def test_next_round_stops_playback_and_old_callback_cannot_restart_it(self):
        self.start();jobs=list(self.jobs)
        self.engine.observe({'spectator_round_state':'fight','round_intro_event':1})
        self.assertFalse(self.engine.active)
        self.overlay.stop_obs_replay.assert_called_once_with('clip-token')
        self.overlay.play_obs_replay.reset_mock()
        for fn in jobs:fn()
        self.overlay.play_obs_replay.assert_not_called()

    def test_reserve_margin_stops_video_even_without_end_beacon(self):
        self.start();self.now=56;self.engine.tick()
        self.assertFalse(self.engine.active)
        self.overlay.stop_obs_replay.assert_called_once()

    def test_duplicate_report_cannot_cover_pending_or_active_video(self):
        self.start();self.assertTrue(self.engine.report({'round':1}))
        self.assertEqual(len(self.jobs),2)

    def test_late_file_can_arrive_after_report_and_report_corrections_keep_same_due_time(self):
        row=self.event('pending-file')
        self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.assertFalse(self.engine.report({'round':1}))
        original=self.engine.pending
        self.now=3
        self.assertFalse(self.engine.report({'round':1,'blue':{'damage':100}}))
        self.assertEqual(self.engine.pending,original)
        self.engine.attach(self.path,{'round_highlight_id':row['id']},'source_record')
        self.now=9.1;self.engine.tick()
        self.assertTrue(self.engine.active)

    def test_late_wrong_source_and_previous_match_files_are_not_attached(self):
        row=self.event('one')
        self.engine.attach(self.path,{'round_highlight_id':row['id']},'replay_buffer')
        self.assertEqual(self.engine.ready(1),[])
        self.engine.reset()
        self.engine.attach(self.path,{'round_highlight_id':row['id']},'source_record')
        self.assertEqual(self.engine.ready(1),[])

    def test_two_clips_use_actual_end_callback_and_different_scenes(self):
        self.cfg.round_highlights_max_clips=2
        self.ready();self.now=10;second=self.event('second',is_counter=True)
        self.engine.attach(self.path,{'round_highlight_id':second['id']},'source_record')
        self.engine.observe({'spectator_round_state':'break','seconds_left':60});self.engine.report({'round':1})
        self.now=20;self.engine.tick();self.assertTrue(self.engine.active)
        self.engine.ended('wrong-token');self.assertEqual(self.overlay.play_obs_replay.call_count,1)
        self.engine.ended('clip-token');self.assertEqual(self.overlay.play_obs_replay.call_count,2)
        self.overlay.push_event.assert_not_called()
        self.engine.ended('clip-token')
        self.overlay.push_event.assert_called_once()

    def test_last_video_restores_latest_corrected_report_without_replaying_commentary(self):
        self.start()
        self.engine.report({'round':1,'blue':{'damage':1250},'showDelayMs':3000})
        self.now=18;self.assertTrue(self.engine.ended('clip-token'))
        self.overlay.push_event.assert_called_once_with('round_report',round=1,blue={'damage':1250},showDelayMs=0)
        self.assertFalse(self.engine.ended('clip-token'))
        self.assertFalse(self.engine.report({'round':1,'blue':{'damage':1251}}))
        self.assertEqual(self.overlay.push_event.call_count,1)

    def test_round_start_or_final_result_never_restores_old_report(self):
        for data in ({'spectator_round_state':'fight'}, {'spectator_match_terminal':True},
                     {'spectator_round_report':{'isFinal':True}}):
            with self.subTest(data=data):
                self.engine.reset();self.now=0;self.overlay.push_event.reset_mock()
                self.start();self.engine.observe(data)
                self.engine.ended('clip-token');self.engine._restore_report()
                self.overlay.push_event.assert_not_called()

    def test_watchdog_and_reserve_cutoff_restore_report_only_while_break_remains(self):
        self.start();self.now=21;self.engine.tick()
        self.overlay.push_event.assert_called_once()
        self.engine.reset();self.now=0;self.overlay.push_event.reset_mock()
        self.start();self.now=56;self.engine.tick()
        self.overlay.push_event.assert_called_once()

    def test_missing_capture_never_repushes_or_restarts_original_report(self):
        self.event('late');self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':1});self.now=10;self.engine.tick()
        self.overlay.push_event.assert_not_called()

    def test_stale_previous_round_report_cannot_replace_return_board(self):
        self.ready(2);self.engine.observe({'spectator_round_state':'break','seconds_left':60})
        self.engine.report({'round':2,'blue':{'damage':200}})
        self.now=10;self.engine.tick()
        self.assertTrue(self.engine.report({'round':1,'blue':{'damage':100}}))
        self.engine.ended('clip-token')
        self.overlay.push_event.assert_called_once_with('round_report',round=2,blue={'damage':200},showDelayMs=0)

    def test_up_to_five_clips_fit_remaining_break_then_report_returns(self):
        for available,expected in ((60,5),(48,3),(30,1)):
            with self.subTest(available=available):
                self.engine.reset();self.overlay.play_obs_replay.reset_mock();self.overlay.push_event.reset_mock()
                self.cfg.round_highlights_max_clips=5;self.cfg.round_highlights_report_sec=15
                for index in range(5):
                    self.now=index*8
                    row=self.event('five-'+str(index))
                    self.assertIsNotNone(row)
                    self.engine.attach(self.path,{'round_highlight_id':row['id']},'source_record')
                self.now=40;self.engine.observe({'spectator_round_state':'break','seconds_left':available})
                self.engine.report({'round':1});self.now=55;self.engine.tick()
                for index in range(expected):
                    self.now=63+index*8
                    self.engine.ended('clip-token')
                self.assertEqual(self.overlay.play_obs_replay.call_count,expected)
                self.overlay.push_event.assert_called_once_with('round_report',round=1,showDelayMs=0)

    def test_only_two_available_clips_do_not_repeat_to_fill_five(self):
        self.cfg.round_highlights_max_clips=5
        self.ready();self.now=10;row=self.event('second')
        self.engine.attach(self.path,{'round_highlight_id':row['id']},'source_record')
        self.engine.observe({'spectator_round_state':'break','seconds_left':60});self.engine.report({'round':1})
        self.now=20;self.engine.tick()
        self.now=28;self.engine.ended('clip-token')
        self.now=36;self.engine.ended('clip-token')
        self.assertEqual(self.overlay.play_obs_replay.call_count,2)
        self.overlay.push_event.assert_called_once()

    def test_candidate_pool_is_bounded_and_does_not_drop_older_best_scene(self):
        self.now=0;best=self.event('best',is_counter=True,effect_kind='knockdown')
        for index in range(1,10):
            self.now=index*8;self.event('scene-'+str(index))
        self.now=80;self.assertIsNone(self.event('lower'))
        self.now=88;self.event('better',is_counter=True)
        self.assertEqual(len(self.engine.pool[1]),10)
        self.assertIn(best['id'],[row['id'] for row in self.engine.pool[1]])

    def test_new_defaults_are_fifteen_seconds_and_five_clips(self):
        cfg=AppConfig()
        self.assertEqual(settings(cfg)['round_highlights_report_sec'],15)
        self.assertEqual(settings(cfg)['round_highlights_max_clips'],5)

    def test_old_default_schedule_migrates_once_but_new_explicit_limit_is_preserved(self):
        import json
        path=Path(self.tmp.name,'old-config.json')
        path.write_text(json.dumps({'round_highlights_report_sec':9,'round_highlights_max_clips':1}),encoding='utf-8')
        cfg=AppConfig.from_json(str(path))
        self.assertEqual((cfg.round_highlights_report_sec,cfg.round_highlights_max_clips),(15,5))
        cfg.round_highlights_report_sec=9;cfg.round_highlights_max_clips=1;cfg.to_json(str(path))
        cfg=AppConfig.from_json(str(path))
        self.assertEqual((cfg.round_highlights_report_sec,cfg.round_highlights_max_clips),(9,1))
        path.write_text(json.dumps({'round_highlights_report_sec':12,'round_highlights_max_clips':2}),encoding='utf-8')
        cfg=AppConfig.from_json(str(path))
        self.assertEqual((cfg.round_highlights_report_sec,cfg.round_highlights_max_clips),(12,2))

    def test_settings_roundtrip_and_limits(self):
        cfg=AppConfig();cfg.round_highlights_capture_source='replay_buffer';cfg.round_highlights_enabled=False
        path=str(Path(self.tmp.name)/'cfg.json');cfg.to_json(path)
        self.assertEqual(settings(AppConfig.from_json(path)),settings(cfg))
        self.assertEqual(settings({'round_highlights_max_clips':999})['round_highlights_max_clips'],5)

    def test_backend_accepts_round_caption_separately_from_potm(self):
        server=BrowserOverlayServer()
        token=server.play_obs_replay(self.path,replay_kind='round_highlight',replay_caption='PLAYER · COUNTER COMBO')
        self.assertTrue(token)
        self.assertEqual(server.snapshot()['obsReplayCaption'],'PLAYER · COUNTER COMBO')
        self.assertEqual(server.snapshot()['obsReplayKind'],'round_highlight')

    def test_auto_capture_source_supports_native_buffer_users(self):
        self.cfg.obs_source_record_enabled=False;self.cfg.obs_replay_buffer_enabled=True
        row=self.event('native')
        self.assertEqual(row['source'],'replay_buffer')
        self.engine.attach(self.path,{'round_highlight_id':row['id']},'replay_buffer')
        self.assertEqual(len(self.engine.ready(1)),1)

    def test_settings_panel_saves_without_starting_capture_or_playback(self):
        code='''
from PyQt6.QtWidgets import QApplication,QCheckBox,QSpinBox,QComboBox
from unittest.mock import Mock
from config_model import AppConfig
from round_highlights import create_settings_panel
app=QApplication([]);cfg=AppConfig();changed=Mock()
panel=create_settings_panel(cfg,None,changed)
panel.findChild(QCheckBox,'roundHighlightsEnabled').setChecked(False)
panel.findChild(QSpinBox,'roundHighlights_max_clips').setValue(5)
panel.findChild(QComboBox,'roundHighlightsSource').setCurrentIndex(2)
assert not cfg.round_highlights_enabled and cfg.round_highlights_max_clips==5
assert cfg.round_highlights_capture_source=='replay_buffer' and changed.called
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
            env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cleanup_only_releases_owned_temporary_files_not_player_archives_or_potm(self):
        from timerauto import MainApp
        from PyQt6.QtCore import QObject
        root=Path(self.tmp.name);owned=root/'_potm_candidates';owned.mkdir()
        stale=owned/'stale.mp4';keep=owned/'current.mp4'
        stale.write_bytes(b'x');keep.write_bytes(b'x')
        app=MainApp.__new__(MainApp);QObject.__init__(app)
        app.cfg=SimpleNamespace(obs_source_record_archive_dir=str(root));app._potm_best={'file':str(keep)}
        app._release_round_highlight_files([str(stale),str(keep),self.path])
        self.assertFalse(stale.exists());self.assertTrue(keep.exists());self.assertTrue(os.path.exists(self.path))
