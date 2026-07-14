from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from typing import Any, Dict


OVERLAY_STUDIO_VERSION = 1

# Keep selectors centralized so the editor and renderer always agree.
ELEMENTS = (
    ("hud", "전체 HUD", ".hud", "HUD"),
    ("bluePortrait", "블루 초상화", "#blueImg", "블루"),
    ("blueTotal", "블루 총 데미지", "#blueTotal", "블루"),
    ("blueHp", "블루 체력 게이지", "#blueBar", "블루"),
    ("blueSp", "블루 SP 게이지", "#blueSp", "블루"),
    ("blueLives", "블루 생명원", "#blueLives", "블루"),
    ("blueName", "블루 닉네임", "#blueName", "블루"),
    ("blueDamage", "블루 라운드 데미지", "#blueDmg", "블루"),
    ("blueFlag", "블루 국기", "#blueFlag", "블루"),
    ("redPortrait", "레드 초상화", "#redImg", "레드"),
    ("redTotal", "레드 총 데미지", "#redTotal", "레드"),
    ("redHp", "레드 체력 게이지", "#redBar", "레드"),
    ("redSp", "레드 SP 게이지", "#redSp", "레드"),
    ("redLives", "레드 생명원", "#redLives", "레드"),
    ("redName", "레드 닉네임", "#redName", "레드"),
    ("redDamage", "레드 라운드 데미지", "#redDmg", "레드"),
    ("redFlag", "레드 국기", "#redFlag", "레드"),
    ("timer", "타이머", "#time", "중앙"),
    ("round", "라운드", "#round", "중앙"),
    ("blueRecent", "블루 타격 문구", "#blueRecent", "이벤트"),
    ("redRecent", "레드 타격 문구", "#redRecent", "이벤트"),
    ("blueCombo", "블루 콤보/카운터", "#blueCombo", "이벤트"),
    ("redCombo", "레드 콤보/카운터", "#redCombo", "이벤트"),
    ("impact", "화면 타격 이펙트", "#impactLayer", "이벤트"),
    ("roundIntro", "라운드 시작 연출", "#roundIntro", "전체화면"),
    ("koOverlay", "다운/KO 연출", "#koOverlay", "전체화면"),
    ("vsOverlay", "VS 연출", "#vs", "전체화면"),
    ("roundReport", "라운드/경기 리포트", "#roundReport .rrPanel", "리포트"),
)

_ELEMENT_BY_ID = {item[0]: item for item in ELEMENTS}
_NUMERIC_LIMITS = {
    "x": (-1920.0, 1920.0),
    "y": (-1080.0, 1080.0),
    "scale": (0.1, 5.0),
    "width": (0.0, 1920.0),
    "height": (0.0, 1080.0),
    "opacity": (0.0, 1.0),
    "fontSize": (0.0, 200.0),
    "zIndex": (-100.0, 10000.0),
    "rotate": (-180.0, 180.0),
}


def _number(value: Any, default: float, low: float, high: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def default_preset() -> Dict[str, Any]:
    return {"version": OVERLAY_STUDIO_VERSION, "name": "사용자 오버레이", "elements": {}}


def sanitize_preset(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    clean = default_preset()
    clean["name"] = str(raw.get("name") or clean["name"])[:80]
    elements = raw.get("elements") if isinstance(raw.get("elements"), dict) else {}
    for element_id, values in elements.items():
        if element_id not in _ELEMENT_BY_ID or not isinstance(values, dict):
            continue
        item: Dict[str, Any] = {}
        for key, (low, high) in _NUMERIC_LIMITS.items():
            if key in values:
                default = 1.0 if key in ("scale", "opacity") else 0.0
                item[key] = _number(values.get(key), default, low, high)
        if "visible" in values:
            item["visible"] = bool(values.get("visible"))
        color = str(values.get("color") or "").strip()
        if color and len(color) <= 32:
            item["color"] = color
        if item:
            clean["elements"][element_id] = item
    return clean


class OverlayStudioStore:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._preset = default_preset()
        self.load()

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._preset)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                preset = sanitize_preset(json.load(stream))
        except FileNotFoundError:
            preset = default_preset()
        except Exception:
            logging.warning("OVERLAY_STUDIO preset load failed path=%s", self.path, exc_info=True)
            preset = default_preset()
        with self._lock:
            self._preset = preset
        return self.get()

    def set(self, raw: Any, persist: bool = False) -> Dict[str, Any]:
        preset = sanitize_preset(raw)
        with self._lock:
            self._preset = preset
        if persist:
            self.save()
        return self.get()

    def reset(self, persist: bool = False) -> Dict[str, Any]:
        return self.set(default_preset(), persist=persist)

    def save(self) -> None:
        with self._lock:
            payload = copy.deepcopy(self._preset)
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".overlay_studio_", suffix=".json", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, self.path)
            logging.info("OVERLAY_STUDIO preset saved path=%s", self.path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def studio_html() -> str:
    schema = [
        {"id": item[0], "label": item[1], "selector": item[2], "group": item[3]}
        for item in ELEMENTS
    ]
    schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return r'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TimerAuto Overlay Studio</title><style>
:root{color-scheme:dark;--bg:#090d13;--panel:#111824;--line:#283548;--cyan:#22d3ee;--gold:#f5bf45;--text:#edf5ff;--muted:#91a2b9}
*{box-sizing:border-box}html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:"Malgun Gothic","Noto Sans KR",sans-serif}
button,input,select{font:inherit}.app{display:grid;grid-template-columns:290px minmax(600px,1fr) 330px;grid-template-rows:58px 1fr;height:100%}
header{grid-column:1/-1;display:flex;align-items:center;gap:10px;padding:0 16px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#172130,#0d131d)}
.brand{font-size:20px;font-weight:900;letter-spacing:.04em;margin-right:auto}.brand b{color:var(--cyan)}button{border:1px solid #34455d;background:#192437;color:var(--text);border-radius:6px;padding:8px 12px;cursor:pointer}button:hover{border-color:var(--cyan);background:#213149}.primary{background:#087f8c;border-color:#18c8d8}.danger{color:#ff8792}.status{font-size:12px;color:var(--muted);min-width:110px;text-align:right}
aside{min-height:0;background:var(--panel);border-right:1px solid var(--line);overflow:auto;padding:12px}.right{border-right:0;border-left:1px solid var(--line)}
.search{width:100%;background:#0a1019;border:1px solid var(--line);color:var(--text);padding:9px;border-radius:6px;margin-bottom:10px}.group{font-size:11px;color:var(--gold);font-weight:800;letter-spacing:.12em;margin:14px 6px 6px}.element{display:flex;align-items:center;gap:8px;padding:9px 10px;border:1px solid transparent;border-radius:5px;cursor:pointer;font-size:13px}.element:hover{background:#182335}.element.active{border-color:var(--cyan);background:#12303a}.eye{width:9px;height:9px;border-radius:50%;background:#4ad5e6}
main{min-width:0;min-height:0;display:flex;align-items:center;justify-content:center;padding:20px;background:radial-gradient(circle at 50% 30%,#26364b 0,#101722 42%,#080c12 100%);overflow:hidden}
.stageShell{position:relative;width:min(100%,calc((100vh - 98px)*16/9));aspect-ratio:16/9;box-shadow:0 0 0 1px #46556a,0 30px 80px #000;background:repeating-conic-gradient(#202b39 0 25%,#18212d 0 50%) 50%/32px 32px;overflow:hidden}
#preview{position:absolute;inset:0;width:100%;height:100%;border:0}.pickLayer{position:absolute;inset:0;z-index:5}.pickBox{position:absolute;border:1px solid transparent;pointer-events:auto}.pickBox:hover{border-color:#f5bf45;background:#f5bf4512}.pickBox.active{border:2px solid var(--cyan);background:#22d3ee0b;box-shadow:0 0 0 1px #001}.pickBox.active:after{content:attr(data-label);position:absolute;left:-2px;top:-24px;background:#09a7b5;color:#001218;font-size:11px;font-weight:900;padding:3px 7px;white-space:nowrap}.handle{position:absolute;width:12px;height:12px;right:-7px;bottom:-7px;border:2px solid #001;background:var(--cyan);cursor:nwse-resize;display:none}.active .handle{display:block}
.hint{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);background:#05080dcc;border:1px solid #3a485d;border-radius:20px;padding:6px 14px;font-size:11px;color:#b9c8dc;z-index:7;pointer-events:none}.snapOn{border-color:var(--gold);color:#ffe29a}
h2{font-size:15px;margin:4px 0 14px}.field{margin-bottom:11px}.field label{display:flex;justify-content:space-between;color:#b7c5d8;font-size:12px;margin-bottom:5px}.field input,.field select{width:100%;background:#080d14;border:1px solid #344359;color:white;border-radius:5px;padding:8px}.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.checks{display:flex;align-items:center;gap:8px;padding:8px 0}.checks input{width:18px;height:18px}.empty{color:var(--muted);font-size:13px;line-height:1.7}.previewGrid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:14px}.previewGrid button{font-size:11px;padding:7px 4px}.kbd{color:var(--muted);font-size:11px;line-height:1.7;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
@media(max-width:1200px){.app{grid-template-columns:230px minmax(480px,1fr) 285px}}
</style></head><body><div class="app"><header><div class="brand">TIMERAUTO <b>OVERLAY STUDIO</b></div><button id="undo">실행 취소</button><button id="redo">다시 실행</button><button id="snap">10px 스냅</button><button id="export">내보내기</button><button id="import">가져오기</button><input id="importFile" type="file" accept="application/json,.json" hidden><button id="reload">저장본 불러오기</button><button id="reset" class="danger">기본값 복원</button><button id="save" class="primary">프리셋 저장</button><span id="status" class="status">준비</span></header>
<aside><input id="search" class="search" placeholder="요소 검색"><div id="elements"></div></aside>
<main><div class="stageShell"><iframe id="preview" src="/overlay?studio=1"></iframe><div id="pickLayer" class="pickLayer"></div><div class="hint">요소를 드래그해 이동 · 우측 아래 핸들로 크기 조절 · 방향키로 미세 조정</div></div></main>
<aside class="right"><h2 id="selectedTitle">요소를 선택하세요</h2><div id="form" class="empty">왼쪽 목록이나 미리보기의 요소를 선택하면 수정 항목이 표시됩니다.</div><div class="previewGrid"><button data-preview="combo_blue">블루 콤보</button><button data-preview="combo_red">레드 콤보</button><button data-preview="counter_blue">블루 카운터</button><button data-preview="counter_red">레드 카운터</button><button data-preview="hit_blue">블루 피격</button><button data-preview="hit_red">레드 피격</button><button data-preview="round">라운드 연출</button><button data-preview="ko">다운 연출</button><button data-preview="vs">VS 연출</button><button data-preview="report">리포트</button></div><div class="kbd">Ctrl+Z 실행 취소 · Ctrl+Y 다시 실행<br>Shift+방향키 10px · 방향키 1px<br>저장 전 변경도 OBS에 즉시 반영됩니다.</div></aside></div>
<script>const SCHEMA=__SCHEMA__;let preset={version:1,name:'사용자 오버레이',elements:{}},selected='',history=[],future=[],drag=null,saveTimer=0,snapSize=1,applyVersion=0;const $=s=>document.querySelector(s),clone=v=>JSON.parse(JSON.stringify(v));
function toast(t,bad=false){$('#status').textContent=t;$('#status').style.color=bad?'#ff7f8b':'#91a2b9';clearTimeout(toast.t);toast.t=setTimeout(()=>$('#status').textContent='준비',2200)}
function val(id,key,def){let p=preset.elements[id]||{};return p[key]===undefined?def:p[key]}function ensure(id){return preset.elements[id]||(preset.elements[id]={})}
async function api(url,opt){let r=await fetch(url,opt);if(!r.ok)throw Error(await r.text());return r.status===204?{}:r.json()}
async function loadPreset(){let version=++applyVersion,result=await api('/api/studio/preset');if(version!==applyVersion)return;preset=result;history=[];future=[];renderList();renderForm();setTimeout(refreshBoxes,180);toast('저장본을 불러왔습니다')}
function pushHistory(){history.push(clone(preset));if(history.length>80)history.shift();future=[]}
function applyLive(){clearTimeout(saveTimer);let version=++applyVersion,payload=JSON.stringify(preset);saveTimer=setTimeout(async()=>{try{let result=await api('/api/studio/preset?persist=0',{method:'POST',headers:{'Content-Type':'application/json'},body:payload});if(version!==applyVersion)return;preset=result;refreshBoxes()}catch(e){if(version===applyVersion)toast('적용 실패: '+e.message,true)}},25)}
function change(key,value,record=true,rerender=true){if(!selected)return;if(record)pushHistory();let p=ensure(selected);if(value===''||value===null){delete p[key]}else p[key]=value;if(rerender)renderForm(false);applyLive()}
function renderList(){let q=$('#search').value.trim().toLowerCase(),box=$('#elements'),group='';box.innerHTML='';SCHEMA.filter(e=>!q||e.label.toLowerCase().includes(q)||e.group.toLowerCase().includes(q)).forEach(e=>{if(e.group!==group){group=e.group;let g=document.createElement('div');g.className='group';g.textContent=group;box.appendChild(g)}let n=document.createElement('div');n.className='element'+(selected===e.id?' active':'');n.dataset.id=e.id;n.innerHTML='<i class="eye"></i><span>'+e.label+'</span>';n.onclick=()=>select(e.id);box.appendChild(n)})}
function field(label,key,type='number',step='1',def=0){let value=val(selected,key,def);return '<div class="field"><label>'+label+'<span>'+value+'</span></label><input data-key="'+key+'" type="'+type+'" step="'+step+'" value="'+value+'"></div>'}
function renderForm(relist=true){if(relist)renderList();let e=SCHEMA.find(x=>x.id===selected);if(!e){$('#selectedTitle').textContent='요소를 선택하세요';return}$('#selectedTitle').textContent=e.label;$('#form').className='';$('#form').innerHTML='<div class="row2">'+field('X 이동','x')+field('Y 이동','y')+'</div><div class="row2">'+field('가로 크기','width')+field('세로 크기','height')+'</div><div class="row2">'+field('배율','scale','number','.01',1)+field('회전','rotate','number','1',0)+'</div><div class="row2">'+field('투명도','opacity','number','.01',1)+field('레이어','zIndex','number','1',0)+'</div>'+field('글자 크기 (0=원본)','fontSize','number','1',0)+field('글자색 (빈값=원본)','color','text','', '')+'<label class="checks"><input id="visible" type="checkbox" '+(val(selected,'visible',true)?'checked':'')+'>화면에 표시</label><button id="elementReset" class="danger">이 요소만 초기화</button>';
$('#form').querySelectorAll('input[data-key]').forEach(i=>{i.onfocus=()=>pushHistory();i.oninput=()=>{let k=i.dataset.key,v=i.type==='number'?Number(i.value):i.value.trim(),label=i.parentElement.querySelector('label span');if(label)label.textContent=v;change(k,v,false,false)}});$('#visible').onchange=e=>change('visible',e.target.checked);$('#elementReset').onclick=()=>{pushHistory();delete preset.elements[selected];renderForm();applyLive()}}
function select(id){selected=id;renderForm();refreshBoxes()}
function overlayDoc(){try{return $('#preview').contentDocument}catch(e){return null}}
function refreshBoxes(){let doc=overlayDoc(),layer=$('#pickLayer'),frame=$('#preview');if(!doc||!doc.body)return;let fw=frame.clientWidth,fh=frame.clientHeight;layer.innerHTML='';SCHEMA.forEach(e=>{let node=doc.querySelector(e.selector);if(!node)return;let r=node.getBoundingClientRect();if(r.width<2||r.height<2)return;let b=document.createElement('div');b.className='pickBox'+(selected===e.id?' active':'');b.dataset.id=e.id;b.dataset.label=e.label;b.style.cssText='left:'+(r.left/doc.defaultView.innerWidth*fw)+'px;top:'+(r.top/doc.defaultView.innerHeight*fh)+'px;width:'+(r.width/doc.defaultView.innerWidth*fw)+'px;height:'+(r.height/doc.defaultView.innerHeight*fh)+'px;';b.innerHTML='<i class="handle"></i>';b.onpointerdown=startDrag;layer.appendChild(b)})}
function startDrag(ev){ev.preventDefault();let id=ev.currentTarget.dataset.id;if(selected!==id)select(id);let resize=ev.target.classList.contains('handle');pushHistory();drag={id,startX:ev.clientX,startY:ev.clientY,x:val(id,'x',0),y:val(id,'y',0),w:val(id,'width',0),h:val(id,'height',0),resize};ev.currentTarget.setPointerCapture(ev.pointerId)}
function snapped(v){return Math.round(v/snapSize)*snapSize}window.addEventListener('pointermove',ev=>{if(!drag)return;let scale=1920/$('#preview').clientWidth,dx=(ev.clientX-drag.startX)*scale,dy=(ev.clientY-drag.startY)*scale,p=ensure(drag.id);if(drag.resize){let doc=overlayDoc(),e=SCHEMA.find(x=>x.id===drag.id),node=doc&&doc.querySelector(e.selector),r=node&&node.getBoundingClientRect();let baseW=drag.w||((r?r.width:100)*scale),baseH=drag.h||((r?r.height:50)*scale);p.width=Math.max(1,snapped(baseW+dx));p.height=Math.max(1,snapped(baseH+dy))}else{p.x=snapped(drag.x+dx);p.y=snapped(drag.y+dy)}renderForm(false);applyLive()});window.addEventListener('pointerup',()=>{drag=null;setTimeout(refreshBoxes,80)});
function undo(){if(!history.length)return;future.push(clone(preset));preset=history.pop();renderForm();applyLive()}function redo(){if(!future.length)return;history.push(clone(preset));preset=future.pop();renderForm();applyLive()}
$('#undo').onclick=undo;$('#redo').onclick=redo;$('#snap').onclick=()=>{snapSize=snapSize===1?10:1;$('#snap').classList.toggle('snapOn',snapSize===10);toast(snapSize===10?'10px 스냅 사용':'자유 이동 사용')};$('#export').onclick=()=>{let blob=new Blob([JSON.stringify(preset,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='TimerAuto_overlay_preset.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('프리셋 파일을 만들었습니다')};$('#import').onclick=()=>$('#importFile').click();$('#importFile').onchange=async e=>{let file=e.target.files&&e.target.files[0];if(!file)return;try{let raw=JSON.parse(await file.text());pushHistory();preset=await api('/api/studio/preset?persist=0',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(raw)});renderForm();setTimeout(refreshBoxes,80);toast('프리셋을 불러왔습니다. 저장하면 확정됩니다')}catch(err){toast('가져오기 실패: '+err.message,true)}finally{e.target.value=''}};$('#reload').onclick=loadPreset;$('#save').onclick=async()=>{try{preset=await api('/api/studio/preset?persist=1',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(preset)});toast('프리셋을 저장했습니다')}catch(e){toast('저장 실패: '+e.message,true)}};$('#reset').onclick=async()=>{if(!confirm('모든 스튜디오 변경을 기본값으로 되돌릴까요?'))return;pushHistory();preset={version:1,name:'사용자 오버레이',elements:{}};renderForm();applyLive();toast('기본값으로 복원했습니다. 저장 버튼을 누르면 확정됩니다')};$('#search').oninput=renderList;
document.querySelectorAll('[data-preview]').forEach(b=>b.onclick=async()=>{try{await api('/api/studio/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:b.dataset.preview})});toast('미리보기 실행')}catch(e){toast('미리보기 실패',true)}});
window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo();return}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();redo();return}if(!selected||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();pushHistory();let p=ensure(selected),d=e.shiftKey?10:snapSize;p.x=Number(p.x||0)+(e.key==='ArrowLeft'?-d:e.key==='ArrowRight'?d:0);p.y=Number(p.y||0)+(e.key==='ArrowUp'?-d:e.key==='ArrowDown'?d:0);renderForm(false);applyLive()});
$('#preview').onload=()=>setTimeout(refreshBoxes,700);window.addEventListener('resize',()=>setTimeout(refreshBoxes,80));setInterval(refreshBoxes,1200);loadPreset();</script></body></html>'''.replace("__SCHEMA__", schema_json)


def runtime_js() -> str:
    selectors = {item[0]: item[2] for item in ELEMENTS}
    selectors_json = json.dumps(selectors, ensure_ascii=False, separators=(",", ":"))
    return r'''(()=>{const SELECTORS=__SELECTORS__;let signature='';if(new URLSearchParams(location.search).get('studio')==='1')document.documentElement.style.background='repeating-conic-gradient(#202b39 0 25%,#18212d 0 50%) 50%/32px 32px';
function clear(el){for(const key of ['translate','scale','rotate','width','height','opacity','font-size','color','z-index','visibility'])el.style.removeProperty(key)}
function set(el,key,value){el.style.setProperty(key,String(value),'important')}function apply(raw){raw=raw&&typeof raw==='object'?raw:{};let next='';try{next=JSON.stringify(raw)}catch(e){}if(next===signature)return;signature=next;let items=raw.elements&&typeof raw.elements==='object'?raw.elements:{};Object.keys(SELECTORS).forEach(id=>document.querySelectorAll(SELECTORS[id]).forEach(el=>{clear(el);let p=items[id];if(!p||typeof p!=='object')return;let x=Number(p.x)||0,y=Number(p.y)||0,scale=Number(p.scale),rotate=Number(p.rotate),width=Number(p.width),height=Number(p.height),fontSize=Number(p.fontSize),zIndex=Number(p.zIndex);set(el,'translate',x+'px '+y+'px');if(isFinite(scale)&&scale>0)set(el,'scale',scale);if(isFinite(rotate)&&rotate)set(el,'rotate',rotate+'deg');if(isFinite(width)&&width>0)set(el,'width',width+'px');if(isFinite(height)&&height>0)set(el,'height',height+'px');if(isFinite(fontSize)&&fontSize>0)set(el,'font-size',fontSize+'px');if(isFinite(zIndex))set(el,'z-index',Math.round(zIndex));if(p.opacity!==undefined)set(el,'opacity',Math.max(0,Math.min(1,Number(p.opacity))));if(p.color)set(el,'color',p.color);if(p.visible===false)set(el,'visibility','hidden')}))}
window.__overlayStudioApply=apply;const baseRender=window.render;if(typeof baseRender==='function'){window.render=function(state){let result=baseRender(state);apply(state&&state.studioPreset);return result}}
fetch('/state?studio=1',{cache:'no-store'}).then(r=>r.json()).then(s=>apply(s&&s.studioPreset)).catch(()=>{});
window.addEventListener('resize',()=>{signature='';fetch('/state?studio=resize',{cache:'no-store'}).then(r=>r.json()).then(s=>apply(s&&s.studioPreset)).catch(()=>{})});
})();'''.replace("__SELECTORS__", selectors_json)
