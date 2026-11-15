import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from match_analytics import detect_stoppage,resolve_match_result
from spectator_log_watcher import SpectatorLogWatcher
from stoppage_rules import official_stoppage_kind,update_life_flags


class StoppageLivesTests(unittest.TestCase):
    def test_explicit_stoppages_do_not_depend_on_down_count(self):
        for token,method in (('TechnicalKnockout','TKO'),('TKO','TKO'),('PunishmentKnockout','KO'),('Knockout','KO')):
            with self.subTest(token=token):
                event={'attacker_side':'blue','receiver_side':'red','damage_type':token,'time':50,'round':1}
                before=copy.deepcopy(event)
                stop=detect_stoppage([event])
                self.assertEqual(stop['method'],method)
                self.assertEqual(stop['winner'],'blue');self.assertEqual(stop['loser'],'red')
                self.assertEqual(event,before)
        for token in ('PunishmentKnockdown','Knockdown','Hit','Stun'):
            self.assertFalse(official_stoppage_kind(token))

    def test_damage_reader_emits_official_stoppage_on_first_terminal_hit(self):
        for token,method in (('TechnicalKnockout','TKO'),('PunishmentKnockout','KO')):
            with self.subTest(token=token),tempfile.TemporaryDirectory() as temp:
                watcher=SpectatorLogWatcher(SimpleNamespace())
                path=Path(temp,'damage_events.txt')
                row='100.0\t10\t1.0\tred\tleft\t.4\t.4\t0\t0\t0\tJab\tHit\tChin\n'
                path.write_text(row,encoding='utf-8');watcher._read_damage_update(str(path),fast_only=True)
                path.write_text(row+'99.0\t40\t1.0\tred\tright\t.4\t.4\t0\t0\t0\tCross\t'+token+'\tChin\n',encoding='utf-8')
                result=watcher._read_damage_update(str(path),fast_only=True)
                self.assertEqual(result['spectator_stoppage']['method'],method)
                self.assertEqual(result['spectator_stoppage']['loser'],'red')

    def test_three_downs_do_not_invent_tko_in_either_scorecard_path(self):
        watcher=SpectatorLogWatcher(SimpleNamespace())
        stats=watcher._new_scorecard_round(1)
        stats.update(events=3,knockdowns_against={'blue':0,'red':3},dealt={'blue':120,'red':30})
        stats['event_rows']=[{'damage_type':'Knockdown','attacker_side':'blue','receiver_side':'red'}]*3
        official={'round':1,'blue_score':10,'red_score':7,'winner':'blue','blue_kds':0,'red_kds':3}
        with tempfile.TemporaryDirectory() as temp:
            for rows in ([],[official]):
                with self.subTest(official=bool(rows)), \
                     patch.object(watcher,'_report_scorecard_rounds',return_value={1:copy.deepcopy(stats)}), \
                     patch.object(watcher,'_read_official_scores',return_value=rows):
                    result=watcher._scorecard_compute(str(Path(temp,'damage_events.txt')),1)
                    self.assertFalse(result['stoppage'])
                    resolution=resolve_match_result({},result['stoppage'],'fight',10,7)
                    self.assertEqual(resolution['source'],'pending')

    def test_official_winner_overrides_contradictory_damage_event(self):
        result=resolve_match_result({'side':'red'},dict(winner='blue',loser='red',method='KO'),'results',30,27)
        self.assertEqual(result['winner'],'red')
        self.assertNotEqual(result['method'],'KO')

    def test_confirmed_winner_plus_knockout_state_is_stoppage_not_decision(self):
        pending=resolve_match_result({}, {}, 'knockout', 30,27)
        self.assertEqual(pending['winner'],'')
        confirmed=resolve_match_result({'side':'red'}, {}, 'knockout', 30,27)
        self.assertEqual(confirmed['winner'],'red')
        self.assertEqual(confirmed['method'],'KO/TKO')
        self.assertEqual(update_life_flags({'spectator_round_report':{
            'winner':confirmed['winner'],'resultMethod':confirmed['method']}})[0],{'blue'})

    def test_unspecified_stoppage_is_not_relabelled_tko_by_commentary_or_chapters(self):
        from timerauto import MainApp
        from commentary_reports import build_report_narration
        self.assertEqual(MainApp._chapter_result_method_text('KO/TKO'),'KO/TKO')
        report={'winner':'blue','resultMethod':'KO/TKO','blue':{'name':'블루'},'red':{'name':'레드'}}
        narration=build_report_narration(report,final=True)
        self.assertIn('경기 중단 승리',narration)
        self.assertNotIn('TKO승',narration)

    def test_one_tko_depletes_only_loser_and_never_changes_actual_down_data(self):
        data={'round_current':1,'spectator_effect_events':[{'side':'red','kind':'tko'}],
              'spectator_log_info':{'red_round_knockdowns':1,'blue_round_knockdowns':0}}
        before=copy.deepcopy(data)
        eliminated,key=update_life_flags(data)
        self.assertEqual(eliminated,{'red'});self.assertEqual(data,before)
        eliminated,key=update_life_flags({'spectator_log_info':{'red_round_knockdowns':1}},eliminated,key)
        self.assertEqual(eliminated,{'red'})
        eliminated,key=update_life_flags({'round_current':2},eliminated,key)
        self.assertEqual(eliminated,set())

    def test_first_down_tko_report_uses_official_one_down_not_three(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);match=root/'match';match.mkdir()
            path=match/'damage_events.txt'
            path.write_text('99.0\t40\t1.0\tred\tright\t.4\t.4\t0\t0\t0\tCross\tTechnicalKnockout\tChin\n',encoding='utf-8')
            (match/'winner.txt').write_text('blue\tBLUE',encoding='utf-8')
            watcher=SpectatorLogWatcher(SimpleNamespace())
            watcher._last_round_state='results';watcher._last_fight_round_no=1
            official={'round':1,'blue_score':10,'red_score':8,'blue_total':10,'red_total':8,
                      'blue_damage_taken':0,'red_damage_taken':40,'blue_kds':0,'red_kds':1}
            with patch.object(watcher,'_read_official_scores',return_value=[official]):
                report=watcher._build_round_report_payload(str(path),1,('BLUE','RED'),force_final=True)
            self.assertEqual(report['resultMethod'],'TKO')
            self.assertEqual(report['blue']['knockdowns'],1)
            self.assertEqual(report['red']['knockdowns'],0)

    def test_official_ko_signal_and_final_report_restore_terminal_display(self):
        for data in ({'spectator_stoppage':{'method':'KO','loser':'blue'}},
                     {'spectator_round_report':{'isFinal':True,'winner':'red','resultMethod':'TKO'}},
                     {'spectator_round_reports':[{'winner':'red','resultMethod':'KO'}]}):
            self.assertEqual(update_life_flags(data)[0],{'blue'})
        self.assertEqual(update_life_flags({'spectator_round_report':{'isFinal':True,'winner':'red','resultMethod':'판정'}})[0],set())

    def test_new_match_and_clear_restore_life_flags(self):
        for data in ({'vs_intro_event':{'matchSessionId':'new'}},{'spectator_match_clear':True},{'spectator_match_stats_reset':True}):
            self.assertEqual(update_life_flags(data,{'red'},1)[0],set())

    def test_main_app_keeps_lives_depleted_separate_from_browser_down_counts(self):
        from timerauto import MainApp
        from PyQt6.QtCore import QObject
        app=MainApp.__new__(MainApp);QObject.__init__(app)
        data={'round_current':1,'spectator_effect_events':[{'side':'red','kind':'tko'}],
              'spectator_log_info':{'red_round_knockdowns':1}}
        app._hud_life_flags(data)
        result=app._browser_overlay_lives_update(data,{})
        self.assertEqual(result['redRoundKnockdowns'],1)
        self.assertTrue(result['redLivesDepleted']);self.assertFalse(result['blueLivesDepleted'])
        app._hud_life_flags({'spectator_match_clear':True})
        cleared=app._browser_overlay_lives_update({'spectator_match_clear':True},{})
        self.assertFalse(cleared['redLivesDepleted'])

    def test_native_qml_backend_keeps_one_down_while_life_icons_are_exhausted(self):
        code='''
from PyQt6.QtCore import QCoreApplication
from timerauto import TimerBackend
app=QCoreApplication([]);backend=TimerBackend()
backend.set_round_time(1,3,100)
backend.set_spectator_log_info({'red_round_knockdowns':1,'red_lives_depleted':True})
assert backend.redRoundKnockdowns==1 and backend.redLivesDepleted and not backend.blueLivesDepleted
backend.set_spectator_log_info({'red_round_knockdowns':1})
assert backend.redLivesDepleted
backend.set_round_time(2,3,180)
assert not backend.redLivesDepleted and backend.redRoundKnockdowns==0
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_browser_renderer_uses_depleted_flag_instead_of_altering_stats(self):
        from browser_overlay import BrowserOverlayServer
        overlay=BrowserOverlayServer()
        overlay.update(redRoundKnockdowns=1,redLivesDepleted=True)
        self.assertEqual(overlay.snapshot()['redRoundKnockdowns'],1)
        html=overlay._html()
        self.assertIn("+'LivesDepleted']===true)kd=3",html)
        self.assertIn('backend.redLivesDepleted',Path('timer_ui.qml').read_text(encoding='utf-8'))
