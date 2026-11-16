"use strict";
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require(process.env.TROIKA_PLAYWRIGHT || "playwright");

const base = __dirname;
const master = process.argv.includes("--master");
const targetFrames = 724;
const previewFrames = [40,86,150,230];

async function build() {
  const [template,font,license] = await Promise.all([
    fs.readFile(path.join(base,"film.template.html"),"utf8"),
    fs.readFile(path.join(base,"InterVariable.woff2")),
    fs.readFile(path.join(base,"Inter-OFL.txt"),"utf8")
  ]);
  const file = path.join(base,"Troika-Cinematic.html");
  await fs.writeFile(file,template.replace("__INTER_WOFF__",font.toString("base64")).replace("__INTER_OFL__",license));
  return pathToFileURL(file).href;
}
async function makeCamera(browser,url) {
  const page = await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  const errors = [];
  page.on("pageerror",error=>errors.push(error.message));
  await page.goto(url);
  await page.evaluate(async()=>{
    await window.timelineReady;
    if (document.fonts.size!==1 || !document.fonts.check("600 24px Inter","Тройка")) throw new Error("Inter not loaded");
  });
  return {
    page,
    async capture(frame) {
      await page.evaluate(value=>window.seek(value),frame);
      const image = await page.screenshot({type:"png",animations:"disabled"});
      if (errors.length) throw new Error(errors.join("\n"));
      return image;
    },
    async close() { await page.context().close(); }
  };
}
async function checkTimeline(camera) {
  const contract = await camera.page.evaluate(()=>{
    const checks = [0,71.5,72,100.5,101,158.5,159,186.5,187,214.5,215,244.5,245,300.5,301,361.5];
    return checks.map(f=>{ window.seek(f); return Number(document.documentElement.dataset.shot); });
  });
  if (contract.join(",")!=="1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8") throw new Error("Cut frames failed: "+contract);
  const frozenA = await camera.capture(269);
  const frozenB = await camera.capture(287);
  if (!frozenA.equals(frozenB)) throw new Error("Symbol should hold still from f269 to f287");
}
async function preview(camera) {
  for (const frame of previewFrames) {
    const image = await camera.capture(frame);
    await camera.capture(frame+.5);
    if (!image.equals(await camera.capture(frame))) throw new Error("Non-deterministic frame "+frame);
    if (frame===150 && !await camera.page.getByText("Тройка, составь план дня",{exact:true}).isVisible()) {
      throw new Error("Command has not finished at f150");
    }
    await fs.writeFile(path.join(base,"Troika-f"+frame+".png"),image);
    process.stdout.write("Verified 1920x1080 at f"+frame+"\n");
  }
}
async function completePng(file) {
  let handle;
  try {
    handle = await fs.open(file,"r");
    const { size } = await handle.stat();
    if (size < 45) return false;
    const trailer = Buffer.alloc(12);
    await handle.read(trailer,0,12,size-12);
    return trailer.equals(Buffer.from("0000000049454e44ae426082","hex"));
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  } finally {
    await handle?.close();
  }
}

async function record(browser,url,firstCamera) {
  const folder = process.env.TROIKA_FRAME_DIR || path.join(base,"frames");
  const prior = process.env.TROIKA_RESUME_FRAME_DIR;
  await fs.mkdir(folder,{recursive:true});
  let next = 0;
  let complete = 0;
  async function worker(camera) {
    try {
      while (next < targetFrames) {
        const index = next++;
        const name = path.join(folder,"frame-"+String(index).padStart(4,"0")+".png");
        const exists = process.argv.includes("--resume") &&
          (await completePng(name) || (prior && await completePng(path.join(prior,path.basename(name)))));
        if (!exists) {
          const image = await camera.capture(index/2);
          await fs.writeFile(name,image);
        }
        if (++complete%60===0 || complete===targetFrames) console.log(complete+"/"+targetFrames);
      }
    } finally {
      await camera.close();
    }
  }
  const cameras = [firstCamera,...await Promise.all([makeCamera(browser,url),makeCamera(browser,url)])];
  await Promise.all(cameras.map(worker));
}
async function render() {
  const url = await build();
  const browser = await chromium.launch({
    ...(process.env.TROIKA_CHROME ? {executablePath:process.env.TROIKA_CHROME} : {}),
    headless:true,
    args:["--force-color-profile=srgb","--disable-gpu","--disable-skia-runtime-opts"]
  });
  try {
    const camera = await makeCamera(browser,url);
    await checkTimeline(camera);
    if (master) await record(browser,url,camera);
    else await preview(camera);
  } finally {
    await browser.close();
  }
}
render().catch(error=>{console.error(error);process.exitCode=1;});
