/* A local API model checks construction, resume behavior and editable layer types.
   It cannot verify rendering, permissions or API support inside real Figma. */
const fs=require('fs'),path=require('path'),vm=require('vm');const root=path.resolve(__dirname,'..');
let serial=0,all=[],collections=[],variables=[],textStyles=[],lastMessage;const counts={};
class Node{constructor(type){this.type=type;this.id='n'+(++serial);this.name='';this.children=[];this.fills=[];this.strokes=[];this.x=0;this.y=0;this.width=100;this.height=100;all.push(this);counts[type]=(counts[type]||0)+1;}appendChild(n){if(n.parent)n.parent.children=n.parent.children.filter(x=>x!==n);this.children.push(n);n.parent=this;}resize(w,h){if(!(Number.isFinite(w)&&Number.isFinite(h)&&w>0&&h>0))throw Error('Invalid size '+w+' '+h);this.width=w;this.height=h;}async setTextStyleIdAsync(id){if(!textStyles.some(s=>s.id===id))throw Error('Missing text style');this.textStyleId=id;}async setReactionsAsync(r){for(const a of r.flatMap(x=>x.actions))if(!all.some(n=>n.id===a.destinationId))throw Error('Missing prototype destination');this.reactions=r;}addComponentProperty(name,type,value){return name+'#'+this.id;}createInstance(){const n=new Node('INSTANCE');n.width=this.width;n.height=this.height;return n;}}
const document=new Node('DOCUMENT'),initial=new Node('PAGE');initial.name='Page 1';document.appendChild(initial);
const figma={root:document,currentPage:initial,ui:{postMessage:m=>lastMessage=m},viewport:{scrollAndZoomIntoView(){}},showUI(){},createPage(){const n=new Node('PAGE');document.appendChild(n);return n;},async setCurrentPageAsync(n){if(n.type!=='PAGE')throw Error('Not a page');figma.currentPage=n;},createFrame:()=>new Node('FRAME'),createRectangle:()=>new Node('RECTANGLE'),createText:()=>new Node('TEXT'),createComponent:()=>new Node('COMPONENT'),createNodeFromSvg(svg){if(!svg.includes('<svg'))throw Error('Invalid SVG');if(/<image\b/.test(svg))throw Error('Rasterized SVG');const n=new Node('SVG');n.svg=svg;return n;},async listAvailableFontsAsync(){return ['Golos Text','Consolas'].flatMap(family=>['Regular','Medium','SemiBold','Bold'].map(style=>({fontName:{family,style}})));},async loadFontAsync(){},async getLocalTextStylesAsync(){return textStyles;},createTextStyle(){const n={id:'style'+(++serial)};textStyles.push(n);return n;},variables:{async getLocalVariableCollectionsAsync(){return collections;},async getLocalVariablesAsync(){return variables;},createVariableCollection(name){const n={id:'collection'+(++serial),name,defaultModeId:'mode'+serial,renameMode(){}};collections.push(n);return n;},createVariable(name,c,type){const n={id:'variable'+(++serial),name,variableCollectionId:c.id,resolvedType:type,setValueForMode(mode,value){this.value=value;},setVariableCodeSyntax(){}};variables.push(n);return n;},setBoundVariableForPaint(p,property,v){if(!variables.some(x=>x.id===v.id))throw Error('Invalid variable');return {...p,boundVariables:{[property]:{id:v.id,type:'VARIABLE_ALIAS'}}};}}};
const context=vm.createContext({figma,__html__:'',setTimeout:(fn)=>{fn();return 0;},Map,Set,console});vm.runInContext(fs.readFileSync(path.join(root,'figma/code.js'),'utf8'),context);
const frameName=s=>`${String(s.index+1).padStart(2,'0')} · ${s.name} · ${s.theme==='dark'?'Тёмная':'Светлая'}`;
const sceneKey=s=>`${s.platform}/${s.theme}/${s.page}`;
const frameFor=s=>document.children.find(p=>p.name===(s.platform==='android'?'Android':'ПК'))?.children.find(n=>n.name===frameName(s));
async function importScenes(scenes){await figma.ui.onmessage({type:'import',scenes});if(lastMessage.type!=='done')throw Error(lastMessage.text);}
function walkScene(source,node,visit){if(!node)throw Error('Missing editable node '+source.name);visit(source,node);if(source.kind==='frame'){if(node.children.length!==(source.children||[]).length)throw Error('Scene hierarchy changed at '+source.name);for(let i=0;i<(source.children||[]).length;i++)walkScene(source.children[i],node.children[i],visit);}}
(async()=>{
  const scenes=JSON.parse(fs.readFileSync(path.join(root,'figma/scenes.json'),'utf8'));
  const firstFive=scenes.filter(s=>s.index<5),firstKeys=new Set(firstFive.map(sceneKey)),delayed=[];
  await importScenes(firstFive);
  for(const scene of firstFive)walkScene(scene.root,frameFor(scene),(source,node)=>{if(source.go&&!firstKeys.has(`${scene.platform}/${scene.theme}/${source.go}`)&&scenes.some(s=>s.platform===scene.platform&&s.theme===scene.theme&&s.page===source.go))delayed.push({scene,source,node});});
  if(!delayed.length)throw Error('Progressive import fixture has no deferred destinations');
  await importScenes(scenes);
  const frames=document.children.flatMap(p=>p.children).filter(n=>/^\d+ · /.test(n.name));
  if(frames.length!==scenes.length)throw Error('Incomplete import '+frames.length);
  let prototypeLinks=0,editableControls=0,radioDots=0;
  const destinations=new Map(scenes.map(s=>[sceneKey(s),frameFor(s).id]));
  for(const scene of scenes)walkScene(scene.root,frameFor(scene),(source,node)=>{
    if(source.go){const target=destinations.get(`${scene.platform}/${scene.theme}/${source.go}`);if(target){if(node.reactions?.[0]?.actions?.[0]?.destinationId!==target)throw Error('Missing prototype link '+sceneKey(scene)+' -> '+source.go);prototypeLinks++;}}
    if(source.kind==='checkbox'){
      editableControls++;
      if(node.type!=='FRAME'||node.children.length!==(source.checked?2:1)||!node.children[0].strokes.length)throw Error('Invisible or detached form control '+sceneKey(scene));
      if(source.checked&&source.round){const dot=node.children[1];if(dot.type!=='RECTANGLE'||dot.cornerRadius!==dot.width/2||!dot.fills.length)throw Error('Radio must use an editable round dot');radioDots++;}
    }
    if(source.kind==='text'&&node.letterSpacing?.value!==(source.letterSpacing||0))throw Error('Text letter spacing was lost');
  });
  for(const {scene,source,node}of delayed)if(node.reactions?.[0]?.actions?.[0]?.destinationId!==destinations.get(`${scene.platform}/${scene.theme}/${source.go}`))throw Error('First import did not gain deferred prototype link');
  const before=all.length;await importScenes(scenes);
  if(all.length!==before)throw Error('Repeat import duplicated editable layers');
  const textStyleCount=textStyles.length;
  const spacingStyles=vm.runInContext("[-.7,0].map(letterSpacing=>styleFor({fontSize:14,lineHeight:22,fontWeight:400,fontFamily:'Golos Text',letterSpacing}))",context);
  if(spacingStyles[0].id===spacingStyles[1].id||spacingStyles[0].letterSpacing.value!==-.7||spacingStyles[1].letterSpacing.value!==0)throw Error('Text styles merge different letter spacing');
  const report={modelOnly:true,realFigmaRun:false,frames:frames.length,pages:document.children.length,layerTypes:counts,variables:variables.length,textStyles:textStyleCount,repeatImportAddedLayers:all.length-before,prototypeLinks,progressiveImportLinksUpdated:delayed.length,editableControls,radioDots,letterSpacingPreserved:true};
  fs.writeFileSync(path.join(root,'review/importer-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
