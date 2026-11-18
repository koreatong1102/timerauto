import unittest
import shutil
import subprocess

from browser_hit_effects import HIT_EFFECT_CSS, HIT_EFFECT_HTML, HIT_EFFECT_JS


class BrowserHitEffectsTests(unittest.TestCase):
    def test_uses_single_logical_canvas(self):
        self.assertIn('id="impactCanvas" width="1920" height="1080"', HIT_EFFECT_HTML)
        self.assertIn("width: 1920px", HIT_EFFECT_CSS)
        self.assertIn("height: 1080px", HIT_EFFECT_CSS)

    def test_effect_is_directional_not_circular_dom(self):
        source = HIT_EFFECT_CSS + HIT_EFFECT_HTML + HIT_EFFECT_JS
        self.assertNotIn("screenImpact", source)
        self.assertNotIn("radial-gradient", source)
        self.assertNotIn("border-radius:999px", source)
        self.assertIn("impactAngle", source)
        self.assertIn("impactBlade", source)
        self.assertIn("impactChevrons", source)

    def test_strength_and_special_hit_classes_are_distinct(self):
        for class_name in ("low", "mid", "high", "weak", "stun", "down"):
            self.assertIn(class_name, HIT_EFFECT_JS)
        self.assertIn("impactCracks", HIT_EFFECT_JS)

    def test_existing_settings_remain_connected(self):
        for setting in (
            "hitFxBaseSize",
            "hitFxDamageScale",
            "hitFxDurationMs",
            "hitFxPopMs",
            "hitFxOpacity",
            "hitFxGlow",
            "hitFxFillOpacity",
            "hitFxRingWidth",
            "hitFxTextScale",
            "hitFxShowText",
            "hitFxSpriteEnabled",
            "hitFxRingEnabled",
            "hitFxColorPreset",
        ):
            self.assertIn(setting, HIT_EFFECT_JS)

    def test_animation_runs_only_while_effects_are_active(self):
        self.assertIn("if(active.length)impactState.raf=requestAnimationFrame", HIT_EFFECT_JS)
        self.assertIn("if(!impactState.raf)impactState.raf=requestAnimationFrame", HIT_EFFECT_JS)
        self.assertIn("desynchronized:true", HIT_EFFECT_JS)

    @unittest.skipUnless(shutil.which('node'), 'JavaScript runtime')
    def test_special_effects_execute_classify_and_remain_bounded(self):
        harness = r'''
const assert=require('assert');let calls=0,clock=100,scheduled=0;
const ctx=new Proxy({}, {get:(obj,key)=>obj[key]||(()=>{calls++})});
var latestState={hitFxLatencyLog:false,hitFxRingEnabled:true},lastSeq=0;
function q(){return {getContext:()=>ctx}}
var performance={now:()=>clock};function requestAnimationFrame(){scheduled++;return scheduled}
'''
        checks = r'''
assert.equal(impactCls({isCounter:true,damage:30,weakPoint:'Chin'}),'counter');
assert.equal(impactCls({counterMult:1.5,isCounter:false,damage:30}),'mid');
assert.equal(impactCls({counterMult:1.5,damage:30}),'mid');
assert.equal(impactLabel({isCounter:false,counterMult:1.5},30),'30');
assert.equal(impactCls({isCounter:true,effectKind:'stun'}),'stun');
assert.equal(impactCls({isCounter:true,effectKind:'knockdown'}),'down');
for(const kind of ['counter','stun']){
 clock+=100;impactState.effects=[];
 showScreenImpact({id:clock,screenX:.5,screenY:.5,damage:55,isCounter:kind==='counter',effectKind:kind});
 let e=impactState.effects[0];assert.equal(e.cls,kind);
 if(kind==='stun')assert.equal(e.label,'STUN');
 assert(e.duration>170&&e.duration<=1200);
 for(const t of [0,.1,.4,.8,1.1])drawScreenImpact(ctx,e,e.started+t*e.duration);
 e.spriteOn=false;e.ringOn=false;drawScreenImpact(ctx,e,e.started+30);
 assert.equal(drawScreenImpact(ctx,e,e.started+e.duration+1),false);
}
// A fast ordinary hit must not suppress the same contact's special upgrade.
clock+=100;impactState.effects=[];
showScreenImpact({screenX:.5,screenY:.5,damage:30});
clock+=1;showScreenImpact({screenX:.5,screenY:.5,isCounter:true,damage:30});
assert.equal(impactState.effects.length,1);assert.equal(impactState.effects[0].cls,'counter');
clock+=1;showScreenImpact({screenX:.5,screenY:.5,effectKind:'stun',damage:30});
assert.equal(impactState.effects.length,1);assert.equal(impactState.effects[0].cls,'stun');
for(let i=0;i<30;i++){clock+=20;showScreenImpact({screenX:.2,screenY:.2,isCounter:true,damage:40})}
assert.equal(impactState.effects.length,impactState.max);
renderImpactFrame(clock+2000);assert.equal(impactState.effects.length,0);
assert(calls>100);assert(scheduled<=1);
console.log('special effects executed');
'''
        result=subprocess.run(['node'],input=harness+HIT_EFFECT_JS+checks,text=True,
                              encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_settings_preview_plays_normal_counter_then_stun(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from timerauto import SettingsDialog
        app=SimpleNamespace(cfg=SimpleNamespace(),_spectator_timer_target=Mock(return_value=Mock()),
                            _push_browser_overlay_event=Mock(),_emit_spectator_test_update=Mock())
        timers=[]
        with patch('timerauto.QTimer.singleShot',side_effect=lambda ms,callback:timers.append((ms,callback))):
            SettingsDialog._test_spectator_hit_fx_sprite(app)
            for _,callback in timers:callback()
        events=[call.kwargs for call in app._push_browser_overlay_event.call_args_list]
        self.assertEqual([event['effectKind'] for event in events],['','counter','stun'])
        self.assertTrue(events[1]['isCounter'])
        self.assertFalse(events[2]['isCounter'])
        self.assertEqual([ms for ms,_ in timers],[600,1200])


if __name__ == "__main__":
    unittest.main()
