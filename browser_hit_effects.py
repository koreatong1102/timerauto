from __future__ import annotations

HIT_EFFECT_CSS = r"""
.impactLayer {
  position: absolute !important;
  inset: 0 !important;
  width: 1920px !important;
  height: 1080px !important;
  overflow: hidden !important;
  pointer-events: none !important;
  z-index: 999 !important;
  transform: none !important;
}
#impactCanvas {
  position: absolute;
  inset: 0;
  width: 1920px;
  height: 1080px;
  display: block;
  pointer-events: none;
}
.recent { display: none !important; }
"""

HIT_EFFECT_HTML = (
    '<div id="impactLayer" class="impactLayer">'
    '<canvas id="impactCanvas" width="1920" height="1080"></canvas>'
    "</div>"
)

HIT_EFFECT_JS = r"""
// Local, bounded canvas accents: no screen shake, DOM filters or asset loading.
function impactRank(cls){return {low:1,mid:2,high:3,weak:4,counter:5,stun:6,down:7}[cls]||0}
function impactSpecialCaption(ctx,e,age){
 var caption=e.caption;if(!caption||age>=caption.duration)return false;
 var stun=e.cls==='stun',t=Math.max(0,age/caption.duration);
 var pop=impactEaseOut(age/(stun?80:55)),rise=5*t;
 ctx.save();ctx.font=caption.font;ctx.textAlign='center';ctx.textBaseline='middle';
 if(caption.width===null)caption.width=ctx.measureText(caption.text).width;
 // Anchor beside the contact, reserving space for the widest pulse and outline.
 var marginX=caption.width*.57+16,marginY=caption.size*.85+10;
 var dir=e.x<960?1:-1,x=e.x+dir*Math.max(22,e.size*.36),offset=Math.max(34,e.size*.60);
 if(stun){x=e.x;offset=e.size*.98+caption.size*.53;}
 x=Math.max(marginX,Math.min(1920-marginX,x));
 var y=e.y-offset-rise;
 if(y<marginY)y=e.y+offset+rise;
 y=Math.max(marginY,Math.min(1080-marginY,y));
 ctx.translate(x,y);var scale=stun?1+.10*(1-pop):.86+.14*pop;ctx.scale(scale,scale);
 ctx.globalAlpha=Math.min(1,e.opacity)*Math.min(1,(1-t)/.32);
 ctx.lineJoin='round';ctx.lineWidth=stun?5:4;ctx.strokeStyle='#090d17';ctx.strokeText(caption.text,0,0);
 ctx.lineWidth=stun?2.1:1.3;ctx.strokeStyle=impactRgba(e.base,.92);ctx.strokeText(caption.text,0,0);
 ctx.shadowColor=impactRgba(e.base,.95);ctx.shadowBlur=stun?8:6;ctx.fillStyle=stun?'#ffe8dc':'#edfcff';
 ctx.fillText(caption.text,0,0);ctx.restore();return true;
}
function impactCaption(cls,scale){
 if(latestState.hitFxShowSpecialText===false||(cls!=='stun'&&cls!=='counter'))return null;
 var stun=cls==='stun',size=Math.max(20,Math.min(64,(stun?36:30)*scale));
 return {text:stun?'STUN':'COUNTER',size:size,duration:stun?450:300,width:null,
         font:(stun?'':'italic ')+'900 '+size+'px "Bahnschrift Condensed","Arial Narrow",sans-serif'};
}
function impactTiming(cls,ms){return Math.min(1200,Math.round(ms*(cls==='stun'?2.1:cls==='counter'?1.35:1)))}
function impactCounterCut(ctx,e,t,burst,alpha){
 var s=e.size,k=impactEaseOut(Math.min(1,t*3.5)),tail=1-t;
 ctx.save();ctx.translate(e.x,e.y);ctx.rotate(e.angle);
 ctx.shadowColor=impactRgba(e.base,.8);ctx.shadowBlur=9*e.glow;
 // Two asymmetric knife-like cuts converge at the contact point, then recoil.
 for(var i=0;i<2;i++){
  ctx.save();ctx.rotate(i===0?-.20:.58);var reach=s*(.55+k*.85)*(i? .62:1),w=s*(.025+.018*tail);
  impactPoly(ctx,[[-reach,-w],[s*.24,-w*.3],[s*.48,0],[-reach*.85,w]],impactRgba(e.base,alpha*(i?.65:.95)));
  impactPoly(ctx,[[-reach*.7,-w*.25],[s*.45,0],[-reach*.5,w*.22]],impactRgba(e.hot,alpha));ctx.restore();
 }
 if(e.ringOn){
  ctx.shadowBlur=5*e.glow;ctx.lineWidth=e.ringWidth;ctx.strokeStyle=impactRgba(e.hot,alpha*.75);
  var r=s*(.24+k*.40);ctx.beginPath();ctx.moveTo(-r,0);ctx.lineTo(0,-r*.65);ctx.lineTo(r,0);ctx.lineTo(0,r*.65);ctx.closePath();ctx.stroke();
 }
 if(e.spriteOn){
  ctx.shadowBlur=0;ctx.lineWidth=Math.max(1,s*.014);
  for(var j=0;j<9;j++){
   var a=(impactRand(e.seed+j*7)-.5)*1.6,dist=s*(.22+k*(.5+impactRand(e.seed+j*11))),x=-Math.cos(a)*dist,y=Math.sin(a)*dist;
   ctx.strokeStyle=impactRgba(j%3?e.base:e.hot,alpha*(1-t)*.9);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-s*(.1+tail*.16),y+s*.03);ctx.stroke();
  }
 }
 ctx.restore();impactCore(ctx,e,burst,alpha);
}
function impactStunLight(ctx,r,stops){
 var g=ctx.createRadialGradient(0,0,0,0,0,r);
 for(var stop of stops)g.addColorStop(stop[0],impactRgba(stop[1],stop[2]));
 return g;
}
function impactStunFilaments(seed){
 var layers=[];
 for(var layer=0;layer<3;layer++){
  var rays=[],count=[21,37,49][layer];
  for(var i=0;i<count;i++){
   var n=seed+layer*991+i*31,a=(i+impactRand(n)*.9)*Math.PI*2/count;
   var envelope=1+.09*Math.cos(5*a+.4)+.06*Math.sin(9*a);
   rays.push({dx:Math.cos(a),dy:Math.sin(a),inner:.38+impactRand(n+1)*.36,
              outer:(1.02+impactRand(n+2)*.67)*envelope,
              width:[.12,.045,.011][layer]*(.45+impactRand(n+3)*.85),
              bow:(impactRand(n+4)-.5)*.13});
  }
  layers.push(rays);
 }
 return layers;
}
function impactStunBurst(ctx,e,t,alpha){
 var p=impactEaseOut(t*2.05),r=e.size*(.43+.76*p);
 var ivory={r:255,g:248,b:230},rose=impactMix(e.base,.66),lilac={r:202,g:158,b:241},peach={r:255,g:180,b:136};
 var a=alpha*Math.min(1,(1-t)*3.6),flash=Math.max(0,1-t*4.5);
 ctx.save();ctx.translate(e.x,e.y);ctx.rotate(e.angle*.18);
 if(e.spriteOn){
  // Two soft, feathered bands give the colored fringe a warm outside and a cool inside.
  var halo=impactStunLight(ctx,r*1.76,[[0,rose,0],[.25,rose,.04*a],[.39,lilac,.26*a],
   [.51,lilac,.48*a],[.63,rose,.69*a],[.74,ivory,.42*a],[.85,peach,.30*a],[1,peach,0]]);
  var b=r*1.76;ctx.fillStyle=halo;ctx.fillRect(-b,-b,b*2,b*2);
  var rays=e.stunFilaments||(e.stunFilaments=impactStunFilaments(e.seed));
  for(var layer=0;layer<rays.length;layer++){
   var hue=layer===0?peach:layer===1?rose:lilac;
   var strength=[.56,.8,.72][layer]*a;
   ctx.fillStyle=impactStunLight(ctx,r*1.78,[[0,ivory,0],[.24,hue,0],[.46,hue,strength*.32],
    [.61,ivory,strength],[.73,ivory,strength*.68],[.89,hue,strength*.24],[1,hue,0]]);
   ctx.beginPath();
   for(var ray of rays[layer]){
    var dx=ray.dx,dy=ray.dy,px=-dy,py=dx,inner=ray.inner*r,outer=ray.outer*r;
    var w=ray.width*r,m=(inner+outer)*.51,bow=ray.bow*r;
    ctx.moveTo(dx*inner,dy*inner);
    ctx.quadraticCurveTo(dx*m+px*(w+bow),dy*m+py*(w+bow),dx*outer+px*bow,dy*outer+py*bow);
    ctx.quadraticCurveTo(dx*m+px*(bow-w),dy*m+py*(bow-w),dx*inner,dy*inner);
    ctx.closePath();
   }
   if(layer===0&&e.glow>0){ctx.shadowColor=impactRgba(rose,.55*a);ctx.shadowBlur=5*Math.min(2,e.glow);}
   ctx.fill();ctx.shadowBlur=0;
  }
 }
 if(e.ringOn){
  // Small luminous insignia inside the much wider, irregular burst.
  var crest=r*.64,w=Math.max(1.3,e.ringWidth*.74),mark=a*Math.max(0,1-t*.52);
  ctx.beginPath();ctx.arc(0,0,crest,0,Math.PI*2);ctx.lineWidth=w+2.3;
  ctx.strokeStyle=impactRgba(e.base,mark*.67);ctx.stroke();
  ctx.lineWidth=w;ctx.strokeStyle=impactRgba(ivory,mark);ctx.shadowColor=impactRgba(rose,.85);
  ctx.shadowBlur=6*e.glow;ctx.stroke();
  ctx.shadowBlur=0;ctx.beginPath();ctx.arc(0,0,crest*.55,.22,Math.PI*2-.17);
  ctx.lineWidth=Math.max(1,w*.78);ctx.strokeStyle=impactRgba(ivory,mark*.82);ctx.stroke();
  ctx.beginPath();
  for(var n=0;n<5;n++){
   var start=n*Math.PI*2/5+t*.22,outer=r*(1.01+.02*(n%2));
   ctx.moveTo(Math.cos(start)*outer,Math.sin(start)*outer);
   ctx.arc(0,0,outer,start,start+(.41+.13*(n%3)));
  }
  ctx.lineWidth=Math.max(1,w*.42);ctx.strokeStyle=impactRgba(lilac,a*.73);ctx.stroke();
  if(e.fill>0){
   ctx.beginPath();
   for(var j=0;j<5;j++){
    var ang=-Math.PI/2+j*Math.PI*2/5,dx=Math.cos(ang),dy=Math.sin(ang),h=crest*.155;
    var tip=crest*[1.02,.82,.91,.72,.88][j],gap=h*.76;
    ctx.moveTo(dx*gap-dy*h,dy*gap+dx*h);ctx.lineTo(dx*tip,dy*tip);ctx.lineTo(dx*gap+dy*h,dy*gap-dx*h);ctx.closePath();
   }
   ctx.fillStyle=impactRgba(ivory,mark*Math.min(1,e.fill)*(.69+.25*flash));ctx.fill();
  }
 }
 if(flash>0&&e.fill>0){
  var c=r*.16;
  impactPoly(ctx,[[0,-c],[c,0],[0,c],[-c,0]],impactRgba(ivory,flash*alpha*e.fill*.8));
 }
 ctx.restore();
}
function impactNum(v){var n=Number(v);return isFinite(n)?n:null}
function impactClamp(v){v=Number(v)||0;return Math.max(0,Math.min(1,v))}
var impactState={lastAt:0,lastX:-10,lastY:-10,max:10,effects:[],raf:0,ctx:null};
function overlayBeacon(event,extra){try{extra=extra||{};var p=new URLSearchParams();p.set('event',String(event||''));p.set('seq',String(lastSeq||0));if(extra.key)p.set('key',String(extra.key).slice(0,240));if(extra.browserMs!=null)p.set('browserMs',String(extra.browserMs));if(extra.pushMs!=null)p.set('pushMs',String(extra.pushMs));for(var name of ['position','duration','speed','muted','errorCode'])if(extra[name]!=null)p.set(name,String(extra[name]).slice(0,100));fetch('/beacon?'+p.toString(),{cache:'no-store',keepalive:true}).catch(function(){})}catch(e){}}
function impactPos(ev){var sx=impactNum(ev&&ev.screenX),sy=impactNum(ev&&ev.screenY);if(sx===null||sy===null)return null;return{x:impactClamp(sx),y:impactClamp(1-sy)}}
function impactCounter(ev){if(ev&&typeof ev.isCounter==='boolean')return ev.isCounter;return String(ev&&ev.effectKind||'').toLowerCase()==='counter'}
function impactCls(ev){var dmg=Number(ev&&ev.damage)||0,k=String(ev&&ev.effectKind||'').toLowerCase(),w=String(ev&&ev.weakPoint||'').toLowerCase();if(k.indexOf('knock')>=0||k==='tko'||k==='down')return'down';if(k.indexOf('stun')>=0)return'stun';if(impactCounter(ev))return'counter';if(w&&w!=='none')return'weak';if(dmg>=60)return'high';if(dmg>=28)return'mid';return'low'}
function impactCfgNum(v,f,minv,maxv){v=Number(v);if(!isFinite(v))v=f;if(minv!==undefined)v=Math.max(minv,v);if(maxv!==undefined)v=Math.min(maxv,v);return v}
function impactSize(cls,dmg){var base=impactCfgNum(latestState.hitFxBaseSize,86,24,240),scale=impactCfgNum(latestState.hitFxDamageScale,.42,0,3),mult={low:.82,mid:1.04,high:1.25,weak:1.16,counter:1.20,stun:1.42,down:1.58}[cls]||1;return Math.max(30,Math.min(260,base*mult+(Number(dmg)||0)*scale))}
function impactHex(v,f){v=String(v||'').trim();return /^#[0-9a-fA-F]{6}$/.test(v)?v:f}
function impactRgb(hex){hex=impactHex(hex,'#ffaa55');return{r:parseInt(hex.slice(1,3),16),g:parseInt(hex.slice(3,5),16),b:parseInt(hex.slice(5,7),16)}}
function impactMix(rgb,t){return{r:Math.round(rgb.r+(255-rgb.r)*t),g:Math.round(rgb.g+(255-rgb.g)*t),b:Math.round(rgb.b+(255-rgb.b)*t)}}
function impactRgba(rgb,a){return'rgba('+rgb.r+','+rgb.g+','+rgb.b+','+Math.max(0,Math.min(1,a))+')'}
function impactPresetColor(cls){var preset=String(latestState.hitFxColorPreset||'classic').toLowerCase(),map={classic:{counter:'#67e8f9',low:'#38bdf8',mid:'#fb923c',high:'#f87171',weak:'#facc15',stun:'#ef4444',down:'#ef4444'},icefire:{counter:'#a5f3fc',low:'#60a5fa',mid:'#f59e0b',high:'#ef4444',weak:'#fde047',stun:'#dc2626',down:'#dc2626'},neon:{counter:'#c4b5fd',low:'#22d3ee',mid:'#a3e635',high:'#fb7185',weak:'#facc15',stun:'#f97316',down:'#ef4444'},custom:{counter:impactHex(latestState.hitFxColorLow,'#67e8f9'),low:impactHex(latestState.hitFxColorLow,'#38bdf8'),mid:impactHex(latestState.hitFxColorMid,'#fb923c'),high:impactHex(latestState.hitFxColorHigh,'#f87171'),weak:impactHex(latestState.hitFxColorWeak,'#facc15'),stun:impactHex(latestState.hitFxColorStun,'#ef4444'),down:impactHex(latestState.hitFxColorStun,'#ef4444')}};var pal=map[preset]||map.classic;return pal[cls]||pal.high}
function impactRand(seed){var x=Math.sin(seed*12.9898+78.233)*43758.5453;return x-Math.floor(x)}
function impactEaseOut(v){v=Math.max(0,Math.min(1,v));return 1-Math.pow(1-v,3)}
function impactAngle(ev,seed){var side=String(ev&&ev.side||'').toLowerCase(),hand=String(ev&&ev.hand||ev&&ev.punchHand||'').toLowerCase(),punch=String(ev&&ev.punch||ev&&ev.punchType||ev&&ev.type||'').toLowerCase(),a=side==='blue'?Math.PI:0;if(punch.indexOf('upper')>=0)a=side==='blue'?-2.15:-.99;else if(punch.indexOf('hook')>=0)a=side==='blue'?-2.78:-.36;else if(punch.indexOf('over')>=0)a=side==='blue'?2.62:.52;if(hand.indexOf('left')>=0)a-=.10;else if(hand.indexOf('right')>=0)a+=.10;return a+(impactRand(seed)-.5)*.18}
function impactLabel(ev,dmg){if(dmg>0)return String(Math.round(dmg));var weak=String(ev&&ev.weakPoint||'').trim();return weak&&weak.toLowerCase()!=='none'?weak.slice(0,8):'HIT'}
function impactParticles(cls,seed,angle,size){var count={low:5,mid:8,high:12,weak:10,stun:15,down:18}[cls]||8,out=[];for(var i=0;i<count;i++){var r1=impactRand(seed+i*7.13),r2=impactRand(seed+i*13.71),spread=(r1-.5)*(cls==='stun'?2.0:1.35);out.push({a:angle+spread,len:size*(.28+r2*.78),width:Math.max(1.2,size*(.012+r1*.024)),speed:.72+r2*.65,spin:(r1-.5)*.8})}return out}
function impactCanvasContext(){if(impactState.ctx)return impactState.ctx;var c=q('impactCanvas');if(!c)return null;impactState.ctx=c.getContext('2d',{alpha:true,desynchronized:true});return impactState.ctx}
function impactPoly(ctx,points,fill){ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);for(var i=1;i<points.length;i++)ctx.lineTo(points[i][0],points[i][1]);ctx.closePath();ctx.fillStyle=fill;ctx.fill()}
function impactBlade(ctx,e,burst,alpha){var size=e.size,dx=Math.cos(e.angle),dy=Math.sin(e.angle),px=-dy,py=dx,tail=size*(.58+burst*.82),head=size*(.18+burst*.18),wide=size*(.055+burst*.035),base=e.base,hot=e.hot;ctx.save();ctx.translate(e.x,e.y);ctx.globalCompositeOperation='source-over';ctx.shadowColor=impactRgba(base,.9*alpha);ctx.shadowBlur=12*e.glow;impactPoly(ctx,[[-dx*tail+px*wide,-dy*tail+py*wide],[dx*head+px*wide*.22,dy*head+py*wide*.22],[dx*head*1.55,dy*head*1.55],[-dx*tail-px*wide,-dy*tail-py*wide]],impactRgba(base,.9*alpha));impactPoly(ctx,[[-dx*tail*.62+px*wide*.28,-dy*tail*.62+py*wide*.28],[dx*head*1.3,dy*head*1.3],[-dx*tail*.62-px*wide*.28,-dy*tail*.62-py*wide*.28]],impactRgba(hot,.98*alpha));ctx.restore()}
function impactCore(ctx,e,burst,alpha){var s=e.size*(.16+.22*burst),a=e.angle,dx=Math.cos(a),dy=Math.sin(a),px=-dy,py=dx,base=e.base,hot=e.hot;ctx.save();ctx.translate(e.x,e.y);ctx.globalCompositeOperation='source-over';ctx.shadowColor=impactRgba(base,.95*alpha);ctx.shadowBlur=(10+e.size*.12)*e.glow;impactPoly(ctx,[[dx*s*1.55,dy*s*1.55],[px*s*.34,py*s*.34],[-dx*s*.9,-dy*s*.9],[-px*s*.34,-py*s*.34]],impactRgba(hot,e.fill*alpha));impactPoly(ctx,[[dx*s*.78,dy*s*.78],[px*s*.16,py*s*.16],[-dx*s*.42,-dy*s*.42],[-px*s*.16,-py*s*.16]],impactRgba({r:255,g:255,b:255},.95*alpha));ctx.restore()}
function impactShards(ctx,e,burst,alpha){if(!e.spriteOn)return;ctx.save();ctx.translate(e.x,e.y);ctx.globalCompositeOperation='source-over';ctx.shadowColor=impactRgba(e.base,.78*alpha);ctx.shadowBlur=6*e.glow;for(var i=0;i<e.particles.length;i++){var p=e.particles[i],travel=p.len*impactEaseOut(Math.min(1,burst*p.speed)),ca=Math.cos(p.a),sa=Math.sin(p.a),tip=travel,tail=Math.max(3,travel-e.size*(.12+.22*(1-burst))),w=p.width*(1-burst*.45);impactPoly(ctx,[[ca*tip,sa*tip],[ca*tail-sa*w,sa*tail+ca*w],[ca*(tail-e.size*.05),sa*(tail-e.size*.05)],[ca*tail+sa*w,sa*tail-ca*w]],impactRgba(i%3===0?e.hot:e.base,(.94-i/e.particles.length*.25)*alpha))}ctx.restore()}
function impactChevrons(ctx,e,burst,alpha){if(!e.ringOn)return;var dist=e.size*(.20+.55*burst),span=e.size*(.18+.16*burst),a=e.angle,dx=Math.cos(a),dy=Math.sin(a),px=-dy,py=dx,lw=e.ringWidth;ctx.save();ctx.translate(e.x,e.y);ctx.globalCompositeOperation='source-over';ctx.lineCap='square';ctx.lineJoin='miter';ctx.strokeStyle=impactRgba(e.hot,.9*alpha);ctx.lineWidth=lw;ctx.shadowColor=impactRgba(e.base,.82*alpha);ctx.shadowBlur=8*e.glow;for(var sign=-1;sign<=1;sign+=2){var cx=px*dist*sign,cy=py*dist*sign;ctx.beginPath();ctx.moveTo(cx-dx*span-px*span*.26*sign,cy-dy*span-py*span*.26*sign);ctx.lineTo(cx+px*span*.20*sign,cy+py*span*.20*sign);ctx.lineTo(cx+dx*span-px*span*.26*sign,cy+dy*span-py*span*.26*sign);ctx.stroke()}ctx.restore()}
function impactCracks(ctx,e,burst,alpha){if(e.cls!=='weak'&&e.cls!=='stun'&&e.cls!=='down')return;var branches=e.cls==='weak'?5:8;ctx.save();ctx.translate(e.x,e.y);ctx.globalCompositeOperation='source-over';ctx.strokeStyle=impactRgba(e.hot,.94*alpha);ctx.lineWidth=Math.max(1.3,e.ringWidth*.55);ctx.shadowColor=impactRgba(e.base,.9*alpha);ctx.shadowBlur=7*e.glow;for(var i=0;i<branches;i++){var a=e.angle+(i/(branches-1)-.5)*(e.cls==='weak'?2.2:3.5)+(impactRand(e.seed+i*23)-.5)*.35,len=e.size*(.18+.42*impactRand(e.seed+i*31))*burst,x1=Math.cos(a)*len*.42,y1=Math.sin(a)*len*.42,x2=Math.cos(a+.18*(i%2?1:-1))*len,y2=Math.sin(a+.18*(i%2?1:-1))*len;ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke()}ctx.restore()}
function impactText(ctx,e,burst,alpha){if(!e.showText)return;var side=String(e.side||'').toLowerCase(),dir=side==='blue'?1:-1,x=e.x+dir*e.size*.28,y=e.y-e.size*.38,fontSize=Math.max(20,Math.min(58,e.size*.27*e.textScale)),kick=(1-burst)*e.size*.18;ctx.save();ctx.translate(x+dir*kick,y);ctx.scale(.84+.16*burst,.84+.16*burst);ctx.globalAlpha=Math.min(1,alpha*1.08);ctx.font='900 '+fontSize.toFixed(1)+'px "Bahnschrift Condensed","Arial Narrow",sans-serif';ctx.textAlign=side==='blue'?'left':'right';ctx.textBaseline='middle';ctx.lineJoin='miter';ctx.miterLimit=3;ctx.strokeStyle='rgba(0,0,0,.92)';ctx.lineWidth=Math.max(3,fontSize*.16);ctx.strokeText(e.label,0,0);ctx.shadowColor=impactRgba(e.base,.95);ctx.shadowBlur=10*e.glow;ctx.fillStyle=impactRgba(e.hot,1);ctx.fillText(e.label,0,0);ctx.restore()}
function drawScreenImpact(ctx,e,now){
 var age=now-e.started,dur=e.duration;
 if(age<dur){
  var t=impactClamp(age/dur),burst=impactEaseOut(age/e.popMs),fade=t<.42?1:Math.max(0,(1-t)/.58),alpha=Math.min(1,e.opacity)*fade;
  if(e.cls==='counter')impactCounterCut(ctx,e,t,burst,alpha);
  else if(e.cls==='stun')impactStunBurst(ctx,e,t,alpha);
  else{
   impactBlade(ctx,e,burst,alpha);impactChevrons(ctx,e,burst,alpha);impactShards(ctx,e,burst,alpha);
   impactCracks(ctx,e,burst,alpha);impactCore(ctx,e,burst,alpha);impactText(ctx,e,burst,alpha);
  }
 }
 var captionActive=impactSpecialCaption(ctx,e,age);
 return age<dur||captionActive;
}
function renderImpactFrame(now){impactState.raf=0;var ctx=impactCanvasContext();if(!ctx)return;ctx.clearRect(0,0,1920,1080);var active=[];for(var i=0;i<impactState.effects.length;i++){var e=impactState.effects[i];if(drawScreenImpact(ctx,e,now))active.push(e)}impactState.effects=active;if(active.length)impactState.raf=requestAnimationFrame(renderImpactFrame)}
function showScreenImpact(ev){var p=impactPos(ev),ctx=impactCanvasContext();if(!p||!ctx)return;var now=(performance&&performance.now)?performance.now():Date.now();var cls=impactCls(ev),rank=impactRank(cls),same=now-impactState.lastAt<16&&Math.abs(p.x-impactState.lastX)<.008&&Math.abs(p.y-impactState.lastY)<.012;if(same&&rank<=impactRank(impactState.lastCls))return;if(same&&impactState.effects.length)impactState.effects.pop();impactState.lastCls=cls;impactState.lastAt=now;impactState.lastX=p.x;impactState.lastY=p.y;var dmg=Number(ev&&ev.damage)||0,dur=Math.round(impactCfgNum(latestState.hitFxDurationMs,170,80,1200)),popMs=Math.round(impactCfgNum(latestState.hitFxPopMs,58,20,280)),seed=(Number(ev&&ev.id)||0)*37+dmg*11+(p.x*991+p.y*577),base=impactRgb(impactPresetColor(cls)),e={x:p.x*1920,y:p.y*1080,side:String(ev&&ev.side||''),cls:cls,damage:dmg,duration:dur,popMs:Math.min(popMs,dur*.72),started:now,seed:seed,size:impactSize(cls,dmg),angle:impactAngle(ev,seed),base:base,hot:impactMix(base,.78),opacity:impactCfgNum(latestState.hitFxOpacity,1,.05,1.5),glow:impactCfgNum(latestState.hitFxGlow,1,0,3),fill:impactCfgNum(latestState.hitFxFillOpacity,1,0,1.5),ringWidth:impactCfgNum(latestState.hitFxRingWidth,4,1,20),textScale:impactCfgNum(latestState.hitFxTextScale,1,.5,2),showText:latestState.hitFxShowText!==false,spriteOn:latestState.hitFxSpriteEnabled!==false,ringOn:latestState.hitFxRingEnabled!==false,label:cls==='stun'?'STUN':impactLabel(ev,dmg)};e.duration=impactTiming(cls,dur);e.caption=impactCaption(cls,e.textScale);e.particles=impactParticles(cls,seed,e.angle,e.size);impactState.effects.push(e);if(impactState.effects.length>impactState.max)impactState.effects.splice(0,impactState.effects.length-impactState.max);if(!impactState.raf)impactState.raf=requestAnimationFrame(renderImpactFrame);try{if(latestState.hitFxLatencyLog!==false&&console&&console.info){var showMs=(performance&&performance.now)?performance.now():Date.now(),pushMs=Number(ev&&ev.pushPerfMs)||0;console.info('[HITFX_BROWSER_SHOW] key='+(ev&&ev.hitfxKey||'')+' dmg='+dmg+' x='+p.x.toFixed(4)+' y='+p.y.toFixed(4)+' browser_show_ms='+showMs.toFixed(1)+' push_perf_ms='+pushMs.toFixed(1));overlayBeacon('hitfx_show',{key:(ev&&ev.hitfxKey)||'',browserMs:showMs.toFixed(1),pushMs:pushMs.toFixed(1)})}}catch(err){}}
"""
