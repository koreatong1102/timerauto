import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker, {handle} from './worker.mjs';
import {ADMIN_SCRIPT} from './admin.mjs';

function fixture(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./migrations/0001_access.sql',import.meta.url),'utf8'));
 const DB={prepare(sql){const statement=sqlite.prepare(sql);return {bind(...args){return {
   async first(){return statement.get(...args)||null},async all(){return {results:statement.all(...args)}},async run(){return statement.run(...args)}
 }}}},async batch(items){return Promise.all(items.map(item=>item.run()))}};
 return {DB,ADMIN_PASSWORD:'test-only-random-example-password-123456789',sqlite}
}
const device_id='a'.repeat(64), token='b'.repeat(64), origin='https://auth.example';
function req(path,data,headers={}){return new Request(origin+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...headers},body:data===undefined?undefined:JSON.stringify(data)})}
function client(path,extra={},credential=token){return req(path,{device_id,...extra},{Authorization:'Bearer '+credential})}
async function login(env){const r=await handle(req('/api/admin/login',{password:env.ADMIN_PASSWORD},{Origin:origin}),env);assert.equal(r.status,200);return r.headers.get('Set-Cookie').split(';')[0]}
async function change(env,cookie,status){return handle(req('/api/admin/device',{device_id,status},{Origin:origin,Cookie:cookie}),env)}

test('unknown -> pending -> approved -> revoked; re-register cannot undo revocation',async()=>{
 const env=fixture();
 assert.equal((await (await handle(client('/api/check'),env)).json()).status,'unknown');
 assert.equal((await (await handle(client('/api/register',{name:'테스트 사용자'}),env)).json()).status,'pending');
 const cookie=await login(env);assert.equal((await change(env,cookie,'approved')).status,200);
 assert.equal((await (await handle(client('/api/check'),env)).json()).status,'approved');
 assert.equal((await change(env,cookie,'revoked')).status,200);
 assert.equal((await (await handle(client('/api/check'),env)).json()).status,'revoked');
 assert.equal((await (await handle(client('/api/register',{name:'이름 바꿔 재신청'}),env)).json()).status,'revoked');
 const row=env.sqlite.prepare('SELECT * FROM devices').get();assert.equal(row.name,'테스트 사용자');assert.notEqual(row.token_hash,token);
 await change(env,cookie,'approved');assert.equal((await (await handle(client('/api/check'),env)).json()).status,'approved');
 env.sqlite.close()
});

test('tokens cannot be replaced, read by admins, or used for another PC',async()=>{
 const env=fixture();await handle(client('/api/register',{name:'테스트'}),env);
 assert.equal((await handle(client('/api/check',{},'c'.repeat(64)),env)).status,409);
 assert.equal((await handle(client('/api/register',{name:'다른 사용자'},'c'.repeat(64)),env)).status,409);
 const cookie=await login(env);
 const response=await handle(req('/api/admin/devices?status=all',undefined,{Cookie:cookie}),env);
 const text=await response.text();assert.ok(!text.includes('token_hash'));assert.ok(!text.includes(token));
 env.sqlite.close()
});

test('admin API needs session and same-origin writes; logout invalidates session',async()=>{
 const env=fixture();
 assert.equal((await handle(req('/api/admin/devices'),env)).status,401);
 assert.equal((await handle(req('/api/admin/login',{password:env.ADMIN_PASSWORD},{Origin:'https://evil.example'}),env)).status,403);
 const cookie=await login(env);
 assert.equal((await handle(req('/api/admin/device',{device_id,status:'approved'},{Cookie:cookie}),env)).status,403);
 assert.equal((await handle(req('/api/admin/logout',{}, {Cookie:cookie,Origin:origin}),env)).status,200);
 assert.equal((await handle(req('/api/admin/devices',undefined,{Cookie:cookie}),env)).status,401);
 env.sqlite.close()
});

test('changing admin password invalidates existing sessions',async()=>{
 const env=fixture(),cookie=await login(env);env.ADMIN_PASSWORD+='changed';
 assert.equal((await handle(req('/api/admin/devices',undefined,{Cookie:cookie}),env)).status,401);env.sqlite.close()
});

test('PC reset revokes old approval until a fresh registration is approved',async()=>{
 const env=fixture();await handle(client('/api/register',{name:'PC'}),env);const cookie=await login(env);
 await change(env,cookie,'approved');await change(env,cookie,'reset');
 assert.equal((await (await handle(client('/api/check'),env)).json()).status,'unknown');
 assert.equal((await (await handle(client('/api/register',{name:'PC 새 등록'},'c'.repeat(64)),env)).json()).status,'pending');
 assert.equal((await handle(client('/api/check'),env)).status,409);env.sqlite.close()
});

test('rate limits password attempts; short/unset secret fails closed',async()=>{
 const env=fixture();
 for(let i=0;i<5;i++)assert.equal((await handle(req('/api/admin/login',{password:'bad'},{Origin:origin}),env)).status,401);
 assert.equal((await handle(req('/api/admin/login',{password:env.ADMIN_PASSWORD},{Origin:origin}),env)).status,429);
 env.ADMIN_PASSWORD='short';assert.equal((await handle(client('/api/check'),env)).status,503);env.sqlite.close()
});

test('bounded payloads, malformed IDs, methods and unsafe names are rejected',async()=>{
 const env=fixture();
 for(const name of ['', 'x'.repeat(41),'bad\nname'])assert.equal((await handle(client('/api/register',{name}),env)).status,400);
 const tooLarge=client('/api/register',{name:'x'.repeat(5000)});assert.equal((await worker.fetch(tooLarge,env)).status,400);
 assert.equal((await handle(req('/api/register',{device_id:'bad',name:'x'},{Authorization:'Bearer '+token}),env)).status,400);
 assert.equal((await handle(req('/api/check'),env)).status,404);
 assert.equal((await handle(new Request('http://auth.example/admin'),env)).status,400);env.sqlite.close()
});

test('admin HTML has no injected names, framing, cache or cross-origin API access',async()=>{
 assert.doesNotThrow(()=>new Function(ADMIN_SCRIPT));
 const env=fixture();await handle(client('/api/register',{name:'<img src=x onerror=alert(1)>'}),env);
 const page=await handle(req('/admin'),env),html=await page.text();
 assert.ok(!html.includes('<img'));assert.ok(page.headers.get('Content-Security-Policy').includes("frame-ancestors 'none'"));
 assert.equal(page.headers.get('Cache-Control'),'no-store, private');assert.equal(page.headers.get('Access-Control-Allow-Origin'),null);
 const script=await (await handle(req('/admin/app.js'),env)).text();assert.ok(!script.includes('innerHTML'));env.sqlite.close()
});

test('expired admin sessions cannot operate; cleanup keeps device approvals',async()=>{
 const env=fixture();await handle(client('/api/register',{name:'PC'}),env);const cookie=await login(env);
 env.sqlite.exec('UPDATE admin_sessions SET expires_at=1');
 assert.equal((await handle(req('/api/admin/devices',undefined,{Cookie:cookie}),env)).status,401);
 await worker.scheduled({},env);assert.equal(env.sqlite.prepare('SELECT count(*) n FROM admin_sessions').get().n,0);
 assert.equal(env.sqlite.prepare('SELECT count(*) n FROM devices').get().n,1);env.sqlite.close()
});
