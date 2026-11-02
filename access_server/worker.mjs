import {ADMIN_HTML, ADMIN_SCRIPT} from './admin.mjs';

const HEADERS = {
  'Cache-Control':'no-store, private', 'X-Content-Type-Options':'nosniff',
  'Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
  'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
};
const hex64 = value => typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
const stamp = () => Math.floor(Date.now()/1000);
export async function hash(text){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(v=>v.toString(16).padStart(2,'0')).join('')}
const random = () => Array.from(crypto.getRandomValues(new Uint8Array(32))).map(v=>v.toString(16).padStart(2,'0')).join('');
function same(a,b){let diff=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0}
function json(value,status=200,extra={}){return new Response(JSON.stringify(value),{status,headers:{...HEADERS,'Content-Type':'application/json; charset=utf-8',...extra}})}
function fail(status,error){return json({error},status)}
async function body(request){
  if(!(request.headers.get('Content-Type')||'').startsWith('application/json'))throw Error('format');
  // Stream-bound body reads, including chunked bodies without Content-Length.
  const reader=request.body?.getReader(); if(!reader)throw Error('body');
  const parts=[];let size=0;
  while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>4096){await reader.cancel();throw Error('size')}parts.push(value)}
  const bytes=new Uint8Array(size);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length}
  const result=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  if(!result||typeof result!=='object'||Array.isArray(result))throw Error('body');return result
}
function bearer(request){return /^Bearer ([a-f0-9]{64})$/.exec(request.headers.get('Authorization')||'')?.[1]}
function cookie(request){return /(?:^|;\s*)__Host-ta_admin=([a-f0-9]{64})(?:;|$)/.exec(request.headers.get('Cookie')||'')?.[1]}
const sessionCookie=(token,age)=>'__Host-ta_admin='+token+'; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age='+age;
async function limited(db,request,kind,limit,seconds){
  const now=stamp(), period=Math.floor(now/seconds);
  const ip=await hash(request.headers.get('CF-Connecting-IP')||'unknown');
  const key=kind+':'+ip+':'+period;
  const row=await db.prepare('INSERT INTO rate_limits(bucket,count,expires_at) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1 RETURNING count').bind(key,(period+1)*seconds).first();
  return row.count>limit
}
async function admin(request,db,password){
  const token=cookie(request);if(!token)return false;
  return !!await db.prepare('SELECT token_hash FROM admin_sessions WHERE token_hash=? AND expires_at>?').bind(await hash(token+':'+password),stamp()).first()
}

export async function handle(request,env){
 const url=new URL(request.url),path=url.pathname,db=env.DB;
 if(url.protocol!=='https:')return fail(400,'HTTPS 연결이 필요합니다.');
 if(!env.ADMIN_PASSWORD||env.ADMIN_PASSWORD.length<32||!db)return fail(503,'운영자 서버 설정이 완료되지 않았습니다.');
 if(request.method==='GET'&&(path==='/admin'||path==='/admin/'))return new Response(ADMIN_HTML,{headers:{...HEADERS,'Content-Type':'text/html; charset=utf-8'}});
 if(request.method==='GET'&&path==='/admin/app.js')return new Response(ADMIN_SCRIPT,{headers:{...HEADERS,'Content-Type':'text/javascript; charset=utf-8'}});
 if(path.startsWith('/api/admin/')){
  if(request.method==='POST'&&request.headers.get('Origin')!==url.origin)return fail(403,'같은 관리자 페이지에서 다시 시도하세요.');
  if(path==='/api/admin/login'&&request.method==='POST'){
   if(await limited(db,request,'login',5,600))return fail(429,'로그인 시도가 많습니다. 최대 10분 후 다시 시도하세요.');
   const data=await body(request);
   if(typeof data.password!=='string'||!same(await hash(data.password),await hash(env.ADMIN_PASSWORD)))return fail(401,'비밀번호가 맞지 않습니다.');
   const token=random();await db.prepare('INSERT INTO admin_sessions(token_hash,expires_at) VALUES(?,?)').bind(await hash(token+':'+env.ADMIN_PASSWORD),stamp()+28800).run();
   return json({ok:true},200,{'Set-Cookie':sessionCookie(token,28800)})
  }
  if(!await admin(request,db,env.ADMIN_PASSWORD))return fail(401,'운영자 로그인이 필요합니다.');
  if(path==='/api/admin/logout'&&request.method==='POST'){
   await db.prepare('DELETE FROM admin_sessions WHERE token_hash=?').bind(await hash(cookie(request)+':'+env.ADMIN_PASSWORD)).run();
   return json({ok:true},200,{'Set-Cookie':sessionCookie('',0)})
  }
  if(path==='/api/admin/devices'&&request.method==='GET'){
   const status=url.searchParams.get('status')||'pending';
   const offset=Number(url.searchParams.get('offset')||0);
   if(!['all','pending','approved','revoked'].includes(status)||!Number.isSafeInteger(offset)||offset<0||offset>100000)return fail(400,'목록 조건이 올바르지 않습니다.');
   const fields='device_id,name,status,created_at,updated_at,last_seen';
   const rows=status==='all'?await db.prepare('SELECT '+fields+' FROM devices ORDER BY updated_at DESC,device_id LIMIT 100 OFFSET ?').bind(offset).all():
    await db.prepare('SELECT '+fields+' FROM devices WHERE status=? ORDER BY updated_at DESC,device_id LIMIT 100 OFFSET ?').bind(status,offset).all();
   return json({devices:rows.results})
  }
  if(path==='/api/admin/device'&&request.method==='POST'){
   const data=await body(request);
   if(!hex64(data.device_id)||!['approved','revoked','reset'].includes(data.status))return fail(400,'변경 내용이 올바르지 않습니다.');
   if(data.status==='reset')await db.prepare('DELETE FROM devices WHERE device_id=?').bind(data.device_id).run();
   else await db.prepare('UPDATE devices SET status=?,updated_at=? WHERE device_id=?').bind(data.status,stamp(),data.device_id).run();
   return json({ok:true})
  }
  return fail(404,'없는 관리자 기능입니다.')
 }
 if(request.method==='POST'&&(path==='/api/register'||path==='/api/check')){
  const token=bearer(request);if(!token)return fail(401,'등록정보가 올바르지 않습니다.');
  const data=await body(request);if(!hex64(data.device_id))return fail(400,'PC 등록번호가 올바르지 않습니다.');
  const tokenHash=await hash(token);let row=await db.prepare('SELECT status,token_hash FROM devices WHERE device_id=?').bind(data.device_id).first();
  if(row&&!same(row.token_hash,tokenHash))return fail(409,'기존 등록정보와 다릅니다. 운영자에게 PC 등록 초기화를 요청하세요.');
  if(path==='/api/register'){
   if(await limited(db,request,'register',10,60))return fail(429,'잠시 후 다시 신청하세요.');
   const name=typeof data.name==='string'?data.name.trim():'';
   if(!name||name.length>40||/[\u0000-\u001f\u007f]/.test(name))return fail(400,'이름은 1~40자로 입력하세요.');
   // Never reset a revoked/approved row to pending, overwrite a credential or
   // rename a registered PC on re-request. Re-read after INSERT for races.
   await db.prepare("INSERT INTO devices(device_id,token_hash,name,status,created_at,updated_at) VALUES(?,?,?,'pending',?,?) ON CONFLICT(device_id) DO NOTHING").bind(data.device_id,tokenHash,name,stamp(),stamp()).run();
   row=await db.prepare('SELECT status,token_hash FROM devices WHERE device_id=?').bind(data.device_id).first();
   if(!row||!same(row.token_hash,tokenHash))return fail(409,'등록정보 충돌입니다. 운영자에게 문의하세요.')
  }
  if(!row)return json({status:'unknown'});
  // Updating once/minute is enough for the dashboard; don't write every poll.
  await db.prepare('UPDATE devices SET last_seen=? WHERE device_id=? AND last_seen<?').bind(stamp(),data.device_id,stamp()-60).run();
  return json({status:row.status})
 }
 return fail(404,'없는 주소입니다.')
}

export default {
 async fetch(request,env){try{return await handle(request,env)}catch{return fail(400,'요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.')}},
 async scheduled(_controller,env){
  await env.DB.batch([
   env.DB.prepare('DELETE FROM admin_sessions WHERE expires_at<?').bind(stamp()),
   env.DB.prepare('DELETE FROM rate_limits WHERE expires_at<?').bind(stamp())
  ])
 }
};
