// No user data is interpolated into HTML. Device names always use textContent.
export const ADMIN_HTML = `<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TimerAuto 사용 승인</title><style>
body{font:16px system-ui,sans-serif;background:#101623;color:#edf3ff;max-width:820px;margin:auto;padding:20px}
input,button{font:inherit;padding:12px;border-radius:9px;border:1px solid #617190;margin:5px 3px;background:#23324b;color:white}
input{box-sizing:border-box;max-width:100%;width:360px}button{cursor:pointer}button:disabled{opacity:.5}
article{background:#1c273a;border-radius:12px;padding:15px;margin:14px 0;overflow-wrap:anywhere}
p{line-height:1.6}.muted{color:#b4c3d9}.danger{background:#7d2635}h2{margin:4px 0}#message{white-space:pre-wrap}
</style><h1>TimerAuto 사용 승인</h1>
<section id="login"><p>운영자 비밀번호로 로그인하세요. 비밀번호를 사용자에게 전달하지 마세요.</p>
<form id="loginform"><input id="password" type="password" autocomplete="current-password" placeholder="운영자 비밀번호" required>
<button>로그인</button></form></section>
<section id="panel" hidden><button id="refresh">목록 새로고침</button><button id="logout">로그아웃</button>
<p class="muted">이름은 신청자가 적은 값입니다. 카톡으로 이름과 PC 등록번호를 확인한 뒤 승인하세요.
중지는 앱의 다음 인증 확인 때 반영됩니다. OBS 방송과 저장 영상은 삭제하지 않습니다.</p>
<label>보기 <select id="filter"><option value="pending">승인 대기</option><option value="all">전체</option><option value="approved">허용</option><option value="revoked">중지</option></select></label>
<div id="list"></div><button id="more" hidden>다음 100명 보기</button></section>
<p id="message" role="status"></p><script type="module" src="/admin/app.js"></script></html>`;

export const ADMIN_SCRIPT = `
const $=id=>document.getElementById(id); let offset=0;
function message(text){$('message').textContent=text}
async function api(path,data){
 const r=await fetch(path,{method:data===undefined?'GET':'POST',credentials:'same-origin',
   headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
 let result; try{result=await r.json()}catch{throw Error('서버에 연결하지 못했습니다.')}
 if(!r.ok){if(r.status===401){$('login').hidden=false;$('panel').hidden=true}
 throw Error(result.error||'요청 실패')};return result
}
async function load(){try{
 const result=await api('/api/admin/devices?status='+encodeURIComponent($('filter').value)+'&offset='+offset);
 $('login').hidden=true;$('panel').hidden=false;$('list').replaceChildren();
 for(const row of result.devices){
  const card=document.createElement('article'),title=document.createElement('h2');title.textContent=row.name;card.append(title);
  const detail=document.createElement('p');detail.textContent='상태: '+({pending:'승인 대기',approved:'사용 허용',revoked:'사용 중지'}[row.status])+
   '\\nPC 등록번호: '+row.device_id.slice(0,12)+'\\n최근 인증: '+(row.last_seen?new Date(row.last_seen*1000).toLocaleString():'아직 없음');
  detail.style.whiteSpace='pre-wrap';card.append(detail);
  for(const [label,status] of [['승인 / 다시 허용','approved'],['사용 중지','revoked'],['PC 등록 초기화','reset']]){
   const button=document.createElement('button');button.textContent=label;if(status!=='approved')button.className='danger';
   button.onclick=async()=>{if(!confirm(row.name+' · '+label+' 하시겠습니까?'+(status==='reset'?' 기존 인증을 지우고 재신청하게 됩니다.':'')))return;
    button.disabled=true;try{await api('/api/admin/device',{device_id:row.device_id,status});await load();message('변경 완료')}catch(e){message(e.message)}finally{button.disabled=false}};
   card.append(button)
  }$('list').append(card)
 }$('more').hidden=result.devices.length<100;message(result.devices.length?'':'해당 사용자가 없습니다.')
 }catch(e){message(e.message)}}
$('loginform').onsubmit=async e=>{e.preventDefault();const password=$('password').value;$('password').value='';
 try{await api('/api/admin/login',{password});offset=0;await load()}catch(e){message(e.message)}};
$('refresh').onclick=()=>{offset=0;load()};$('filter').onchange=()=>{offset=0;load()};$('more').onclick=()=>{offset+=100;load()};
$('logout').onclick=async()=>{try{await api('/api/admin/logout',{});$('list').replaceChildren();$('login').hidden=false;$('panel').hidden=true;message('로그아웃했습니다.')}catch(e){message(e.message)}};
load();
`;
