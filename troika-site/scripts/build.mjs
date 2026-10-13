import { readFile, writeFile, mkdir, cp, readdir } from 'node:fs/promises';
import { pages, documentHTML } from '../src/content.mjs';
const output = process.argv.includes('--hosting') ? 'dist' : 'build';

const assets = {};
for (const [slug, page] of Object.entries(pages)) {
  assets[slug === 'home' ? '/' : `/${slug}/`] = {
    type: 'text/html; charset=utf-8', body: documentHTML(slug, page),
  };
}
for (const [name, type] of [['app.js', 'text/javascript'], ['styles.css', 'text/css'], ['favicon.svg', 'image/svg+xml']]) {
  assets[`/assets/${name}`] = { type: `${type}; charset=utf-8`, body: await readFile(`src/${name}`, 'utf8') };
}
for (const name of await readdir('src/brand')) {
  const binary = /\.(ttf|png)$/.test(name);
  const data = await readFile(`src/brand/${name}`);
  assets[`/assets/brand/${name}`] = { type: name.endsWith('.ttf') ? 'font/ttf' : name.endsWith('.png') ? 'image/png' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/plain; charset=utf-8', body: data.toString(binary ? 'base64' : 'utf8'), base64: binary };
}
const origin = 'https://troika-voice-assistant.mihailkamihaa.chatgpt.site';
assets['/robots.txt'] = { type: 'text/plain', body: `User-agent: *\nDisallow: /account/\nDisallow: /api/\nSitemap: ${origin}/sitemap.xml\n` };
assets['/sitemap.xml'] = { type: 'application/xml', body: `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${Object.keys(assets).filter(p => p.endsWith('/') && !['/account/', '/404/'].includes(p)).map(p => `<url><loc>${origin}${p}</loc></url>`).join('')}</urlset>` };
await mkdir(`${output}/server`, { recursive: true });
await mkdir(`${output}/.openai`, { recursive: true });
await writeFile(`${output}/server/index.js`, `const ASSETS = ${JSON.stringify(assets)};\n${await readFile('worker/index.js', 'utf8')}`);
await cp('.openai/hosting.json', `${output}/.openai/hosting.json`);
console.log(`Built ${Object.keys(assets).length} routes and assets.`);
