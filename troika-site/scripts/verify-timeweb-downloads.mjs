import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const origin = 'https://cm444726.tw1.ru';
async function get(path, options = {}) {
  for (let attempt = 0; ; attempt++) {
    try { return await fetch(origin + path, { redirect: 'error', signal: AbortSignal.timeout(180000), ...options }); }
    catch (error) { if (attempt >= 2) throw error; }
  }
}
const response = await get('/api/releases');
assert.equal(response.status, 200);
const { releases } = await response.json();
const platforms = process.argv.slice(2);
assert.ok(platforms.every(platform => ['android', 'windows'].includes(platform)));
for (const platform of platforms.length ? platforms : ['android', 'windows']) {
  const release = releases[platform];
  const path = '/transfer.php?download=' + encodeURIComponent(release.url);
  const head = await get(path, { method: 'HEAD' });
  assert.equal(head.status, 200);
  assert.equal(Number(head.headers.get('Content-Length')), release.size);
  const range = await get(path, { headers: { Range: 'bytes=0-1023' } });
  assert.equal(range.status, 206);
  assert.equal(range.headers.get('Content-Range'), `bytes 0-1023/${release.size}`);
  assert.equal((await range.arrayBuffer()).byteLength, 1024);
  const invalid = await get(path, { headers: { Range: `bytes=${release.size}-` } });
  assert.equal(invalid.status, 416);
  await invalid.arrayBuffer();
  const full = await get(path);
  assert.equal(full.status, 200);
  let size = 0;
  const hash = createHash('sha256');
  for await (const chunk of full.body) { size += chunk.length; hash.update(chunk); }
  const sha256 = hash.digest('hex');
  assert.equal(size, release.size);
  assert.equal(sha256, release.sha256);
  console.log(`${platform}: ${size} bytes; SHA-256 ${sha256}; HEAD, range and invalid range passed.`);
}
const traversal = await get('/transfer.php?download=' + encodeURIComponent('/downloads/android/../backend.json'));
assert.equal(traversal.status, 404);
console.log('Download traversal rejected.');
