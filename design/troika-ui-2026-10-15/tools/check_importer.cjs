const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const ROOT=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(ROOT,'figma/code.js'),'utf8');
const scenes=JSON.parse(fs.readFileSync(path.join(ROOT,'figma/scenes.json'),'utf8'));
class Layer{
  constructor(type){this.type=type;this.children=[];this.width=100;this.height=100;this.name='';this.removed=false;}
  resize(w,h){assert(Number.isFinite(w)&&w>0&&Number.isFinite(h)&&h>0);this.width=w;this.height=h;}
  appendChild(node){assert(node instanceof Layer);this.children.push(node);}
}
async function scenario(platform,theme,failFont=false){
  const pages=[],messages=[],allNodes=[],existing=new Layer('PAGE');existing.name='Existing user work';
  const make=type=>{const node=new Layer(type);allNodes.push(node);return node;};
  const api={currentPage:existing,root:{children:[existing]},viewport:{scrollAndZoomIntoView(nodes){assert(nodes.length===1);}},ui:{postMessage(m){messages.push(m);}},showUI(html,size){assert(html.includes('Добавить макеты'));assert(size.width>0);},notify(){},loadFontAsync:async font=>{assert.strictEqual(font.family,'Golos Text');assert(['Regular','Medium'].includes(font.style));if(failFont)throw Error('Font unavailable');},
    createPage(){const node=make('PAGE');pages.push(node);return node;},createFrame(){return make('FRAME');},createComponent(){return make('COMPONENT');},createRectangle(){return make('RECTANGLE');},createText(){return make('TEXT');},createNodeFromSvg(svg){assert(svg.startsWith('<svg'));assert(!/<image\b/i.test(svg));const node=make('VECTOR_FRAME');const tag=svg.match(/<svg\b[^>]*>/)[0];const w=+(tag.match(/\bwidth="([\d.]+)"/)||[])[1],h=+(tag.match(/\bheight="([\d.]+)"/)||[])[1];assert(w>0&&h>0);node.resize(w,h);return node;},async setCurrentPageAsync(page){api.currentPage=page;}};
  const context=vm.createContext({figma:api,console,Map,Promise,Math,Error});
  vm.runInContext(source,context,{timeout:10000});
  await api.ui.onmessage({type:'import',platform,theme});
  const wanted=failFont?0:scenes.filter(s=>(platform==='all'||s.platform===platform)&&(theme==='all'||s.theme===theme)).length;
  const frames=allNodes.filter(n=>['FRAME','COMPONENT'].includes(n.type));
  assert.strictEqual(frames.length,wanted);
  assert(!existing.removed&&existing.name==='Existing user work');
  if(!failFont){assert(messages.some(m=>m.done&&m.status.startsWith('Готово')));assert(allNodes.some(n=>n.type==='TEXT'&&n.characters==='Скажи, что нужно')||platform==='components');}
  else assert(messages.some(m=>m.done&&m.status.includes('Font unavailable')));
  return {platform,theme,fontFailure:failFont,pages:pages.length,frames:frames.length,textLayers:allNodes.filter(n=>n.type==='TEXT').length,svgLayers:allNodes.filter(n=>n.type==='VECTOR_FRAME').length};
}
(async()=>{const results=[];results.push(await scenario('android','dark'));results.push(await scenario('all','all'));results.push(await scenario('android','dark',true));fs.writeFileSync(path.join(ROOT,'figma/importer-check.json'),JSON.stringify({method:'Local Figma API model; not an actual Figma import',results},null,2));console.log(JSON.stringify(results,null,2));})().catch(error=>{console.error(error);process.exitCode=1;});
