// Executed by Figma MCP after the batch constants have been decoded.
// Geometry comes from the reviewed local mockups. No complete UI raster is used.
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
await Promise.all(['Regular', 'Medium'].map(style => figma.loadFontAsync({family:'Golos Text', style})));
const allVariables = await figma.variables.getLocalVariablesAsync();
const oldIds = new Set(page.findAll(() => true).map(n => n.id));
const colorKey = c => [c.r,c.g,c.b].map(v => Math.round(v*255)).join(',');
function paint(c, theme) {
  if (!c || c.a === 0) return [];
  let p = {type:'SOLID',color:{r:c.r,g:c.g,b:c.b},opacity:c.a===undefined?1:c.a};
  const variable = VARIABLES.find(v => v.theme===theme && colorKey(v.color)===colorKey(c));
  if (variable) p=figma.variables.setBoundVariableForPaint(p,'color',allVariables.find(v=>v.id===variable.id));
  return [p];
}
function makeTree(scene) {
  const root={item:{x:0,y:0,w:scene.width,h:scene.height},children:[]}, surfaces=[];
  for (const raw of scene.nodes) {
    const item={...raw}; if(item.kind==='svg') item.svg=ASSETS[item.asset];
    const t={item,children:[]}; let parent=root,area=Infinity;
    for (const s of surfaces) {
      const a=s.item;
      if(a.w*a.h<area && a.w*a.h>item.w*item.h+.1 && item.x>=a.x-.2 && item.y>=a.y-.2 && item.x+item.w<=a.x+a.w+.2 && item.y+item.h<=a.y+a.h+.2) {parent=s;area=a.w*a.h;}
    }
    parent.children.push(t);
    if(item.kind==='rect' && item.w>3 && item.h>3) surfaces.push(t);
  }
  return root;
}
function signature(t,ox=0,oy=0) {
  const a={...t.item,x:Math.round((t.item.x-ox)*100)/100,y:Math.round((t.item.y-oy)*100)/100};
  delete a.id; delete a.name; delete a.asset;
  return JSON.stringify([a,t.children.map(c=>signature(c,t.item.x,t.item.y))]);
}
const roots=SCENES.map(makeTree),frequency=new Map();
function tally(t,scene) {
  if(t.item.kind==='rect' && t.children.length && t.item.w<scene.width*.98 && t.item.h<scene.height*.7) {
    t.signature=signature(t,t.item.x,t.item.y);
    frequency.set(t.signature,(frequency.get(t.signature)||0)+1);
  }
  t.children.forEach(c=>tally(c,scene));
}
roots.forEach((r,i)=>tally(r,SCENES[i]));
const masters=new Map(),mainComponents=[],frames=[],geometry=[];
let masterY=Math.max(80,...page.children.filter(n=>n.type==='COMPONENT').map(n=>n.y+n.height+40));
const masterX=SCENES[0].platform==='desktop'?8000:5200;
function rect(node,item,theme) {
  node.resize(Math.max(.1,item.w),Math.max(.1,item.h));
  node.cornerRadius=Math.min(item.radius||0,item.w/2,item.h/2);
  node.fills=paint(item.fill,theme);node.strokes=item.strokeWidth?paint(item.stroke,theme):[];
  if(item.strokeWidth){node.strokeWeight=item.strokeWidth;node.strokeAlign='INSIDE';}
  if('clipsContent' in node) node.clipsContent=false;
}
function content(t,theme,component=false) {
  const item=t.item;let node;
  if(item.kind==='rect') {
    const sorted=[...t.children].sort((a,b)=>a.item.x-b.item.x);
    const gaps=sorted.slice(1).map((c,i)=>c.item.x-sorted[i].item.x-sorted[i].item.w);
    const simple=sorted.length>0 && (!gaps.length||Math.max(...gaps)-Math.min(...gaps)<.8) && sorted.every((c,i)=>!i||c.item.x>=sorted[i-1].item.x+sorted[i-1].item.w-1) && sorted.every(c=>Math.abs(c.item.y+c.item.h/2-(item.y+item.h/2))<3);
    node=component?figma.createComponent():simple?figma.createAutoLayout('HORIZONTAL'):t.children.length?figma.createFrame():figma.createRectangle();
    rect(node,item,theme);
    for(const c of t.children) {
      const child=build(c,theme);node.appendChild(child);
      child.x=c.item.x-item.x;child.y=c.item.y-item.y-(c.item.kind==='text'?(c.item.lineHeight-c.item.h)/2:0);
    }
    if(simple) {
      node.layoutMode='HORIZONTAL';node.primaryAxisSizingMode='FIXED';node.counterAxisSizingMode='FIXED';
      node.counterAxisAlignItems='CENTER';node.primaryAxisAlignItems='MIN';
      node.paddingLeft=Math.max(0,sorted[0].item.x-item.x);
      node.paddingRight=Math.max(0,item.x+item.w-sorted[sorted.length-1].item.x-sorted[sorted.length-1].item.w);
      node.paddingTop=0;node.paddingBottom=0;node.itemSpacing=gaps.length?Math.max(0,gaps.reduce((s,x)=>s+x,0)/gaps.length):0;
      node.resize(Math.max(.1,item.w),Math.max(.1,item.h));
      node.layoutSizingHorizontal='FIXED';node.layoutSizingVertical='FIXED';
    }
    geometry.push({id:node.id,w:item.w,h:item.h});
  } else if(item.kind==='text') {
    node=figma.createText();node.fontName={family:'Golos Text',style:item.fontWeight>=500?'Medium':'Regular'};
    const style=TEXT_STYLES.find(s=>s.key===[item.fontSize,item.fontWeight,item.lineHeight].join('-'));
    if(style)node.textStyleId=style.id;
    node.fontSize=item.fontSize;node.characters=item.text;node.lineHeight={unit:'PIXELS',value:item.lineHeight};
    node.fills=paint(item.color,theme);node.textAutoResize='WIDTH_AND_HEIGHT';
  } else if(item.kind==='svg') {
    const svg=item.svg.replace(/<svg\b([^>]*)>/,(m,a)=>'<svg'+a.replace(/\s(?:width|height)="[^"]*"/g,'')+' width="'+item.w+'" height="'+item.h+'">');
    node=figma.createNodeFromSvg(svg);node.resize(Math.max(.1,item.w),Math.max(.1,item.h));
  } else if(item.kind==='checkbox') {
    const s=Math.min(item.w,item.h);
    node=figma.createNodeFromSvg('<svg xmlns="http://www.w3.org/2000/svg" width="'+s+'" height="'+s+'" viewBox="0 0 '+s+' '+s+'"><rect x="1" y="1" width="'+(s-2)+'" height="'+(s-2)+'" rx="4" fill="'+(item.checked?'#F5A623':'none')+'" stroke="'+(item.checked?'#F5A623':'#8C887F')+'"/>'+(item.checked?'<path d="M'+s*.22+' '+s*.5+' L'+s*.43+' '+s*.72+' L'+s*.8+' '+s*.28+'" fill="none" stroke="#0C0B0A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>':'')+'</svg>');
  } else throw new Error('Unknown layer '+item.kind);
  node.name=item.name||item.text||item.kind;return node;
}
function build(t,theme) {
  const key=theme+'|'+t.signature;
  if(t.signature&&frequency.get(t.signature)>1) {
    let main=masters.get(key);
    if(!main) {
      main=content(t,theme,true);page.appendChild(main);main.name='UI/'+theme+'/'+(t.item.name||'Элемент');
      main.description='Повторяемый элемент Тройки. Надписи меняются в свойствах экземпляра, общее оформление — в главном компоненте.';
      let label=0;
      for(const text of main.findAllWithCriteria({types:['TEXT']})) if(text.parent===main) {
        const property=main.addComponentProperty('Текст '+(++label),'TEXT',text.characters);
        text.componentPropertyReferences={characters:property};
      }
      main.x=masterX;main.y=masterY;masterY+=main.height+40;
      masters.set(key,main);mainComponents.push({id:main.id,name:main.name});
    }
    const instance=main.createInstance();instance.resize(t.item.w,t.item.h);return instance;
  }
  return content(t,theme);
}
for(let i=0;i<SCENES.length;i++) {
  const scene=SCENES[i],theme=scene.theme;
  const frame=scene.component?figma.createComponent():figma.createFrame();page.appendChild(frame);
  frame.name=(theme==='dark'?'Тёмная / ':'Светлая / ')+scene.name;
  frame.resize(scene.width,scene.height);frame.fills=[];frame.clipsContent=true;
  frame.x=scene.canvasX;frame.y=scene.canvasY;
  if(scene.component)frame.description='Голосовой контур Тройки: '+scene.name+'. Все элементы являются редактируемыми векторами и текстом.';
  for(const t of roots[i].children) {const child=build(t,theme);frame.appendChild(child);child.x=t.item.x;child.y=t.item.y-(t.item.kind==='text'?(t.item.lineHeight-t.item.h)/2:0);}
  frames.push({id:frame.id,sceneId:scene.id,name:frame.name,x:frame.x,y:frame.y,width:frame.width,height:frame.height});
}
const nodes=page.findAll(()=>true),counts={};for(const n of nodes)counts[n.type]=(counts[n.type]||0)+1;
const imageNodes=nodes.filter(n=>'fills' in n&&Array.isArray(n.fills)&&n.fills.some(f=>f.type==='IMAGE')).map(n=>({id:n.id,name:n.name,type:n.type,width:n.width,height:n.height}));
const byId=new Map(nodes.map(n=>[n.id,n]));const geometryErrors=geometry.filter(g=>{const n=byId.get(g.id);return n&&(Math.abs(n.width-g.w)>.1||Math.abs(n.height-g.h)>.1);});
return {geometryErrors,createdNodeIds:nodes.filter(n=>!oldIds.has(n.id)).map(n=>n.id),pageId:page.id,frames,mainComponents,geometry,counts,imageNodes,fontFamilies:[...new Set(nodes.filter(n=>n.type==='TEXT').map(n=>n.fontName.family))]};
