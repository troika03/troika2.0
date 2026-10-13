import { randomBytes, randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import worker from '../build/server/index.js';
import { databaseBinding } from './sqlite-binding.mjs';
const env={DB:databaseBinding(),SESSION_SECRET:randomBytes(48).toString('base64'),PAYMENTS_ENABLED:'false'};
const origin='https://smoke.test';
let verified=0;
async function call(path,method='GET',body,cookie){const result=await worker.fetch(new Request(origin+path,{method,headers:{...(method!=='GET'?{Origin:origin}:{}),...(body?{'Content-Type':'application/json'}:{}),...(cookie?{Cookie:cookie}:{})},...(body?{body:JSON.stringify(body)}:{})}),env,{});return result;}
const accounts=[];
try {
  for(let i=0;i<2;i++){
    const email=`site-smoke-${randomUUID()}@example.invalid`,password=randomBytes(20).toString('hex');
    const result=await call('/api/auth/register','POST',{email,password,consent:true});
    assert.equal(result.status,201,`Registration returned ${result.status}`);
    const cookie=result.headers.get('Set-Cookie').split(';')[0];accounts.push({cookie,email,password});verified++;
  }
  const first=accounts[0],second=accounts[1];
  for(const path of ['/api/subscription','/api/devices','/api/memories']){assert.equal((await call(path,'GET',undefined,first.cookie)).status,200);verified++;}
  const memoryResponse=await call('/api/memories','POST',{kind:'fact',title:'Website smoke',content:'Synthetic verification data; remove after test.'},first.cookie);assert.equal(memoryResponse.status,201);const memory=(await memoryResponse.json()).memory;verified++;
  const other=await(await call('/api/memories','GET',undefined,second.cookie)).json();assert.ok(!other.memories.some(m=>m.id===memory.id));verified++;
  assert.equal((await call(`/api/memories/${memory.id}`,'DELETE',undefined,second.cookie)).status,404);verified++;
  assert.equal((await call(`/api/memories/${memory.id}`,'PATCH',{content:'Synthetic updated verification data.'},first.cookie)).status,200);verified++;
  assert.equal((await call(`/api/memories/${memory.id}`,'DELETE',undefined,first.cookie)).status,200);verified++;
  const support=await call('/api/support','POST',{category:'technical',subject:'Website smoke only',message:'Synthetic temporary test ticket. No action required.'},first.cookie);assert.equal(support.status,201);const ticket=await support.json();verified++;
  assert.equal((await(await call('/api/support','GET',undefined,second.cookie)).json()).tickets.length,0);verified++;
  assert.equal((await call(`/api/support/${ticket.id}`,'DELETE',undefined,first.cookie)).status,200);verified++;
  const exported=await call('/api/export','GET',undefined,first.cookie);assert.equal(exported.status,200);const bytes=new Uint8Array(await exported.arrayBuffer());assert.equal(bytes[0],0x50);assert.equal(bytes[1],0x4b);verified++;
  const refreshed=await call('/api/auth/refresh','POST',undefined,first.cookie);assert.equal(refreshed.status,200);first.cookie=refreshed.headers.get('Set-Cookie').split(';')[0];verified++;
  assert.equal((await call('/api/subscription','GET',undefined,first.cookie)).status,200);verified++;
  console.log(`Live product API: ${verified} checks passed; no AI or payment calls.`);
} finally {
  for(const account of accounts){
    let removed=false;
    for(let attempt=0;attempt<5&&!removed;attempt++){
      const result=await call('/api/account','DELETE',{confirmation:'DELETE_MY_ACCOUNT'},account.cookie);
      // A repeated deletion may see a revoked token after the first request completed.
      if(result.ok) removed=true;
      else if(result.status===401){
        const login=await call('/api/auth/login','POST',{email:account.email,password:account.password});
        if(login.status===401) removed=true;
        else if(login.ok)account.cookie=login.headers.get('Set-Cookie').split(';')[0];
      }
    }
    if(!removed)throw new Error('Disposable account cleanup requires operator verification.');
  }
  env.DB.close();
  console.log(`Removed ${accounts.length} disposable accounts.`);
}
