import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from hud_layout import HUD_DEFAULTS, HUD_LAYOUT_CSS, HUD_LAYOUT_JS, hud_settings, hud_browser_state
from config_model import AppConfig
from browser_overlay import BrowserOverlayServer

ROOT = Path(__file__).resolve().parents[1]


class HudLayoutTests(unittest.TestCase):
    def test_defaults_reset_and_saved_asymmetric_values(self):
        self.assertEqual(hud_settings(AppConfig()),HUD_DEFAULTS)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            cfg=AppConfig();cfg.overlay_hud_link_sides=False
            cfg.overlay_hud_left_margin=400;cfg.overlay_hud_right_margin=350;cfg.overlay_hud_y=25;cfg.overlay_hud_portrait_pct=65
            cfg.overlay_hud_dock='bottom';cfg.overlay_hud_bottom_margin_pct=5.5
            cfg.to_json(str(path))
            self.assertEqual(hud_settings(AppConfig.from_json(str(path))),hud_settings(cfg))
            self.assertEqual(hud_browser_state(cfg),{'hudLeftMargin':400,'hudRightMargin':350,'hudOffsetY':25,
                                                   'hudLeftMarginPct':400/19.2,'hudRightMarginPct':350/19.2,'hudPortraitPct':65,
                                                   'hudDock':'bottom','hudBottomMarginPct':5.5})

    def test_link_and_invalid_values_are_normalized(self):
        self.assertEqual(hud_settings({'overlay_hud_left_margin':400})['overlay_hud_right_margin'],400)
        value=hud_settings({'overlay_hud_left_margin':float('nan'),'overlay_hud_y':99999,'overlay_hud_right_margin':99999,'overlay_hud_link_sides':False})
        self.assertEqual(value['overlay_hud_left_margin'],0)
        self.assertEqual(value['overlay_hud_right_margin'],864)
        self.assertEqual(value['overlay_hud_y'],700)
        self.assertEqual(hud_settings({'overlay_hud_portrait_pct':0})['overlay_hud_portrait_pct'],30)
        self.assertEqual(hud_settings({'overlay_hud_portrait_pct':float('nan')})['overlay_hud_portrait_pct'],100)
        self.assertEqual(hud_settings({'overlay_hud_dock':'garbage'})['overlay_hud_dock'],'top')
        self.assertEqual(hud_settings({'overlay_hud_bottom_margin_pct':100})['overlay_hud_bottom_margin_pct'],40)

    def test_layout_css_targets_only_hud_and_preview_is_page_local(self):
        html=BrowserOverlayServer()._html()
        self.assertIn('#root > .hud.hud-safe-layout',html)
        for forbidden in ('#roundReport','#vs','#koOverlay','#obsReplay','scale('):
            self.assertNotIn(forbidden,HUD_LAYOUT_CSS)
        self.assertNotIn('fetch(',HUD_LAYOUT_JS)
        self.assertIn("get('hudPreview')==='1'",HUD_LAYOUT_JS)
        self.assertIn('events:[]',HUD_LAYOUT_JS)
        self.assertIn('obsReplayActive:false',HUD_LAYOUT_JS)
        self.assertNotIn('.hud-compact .combo',HUD_LAYOUT_CSS)
        self.assertNotIn('.hud-compact .recent',HUD_LAYOUT_CSS)
        self.assertIn('white-space:nowrap!important',HUD_LAYOUT_CSS)
        self.assertIn('> .side.blue',HUD_LAYOUT_CSS)
        self.assertIn('width:calc(1920px / var(--ui-scale))',HUD_LAYOUT_CSS)
        # Studio clears inline width/font-size each render; custom variables survive it.
        self.assertIn('width:var(--hud-round-damage-width,122px)!important',HUD_LAYOUT_CSS)
        self.assertIn('font-size:var(--hud-total-fitted-size,var(--bt-total-size))',HUD_LAYOUT_CSS)
        self.assertIn("set(damage,'--hud-round-damage-width'",HUD_LAYOUT_JS)

    def test_direct_updates_reach_browser_and_other_state_is_unchanged(self):
        from PyQt6.QtCore import QObject
        from timerauto import MainApp
        app=MainApp.__new__(MainApp);QObject.__init__(app)
        app.cfg=AppConfig();app.browser_overlay=Mock()
        app.browser_overlay.snapshot.return_value={}
        app._sync_browser_overlay_player_assets=lambda data:{}
        app._update_pending_browser_vs_intro=lambda data:None
        app._apply_browser_overlay_direct_update({'overlay_hud_left_margin':405,'overlay_hud_y':30,'overlay_hud_portrait_pct':60,
                                                'overlay_hud_dock':'bottom','overlay_hud_bottom_margin_pct':4})
        state=app.browser_overlay.update.call_args.kwargs
        self.assertEqual(state['hudLeftMargin'],405)
        self.assertEqual(state['hudRightMargin'],405)
        self.assertEqual(state['hudOffsetY'],30)
        self.assertEqual(state['hudPortraitPct'],60)
        self.assertEqual(state['hudDock'],'bottom')
        self.assertEqual(state['hudBottomMarginPct'],4)
        self.assertNotIn('events',state)

    def test_qt_settings_panel_links_resets_and_opens_only_local_preview(self):
        script='''
import os,tempfile
from contextlib import chdir
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtCore import QObject,pyqtSignal
from unittest.mock import patch
from config_model import AppConfig
from timerauto import SettingsDialog
class Controller(QObject):
 ui_update=pyqtSignal(dict)
app=QApplication([])
with tempfile.TemporaryDirectory() as folder, chdir(folder):
 cfg=AppConfig();dlg=SettingsDialog(None,cfg,None,None,cfg_path=os.path.join(folder,'config.json'))
 controller=Controller();calls=[];controller.ui_update.connect(calls.append);dlg.controller=controller
 panel=dlg.hud_layout_panel
 assert panel.dock.currentData()=='top'
 assert not panel.controls['overlay_hud_bottom_margin_pct'].isEnabled()
 panel.dock.setCurrentIndex(1)
 assert cfg.overlay_hud_dock=='bottom' and calls[-1]['overlay_hud_dock']=='bottom'
 assert not panel.controls['overlay_hud_y'].isEnabled()
 panel.controls['overlay_hud_bottom_margin_pct'].setValue(5.5)
 assert cfg.overlay_hud_bottom_margin_pct==5.5
 panel.controls['overlay_hud_portrait_pct'].setValue(60)
 assert cfg.overlay_hud_portrait_pct==60 and calls[-1]['overlay_hud_portrait_pct']==60
 assert panel.controls['overlay_hud_left_margin'].maximum()==45
 cfg.overlay_hud_left_margin=350;panel.reload()
 assert panel.controls['overlay_hud_left_margin'].value()==18.23
 assert cfg.overlay_hud_left_margin==350 # Opening settings never rounds legacy saved position.
 assert panel.controls['overlay_hud_left_margin'].suffix()==' %'
 panel.controls['overlay_hud_left_margin'].setValue(20)
 assert cfg.overlay_hud_right_margin==384 and calls[-1]['overlay_hud_left_margin']==384
 assert not panel.controls['overlay_hud_right_margin'].isEnabled()
 panel.link.setChecked(False);panel.controls['overlay_hud_right_margin'].setValue(12.5)
 assert cfg.overlay_hud_right_margin==240
 with patch('timerauto.QDesktopServices.openUrl') as opened:
  next(b for b in panel.findChildren(QPushButton) if '미리보기 열기' in b.text()).click()
  assert opened.call_args.args[0].toString().endswith('/overlay?hudPreview=1')
 assert isinstance(dlg._collect_overlay_ko_settings(),dict)
 preset=dlg._collect_overlay_preset()
 assert preset['overlay_hud_left_margin']==384 and preset['overlay_hud_right_margin']==240
 assert preset['overlay_hud_portrait_pct']==60
 assert preset['overlay_hud_dock']=='bottom' and preset['overlay_hud_bottom_margin_pct']==5.5
 dlg._apply_overlay_preset(dict(preset,overlay_hud_left_margin=350,overlay_hud_right_margin=300))
 assert cfg.overlay_hud_left_margin==350 and cfg.overlay_hud_right_margin==300
 assert panel.controls['overlay_hud_left_margin'].value()==18.23
 panel.reset();assert cfg.overlay_hud_left_margin==cfg.overlay_hud_right_margin==cfg.overlay_hud_y==0
 assert cfg.overlay_hud_portrait_pct==100
 assert panel.dock.currentData()=='top' and cfg.overlay_hud_bottom_margin_pct==3
 assert panel.controls['overlay_hud_y'].isEnabled()
 dlg._apply_timer.stop();dlg.deleteLater()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node required for geometry tests')
    def test_browser_geometry_keeps_size_and_fullscreen_siblings(self):
        script='''
const assert=require('node:assert/strict');
const properties={},classes={};let changes=0;
const hud={dataset:{},classList:{toggle:(k,v)=>classes[k]=v},style:{setProperty:(k,v)=>{properties[k]=v;changes++}}};
const document={querySelector:selector=>{assert.equal(selector,'#root > .hud');return hud}};
const location={search:''};let latestState=null;function render(s){latestState=s}
'''+HUD_LAYOUT_JS+'''
let geometry=hudSafeGeometry({hudLeftMargin:400,hudRightMargin:350,hudOffsetY:25,browserOverlayScale:1});
assert.deepEqual(geometry,{left:400,right:350,width:1170,y:25});
render({hudLeftMargin:400,hudRightMargin:350,hudOffsetY:25,browserOverlayScale:1});
assert.equal(properties['--hud-safe-width'],'1170px');assert.equal(properties['--hud-safe-left'],'400px');
assert.equal(classes['hud-safe-layout'],true);assert(!Object.keys(properties).some(k=>k.includes('scale')));
const previous=changes;render(latestState);assert.equal(changes,previous);
for(const scale of [.75,1,1.5,2]){
 for(const margin of [0,3,8,40]){
  const bottom=hudSafeGeometry({hudDock:'bottom',hudBottomMarginPct:margin,browserOverlayScale:scale});
  assert(Math.abs(40+bottom.y+134*scale-(1080-margin*10.8))<1e-6);
 }
}
assert.equal(hudSafeGeometry({hudDock:'bottom',hudOffsetY:700}).y,hudSafeGeometry({hudDock:'bottom',hudOffsetY:0}).y);
render({hudDock:'bottom'});assert.equal(classes['hud-safe-layout'],true);
render({hudDock:'top'});assert.equal(classes['hud-safe-layout'],false);
geometry=hudSafeGeometry({hudLeftMargin:600,hudRightMargin:600,browserOverlayScale:2});
assert(geometry.width>=1304);assert(Math.abs(geometry.left-geometry.right)<1e-6);
for(const width of [280,310,400,510,660,860]){
 for(const damage of [80,150,320]){
  const g=hudInnerGeometry({roundDamageWidth:damage},width);
  assert(g.damage<=width-g.start-g.end);
  assert.equal(g.nameEnd,10);
  assert(g.damageStart+g.damage<g.start);
  assert.equal(g.damageTop,104); // Portrait bottom 98 + 6px gap.
  assert.equal(g.damageStart+g.damage/2,51); // Portrait center -10 + 122/2.
 }
}
assert.equal(hudInnerGeometry({},280).stacked,true);
assert.equal(hudInnerGeometry({},860).stacked,false);
geometry=hudSafeGeometry({hudLeftMargin:600,hudRightMargin:600,browserOverlayScale:1});
assert(geometry.width>=652);
const large=hudSafeGeometry({hudLeftMarginPct:45,hudRightMarginPct:45,hudPortraitPct:100});
const small=hudSafeGeometry({hudLeftMarginPct:45,hudRightMarginPct:45,hudPortraitPct:30});
assert(small.width<large.width);assert(small.width>=481.2-1e-6);
for(const pct of [30,50,65,80,100]){
 const frame=hudSafeGeometry({hudLeftMarginPct:45,hudRightMarginPct:45,hudPortraitPct:pct});
 const width=frame.width/2-100,g=hudInnerGeometry({hudPortraitPct:pct},width),portrait=122*pct/100;
 assert(width-g.start-10>=99.99); // Keep the minimum text/gauge region intact.
 assert(Math.abs(g.damageTop-(-24+portrait+6))<1e-6);
 assert(Math.abs(g.damageStart+g.damage/2-(-10+portrait/2))<1e-6);
 assert(g.damageStart+g.damage<g.start);
}
render({});assert.equal(classes['hud-safe-layout'],false);
// At 350px margins the player panels narrow, not their full-width HUD parent.
geometry=hudSafeGeometry({hudLeftMargin:350,hudRightMargin:350});
assert.equal(geometry.width/2-100,510);
const pctGeometry=hudSafeGeometry({hudLeftMarginPct:350/19.2,hudRightMarginPct:350/19.2});
assert.deepEqual(pctGeometry,geometry);
for(const viewportWidth of [1280,1920,2560,3840]){
 const physicalMargin=pctGeometry.left*(viewportWidth/1920);
 assert(Math.abs(physicalMargin/viewportWidth-350/1920)<1e-9);
}
assert.equal(properties['--hud-safe-right'],'0px');
let fontWrites=0;const label={clientWidth:154,scrollWidth:190,textContent:'TOTAL DAMAGE 12345',dataset:{},
 style:{removeProperty:()=>{},setProperty:(k,v)=>{assert.equal(k,'--hud-total-fitted-size');assert(parseFloat(v)<12);fontWrites++}}};
function getComputedStyle(){return {fontSize:'12px'}}
hud.querySelectorAll=selector=>selector==='.side .total'?[label]:[];
fitHudTotalLabels(hud,{});assert.equal(fontWrites,1);
fitHudTotalLabels(hud,{});assert.equal(fontWrites,1); // No repeated layout/style writes.
label.textContent='TOTAL DAMAGE 99999';fitHudTotalLabels(hud,{});assert.equal(fontWrites,2);
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
