const fs=require('fs');
const path=require('path');
const {contourSvg,vectorMarkup,writeSvg}=require('./export_design.cjs');
const ROOT=path.resolve(__dirname,'..');
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const scenes=JSON.parse(fs.readFileSync(path.join(ROOT,'figma/scenes.json'),'utf8'));
const manifest=JSON.parse(fs.readFileSync(path.join(ROOT,'manifest.json'),'utf8'));
const components=[];
const labels={idle:'Ожидание',listening:'Слушаю',thinking:'Разбираюсь',acting:'Выполняю',approval:'Нужно разрешение',speaking:'Отвечаю',done:'Готово',error:'Ошибка'};
const mic=scenes.find(s=>s.id==='android-dark-home').nodes.find(n=>n.kind==='svg'&&n.name==='Иконка · mic');
for(const [index,state] of Object.keys(labels).entries()){
  let signal='';
  const markup=contourSvg(260,state,'component-'+state);
  const svg=markup.replace('</svg>',signal+'</svg>');
  const scene={id:'voice-'+state,name:'Голос · '+labels[state],screen:state,platform:'components',theme:'dark',width:320,height:340,component:true,
    nodes:[{kind:'rect',id:'bg',x:0,y:0,w:320,h:340,radius:16,fill:{r:12/255,g:11/255,b:10/255,a:1},name:'Фон'},
      {kind:'text',id:'label',x:24,y:20,w:272,h:24,baseline:39,text:labels[state],fontSize:16,fontWeight:500,lineHeight:24,color:{r:243/255,g:240/255,b:234/255,a:1},name:'Название состояния'},
      {kind:'svg',id:'contour',x:30,y:60,w:260,h:260,svg,name:'Деформируемый янтарный контур'}]};
  if(state==='idle'&&mic)scene.nodes.push({...mic,id:'mic',x:142,y:172,w:36,h:36});
  if(['approval','done'].includes(state)){
    const file=state==='approval'?'shield':'check';
    const icon=fs.readFileSync(path.join(ROOT,'../../brand/troika/icons',file+'.svg'),'utf8').replace(/currentColor/g,'#FFF8E7');
    scene.nodes.push({kind:'svg',id:'signal',x:142,y:172,w:36,h:36,svg:icon,name:'Сигнал состояния'});
  }
  if(state==='acting')scene.nodes.push({kind:'svg',id:'signal',x:142,y:172,w:36,h:36,svg:'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24"><path d="M13 2L4 14h7l-1 8L20 10h-7z" fill="none" stroke="#FFF8E7" stroke-width="1.8" stroke-linejoin="round"/></svg>',name:'Выполнение'});
  if(state==='thinking')scene.nodes.push({kind:'svg',id:'signal',x:142,y:172,w:36,h:36,svg:'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><path d="M18 4 A14 14 0 1 1 4 18" fill="none" stroke="#FFF8E7" stroke-width="2.5" stroke-linecap="round"/></svg>',name:'Ожидание ответа'});
  if(state==='error')scene.nodes.push({kind:'text',id:'signal',x:153,y:168,w:20,h:48,baseline:207,text:'!',fontSize:36,fontWeight:500,lineHeight:48,color:{r:1,g:248/255,b:231/255,a:1},name:'Ошибка'});
  scene.svg=`components/voice-${state}.svg`;
  writeSvg(scene,path.join(ROOT,scene.svg));components.push(scene);
}
const all=[...scenes,...components];
fs.writeFileSync(path.join(ROOT,'figma/scenes.json'),JSON.stringify(all));
const template=fs.readFileSync(path.join(ROOT,'figma/importer-template.js'),'utf8');
fs.writeFileSync(path.join(ROOT,'figma/code.js'),template.replace('__TROIKA_SCENES__',JSON.stringify(all)));
fs.mkdirSync(path.join(ROOT,'boards'),{recursive:true});
for(const platform of ['android','desktop'])for(const theme of ['dark','light']){
  const subset=scenes.filter(s=>s.platform===platform&&s.theme===theme);
  const cols=platform==='android'?5:3;
  const columnWidth=platform==='android'?460:1120;
  let rowY=100,rowHeight=0;
  const parts=[];
  subset.forEach((s,index)=>{
    if(index&&index%cols===0){rowY+=rowHeight+100;rowHeight=0;}
    const x=48+(index%cols)*columnWidth;
    parts.push(`<text x="${x}" y="${rowY-16}" font-family="Golos Text,Arial,sans-serif" font-size="16" fill="${theme==='dark'?'#F3F0EA':'#0C0B0A'}">${escape(s.name)}</text><svg x="${x}" y="${rowY}" width="${s.width}" height="${s.height}" viewBox="0 0 ${s.width} ${s.height}">${vectorMarkup(s.nodes,'board-'+s.id)}</svg>`);
    rowHeight=Math.max(rowHeight,s.height);
  });
  const width=cols*columnWidth+16,height=rowY+rowHeight+48;
  fs.writeFileSync(path.join(ROOT,`boards/${platform}-${theme}.svg`),`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="${theme==='dark'?'#25231F':'#E6E2D9'}"/><text x="48" y="46" font-family="Golos Text,Arial,sans-serif" font-size="24" fill="${theme==='dark'?'#F3F0EA':'#0C0B0A'}">Тройка · ${platform==='android'?'Android':'Компьютер'} · ${theme==='dark'?'тёмная тема':'светлая тема'}</text>${parts.join('\n')}</svg>`);
}
const fontData=fs.readFileSync(path.join(ROOT,'fonts/GolosText-Variable.ttf')).toString('base64');
const cards=scenes.map(s=>`<article data-platform="${s.platform}" data-theme="${s.theme}"><a href="${s.svg}" aria-label="Открыть SVG: ${escape(s.name)}"><img src="${s.preview}" alt="${escape(s.name)}" loading="lazy"></a><div><strong>${escape(s.name)}</strong><span>${s.platform==='android'?'Android':'ПК'} · ${s.theme==='dark'?'тёмная':'светлая'}</span><a href="${s.svg}" download>SVG</a></div></article>`).join('');
fs.writeFileSync(path.join(ROOT,'index.html'),`<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Тройка · все страницы</title><style>@font-face{font-family:Golos;src:url(data:font/ttf;base64,${fontData})}*{box-sizing:border-box}body{margin:0;background:#f3f0ea;color:#24221d;font:14px/1.5 Golos,Arial,sans-serif}main{max-width:1500px;margin:auto;padding:40px 24px}h1{font-size:28px;font-weight:500;letter-spacing:-.5px;margin:0 0 8px}p{margin:0;color:#625f56}nav{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:24px 0}label{display:flex;align-items:center;gap:8px}select{font:inherit;padding:10px 12px;background:#fff;border:1px solid #d6d1c7;border-radius:8px}a{color:#805019}nav a{margin-left:8px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:28px}article{min-width:0}article img{display:block;width:100%;height:500px;object-fit:contain;object-position:top;background:#e9e5dc;border:1px solid #ded8cc;border-radius:12px}article[data-platform=desktop] img{height:300px}article>div{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}strong{font-weight:500}article span{font-size:12px;color:#666258}article>div>a{margin-left:auto}[hidden]{display:none!important}.links{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0 28px}footer{margin-top:40px;padding-top:20px;border-top:1px solid #d6d1c7;color:#666258;font-size:12px}@media(max-width:600px){main{padding:24px 16px}.grid{grid-template-columns:1fr}article img{height:560px}}</style></head><body><main><h1>Тройка · все страницы</h1><p>${scenes.length} экранов · две темы · Android и компьютер</p><div class="links"><a href="prototype/android.html">Телефон · интерактивно</a><a href="prototype/desktop.html">Компьютер · интерактивно</a><a href="FIGMA.md">Как открыть в Figma</a></div><nav aria-label="Фильтры"><label>Платформа<select id="platform"><option value="all">Все</option><option value="android" selected>Android</option><option value="desktop">Компьютер</option></select></label><label>Тема<select id="theme"><option value="dark">Тёмная</option><option value="light">Светлая</option><option value="all">Обе темы</option></select></label><span id="count" role="status"></span></nav><div class="grid">${cards}</div><footer>Дизайн-концепт. Данные демонстрационные. Голосовой контур повторяет Android StatusOrb. Анимация работает в интерактивном просмотре; SVG содержит статичный векторный кадр.</footer></main><script>const p=document.getElementById('platform'),t=document.getElementById('theme');function render(){let n=0;document.querySelectorAll('article').forEach(el=>{el.hidden=!(p.value==='all'||p.value===el.dataset.platform)||!(t.value==='all'||t.value===el.dataset.theme);if(!el.hidden)n++});document.getElementById('count').textContent=n+' экранов'}p.onchange=render;t.onchange=render;render();</script></body></html>`);
manifest.components=components.map(({id,name,svg})=>({id,name,svg}));
manifest.figma={nativeTextImporter:'figma/code.js',nativeFigmaImportVerified:false,svgTextMayImportAsVectors:true};
manifest.animation={source:'hermes-android/lib/widgets/status_orb.dart',idleBreathMs:2600,idleMotionMs:8000,listeningBreathMs:760,listeningMotionMs:1200,reducedMotionSupported:true,svgIsStatic:true};
fs.writeFileSync(path.join(ROOT,'manifest.json'),JSON.stringify(manifest,null,2));
console.log(JSON.stringify({screens:scenes.length,components:components.length,boards:4,allLayers:all.reduce((n,s)=>n+s.nodes.length,0)},null,2));
