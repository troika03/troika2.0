import test from 'node:test';
import assert from 'node:assert/strict';
import { pages, documentHTML } from '../src/content.mjs';

test('public Timeweb pages have matching canonical and social preview URLs', () => {
  const origin = 'https://cm444726.tw1.ru';
  const home = documentHTML('home', pages.home, origin);
  assert.ok(home.includes('<link rel="canonical" href="https://cm444726.tw1.ru/">'));
  assert.ok(home.includes('<meta property="og:url" content="https://cm444726.tw1.ru/">'));
  assert.ok(home.includes('<meta property="og:image" content="https://cm444726.tw1.ru/assets/brand/social-1200x630.png">'));
  assert.ok(!home.includes('troika-voice-assistant.mihailkamihaa.chatgpt.site'));
  assert.ok(documentHTML('features', pages.features, origin).includes('<link rel="canonical" href="https://cm444726.tw1.ru/features/">'));
});

test('account and 404 pages stay noindex, original hosting keeps own social URL', () => {
  const account = documentHTML('account', pages.account, 'https://cm444726.tw1.ru');
  assert.ok(account.includes('name="robots" content="noindex,nofollow"'));
  assert.ok(!account.includes('<link rel="canonical"'));
  const missing = documentHTML('404', pages['404'], 'https://cm444726.tw1.ru');
  assert.ok(missing.includes('name="robots" content="noindex,nofollow"'));
  const original = documentHTML('home', pages.home);
  assert.ok(original.includes('<meta property="og:image" content="https://troika-voice-assistant.mihailkamihaa.chatgpt.site/assets/brand/social-1200x630.png">'));
});
