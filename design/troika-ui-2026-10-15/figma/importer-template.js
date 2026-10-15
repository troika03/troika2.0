// Run in a newly created, local Figma Design development plugin.
// No network access. Only creates new pages; never clears existing content.
const TROIKA_SCENES = __TROIKA_SCENES__;
const UI = '<style>body{font:14px/1.5 Inter,Arial,sans-serif;margin:24px;color:#24231f}h2{font-size:20px;font-weight:500}label{display:block;margin:16px 0}select,button{font:inherit;padding:10px;width:100%;box-sizing:border-box}button{background:#191714;color:#fff;border:0;border-radius:8px;margin-top:16px}p{font-size:12px;color:#626057}</style><h2>Макеты Тройки</h2><label>Платформа<select id="platform"><option value="android">Android</option><option value="desktop">Компьютер</option><option value="components">Компоненты и состояния</option><option value="all">Всё</option></select></label><label>Тема<select id="theme"><option value="dark">Тёмная</option><option value="light">Светлая</option><option value="all">Обе темы</option></select></label><p>Нужен установленный Golos Text. Создаются обычные текстовые и векторные слои.</p><button id="run">Добавить макеты</button><p id="status" role="status"></p><script>document.getElementById("run").onclick=()=>{document.getElementById("run").disabled=true;parent.postMessage({pluginMessage:{type:"import",platform:document.getElementById("platform").value,theme:document.getElementById("theme").value}},"*")};onmessage=e=>{if(e.data.pluginMessage){document.getElementById("status").textContent=e.data.pluginMessage.status||"";if(e.data.pluginMessage.done)document.getElementById("run").disabled=false}};</script>';

function paint(c) {
  return c && (c.a === undefined || c.a > 0)
    ? [{type:'SOLID',color:{r:c.r,g:c.g,b:c.b},opacity:c.a===undefined?1:c.a}]
    : [];
}

async function addLayer(parent,item) {
  let node;
  if(item.kind==='rect'){
    node=figma.createRectangle();
    node.resize(Math.max(0.1,item.w),Math.max(0.1,item.h));
    node.cornerRadius=Math.min(item.radius||0,item.w/2,item.h/2);
    node.fills=paint(item.fill);
    node.strokes=item.strokeWidth?paint(item.stroke):[];
    if(item.strokeWidth)node.strokeWeight=item.strokeWidth;
  }else if(item.kind==='text'){
    node=figma.createText();
    node.fontName={family:'Golos Text',style:item.fontWeight>=500?'Medium':'Regular'};
    node.fontSize=item.fontSize;
    node.characters=item.text;
    node.lineHeight={unit:'PIXELS',value:item.lineHeight};
    node.fills=paint(item.color);
    node.textAutoResize='WIDTH_AND_HEIGHT';
  }else if(item.kind==='checkbox'){
    const size=Math.min(item.w,item.h);
    node=figma.createNodeFromSvg('<svg xmlns="http://www.w3.org/2000/svg" width="'+size+'" height="'+size+'"><rect x="1" y="1" width="'+(size-2)+'" height="'+(size-2)+'" rx="4" fill="'+(item.checked?'#F5A623':'none')+'" stroke="'+(item.checked?'#F5A623':'#8C887F')+'"/>'+(item.checked?'<path d="M'+size*.22+' '+size*.5+' L'+size*.43+' '+size*.72+' L'+size*.8+' '+size*.28+'" fill="none" stroke="#0C0B0A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>':'')+'</svg>');
  }else if(item.kind==='svg'){
    const normalized=item.svg.replace(/<svg\b([^>]*)>/,(match,attributes)=>'<svg'+attributes.replace(/\s(?:width|height)="[^"]*"/g,'')+' width="'+item.w+'" height="'+item.h+'">');
    node=figma.createNodeFromSvg(normalized);
    node.resize(Math.max(0.1,item.w),Math.max(0.1,item.h));
  }else return;
  parent.appendChild(node);
  node.name=item.name||item.text||item.kind;
  node.x=item.x;node.y=item.y;
}

figma.showUI(UI,{width:360,height:430});
let importing=false;
figma.ui.onmessage=async message=>{
  if(message.type!=='import'||importing)return;
  importing=true;
  let created=0;
  try{
    const needed=TROIKA_SCENES.filter(s=>(message.platform==='all'||s.platform===message.platform)&&(message.theme==='all'||s.theme===message.theme));
    if(!needed.length)throw new Error('Для выбранного сочетания нет макетов. Для компонентов выберите тёмную тему.');
    await Promise.all([figma.loadFontAsync({family:'Golos Text',style:'Regular'}),figma.loadFontAsync({family:'Golos Text',style:'Medium'})]);
    const pages=new Map(),positions=new Map();let first=null;
    for(const scene of needed){
      const key=scene.platform+'-'+scene.theme;
      if(!pages.has(key)){
        const page=figma.createPage();page.name='Тройка · '+({android:'Android',desktop:'Компьютер',components:'Компоненты'}[scene.platform])+' · '+(scene.theme==='dark'?'тёмная':'светлая');
        pages.set(key,page);positions.set(key,{x:0,y:0,count:0,rowHeight:0});
      }
      const page=pages.get(key),p=positions.get(key);
      const frame=scene.component?figma.createComponent():figma.createFrame();page.appendChild(frame);frame.name=scene.name;frame.resize(scene.width,scene.height);frame.fills=[];frame.clipsContent=true;
      frame.x=p.x;frame.y=p.y;
      for(const item of scene.nodes)await addLayer(frame,item);
      if(!first)first={page,frame};
      p.rowHeight=Math.max(p.rowHeight,scene.height);p.x+=scene.width+80;p.count++;
      if(p.count%(scene.platform==='desktop'?3:5)===0){p.x=0;p.y+=p.rowHeight+120;p.rowHeight=0;}
      created++;figma.ui.postMessage({status:'Добавлено '+created+' из '+needed.length});
    }
    if(first){await figma.setCurrentPageAsync(first.page);figma.currentPage.selection=[first.frame];figma.viewport.scrollAndZoomIntoView([first.frame]);}
    figma.ui.postMessage({status:'Готово. '+created+' экранов. Текст и элементы редактируются.',done:true});
    figma.notify('Макеты Тройки добавлены: '+created);
  }catch(error){
    figma.ui.postMessage({status:'Импорт остановлен. '+String(error.message||error)+' Уже создано: '+created+'. Установите Golos Text из папки fonts и повторите при необходимости.',done:true});
  }finally{importing=false;}
};
