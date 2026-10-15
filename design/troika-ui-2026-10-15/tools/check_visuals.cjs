const fs=require('fs'),path=require('path');
const {chromium}=require('C:/Users/kiqu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const ROOT=path.resolve(__dirname,'..');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const report={javascriptErrors:[],overflow:[],checks:[],svgSamples:[]};
  try{
    for(const platform of ['android','desktop']){
      const page=await browser.newPage({viewport:{width:platform==='android'?420:1060,height:1600}});
      page.on('pageerror',e=>report.javascriptErrors.push(String(e)));
      await page.goto('file:///'+path.join(ROOT,'prototype',platform+'.html').replace(/\\/g,'/'),{waitUntil:'domcontentloaded'});
      const frame=page.frameLocator('iframe'),id=platform==='android'?'#troika-phone':'#troika-desktop';
      await frame.locator(id).waitFor();
      await frame.locator('body').evaluate(async()=>{await document.fonts.ready;for(let n=0;n<120&&!globalThis.lucide;n++)await new Promise(resolve=>setTimeout(resolve,100));if(globalThis.lucide)lucide.createIcons({attrs:{width:20,height:20}});});
      const names=await frame.locator(id).evaluate(root=>root.troikaDesign.screens);
      for(const width of [320,platform==='android'?420:1060]){
        await page.setViewportSize({width,height:1800});
        for(const name of names){
          await frame.locator(id).evaluate((root,name)=>{root.troikaDesign.go(name);root.troikaDesign.theme('dark');},name);
          const o=await frame.locator(id).evaluate(root=>{const r=root.getBoundingClientRect();return [...root.querySelectorAll('*')].filter(el=>{const b=el.getBoundingClientRect();return b.width>0&&(b.right>r.right+1||b.left<r.left-1);}).map(el=>el.tagName).slice(0,5);});
          if(o.length)report.overflow.push({platform,width,name,elements:o});
        }
      }
      await frame.locator(id).evaluate(root=>{root.troikaDesign.go('home');root.troikaDesign.theme('dark');});
      const movement=await frame.locator(id).evaluate(root=>new Promise(resolve=>{requestAnimationFrame(()=>{const canvas=root.querySelector('canvas'),first=canvas.toDataURL();let frames=0;function sample(){if(++frames<12)return requestAnimationFrame(sample);resolve({frames:+canvas.dataset.frame,changes:first!==canvas.toDataURL()});}requestAnimationFrame(sample);});}));
      if(!movement.changes)throw Error('Voice contour does not animate');
      report.checks.push({platform,name:'Animated contour changes geometry',passed:true});
      await page.emulateMedia({reducedMotion:'reduce'});
      const reduced=await frame.locator(id).evaluate(root=>new Promise(resolve=>{let n=0;function sample(){if(++n<6)return requestAnimationFrame(sample);resolve({count:root.querySelectorAll('[data-voice-contour]').length,frames:+root.querySelector('canvas').dataset.frame});}requestAnimationFrame(sample);}));
      if(reduced.count!==1||reduced.frames!==1)throw Error('Reduced-motion state is incorrect: '+JSON.stringify(reduced));
      report.checks.push({platform,name:'Reduced motion renders one static canvas',passed:true});
      await page.emulateMedia({reducedMotion:'no-preference'});
      await frame.locator(id).evaluate(root=>root.troikaDesign.go('text'));
      const input=frame.locator(platform==='android'?'#tk-phone-input':'#td-input');await input.fill('Пример сообщения');await input.press('Enter');
      const sent=await frame.locator(platform==='android'?'.tk-messages':'#td-messages').innerText();
      if(!sent.includes('Пример сообщения'))throw Error('Message entry failed');
      report.checks.push({platform,name:'Enter appends a local demonstration message',passed:true});
      await frame.locator('[data-file]').first().click();
      if(await frame.locator(id).getAttribute('data-screen')!=='file-detail')throw Error('File details navigation failed');
      report.checks.push({platform,name:'File opens its design details page',passed:true});
      await page.close();
    }
    const gallery=await browser.newPage({viewport:{width:1440,height:1000}});
    await gallery.goto('file:///'+path.join(ROOT,'index.html').replace(/\\/g,'/'));
    const before=await gallery.locator('article:visible').count();await gallery.locator('#platform').selectOption('desktop');await gallery.locator('#theme').selectOption('all');const after=await gallery.locator('article:visible').count();
    if(before!==36||after!==72)throw Error('Gallery filter mismatch');
    report.checks.push({name:'Gallery filters Android dark / desktop both themes',passed:true});
    await gallery.locator('#platform').selectOption('android');await gallery.locator('#theme').selectOption('dark');await gallery.screenshot({path:path.join(ROOT,'review/gallery.png')});
    await gallery.close();
    const font=fs.readFileSync(path.join(ROOT,'fonts/GolosText-Variable.ttf')).toString('base64');
    const manifest=JSON.parse(fs.readFileSync(path.join(ROOT,'manifest.json'),'utf8'));
    const samples=[manifest.screens.find(s=>s.platform==='android'&&s.theme==='dark'&&s.screen==='home').svg,manifest.screens.find(s=>s.platform==='android'&&s.theme==='light'&&s.screen==='home').svg,manifest.screens.find(s=>s.platform==='desktop'&&s.theme==='dark'&&s.screen==='file-detail').svg,'components/voice-idle.svg','components/voice-listening.svg'];
    for(const sample of samples){
      const page=await browser.newPage({viewport:{width:1100,height:1300}});
      await page.setContent('<style>@font-face{font-family:"Golos Text";src:url(data:font/ttf;base64,'+font+')}body{margin:0;background:#ddd}</style>'+fs.readFileSync(path.join(ROOT,sample),'utf8'));
      await page.evaluate(()=>document.fonts.ready);
      const output='review/vector-'+path.basename(sample,'.svg')+(sample.includes('/light/')?'-light':'-dark')+'.png';
      await page.locator('body>svg').screenshot({path:path.join(ROOT,output)});report.svgSamples.push({source:sample,preview:output});await page.close();
    }
  }finally{await browser.close();}
  report.actualFigmaImportVerified=false;
  fs.writeFileSync(path.join(ROOT,'quality-visuals.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
  if(report.javascriptErrors.length||report.overflow.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
