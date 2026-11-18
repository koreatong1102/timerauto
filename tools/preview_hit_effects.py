"""Render a deterministic special-FX contact sheet, without live OBS/app access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_hit_effects import HIT_EFFECT_JS
from report_images import browser_executable


def render_preview(target, *, rings=True):
    browser=browser_executable()
    if not browser:raise RuntimeError('Edge/Chrome is required')
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    html='''<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;background:#0a101d;color:#d7e3f5;font:20px Arial}canvas{width:1600px;height:900px}
</style></head><body><canvas id="impactCanvas" width="1600" height="900"></canvas><script>
var latestState={hitFxLatencyLog:false,hitFxBaseSize:115,hitFxRingEnabled:true},lastSeq=0;
function q(id){return document.getElementById(id)}function requestAnimationFrame(){return 1}
''' + HIT_EFFECT_JS + '''
let ctx=q('impactCanvas').getContext('2d');ctx.fillStyle='#0a101d';ctx.fillRect(0,0,1600,900);
ctx.font='bold 26px Arial';ctx.fillStyle='#d7e3f5';ctx.fillText('COUNTER / STUN — IMPACT STUDY',54,54);
ctx.font='16px Arial';ctx.fillStyle='#7a8da9';ctx.fillText('Deterministic animation samples · ring layer enabled',54,86);
for(let row=0;row<2;row++)for(let col=0;col<3;col++){
 let x=270+col*530,y=280+row*390,t=[.13,.43,.78][col];
 if(row){ctx.fillStyle=['#171e2c','#377995','#96a9b4'][col];ctx.fillRect(x-240,y-145,480,310);}
 ctx.strokeStyle='#223047';ctx.lineWidth=1;ctx.strokeRect(x-240,y-145,480,310);
 ctx.fillStyle='#7a8da9';ctx.font='14px Arial';ctx.fillText((row?'STUN':'COUNTER')+' / '+Math.round(t*100)+'%',x-218,y-120);
 impactState.effects=[];impactState.lastAt=-100;
 showScreenImpact({id:7,screenX:x/1920,screenY:1-y/1080,side:'red',damage:55,isCounter:!row,effectKind:row?'stun':'hit'});
 let e=impactState.effects[0];drawScreenImpact(ctx,e,e.started+t*e.duration);
}
</script></body></html>'''
    if not rings:
        html=html.replace('hitFxRingEnabled:true','hitFxRingEnabled:false').replace('ring layer enabled','ring layer disabled')
    with tempfile.TemporaryDirectory(prefix='rfc_fx_preview_') as temp:
        page=Path(temp,'preview.html');page.write_text(html,encoding='utf-8')
        result=subprocess.run([browser,'--headless=new','--no-first-run','--no-default-browser-check',
            '--hide-scrollbars','--force-device-scale-factor=1','--window-size=1600,900',
            '--user-data-dir='+str(Path(temp,'profile')),'--screenshot='+str(target),page.as_uri()],
            capture_output=True,timeout=35,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not target.is_file():raise RuntimeError(result.stderr.decode('utf-8','replace'))
    print(target)


if __name__=='__main__':
    render_preview(sys.argv[1] if len(sys.argv)>1 else 'diagnostics/hit_effects_preview.png',
                   rings='--no-rings' not in sys.argv[2:])
