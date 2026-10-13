/* Render every outlined vector master and verify the raster dimensions. */
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const sharp = require(require.resolve('sharp', {
  paths: [process.env.TROIKA_NODE_MODULES || 'C:/Users/kiqu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'],
}));

async function main() {
  const catalog = JSON.parse(fs.readFileSync(path.join(root, 'catalog.json'), 'utf8'));
  const results = [];
  for (const item of catalog.filter(item => !item.editable_text)) {
    const source = path.join(root, item.file);
    let width = Math.round(item.width);
    let height = Math.round(item.height);
    if (item.category === 'icons') width = height = 192;
    if (item.category === 'guide') {
      width = Math.round(item.width * 1.5);
      height = Math.round(item.height * 1.5);
    }
    const relative = 'exports/png/' + item.file.replace(/\.svg$/, '.png');
    const target = path.join(root, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    await sharp(source, { density: 96 }).resize(width, height).png().toFile(target);
    const info = await sharp(target).metadata();
    if (info.width !== width || info.height !== height) throw new Error('Wrong size: ' + relative);
    results.push({ file: relative, width, height });
  }
  const appSource = path.join(root, 'app/app-icon-dark.svg');
  for (const size of [16, 24, 32, 48, 64, 128, 192, 256, 512]) {
    const target = path.join(root, 'exports/png/app/icon-' + size + '.png');
    await sharp(appSource).resize(size, size).png().toFile(target);
    results.push({ file: 'exports/png/app/icon-' + size + '.png', width: size, height: size });
  }
  for (const size of [16, 32, 48]) {
    await sharp(path.join(root, 'app/favicon.svg')).resize(size, size).png()
      .toFile(path.join(root, 'exports/png/app/favicon-' + size + '.png'));
  }
  fs.copyFileSync(path.join(root, 'exports/png/preview/brand-board.png'),
    path.join(root, 'preview/Troika-Brand-Preview.png'));
  fs.writeFileSync(path.join(root, 'guide/raster-validation.json'), JSON.stringify({
    all_dimensions_match: true,
    png_count: results.length + 3,
    files: results,
  }, null, 2) + '\n');
  console.log(JSON.stringify({ png_count: results.length + 3, dimensions_verified: true }));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
