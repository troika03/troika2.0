import { open, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';

// Credentials arrive through hidden stdin, never arguments or a local file.
async function input() {
  process.stderr.write('Ready for release upload JSON on stdin (input is hidden).\n');
  if(process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.setEncoding('utf8');
  const raw=await new Promise((resolve,reject)=>{let value='';const read=chunk=>{value+=chunk;if(value.length>16000)reject(new Error('Input too large'));else if(/[\r\n]/.test(value)){process.stdin.off('data',read);resolve(value);}};process.stdin.on('data',read);process.stdin.once('end',()=>resolve(value));process.stdin.resume();});
  if(process.stdin.isTTY)process.stdin.setRawMode(false);process.stdin.pause();
  return JSON.parse(raw);
}
const settings=await input();
if(!['android','windows'].includes(settings.platform)||!settings.path||!settings.uploadKey||!settings.siteToken||new URL(settings.origin).protocol!=='https:')throw new Error('Invalid upload settings');
const headers={Authorization:`Bearer ${settings.uploadKey}`,'OAI-Sites-Authorization':`Bearer ${settings.siteToken}`};
async function api(path,method,body,type='application/json') {
  const response=await fetch(new URL(path,settings.origin),{method,redirect:'error',signal:AbortSignal.timeout(60000),headers:{...headers,'Content-Type':type},...(body?{body:type==='application/json'?JSON.stringify(body):body}:{})});
  if(!response.ok)throw new Error(`Release upload failed: HTTP ${response.status}`);
  return response.json();
}
const size=(await stat(settings.path)).size,hash=createHash('sha256');
for await(const chunk of createReadStream(settings.path))hash.update(chunk);
const sha256=hash.digest('hex');
const{id}=await api(`/api/admin/releases/${settings.platform}/multipart`,'POST',{version:settings.version,size,sha256});
const file=await open(settings.path,'r');
try {
  for(let offset=0,part=1;offset<size;part++){
    const buffer=Buffer.alloc(Math.min(8*1024*1024,size-offset));
    const{bytesRead}=await file.read(buffer,0,buffer.length,offset);
    if(bytesRead!==buffer.length)throw new Error('Source file changed during upload');
    await api(`/api/admin/release-parts/${id}/${part}`,'PUT',buffer,'application/octet-stream');
    offset+=bytesRead;
    console.log(`${settings.platform}: ${Math.round(offset/size*100)}% uploaded`);
  }
  const release=await api(`/api/admin/release-parts/${id}`,'POST');
  const response=await fetch(new URL(release.url,settings.origin),{headers:{'OAI-Sites-Authorization':headers['OAI-Sites-Authorization']},redirect:'error',signal:AbortSignal.timeout(60000)});
  if(!response.ok)throw new Error(`Download verification failed: HTTP ${response.status}`);
  const checked=createHash('sha256');let count=0;
  for await(const chunk of response.body){checked.update(chunk);count+=chunk.length;}
  if(count!==size||checked.digest('hex')!==sha256)throw new Error('Downloaded release checksum mismatch');
  console.log(JSON.stringify({platform:settings.platform,version:settings.version,size,sha256,download_verified:true}));
}catch(error){await api(`/api/admin/release-parts/${id}`,'DELETE').catch(()=>{});throw error;}
finally{await file.close();}
