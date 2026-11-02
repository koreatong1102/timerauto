import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from report_combo import punch_label, classified_combo_rows, combo_details
from event_engine import FightEventEngine
from match_log_archive import MatchLogArchive
from spectator_log_watcher import SpectatorLogWatcher
from browser_overlay import BrowserOverlayServer


class ComboDetailTests(unittest.TestCase):
    def hit(self, clock, punch='Jab', hand='left', damage=30, side='blue', **extra):
        return dict(time=clock, punch=punch, hand=hand, damage=damage,
                    attacker_side=side, receiver_side='red' if side=='blue' else 'blue', **extra)

    def test_english_labels_use_actual_hand_not_stance(self):
        self.assertEqual(punch_label({'punch':'Jab','hand':'right'}),'JAB')
        self.assertEqual(punch_label({'punch':'Cross','hand':'left'}),'CROSS')
        self.assertEqual(punch_label({'punch':'LeadHook','hand':'right'}),'R.HOOK')
        self.assertEqual(punch_label({'punch':'RearUppercut','hand':'left'}),'L.UPPERCUT')
        self.assertEqual(punch_label({'punch':'RearOverhand'}),'OVERHAND')
        self.assertEqual(punch_label({'punch':'unknown-type','hand':'left'}),'PUNCH')

    def classified(self, rows):
        engine=FightEventEngine(SimpleNamespace())
        for row in rows:
            verdict=engine.classify(row)
            row.update(combo_hits=verdict['combo_hits'],combo_damage=verdict['combo_damage'],_central_event=verdict)
        return rows

    def test_canonical_chain_ignores_light_contact_but_honors_return_hit_reset(self):
        rows=self.classified([
            self.hit(100),self.hit(99.9,damage=5,side='red'),self.hit(99.8,'Cross','right'),
            self.hit(99.7,damage=25,side='red'),self.hit(99.6,'LeadHook'),self.hit(99.4,'RearUppercut','right'),
        ])
        first=classified_combo_rows(rows,rows[2],'blue')
        second=classified_combo_rows(rows,rows[-1],'blue')
        self.assertEqual(combo_details(first,2,60)['maxComboSequence'],['JAB','CROSS'])
        self.assertEqual(combo_details(second,2,60)['maxComboSequence'],['L.HOOK','R.UPPERCUT'])

    def test_incomplete_or_mismatched_detail_is_not_invented(self):
        rows=[self.hit(100,combo_hits=2,combo_damage=70)]
        self.assertEqual(classified_combo_rows(rows,rows[0],'blue'),[])
        self.assertEqual(combo_details(rows,2,70)['maxComboSequence'],[])
        full=[self.hit(100),self.hit(99.5,'Cross')]
        self.assertEqual(combo_details(full,2,99)['maxComboSequence'],[])
        self.assertEqual(combo_details(full,2,60)['maxComboSequence'],['JAB','CROSS'])

    def test_round_boundary_cannot_supply_a_missing_prefix(self):
        rows=[self.hit(100,combo_hits=1,_report_round=1),self.hit(99.5,combo_hits=2,_report_round=2)]
        self.assertEqual(classified_combo_rows(rows,rows[-1],'blue'),[])

    def test_final_and_round_reports_use_selected_archived_combo(self):
        with tempfile.TemporaryDirectory() as folder:
            match=Path(folder)/'match';match.mkdir()
            (match/'damage_events.txt').write_text('')
            (match/'punches_thrown.txt').write_text('')
            (match/'scores.csv').write_text('round,blue_score,red_score\n1,10,9\n2,9,10\n')
            (match/'winner.txt').write_text('blue\tBLUE')
            archive=MatchLogArchive(str(Path(folder)/'archive'))
            archive.start('combo-details',('BLUE','RED'))
            self.addCleanup(archive.close)
            one=[self.hit(100,'Jab',damage=35,counter_mult=1.2),self.hit(99.7,'Cross','right',damage=20),
                 self.hit(99.4,'LeadHook',damage=20),self.hit(99.1,'RearHook','right',damage=20,damage_type='Knockdown')]
            two=[self.hit(100,'RearUppercut','right',damage=80),self.hit(99.5,'LeadHook',damage=80)]
            archive.record_damage(1,one);archive.record_damage(2,two)
            watcher=SpectatorLogWatcher(SimpleNamespace(players={}))
            watcher._match_archive=archive;watcher._match_session_id='combo-details';watcher._last_round_state='break'
            path=str(match/'damage_events.txt')
            current=watcher._build_round_report_payload(path,2,('BLUE','RED'),force_final=False)['blue']
            self.assertEqual(current['maxComboHits'],2)
            self.assertEqual(current['maxComboDamage'],160)
            self.assertEqual(current['maxComboSequence'],['R.UPPERCUT','L.HOOK'])
            final=watcher._build_round_report_payload(path,2,('BLUE','RED'),force_final=True)['blue']
            self.assertEqual(final['maxComboHits'],4)
            self.assertEqual(final['maxComboDamage'],95)
            self.assertEqual(final['maxComboSequence'],['JAB','CROSS','L.HOOK','R.HOOK'])
            self.assertEqual(final['maxComboRound'],1)
            self.assertTrue(final['maxComboCounterStart'])
            self.assertTrue(final['maxComboDownFinish'])

    @unittest.skipUnless(shutil.which('node'),'Node needed for browser function test')
    def test_browser_renders_english_sequence_with_korean_notes_and_escapes_content(self):
        html=BrowserOverlayServer()._html()
        function=html[html.index('function rrV4ComboDetails('):html.index('function rrV4Fighter(')]
        script='''
const assert=require('node:assert/strict');
const rrV4Num=x=>Math.max(0,Math.round(Number(x)||0));
const escapeHtml=x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
'''+function+'''
const data={maxComboHits:4,maxComboSequence:['JAB','CROSS','L.HOOK','R.HOOK'],maxComboRound:2,maxComboCounterStart:true,maxComboDownFinish:true};
let text=rrV4ComboDetails(data,true);
assert(text.includes('JAB'));assert(text.includes('CROSS'));assert(text.includes('2라운드'));
assert(text.includes('카운터 시작'));assert(text.includes('다운 마무리'));
assert(!rrV4ComboDetails(data,false).includes('2라운드'));
assert.equal(rrV4ComboDetails({maxComboHits:4,maxComboSequence:['JAB']},false),'');
assert(!rrV4ComboDetails({maxComboHits:2,maxComboSequence:['<img>','JAB']},false).includes('<img>'));
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,encoding='utf8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("label:'\\uCD5C\\uB300 \\uCF64\\uBCF4'",html)
        self.assertIn('.rrSideStack.hasComboDetails',html)
