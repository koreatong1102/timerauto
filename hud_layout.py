"""Adjust only the in-fight browser HUD; fullscreen presentation stays put."""
import math

HUD_DEFAULTS = {"overlay_hud_left_margin":0, "overlay_hud_right_margin":0,
                "overlay_hud_y":0, "overlay_hud_link_sides":True,
                "overlay_hud_portrait_pct":100}


def hud_settings(source, overrides=None):
    values = {}
    for key, default in HUD_DEFAULTS.items():
        value = source.get(key,default) if isinstance(source,dict) else getattr(source,key,default)
        if overrides and key in overrides:
            value = overrides[key]
        if key == "overlay_hud_link_sides":
            values[key] = value if isinstance(value,bool) else default
            continue
        try:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError()
            low, high = ((-40,700) if key == "overlay_hud_y" else
                         (30,100) if key == "overlay_hud_portrait_pct" else (0,864))
            values[key] = max(low,min(high,int(value) if key == 'overlay_hud_y' else round(value,6)))
        except (TypeError,ValueError,OverflowError):
            values[key] = default
    if values["overlay_hud_link_sides"]:
        values["overlay_hud_right_margin"] = values["overlay_hud_left_margin"]
    return values


def hud_browser_state(source, overrides=None):
    values = hud_settings(source,overrides)
    return {"hudLeftMargin":values["overlay_hud_left_margin"],
            "hudRightMargin":values["overlay_hud_right_margin"],"hudOffsetY":values["overlay_hud_y"],
            "hudLeftMarginPct":values["overlay_hud_left_margin"]/19.2,
            "hudRightMarginPct":values["overlay_hud_right_margin"]/19.2,
            "hudPortraitPct":values["overlay_hud_portrait_pct"]}


def create_hud_layout_panel(cfg, changed, preview, parent=None):
    from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton
    class Panel(QGroupBox):
        def __init__(self):
            super().__init__("관전툴 UI 피하기 · 브라우저 경기 HUD",parent)
            layout = QGridLayout(self)
            explanation = QLabel("좌우 공간을 비우면 초상화·체력바·닉네임·데미지가 함께 안쪽으로 이동합니다.\n"
                                 "초상화 옆 빈틈을 줄이고, 라운드 데미지는 초상화 바로 아래에 표시합니다.\n"
                                 "좌우 여백은 화면 가로폭의 %입니다. 예: 18.23% ≈ 기존 350px 배치.\n"
                                 "카운터·콤보 위치는 유지합니다. 세로 이동만 1920×1080 기준 px입니다.\n"
                                 "VS·리포트·KO·POTM과 로컬 QML 창에는 적용하지 않습니다.")
            explanation.setWordWrap(True)
            layout.addWidget(explanation,0,0,1,4)
            self.controls = {}
            for row,(key,label) in enumerate((("overlay_hud_left_margin","왼쪽 비워둘 폭"),
                                               ("overlay_hud_right_margin","오른쪽 비워둘 폭"),
                                               ("overlay_hud_y","HUD 세로 이동 · + 아래 / − 위"),
                                               ("overlay_hud_portrait_pct","초상화 크기 · 기존 크기 대비")),1):
                vertical = key == 'overlay_hud_y'
                portrait = key == 'overlay_hud_portrait_pct'
                spin = QSpinBox() if vertical else QDoubleSpinBox()
                spin.setRange(*((-40,700) if vertical else (30,100) if portrait else (0,45)))
                spin.setSuffix(' px' if vertical else ' %')
                spin.setSingleStep(5 if vertical or portrait else .5)
                if not vertical:
                    spin.setDecimals(2)
                spin.setObjectName(key)
                self.controls[key] = spin
                layout.addWidget(QLabel(label),row,0,1,2)
                layout.addWidget(spin,row,2,1,2)
                spin.valueChanged.connect(lambda value,k=key:self.update_value(k,value))
            self.link = QCheckBox("좌우 동일하게 조절")
            self.link.setObjectName("overlay_hud_link_sides")
            self.link.toggled.connect(self.update_link)
            layout.addWidget(self.link,5,0,1,4)
            button = QPushButton("경기 없이 HUD 미리보기 열기")
            button.clicked.connect(preview)
            layout.addWidget(button,6,0,1,2)
            reset = QPushButton("기본 배치 복원")
            reset.clicked.connect(self.reset)
            layout.addWidget(reset,6,2,1,2)
            note = QLabel("미리보기는 별도 브라우저 화면에만 테스트 선수를 띄웁니다. 방송 화면이나 경기 기록은 바꾸지 않습니다.\n"
                          "초상화를 줄이면 체력바·닉네임도 가까이 붙고, 가로폭을 더 줄일 수 있습니다.\n"
                          "글자 영역이 최소 폭에 도달하면 여백이 제한됩니다. 스튜디오에서 별도로 바꾼 크기·위치도 확인하세요.")
            note.setWordWrap(True)
            layout.addWidget(note,7,0,1,4)
            self.reload()

        def reload(self):
            values = hud_settings(cfg)
            for key,spin in self.controls.items():
                spin.blockSignals(True);spin.setValue(values[key]/19.2 if key in ('overlay_hud_left_margin','overlay_hud_right_margin') else values[key]);spin.blockSignals(False)
            self.link.blockSignals(True);self.link.setChecked(values["overlay_hud_link_sides"]);self.link.blockSignals(False)
            self.controls["overlay_hud_right_margin"].setEnabled(not self.link.isChecked())

        def update_value(self,key,value):
            if key in ('overlay_hud_left_margin','overlay_hud_right_margin'):
                value = round(value*19.2,6)
            setattr(cfg,key,value)
            if self.link.isChecked() and key == "overlay_hud_left_margin":
                cfg.overlay_hud_right_margin = value
            self.reload()
            changed()

        def update_link(self,value):
            cfg.overlay_hud_link_sides = bool(value)
            if value:
                cfg.overlay_hud_right_margin = cfg.overlay_hud_left_margin
            self.reload()
            changed()

        def reset(self):
            for key,value in HUD_DEFAULTS.items():
                setattr(cfg,key,value)
            self.reload()
            changed()
    return Panel()


HUD_LAYOUT_CSS = r"""
#root > .hud{
  --hud-portrait-size:122px;--hud-content-start:116px;--hud-content-inset:126px;
}
#root > .hud .side .portrait,#root > .hud .side .portraitFxLayer{
  width:var(--hud-portrait-size)!important;height:var(--hud-portrait-size)!important;
}
#root > .hud .side:after{width:calc(var(--hud-portrait-size) + 2px)!important;}
#root > .hud .side.blue:before{left:var(--hud-content-start)!important;}
#root > .hud .side.red:before{right:var(--hud-content-start)!important;}
/* Scope the adjustment to the HUD, never #root/fullscreen siblings. */
#root > .hud.hud-safe-layout {
  left:0!important;top:0!important;
  width:calc(1920px / var(--ui-scale))!important;
}
/* Only player panels move. Combat feedback remains in the full-width HUD. */
#root > .hud.hud-safe-layout > .side{
  min-width:var(--hud-min-panel)!important;
  top:calc(var(--hud-safe-y) / var(--ui-scale))!important;
  width:calc(var(--hud-safe-width) / var(--ui-scale) / 2 - 100px)!important;
  max-width:calc(var(--hud-safe-width) / var(--ui-scale) / 2 - 100px)!important;
}
#root > .hud.hud-safe-layout > .side.blue{
  left:calc(20px + var(--hud-safe-left) / var(--ui-scale))!important;
}
#root > .hud.hud-safe-layout > .side.red{
  right:calc(20px + var(--hud-safe-right) / var(--ui-scale))!important;
}
#root > .hud.hud-safe-layout > .center{
  left:calc(50% + (var(--hud-safe-left) - var(--hud-safe-right)) / var(--ui-scale) / 2)!important;
  top:calc(-5px + var(--hud-safe-y) / var(--ui-scale))!important;
}
/* Portrait ends at 112px. Keep a 4px gap, not the old 16–20px gutter. */
#root > .hud .side .barWrap{inset-inline:auto!important;}
#root > .hud .side .spWrap{
  width:var(--hud-sp-width,calc(100% - var(--hud-content-inset)))!important;
  height:var(--hud-sp-thickness,10px)!important;
}
#root > .hud .side.blue .barWrap{left:var(--hud-content-start)!important;right:10px!important;}
#root > .hud .side.red .barWrap{right:var(--hud-content-start)!important;left:10px!important;}
#root > .hud .side.blue .total{left:var(--hud-content-start)!important;}
#root > .hud .side.red .total{right:var(--hud-content-start)!important;}
#root > .hud .side .total{
  white-space:nowrap!important;overflow-wrap:normal!important;word-break:normal!important;
  width:calc(100% - var(--hud-content-inset))!important;max-width:calc(100% - var(--hud-content-inset))!important;
  height:18px!important;line-height:18px!important;overflow:hidden!important;
  font-size:var(--hud-total-fitted-size,var(--bt-total-size))!important;
}
#root > .hud .side .name{clip-path:none!important;overflow:hidden!important;min-width:0!important;}
#root > .hud .side .nicknameText{
  white-space:normal!important;overflow-wrap:anywhere!important;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;
  line-height:20px!important;max-height:42px;
}
#root > .hud .side .playerGameId{max-width:100%;}
#root > .hud .side .dmg{
  text-align:center!important;width:var(--hud-round-damage-width,122px)!important;
  padding:3px 2px 0!important;
  font-size:min(var(--bt-dmg-size),calc(var(--hud-portrait-size) * .2))!important;
}
/* Keep the flag as a portrait-corner badge, clear of the damage row. */
#root > .hud .side .flag{top:var(--hud-flag-top,76px)!important;width:var(--hud-flag-width,34px)!important;height:var(--hud-flag-height,20px)!important;}
#root > .hud .side.blue .flag{left:var(--hud-flag-inset,78px)!important;right:auto!important;}
#root > .hud .side.red .flag{right:var(--hud-flag-inset,78px)!important;left:auto!important;}
body.hud-layout-preview{background:repeating-conic-gradient(#202b39 0 25%,#18212d 0 50%) 50%/32px 32px!important;}
.hudSafePreviewPanel{position:absolute;top:12px;height:145px;box-sizing:border-box;padding:15px;border:2px dashed #7dd3fc;border-radius:12px;color:white;background:rgba(56,100,170,.3);font:700 24px/1.5 sans-serif;overflow:hidden;z-index:5;}
#hudSafePreviewRight{right:0;border-color:#fda4af;background:rgba(170,60,56,.3);text-align:right;}
#hudSafePreviewNote{position:absolute;bottom:24px;left:15%;width:70%;box-sizing:border-box;padding:12px;background:rgba(0,0,0,.8);color:#fff;font:600 21px/1.4 sans-serif;text-align:center;z-index:10;}
"""

HUD_LAYOUT_JS = r"""
const hudLayoutPreview=new URLSearchParams(location.search).get('hudPreview')==='1';
function hudPortraitSize(s){
  const pct=Number(s.hudPortraitPct??100);
  return 122*(Number.isFinite(pct)?Math.max(30,Math.min(100,pct)):100)/100;
}
function hudSafeGeometry(s){
  const number=(v,lo,hi,fallback=0)=>{v=Number(v);return Number.isFinite(v)?Math.max(lo,Math.min(hi,v)):fallback};
  const scale=number(s.browserOverlayScale,.25,4,1)||1;
  // Percent is relative to the logical stage; viewport scaling preserves it at
  // 1280/1920/2560/3840 widths. Retain old state/config compatibility.
  let left=s.hudLeftMarginPct!=null?number(s.hudLeftMarginPct,0,45)*19.2:number(s.hudLeftMargin,0,864),
      right=s.hudRightMarginPct!=null?number(s.hudRightMarginPct,0,45)*19.2:number(s.hudRightMargin,0,864);
  const minWidth=2*(hudPortraitSize(s)+204);
  const maxTotal=Math.max(0,1920-Math.min(1920,minWidth*scale));
  if(left+right>maxTotal){const ratio=maxTotal/(left+right);left*=ratio;right*=ratio}
  return {left,right,width:1920-left-right,y:number(s.hudOffsetY,-40,700)};
}
function hudInnerGeometry(s,width){
  const clamp=(v,a,b,d)=>Number.isFinite(Number(v))?Math.max(a,Math.min(b,Number(v))):d;
  // Damage belongs to the portrait column, not the nameplate column.
  const portrait=hudPortraitSize(s),start=portrait-6;
  const damage=clamp(s.roundDamageWidth,Math.min(80,portrait),portrait,portrait);
  return {stacked:width-start-10<210,start,end:10,damage,
    damageStart:-10+(portrait-damage)/2,damageTop:portrait-18,nameEnd:10,
    nameX:clamp(s.nameBarX,-300,300,0),nameY:clamp(s.nameBarY,-100,100,0)};
}
function applyHudInnerLayout(s){
  const hud=document.querySelector('#root > .hud');if(!hud||!hud.querySelectorAll)return;
  let compact=false;
  for(const host of hud.querySelectorAll('.side')){
    const side=host.classList.contains('blue')?'blue':'red',g=hudInnerGeometry(s,host.clientWidth);
    compact=compact||g.stacked;
    const signature=JSON.stringify([host.clientWidth,g,s.spBarX,s.spBarY,s.spBarLengthPct,s.spBarThickness,s.spBarColor]);
    if(host.dataset.innerLayout===signature)continue;
    host.dataset.innerLayout=signature;
    const inward=side==='blue'?'left':'right',outward=side==='blue'?'right':'left';
    const set=(el,key,value)=>{if(el)el.style.setProperty(key,value,'important')};
    const name=host.querySelector('.name'),damage=host.querySelector('.dmg'),sp=host.querySelector('.spWrap');
    // Clamp optional legacy offsets to the available text region, too.
    const start=Math.max(g.start,Math.min(g.start+g.nameX,host.clientWidth-g.nameEnd-100));
    set(name,inward,start+'px');set(name,outward,g.nameEnd+'px');
    set(name,'top',(64+g.nameY)+'px');set(name,'width','auto');
    set(name,'max-height','70px');
    set(damage,'top',g.damageTop+'px');
    set(damage,inward,g.damageStart+'px');set(damage,outward,'auto');
    set(damage,'--hud-round-damage-width',g.damage+'px');set(damage,'box-sizing','border-box');
    const n=(v,a,b,d)=>Number.isFinite(Number(v))?Math.max(a,Math.min(b,Number(v))):d;
    const spStart=Math.max(g.start,Math.min(g.start+n(s.spBarX,-300,300,0),host.clientWidth-50));
    const available=Math.max(24,host.clientWidth-spStart-10);
    set(sp,inward,spStart+'px');set(sp,outward,'auto');
    set(sp,'--hud-sp-width',Math.min(available,available*n(s.spBarLengthPct,25,160,100)/100)+'px');
    set(sp,'top',(52+n(s.spBarY,-100,100,0))+'px');
    set(sp,'--hud-sp-thickness',n(s.spBarThickness,2,40,10)+'px');
    const fill=sp&&sp.querySelector('.spFill');
    const color=/^#[0-9a-f]{6}$/i.test(String(s.spBarColor||''))?s.spBarColor:'#1876d3';
    set(fill,'background','linear-gradient(180deg,rgba(255,255,255,.46) 0%,'+color+' 34%,'+color+' 66%,rgba(0,0,0,.58) 100%)');
  }
  hud.classList.toggle('hud-compact',compact);
}
function fitHudTotalLabels(hud,s){
  if(!hud.querySelectorAll)return;
  for(const el of hud.querySelectorAll('.side .total')){
    const signature=JSON.stringify([el.clientWidth,el.textContent,s.browserTextStyles]);
    if(el.dataset.totalFit===signature)continue;
    el.dataset.totalFit=signature;
    el.style.removeProperty('--hud-total-fitted-size');
    const base=parseFloat(getComputedStyle(el).fontSize)||12;
    // Measure the actual one-line label, including four/five-digit totals.
    if(el.clientWidth>0&&el.scrollWidth>el.clientWidth){
      el.style.setProperty('--hud-total-fitted-size',Math.max(1,base*(el.clientWidth-2)/el.scrollWidth)+'px','important');
    }
  }
}
// Replace the legacy writers so they cannot restore fixed offsets on each tick.
if(typeof applyNameBarLayout==='function')applyNameBarLayout=function(){};
if(typeof applyRoundDamageLayout==='function')applyRoundDamageLayout=function(){};
if(typeof applySpBarLayout==='function')applySpBarLayout=function(){};
function applyHudSafeLayout(s){
  const hud=document.querySelector('#root > .hud');if(!hud)return;
  const g=hudSafeGeometry(s||{}),active=g.left!==0||g.right!==0||g.y!==0;
  const portrait=hudPortraitSize(s||{}),signature=JSON.stringify([g,portrait]);
  if(hud.dataset.safeLayout!==signature){
    hud.dataset.safeLayout=signature;
    hud.classList.toggle('hud-safe-layout',active);
    hud.style.setProperty('--hud-safe-left',g.left+'px');
    hud.style.setProperty('--hud-safe-right',g.right+'px');
    hud.style.setProperty('--hud-safe-width',g.width+'px');
    hud.style.setProperty('--hud-safe-y',g.y+'px');
    hud.style.setProperty('--hud-portrait-size',portrait+'px');
    hud.style.setProperty('--hud-content-start',(portrait-6)+'px');
    hud.style.setProperty('--hud-content-inset',(portrait+4)+'px');
    hud.style.setProperty('--hud-min-panel',(portrait+104)+'px');
    const flagWidth=Math.min(34,portrait*.28),flagHeight=flagWidth*20/34;
    hud.style.setProperty('--hud-flag-width',flagWidth+'px');
    hud.style.setProperty('--hud-flag-height',flagHeight+'px');
    hud.style.setProperty('--hud-flag-top',(portrait-24-flagHeight-2)+'px');
    hud.style.setProperty('--hud-flag-inset',(portrait-10-flagWidth)+'px');
  }
  applyHudInnerLayout(s||{});
  fitHudTotalLabels(hud,s||{});
  if(!hudLayoutPreview)return;
  const root=document.getElementById('root');
  for(const [id,side,width] of [['hudSafePreviewLeft','left',g.left],['hudSafePreviewRight','right',g.right]]){
    let panel=document.getElementById(id);
    if(!panel){panel=document.createElement('div');panel.id=id;panel.className='hudSafePreviewPanel';panel.textContent=(side==='left'?'관전툴 왼쪽 정보':'관전툴 오른쪽 정보');root.appendChild(panel)}
    panel.style.width=width+'px';panel.hidden=width<1;
  }
  let note=document.getElementById('hudSafePreviewNote');
  if(!note){note=document.createElement('div');note.id='hudSafePreviewNote';root.appendChild(note)}
  note.textContent='HUD 배치 미리보기 · 실제 경기/방송에 테스트 데이터를 보내지 않습니다. 왼쪽 '+(g.left/19.2).toFixed(2)+'% / 오른쪽 '+(g.right/19.2).toFixed(2)+'% · 라운드 데미지는 초상화 아래에 표시하며 최소 가독 폭에서 여백을 제한합니다.';
}
function hudPreviewState(s){
  const preview=Object.assign({},s,{blueName:'BLUE PLAYER',redName:'RED PLAYER',bluePlayerId:'BLUE_GAME_ID',redPlayerId:'RED_GAME_ID',
    timeText:'2:15',roundText:'RD 1 OF 3',blueDamageText:'DMG 128',redDamageText:'DMG 96',blueTotalDamageText:'328',redTotalDamageText:'296',
    blueHpRatio:.78,redHpRatio:.65,blueHpGhostRatio:0,redHpGhostRatio:0,blueSpRatio:.82,redSpRatio:.71,
    blueHasImage:true,redHasImage:true,showBlueImage:true,showRedImage:true,showBlueName:true,showRedName:true,showTime:true,showRound:true,
    blueRoundKnockdowns:1,redRoundKnockdowns:0,blueComboHitText:'',redComboHitText:'',events:[],potmIntro:{},potmIntroRev:0,
    obsReplayActive:false,idleHighlightEnabled:false});
  return preview;
}
if(hudLayoutPreview)document.body.classList.add('hud-layout-preview');
const renderBeforeHudLayout=render;
render=function(s){
  const state=hudLayoutPreview?hudPreviewState(s||{}):s;
  renderBeforeHudLayout(state);
  applyHudSafeLayout(typeof latestState!=='undefined'&&latestState?latestState:state);
  if(hudLayoutPreview){
    for(const side of ['blue','red']){
      const img=document.getElementById(side+'Img');if(!img)continue;
      const color=side==='blue'?'#38bdf8':'#fb7185';
      const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120"><circle cx="50" cy="31" r="24" fill="'+color+'"/><path d="M5 120V96Q5 60 50 60Q95 60 95 96V120Z" fill="'+color+'"/></svg>';
      const url='data:image/svg+xml,'+encodeURIComponent(svg);if(img.src!==url)img.src=url;
    }
  }
};
"""


def add_hud_layout(html):
    html = html.replace("</style>",HUD_LAYOUT_CSS+"\n</style>",1)
    return html.replace("</body>","<script>"+HUD_LAYOUT_JS+"</script></body>",1)
