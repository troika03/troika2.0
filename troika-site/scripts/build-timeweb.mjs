import { readFile,writeFile,mkdir,cp } from 'node:fs/promises';
import { pages,documentHTML } from '../src/content.mjs';
const root='build-timeweb/public_html';
const origin='https://cm444726.tw1.ru';
await mkdir(`${root}/assets`,{recursive:true});
for(const[slug,page]of Object.entries(pages)){
  const file=slug==='home'?'index.html':slug==='404'?'404.html':`${slug}/index.html`;
  await mkdir(`${root}/${slug==='home'||slug==='404'?'':slug}`,{recursive:true});
  await writeFile(`${root}/${file}`,documentHTML(slug,page,origin));
}
await cp('src/brand',`${root}/assets/brand`,{recursive:true});
await cp('src/styles.css',`${root}/assets/styles.css`);
let app=await readFile('src/app.js','utf8');
app=app.replace('href="${e(release.url)}"','href="/transfer.php?download=${encodeURIComponent(release.url)}"');
await writeFile(`${root}/assets/app.js`,app);
await cp('timeweb/transfer.php',`${root}/transfer.php`);
await cp('timeweb/application.php',`${root}/application.php`);
for(const file of ['setup.php','support-schema.sql','support-operator.php'])await cp(`timeweb/${file}`,`build-timeweb/${file}`);
await cp('timeweb/.htaccess',`${root}/.htaccess`);
await writeFile(`${root}/robots.txt`,`User-agent: *\nDisallow: /account/\nDisallow: /api/\nDisallow: /transfer.php\nSitemap: ${origin}/sitemap.xml\n`);
await writeFile(`${root}/sitemap.xml`,`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${Object.keys(pages).filter(p=>!['account','404'].includes(p)).map(p=>`<url><loc>${origin}/${p==='home'?'':p+'/'}</loc></url>`).join('')}</urlset>`);
console.log('Built Timeweb website without runtime secrets.');
