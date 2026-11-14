/* Prepare Telegram uploads from the approved generated banners and vector brand. */
const fs = require('node:fs');
const path = require('node:path');
const sharp = require(require.resolve('sharp', {
  paths: [process.env.TROIKA_NODE_MODULES || 'C:/Users/kiqu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'],
}));

async function main() {
  const [welcome, support] = process.argv.slice(2);
  if (!welcome || !support) throw new Error('Pass the two approved banner image paths');
  const root = path.resolve(__dirname, '..');
  const destination = path.join(root, 'troika_product/telegram_commerce/assets');
  fs.mkdirSync(destination, { recursive: true });
  for (const [name, input] of [['welcome', welcome], ['support', support]]) {
    await sharp(input).resize({ width: 1600, withoutEnlargement: true }).jpeg({ quality: 88, mozjpeg: true }).toFile(path.join(destination, name + '.jpg'));
  }
  fs.copyFileSync(path.join(destination, 'welcome.jpg'), path.join(destination, 'plans.jpg'));
  for (const [name, color] of [['shop', 'amber'], ['support', 'dark']]) {
    await sharp(path.join(root, 'brand/troika/app/app-icon-' + color + '.svg')).resize(640, 640).jpeg({ quality: 94 }).toFile(path.join(destination, name + '-avatar.jpg'));
  }
  console.log('Prepared two banners, a tariff banner, and two brand avatars');
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
