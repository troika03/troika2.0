import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
process.stderr.write('Ready for hosted smoke JSON on stdin (input is hidden).\n');
if(process.stdin.isTTY)process.stdin.setRawMode(true);
process.stdin.setEncoding('utf8');
const raw=await new Promise(resolve=>{let s='';const read=c=>{s+=c;if(/[\n\r]/.test(s)){process.stdin.off('data',read);resolve(s);}};process.stdin.on('data',read);process.stdin.resume();});
if(process.stdin.isTTY)process.stdin.setRawMode(false);process.stdin.pause();
const settings=JSON.parse(raw),origin=settings.origin;
const accounts=[];let passed=0;
async function call(path,{method='GET',body,cookie,requestOrigin=origin}={}) {
  return fetch(origin+path,{method,redirect:'error',signal:AbortSignal.timeout(30000),headers:{...(settings.siteToken?{'OAI-Sites-Authorization':`Bearer ${settings.siteToken}`} : {}),...(method!=='GET'?{Origin:requestOrigin}:{}),...(body?{'Content-Type':'application/json'}:{}),...(cookie?{Cookie:cookie}:{})},...(body?{body:JSON.stringify(body)}:{})});
}
const check=(condition,message)=>{assert.ok(condition,message);passed++;};
try{
  for(const path of ['/','/pricing/','/download/','/account/','/help/','/privacy/','/status/']) {const r=await call(path);check(r.status===200,`${path}: ${r.status}`);check(r.headers.get('Content-Type')?.includes('text/html'),`${path}: HTML`);}
  const available=await(await call('/api/releases')).json();check(Boolean(available.releases.android&&available.releases.windows),'Both downloads published');
  check((await(await call('/api/status')).json()).available===true,'Fresh product health probe succeeds');
  check((await call('/api/devices')).status===401,'Product account required');
  if(settings.publicProxy){
    for(const path of ['/private/backend.json','/.git/config','/api/admin/releases/android'])check([403,404].includes((await call(path)).status),`${path}: inaccessible`);
    check((await call('/api/auth/register',{method:'POST',requestOrigin:'https://untrusted.example',body:{email:'not-created@example.invalid',password:randomBytes(20).toString('hex'),consent:true}})).status===403,'Cross-origin mutation rejected by public proxy');
    check((await call('/api/auth/register',{method:'POST',body:{email:'not-created@example.invalid',password:randomBytes(20).toString('hex'),consent:false}})).status===400,'Registration requires consent');
  }
  for(let i=0;i<2;i++) {
    const email=`site-hosted-${randomUUID()}@example.invalid`,password=randomBytes(20).toString('hex');
    const r=await call('/api/auth/register',{method:'POST',body:{email,password,consent:true}});check(r.status===201,`Register: ${r.status}`);
    accounts.push({email,password,cookie:r.headers.get('Set-Cookie').split(';')[0]});
    if(settings.publicProxy)check(/^__Host-troika_session=/.test(r.headers.get('Set-Cookie'))&&/HttpOnly/i.test(r.headers.get('Set-Cookie'))&&/Secure/i.test(r.headers.get('Set-Cookie')),'Public proxy preserves secure product session');
  }
  const first=accounts[0],second=accounts[1];
  const lastCharacter=first.cookie.slice(-1),tamperedCookie=first.cookie.slice(0,-1)+(lastCharacter==='A'?'z':'A');
  check((await call('/api/devices',{cookie:tamperedCookie})).status===401,'Tampered encrypted cookie rejected');
  for(const path of ['/api/subscription','/api/devices','/api/memories'])check((await call(path,{cookie:first.cookie})).status===200,path);
  const createdMemory=await call('/api/memories',{method:'POST',cookie:first.cookie,body:{kind:'fact',title:'Synthetic website check',content:'Disposable memory created by the deployment verification.'}});
  check(createdMemory.status===201,'Create memory');const memoryId=(await createdMemory.json()).memory.id;
  check((await call(`/api/memories/${memoryId}`,{method:'PATCH',cookie:second.cookie,body:{content:'This change must be rejected.'}})).status===404,'Other account cannot edit memory');
  check((await call(`/api/memories/${memoryId}`,{method:'PATCH',cookie:first.cookie,body:{content:'Updated disposable website verification memory.'}})).status===200,'Edit own memory');
  const listedMemories=await(await call('/api/memories',{cookie:first.cookie})).json();
  check(listedMemories.memories.some(m=>m.id===memoryId&&m.content==='Updated disposable website verification memory.'),'Read updated memory');
  check((await call('/api/memory-preferences',{method:'PUT',cookie:first.cookie,body:{automatic_enabled:false}})).status===200,'Change memory preference');
  check((await(await call('/api/memory-preferences',{cookie:first.cookie})).json()).automatic_enabled===false,'Read memory preference');
  check((await call(`/api/memories/${memoryId}`,{method:'DELETE',cookie:first.cookie})).status===200,'Delete own memory');
  const ticket=await call('/api/support',{method:'POST',cookie:first.cookie,body:{category:'technical',subject:'Synthetic hosted verification',message:'Temporary automated site check. No support action required.'}});check(ticket.status===201,`Durable ticket: ${ticket.status}`);const{id}=await ticket.json();
  const own=await(await call('/api/support',{cookie:first.cookie})).json();check(own.tickets.some(t=>t.id===id),'Owner can read durable ticket');
  const other=await(await call('/api/support',{cookie:second.cookie})).json();check(!other.tickets.some(t=>t.id===id),'Other account cannot read ticket');
  check((await call(`/api/support/${id}`,{cookie:second.cookie,method:'DELETE'})).status===404,'Cross-account delete denied');
  check((await call(`/api/support/${id}`,{cookie:first.cookie,method:'DELETE'})).status===200,'Owner deletion succeeds');
  check((await call('/api/support-admin',{cookie:first.cookie})).status===(settings.publicProxy?404:403),'Public visitor cannot become support admin');
  const refreshed=await call('/api/auth/refresh',{cookie:first.cookie,method:'POST'});check(refreshed.status===200,'Refresh rotates');first.cookie=refreshed.headers.get('Set-Cookie').split(';')[0];
  check((await call('/api/subscription',{cookie:first.cookie})).status===200,'Refreshed cookie works');
  const exported=await call('/api/export',{cookie:first.cookie});check(exported.status===200,'Export download');const bytes=new Uint8Array(await exported.arrayBuffer());check(bytes[0]===0x50&&bytes[1]===0x4b,'Export is ZIP');
  check((await call('/api/billing/checkout',{cookie:first.cookie,method:'POST',body:{sku:'plus'}})).status===503,'Payments remain off');
  check((await call('/api/account',{cookie:second.cookie,method:'DELETE',body:{confirmation:'WRONG'}})).status===400,'Deletion requires exact confirmation');
  const secondOldCookie=second.cookie;
  check((await call('/api/auth/logout',{cookie:second.cookie,method:'POST'})).status===200,'Logout revokes current web device');
  check((await call('/api/subscription',{cookie:secondOldCookie})).status===401,'Revoked cookie loses API access');
  const login=await call('/api/auth/login',{method:'POST',body:{email:second.email,password:second.password}});check(login.status===200,'Login existing product account');second.cookie=login.headers.get('Set-Cookie').split(';')[0];
  console.log(`Hosted website: ${passed} checks passed.`);
}finally{
  let removed=0;
  for(const account of accounts){
    for(let attempt=0;attempt<5;attempt++){
      const r=await call('/api/account',{cookie:account.cookie,method:'DELETE',body:{confirmation:'DELETE_MY_ACCOUNT'}}).catch(()=>null);
      if(r?.ok){removed++;break;}
      if(r?.status===401){const login=await call('/api/auth/login',{method:'POST',body:{email:account.email,password:account.password}});if(login.status===401){removed++;break;}if(login.ok)account.cookie=login.headers.get('Set-Cookie').split(';')[0];}
    }
  }
  check(removed===accounts.length,'All disposable hosted accounts removed');
  console.log(`Removed ${removed} disposable hosted accounts.`);
}
