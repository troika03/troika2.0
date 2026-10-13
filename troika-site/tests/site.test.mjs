import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import worker from '../build/server/index.js';
import { databaseBinding } from '../scripts/sqlite-binding.mjs';
import { pages, documentHTML } from '../src/content.mjs';
globalThis.crypto ||= webcrypto;
const origin = 'https://site.test';
const env = () => ({ DB:databaseBinding(), SESSION_SECRET:'test-session-secret-'.repeat(4), RELEASE_UPLOAD_KEY:'upload-test-key', SUPPORT_ADMIN_EMAIL:'owner@example.test', PAYMENTS_ENABLED:'false' });
function call(path, bindings, {method='GET',body,cookie,headers={}} = {}) {
  return worker.fetch(new Request(origin+path,{method,headers:{...(method!=='GET'?{Origin:origin}:{}),...(body?{'Content-Type':'application/json'}:{}),...(cookie?{Cookie:cookie}:{}),...headers},...(body?{body:JSON.stringify(body)}:{})}),bindings,{});
}
function mockAPI(callback) {
  const old=globalThis.fetch;
  globalThis.fetch=async(input,options)=>callback(new URL(input),options);
  return ()=>{globalThis.fetch=old;};
}
const reply=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
async function login(bindings,email='first@example.test',home='ses_first') {
  const restore=mockAPI(()=>reply({access_token:'access_'+home,refresh_token:'refresh_'+home,refresh_expires_at:Date.now()/1000+86400,home_session_id:home}));
  try { const result=await call('/api/auth/login',bindings,{method:'POST',body:{email,password:'test-password-only'}}); assert.equal(result.status,200); return result.headers.get('Set-Cookie').split(';')[0]; } finally{restore();}
}
test('all pages contain rendered content, metadata and accessible main without JavaScript',()=>{
  for(const[slug,page]of Object.entries(pages)) { const html=documentHTML(slug,page); assert.match(html,/<html lang="ru">/);assert.match(html,/<main id="content">/);assert.match(html,/<meta name="description"/);assert.ok(html.includes(page.title));assert.ok(!html.includes('Закрытая бета')); }
});
test('page routes, redirects, 404 and font use correct content types',async()=>{
  const bindings=env();
  for(const path of ['/','/pricing/','/account/','/privacy/','/download/']){const result=await call(path,bindings);assert.equal(result.status,200);assert.match(result.headers.get('Content-Type'),/text\/html/);assert.ok(result.headers.has('Content-Security-Policy'));}
  assert.equal((await call('/pricing',bindings)).status,308);
  assert.equal((await call('/absent/',bindings)).status,404);
  const font=await call('/assets/brand/GolosText-Variable.ttf',bindings);assert.equal(font.headers.get('Content-Type'),'font/ttf');assert.ok((await font.arrayBuffer()).byteLength>100000);
  bindings.DB.close();
});
test('cross-origin mutations rejected before any upstream request',async()=>{
  const bindings=env();const result=await call('/api/auth/login',bindings,{method:'POST',body:{},headers:{Origin:'https://evil.test'}});assert.equal(result.status,403);bindings.DB.close();
});
test('login cookie is authenticated encryption, HttpOnly and never exposes tokens to browser JSON',async()=>{
  const bindings=env(),cookie=await login(bindings);assert.ok(!cookie.includes('access_'));assert.ok(!cookie.includes('refresh_'));
  const result=await call('/api/session',bindings,{cookie});const data=await result.json();assert.equal(data.signed_in,true);assert.equal(data.email,'first@example.test');assert.ok(!JSON.stringify(data).includes('token'));
  const forged=cookie.slice(0,-4)+'abcd';assert.equal((await(await call('/api/session',bindings,{cookie:forged})).json()).signed_in,false);
  const restore=mockAPI(()=>reply({access_token:'a',refresh_token:'r',refresh_expires_at:Date.now()/1000+86400,home_session_id:'ses'}));
  try{const result=await call('/api/auth/login',bindings,{method:'POST',body:{email:'first@example.test',password:'test-password-only'}});assert.match(result.headers.get('Set-Cookie'),/Secure; HttpOnly; SameSite=Lax/);}finally{restore();bindings.DB.close();}
});
test('registration requires consent and auth attempts are bounded',async()=>{
  const bindings=env();assert.equal((await call('/api/auth/register',bindings,{method:'POST',body:{email:'first@example.test',password:'test-password-only'}})).status,400);
  for(let i=0;i<7;i++)await call('/api/auth/login',bindings,{method:'POST',body:{}});
  assert.equal((await call('/api/auth/login',bindings,{method:'POST',body:{}})).status,429);bindings.DB.close();
});
test('proxy only accepts fixed routes, preserves revocation and blocks payments when disabled',async()=>{
  const bindings=env(),cookie=await login(bindings);let paths=[];
  const restore=mockAPI((url,options)=>{paths.push(url.pathname);assert.match(options.headers.Authorization,/^Bearer access_/);return reply({subscription:{plan:'free',daily_limit:1,remaining:1}});});
  try{assert.equal((await call('/api/subscription',bindings,{cookie})).status,200);assert.deepEqual(paths,['/v1/subscription']);assert.equal((await call('/api/proxy?url=https://evil.test',bindings,{cookie})).status,404);assert.equal((await call('/api/billing/checkout',bindings,{cookie,method:'POST',body:{sku:'plus'}})).status,503);}finally{restore();bindings.DB.close();}
});
test('support is durable, shared for one account and isolated from another; deletion cannot cross owners',async()=>{
  const bindings=env(),first=await login(bindings),second=await login(bindings,'second@example.test','ses_second');
  const restore=mockAPI(()=>reply({subscription:{plan:'free'}}));
  try {
    const result=await call('/api/support',bindings,{cookie:first,method:'POST',body:{category:'technical',subject:'Test issue',message:'Synthetic support test only'}});assert.equal(result.status,201);const{id}=await result.json();
    assert.equal((await(await call('/api/support',bindings,{cookie:first})).json()).tickets.length,1);
    assert.equal((await(await call('/api/support',bindings,{cookie:second})).json()).tickets.length,0);
    assert.equal((await call(`/api/support/${id}`,bindings,{cookie:second,method:'DELETE'})).status,404);
    assert.equal((await call(`/api/support/${id}`,bindings,{cookie:first,method:'DELETE'})).status,200);
    assert.equal((await(await call('/api/support',bindings,{cookie:first})).json()).tickets.length,0);
  }finally{restore();bindings.DB.close();}
});
test('support admin is server-authorized and replies reach only ticket owner',async()=>{
  const bindings=env(),cookie=await login(bindings);const restore=mockAPI(()=>reply({subscription:{plan:'free'}}));
  try{const created=await(await call('/api/support',bindings,{cookie,method:'POST',body:{category:'technical',subject:'Support reply',message:'Synthetic support issue'}})).json();assert.equal((await call('/api/support-admin',bindings,{cookie})).status,403);const headers={'oai-authenticated-user-email':'owner@example.test'};const result=await call(`/api/support-admin/${created.id}`,bindings,{method:'POST',headers,body:{message:'Synthetic response',status:'closed'}});assert.equal(result.status,200);const tickets=(await(await call('/api/support',bindings,{cookie})).json()).tickets;assert.equal(tickets[0].status,'closed');assert.equal(tickets[0].replies[0].message,'Synthetic response');}finally{restore();bindings.DB.close();}
});
test('logout revokes only current device and reports upstream failure instead of fake success',async()=>{
  const bindings=env(),cookie=await login(bindings);let seen=[];
  const restore=mockAPI((url,options)=>{seen.push([url.pathname,options.method]);return url.pathname.endsWith('/devices')?reply({devices:[{id:'dev_current',current:true,status:'active'}]}):reply({status:'revoked'});});
  try{const result=await call('/api/auth/logout',bindings,{cookie,method:'POST'});assert.equal(result.status,200);assert.match(result.headers.get('Set-Cookie'),/Max-Age=0/);assert.deepEqual(seen,[['/v1/account/devices','GET'],['/v1/account/devices/dev_current','DELETE']]);}finally{restore();}
  const failing=mockAPI(()=>reply({error:'Unavailable'},503));try{assert.equal((await call('/api/auth/logout',bindings,{cookie,method:'POST'})).status,503);}finally{failing();bindings.DB.close();}
});
test('account deletion requires exact confirmation and also deletes website support rows',async()=>{
  const bindings=env(),cookie=await login(bindings);const restore=mockAPI((url)=>url.pathname==='/v1/account'?reply({status:'deleted'}):reply({subscription:{plan:'free'}}));
  try{await call('/api/support',bindings,{cookie,method:'POST',body:{category:'account',subject:'Deletion test',message:'Synthetic account deletion test'}});assert.equal((await call('/api/account',bindings,{cookie,method:'DELETE',body:{confirmation:'yes'}})).status,400);const result=await call('/api/account',bindings,{cookie,method:'DELETE',body:{confirmation:'DELETE_MY_ACCOUNT'}});assert.equal(result.status,200);assert.equal((await bindings.DB.prepare('SELECT count(*) AS n FROM support_tickets').first()).n,0);}finally{restore();bindings.DB.close();}
});
test('downloads stream immutable objects and reject traversal; uploads require separate credential',async()=>{
  const bindings=env();bindings.BUCKET={get:async()=>({size:4,body:new Uint8Array([1,2,3,4]),httpEtag:'"test"'})};
  const hash='a'.repeat(64),url=`/downloads/windows/${hash}/Troika-1.0.zip`;const result=await call(url,bindings);assert.equal(result.status,200);assert.equal((await result.arrayBuffer()).byteLength,4);assert.match(result.headers.get('Cache-Control'),/immutable/);assert.equal((await call('/downloads/../../secret',bindings)).status,404);assert.equal((await call('/api/admin/releases/windows',bindings,{method:'PUT'})).status,403);bindings.DB.close();
});
test('status reflects actual probe failure rather than permanent green',async()=>{
  const bindings=env(),restore=mockAPI(()=>reply({error:'down'},503));try{assert.equal((await(await call('/api/status',bindings)).json()).available,false);}finally{restore();bindings.DB.close();}
});
