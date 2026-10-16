// Prepare bounded native-layer batches for the connected Figma Design file.
const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'..');
const work=path.resolve(root,'../../work/troika-figma-import');
const config=JSON.parse(fs.readFileSync(path.join(work,'config.json'),'utf8'));
const scenes=JSON.parse(fs.readFileSync(path.join(root,'figma/scenes.json'),'utf8'));
const importer=fs.readFileSync(path.join(root,'figma/native-import-page.js'),'utf8');
const variables=config.variables.map(v=>{
  const [theme,name]=v.name.split('/'),hex=config.palette[theme][name.slice(3)];
  return {id:v.id,theme,color:{r:parseInt(hex.slice(1,3),16)/255,g:parseInt(hex.slice(3,5),16)/255,b:parseInt(hex.slice(5,7),16)/255}};
});
// LZW is data transport only. The decoded payload is JSON, never evaluated code.
function compress(s){
  const a=[...new Set(s.split(''))].join(''),dict=new Map(a.split('').map((c,i)=>[c,i]));
  let next=a.length,w='',codes=[];
  for(const c of s){const joined=w+c;if(dict.has(joined))w=joined;else{codes.push(dict.get(w));if(next<53000)dict.set(joined,next++);w=c;}}
  if(w)codes.push(dict.get(w));
  const bytes=Buffer.alloc(codes.length*2);codes.forEach((c,i)=>bytes.writeUInt16LE(c,i*2));
  return {a,c:bytes.toString('base64')};
}
const decoder=`function unpack(p){const a="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",bytes=[];let v=0,b=0;for(const c of p.c){if(c==="=")break;const k=a.indexOf(c);if(k<0)continue;v=(v<<6)|k;b+=6;if(b>=8){b-=8;bytes.push((v>>b)&255);}}const d=p.a.split("");let next=d.length,codes=[];for(let i=0;i<bytes.length;i+=2)codes.push(bytes[i]|bytes[i+1]<<8);let w=d[codes[0]],out=w;for(let i=1;i<codes.length;i++){const k=codes[i],e=d[k]===undefined?w+w[0]:d[k];out+=e;if(next<53000)d[next++]=w+e[0];w=e;}return out;}`;
const batches=[];
for(const platform of ['android','desktop','components']){
  for(const theme of ['dark','light']){
    const list=scenes.filter(s=>s.platform===platform&&s.theme===theme),cols=platform==='desktop'?3:5;
    let x=80+(theme==='light'?(platform==='desktop'?3700:2450):0),start=x,y=80,rowHeight=0;
    list.forEach((s,i)=>{s.canvasX=x;s.canvasY=y;x+=s.width+80;rowHeight=Math.max(rowHeight,s.height);if((i+1)%cols===0){x=start;y+=rowHeight+120;rowHeight=0;}});
  }
  const list=scenes.filter(s=>s.platform===platform);
  let start=platform==='android'?6:0;
  while(start<list.length){
    let size=Math.min(6,list.length-start),code,selected;
    do{
      selected=list.slice(start,start+size);const assets=[],map=new Map();
      const packed=selected.map(s=>{const {nodes,...meta}=s;delete meta.svg;delete meta.preview;return {...meta,nodes:nodes.map(n=>{const out={...n};delete out.id;delete out.baseline;if(out.name===out.text)delete out.name;if(n.kind==='svg'){if(!map.has(n.svg)){map.set(n.svg,assets.length);assets.push(n.svg);}out.asset=map.get(n.svg);delete out.svg;}return out;})};});
      const payload={PAGE_ID:config.pages[platform==='android'?0:platform==='desktop'?1:2].id,SCENES:packed,ASSETS:assets,VARIABLES:variables,TEXT_STYLES:config.textStyles};
      code=decoder+'\nconst {PAGE_ID,SCENES,ASSETS,VARIABLES,TEXT_STYLES}=JSON.parse(unpack('+JSON.stringify(compress(JSON.stringify(payload)))+'));\n'+importer;
      if(Buffer.byteLength(code,'utf8')<=48000&&code.length<=48000)break;
      size--;
    }while(size>0);
    if(!size)throw new Error('A single screen exceeds the import limit');
    const id=batches.length,file=String(id).padStart(2,'0')+'.js';
    fs.writeFileSync(path.join(work,file),code);
    batches.push({id,file,platform,sceneIds:selected.map(s=>s.id),count:selected.length,bytes:Buffer.byteLength(code,'utf8')});
    start+=size;
  }
}
fs.writeFileSync(path.join(work,'batches.json'),JSON.stringify(batches,null,2));
console.log(JSON.stringify({batches:batches.length,screens:batches.reduce((n,b)=>n+b.count,0),maxBytes:Math.max(...batches.map(b=>b.bytes))}));
