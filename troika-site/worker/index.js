const SESSION_COOKIE = '__Host-troika_session';
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const json = (data, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers } });
const fail = (message, status) => json({ error: message }, status);
const b64 = (bytes) => btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
const unb64 = (text) => Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
async function digest(text) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(text))), v => v.toString(16).padStart(2, '0')).join(''); }
async function cipherKey(env) {
  if (!env.SESSION_SECRET || env.SESSION_SECRET.length < 40) throw new Error('Session configuration unavailable');
  return crypto.subtle.importKey('raw', await crypto.subtle.digest('SHA-256', encoder.encode(env.SESSION_SECRET)), 'AES-GCM', false, ['encrypt', 'decrypt']);
}
async function seal(session, env) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const bytes = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: encoder.encode(SESSION_COOKIE) }, await cipherKey(env), encoder.encode(JSON.stringify(session)));
  return `${b64(iv)}.${b64(new Uint8Array(bytes))}`;
}
async function readSession(request, env) {
  try {
    const value = request.headers.get('Cookie')?.split(';').map(x => x.trim()).find(x => x.startsWith(`${SESSION_COOKIE}=`))?.slice(SESSION_COOKIE.length + 1);
    if (!value || value.length > 3800) return null;
    const [iv, data, extra] = value.split('.');
    if (extra) return null;
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(iv), additionalData: encoder.encode(SESSION_COOKIE) }, await cipherKey(env), unb64(data));
    const s = JSON.parse(decoder.decode(plain));
    return s.refresh_expires_at > Date.now() / 1000 && typeof s.access_token === 'string' && typeof s.home_session_id === 'string' ? s : null;
  } catch { return null; }
}
const clearCookie = () => `${SESSION_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0`;
async function sessionCookie(session, env) {
  const age = Math.max(0, Math.min(30 * 86400, Math.floor(session.refresh_expires_at - Date.now() / 1000)));
  return `${SESSION_COOKIE}=${await seal(session, env)}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${age}`;
}
async function bodyJSON(request, max = 16000) {
  if (!request.headers.get('Content-Type')?.startsWith('application/json')) throw new Error('Ожидается JSON');
  const reader = request.body?.getReader();
  if (!reader) throw new Error('Пустой запрос');
  let length = 0, chunks = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > max) { await reader.cancel(); throw new Error('Слишком большой запрос'); }
    chunks.push(value);
  }
  const joined = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.length; }
  const value = JSON.parse(decoder.decode(joined));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Некорректный запрос');
  return value;
}
async function upstream(env, path, session, method = 'GET', body) {
  const origin = new URL(env.API_ORIGIN || 'https://api.zhulebino-teahouse.ru');
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/') throw new Error('Invalid API origin');
  return fetch(new URL(path, origin), {
    method, redirect: 'manual', signal: AbortSignal.timeout(20000),
    headers: { Accept: 'application/json', ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}
async function upstreamJSON(response) {
  if (response.status >= 300 && response.status < 400) throw new Error('Unexpected API redirect');
  const raw = await response.text();
  if (raw.length > 1024 * 1024) throw new Error('API response too large');
  try { return JSON.parse(raw); } catch { throw new Error('Invalid API response'); }
}
async function limited(request, env, operation, limit = 10) {
  if (!env.DB) return true;
  const now = Math.floor(Date.now() / 1000), bucket = Math.floor(now / 60);
  const key = await digest(`${env.SESSION_SECRET}:${operation}:${request.headers.get('CF-Connecting-IP') || 'local'}`);
  const row = await env.DB.prepare('INSERT INTO site_rate_limits(key,bucket,used) VALUES(?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET used=used+1 RETURNING used').bind(key, bucket).first();
  await env.DB.prepare('DELETE FROM site_rate_limits WHERE bucket < ?').bind(bucket - 60).run();
  return row.used > limit;
}
const isAdmin = (request, env) => Boolean(env.SUPPORT_ADMIN_EMAIL && request.headers.get('oai-authenticated-user-email')?.toLowerCase() === env.SUPPORT_ADMIN_EMAIL.toLowerCase());
async function validSession(request, env) {
  const session = await readSession(request, env);
  if (!session) return null;
  const response = await upstream(env, '/v1/subscription', session);
  if (!response.ok) return null;
  return session;
}
async function api(request, env, url) {
  const path = url.pathname, method = request.method;
  if (!['GET', 'HEAD'].includes(method)) {
    const serviceUpload = path.startsWith('/api/admin/release') && request.headers.get('Authorization') === `Bearer ${env.RELEASE_UPLOAD_KEY}` && env.RELEASE_UPLOAD_KEY;
    if (!serviceUpload && request.headers.get('Origin') !== url.origin) return fail('Источник запроса не разрешён.', 403);
  }
  if (path === '/api/status' && method === 'GET') {
    const started = Date.now(); let available = false;
    try { const response = await upstream(env, '/health'); const data = await upstreamJSON(response); available = response.ok && data.status === 'ok'; } catch { /* Report a failed fresh probe, never cached green status. */ }
    return json({ available, checked_at: new Date().toISOString(), latency_ms: Date.now() - started });
  }
  if (path === '/api/releases' && method === 'GET') {
    const data = {};
    for (const platform of ['android', 'windows']) {
      const object = await env.BUCKET?.get(`releases/${platform}.json`);
      data[platform] = object ? await object.json() : null;
    }
    return json({ releases: data });
  }
  if (path.startsWith('/api/admin/release-parts/')) {
    if (!env.RELEASE_UPLOAD_KEY || request.headers.get('Authorization') !== `Bearer ${env.RELEASE_UPLOAD_KEY}`) return fail('Нет доступа.', 403);
    const match = path.match(/^\/api\/admin\/release-parts\/([a-f0-9-]{36})(?:\/(\d+))?$/);
    if (!match) return fail('Передача не найдена.', 404);
    const recordKey = `releases/pending/${match[1]}.json`;
    const record = await env.BUCKET.get(recordKey);
    if (!record) return fail('Передача не найдена.', 404);
    const pending = await record.json();
    const upload = env.BUCKET.resumeMultipartUpload(pending.key, pending.upload_id);
    if (method === 'DELETE' && !match[2]) { await upload.abort(); await env.BUCKET.delete(recordKey); return json({ aborted: true }); }
    if (method === 'PUT' && match[2]) {
      const number = Number(match[2]), size = Number(request.headers.get('Content-Length'));
      const received = pending.parts.reduce((n,p)=>n+p.size,0);
      if (number !== pending.parts.length + 1 || size < 1 || size > 8 * 1024 * 1024 || received + size > pending.size || (received + size < pending.size && size < 5 * 1024 * 1024)) return fail('Неверная часть файла.', 400);
      const part = await upload.uploadPart(number, request.body);
      pending.parts.push({ ...part, size });
      await env.BUCKET.put(recordKey, JSON.stringify(pending));
      return json({ received: received + size });
    }
    if (method === 'POST' && !match[2]) {
      if (pending.parts.reduce((n,p)=>n+p.size,0) !== pending.size) return fail('Файл получен не полностью.', 400);
      const object = await upload.complete(pending.parts.map(({partNumber,etag})=>({partNumber,etag})));
      if (object.size !== pending.size) return fail('Размер файла не совпал.', 503);
      const entry = { version:pending.version, filename:pending.filename, size:pending.size, sha256:pending.sha256, url:`/downloads/${pending.platform}/${pending.sha256}/${pending.filename}`, published_at:new Date().toISOString() };
      await env.BUCKET.put(`releases/${pending.platform}.json`, JSON.stringify(entry));
      await env.BUCKET.delete(recordKey);
      return json(entry, 201);
    }
    return fail('Метод не поддерживается.', 405);
  }
  if (/^\/api\/admin\/releases\/(android|windows)\/multipart$/.test(path) && method === 'POST') {
    if (!env.RELEASE_UPLOAD_KEY || request.headers.get('Authorization') !== `Bearer ${env.RELEASE_UPLOAD_KEY}`) return fail('Нет доступа.', 403);
    const body = await bodyJSON(request), platform = path.split('/')[4];
    if (!/^[a-f0-9]{64}$/.test(body.sha256 || '') || !Number.isSafeInteger(body.size) || body.size < 1000 || body.size > 160 * 1024 * 1024 || !/^[a-zA-Z0-9.+_-]{1,60}$/.test(body.version || '')) return fail('Неверные параметры файла.', 400);
    const filename = `Troika-${body.version}.${platform === 'android' ? 'apk' : 'zip'}`, key = `releases/${platform}/${body.sha256}/${filename}`;
    const upload = await env.BUCKET.createMultipartUpload(key, { httpMetadata:{contentType:'application/octet-stream'},customMetadata:{sha256:body.sha256} });
    const id = crypto.randomUUID();
    await env.BUCKET.put(`releases/pending/${id}.json`,JSON.stringify({platform,key,filename,version:body.version,size:body.size,sha256:body.sha256,upload_id:upload.uploadId,parts:[]}));
    return json({ id },201);
  }
  if (path.startsWith('/api/admin/releases/') && method === 'PUT') {
    if (!env.RELEASE_UPLOAD_KEY || request.headers.get('Authorization') !== `Bearer ${env.RELEASE_UPLOAD_KEY}`) return fail('Нет доступа.', 403);
    const platform = path.split('/').at(-1);
    if (!['android', 'windows'].includes(platform)) return fail('Неизвестная платформа.', 400);
    const size = Number(request.headers.get('Content-Length'));
    const hash = request.headers.get('X-File-SHA256');
    const version = request.headers.get('X-Release-Version');
    if (!/^[a-f0-9]{64}$/.test(hash || '') || !Number.isSafeInteger(size) || size < 1000 || size > 160 * 1024 * 1024 || !/^[a-zA-Z0-9.+_-]{1,60}$/.test(version || '')) return fail('Неверные параметры файла.', 400);
    const filename = `Troika-${version}.${platform === 'android' ? 'apk' : 'zip'}`;
    const key = `releases/${platform}/${hash}/${filename}`;
    await env.BUCKET.put(key, request.body, { sha256: hash, httpMetadata: { contentType: 'application/octet-stream' }, customMetadata: { sha256: hash } });
    const entry = { version, filename, size, sha256: hash, url: `/downloads/${platform}/${hash}/${filename}`, published_at: new Date().toISOString() };
    await env.BUCKET.put(`releases/${platform}.json`, JSON.stringify(entry));
    return json(entry, 201);
  }
  if (path === '/api/session' && method === 'GET') {
    const session = await readSession(request, env);
    return json({ signed_in: Boolean(session), ...(session ? { email: session.email } : {}), support_admin: isAdmin(request, env) });
  }
  if (['/api/auth/login', '/api/auth/register'].includes(path) && method === 'POST') {
    if (await limited(request, env, 'auth', 8)) return fail('Слишком много попыток. Попробуйте через минуту.', 429);
    const body = await bodyJSON(request);
    const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254 || typeof body.password !== 'string' || body.password.length < 10 || body.password.length > 128) return fail('Проверьте почту и пароль: от 10 до 128 символов.', 400);
    if (path.endsWith('/register') && body.consent !== true) return fail('Подтвердите условия и обработку данных.', 400);
    const response = await upstream(env, path.replace('/api/', '/v1/'), null, 'POST', { email, password: body.password, device_name: 'Сайт Тройки', platform: 'web' });
    const data = await upstreamJSON(response);
    if (!response.ok) return fail(response.status === 409 ? 'Аккаунт с этой почтой уже есть. Войдите.' : response.status === 401 ? 'Неверная почта или пароль.' : 'Вход недоступен. Попробуйте позже.', response.status);
    const session = { access_token: data.access_token || data.token, refresh_token: data.refresh_token, refresh_expires_at: data.refresh_expires_at, home_session_id: data.home_session_id, email };
    if (!session.access_token || !session.refresh_token || !session.home_session_id || !Number.isFinite(session.refresh_expires_at)) return fail('Сервер не поддерживает безопасный веб-вход.', 503);
    return json({ signed_in: true, email }, response.status, { 'Set-Cookie': await sessionCookie(session, env) });
  }
  if (path === '/api/auth/refresh' && method === 'POST') {
    const old = await readSession(request, env);
    if (!old) return fail('Войдите снова.', 401);
    const response = await upstream(env, '/v1/auth/refresh', null, 'POST', { refresh_token: old.refresh_token });
    const data = await upstreamJSON(response);
    if (!response.ok) return json({ error: 'Сеанс завершён. Войдите снова.' }, response.status, response.status === 401 ? { 'Set-Cookie': clearCookie() } : {});
    const session = { ...old, access_token: data.access_token || data.token, refresh_token: data.refresh_token, refresh_expires_at: data.refresh_expires_at };
    return json({ signed_in: true }, 200, { 'Set-Cookie': await sessionCookie(session, env) });
  }
  if (path === '/api/support-admin' && method === 'GET') {
    if (!isAdmin(request, env)) return fail('Нет доступа.', 403);
    const result = await env.DB.prepare('SELECT id,email,category,subject,message,status,created_at FROM support_tickets ORDER BY created_at DESC LIMIT 100').all();
    return json({ tickets: result.results });
  }
  if (/^\/api\/support-admin\/[a-f0-9-]{36}$/.test(path) && method === 'POST') {
    if (!isAdmin(request, env)) return fail('Нет доступа.', 403);
    const body = await bodyJSON(request);
    const message = typeof body.message === 'string' ? body.message.trim() : '';
    if (!message || message.length > 5000 || !['open', 'closed'].includes(body.status)) return fail('Проверьте ответ и статус.', 400);
    const id = path.split('/').at(-1), now = Date.now();
    if (!await env.DB.prepare('SELECT id FROM support_tickets WHERE id=?').bind(id).first()) return fail('Обращение не найдено.', 404);
    await env.DB.batch([
      env.DB.prepare('INSERT INTO support_replies(id,ticket_id,author,message,created_at) VALUES(?,?,?,?,?)').bind(crypto.randomUUID(), id, 'support', message, now),
      env.DB.prepare('UPDATE support_tickets SET status=?,updated_at=? WHERE id=?').bind(body.status, now, id),
    ]);
    return json({ saved: true });
  }
  const session = await readSession(request, env);
  if (!session) return fail('Войдите в аккаунт.', 401);
  if (path === '/api/auth/logout' && method === 'POST') {
    const response = await upstream(env, '/v1/account/devices', session);
    if (response.status !== 401) {
      if (!response.ok) return fail('Не удалось завершить сеанс. Повторите выход.', 503);
      const data = await upstreamJSON(response), current = data.devices?.find(d => d.current && d.status === 'active');
      if (!current) return fail('Не удалось определить текущее устройство.', 503);
      const revoked = await upstream(env, `/v1/account/devices/${encodeURIComponent(current.id)}`, session, 'DELETE');
      if (!revoked.ok) return fail('Не удалось отозвать доступ. Повторите выход.', revoked.status);
    }
    return json({ signed_in: false }, 200, { 'Set-Cookie': clearCookie() });
  }
  if (path.startsWith('/api/support')) {
    if (!await validSession(request, env)) return fail('Войдите снова.', 401);
    const owner = await digest(session.home_session_id);
    if (path === '/api/support' && method === 'GET') {
      const tickets = (await env.DB.prepare('SELECT id,category,subject,message,status,created_at FROM support_tickets WHERE owner_key=? ORDER BY created_at DESC LIMIT 100').bind(owner).all()).results;
      const replies = (await env.DB.prepare('SELECT r.ticket_id,r.author,r.message,r.created_at FROM support_replies r JOIN support_tickets t ON t.id=r.ticket_id WHERE t.owner_key=? ORDER BY r.created_at LIMIT 1000').bind(owner).all()).results;
      return json({ tickets: tickets.map(t => ({ ...t, replies: replies.filter(r => r.ticket_id === t.id) })) });
    }
    if (path === '/api/support' && method === 'POST') {
      if (await limited(request, env, 'support', 3)) return fail('Подождите минуту перед новым обращением.', 429);
      const body = await bodyJSON(request);
      if (!['technical', 'account', 'billing', 'security'].includes(body.category) || typeof body.subject !== 'string' || body.subject.trim().length < 3 || body.subject.length > 150 || typeof body.message !== 'string' || body.message.trim().length < 10 || body.message.length > 5000) return fail('Тема: 3–150 символов. Описание: 10–5000 символов.', 400);
      const id = crypto.randomUUID(), now = Date.now();
      await env.DB.prepare('INSERT INTO support_tickets(id,owner_key,email,category,subject,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)').bind(id, owner, session.email, body.category, body.subject.trim(), body.message.trim(), now, now).run();
      return json({ id, saved: true }, 201);
    }
    if (/^\/api\/support\/[a-f0-9-]{36}$/.test(path) && method === 'DELETE') {
      const id = path.split('/').at(-1);
      const row = await env.DB.prepare('SELECT id FROM support_tickets WHERE id=? AND owner_key=?').bind(id, owner).first();
      if (!row) return fail('Обращение не найдено.', 404);
      await env.DB.batch([env.DB.prepare('DELETE FROM support_replies WHERE ticket_id=?').bind(id), env.DB.prepare('DELETE FROM support_tickets WHERE id=? AND owner_key=?').bind(id, owner)]);
      return json({ deleted: true });
    }
    return fail('Такого действия нет.', 404);
  }
  const routes = [
    ['/api/subscription', '/v1/subscription', ['GET']],
    ['/api/devices', '/v1/account/devices', ['GET']],
    ['/api/export', '/v1/account/export', ['GET']],
    ['/api/account', '/v1/account', ['DELETE']],
    ['/api/logout-all', '/v1/auth/logout-all', ['POST']],
    ['/api/memories', '/v1/memories', ['GET', 'POST']],
    ['/api/memory-preferences', '/v1/memory-preferences', ['GET', 'PUT']],
    ['/api/billing', '/v1/billing', ['GET']],
    ['/api/billing/checkout', '/v1/billing/checkout', ['POST']],
  ];
  let target = routes.find(([p,,methods]) => p === path && methods.includes(method))?.[1];
  if (/^\/api\/devices\/[A-Za-z0-9_-]{1,100}$/.test(path) && method === 'DELETE') target = path.replace('/api/devices/', '/v1/account/devices/');
  if (/^\/api\/memories\/[A-Za-z0-9_-]{1,100}$/.test(path) && ['PATCH', 'DELETE'].includes(method)) target = path.replace('/api/', '/v1/');
  if (/^\/api\/billing\/[A-Za-z0-9_-]{1,100}$/.test(path) && method === 'GET') target = path.replace('/api/', '/v1/');
  if (!target) return fail('Такого действия нет.', 404);
  if (path === '/api/billing/checkout' && env.PAYMENTS_ENABLED !== 'true') return fail('Оплата ещё не подключена.', 503);
  const body = ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method) && request.body ? await bodyJSON(request) : undefined;
  if (path === '/api/account' && body?.confirmation !== 'DELETE_MY_ACCOUNT') return fail('Нужно явное подтверждение удаления.', 400);
  const response = await upstream(env, target, session, method, body);
  if (response.status >= 300 && response.status < 400) return fail('Сервер вернул неверный ответ.', 502);
  if (path === '/api/export' && response.ok) return new Response(response.body, { status: 200, headers: { 'Content-Type': response.headers.get('Content-Type') || 'application/zip', 'Content-Disposition': 'attachment; filename="Troika-account-export.zip"', 'Cache-Control': 'no-store' } });
  const data = await upstreamJSON(response);
  if (path === '/api/billing' && response.ok) data.enabled = data.enabled === true && env.PAYMENTS_ENABLED === 'true';
  const headers = {};
  if (response.ok && (path === '/api/account' || path === '/api/logout-all')) {
    if (path === '/api/account' && env.DB) {
      const owner = await digest(session.home_session_id);
      await env.DB.batch([
        env.DB.prepare('DELETE FROM support_replies WHERE ticket_id IN (SELECT id FROM support_tickets WHERE owner_key=?)').bind(owner),
        env.DB.prepare('DELETE FROM support_tickets WHERE owner_key=?').bind(owner),
      ]);
    }
    headers['Set-Cookie'] = clearCookie();
  }
  return json(data, response.status, headers);
}
function secure(response) {
  const headers = new Headers(response.headers);
  headers.set('X-Content-Type-Options', 'nosniff');
  headers.set('Referrer-Policy', 'same-origin');
  headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  headers.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; object-src 'none'");
  return new Response(response.body, { status: response.status, headers });
}
export default {
  async fetch(request, env) {
    let response;
    try {
      const url = new URL(request.url);
      if (url.pathname.startsWith('/api/')) response = await api(request, env, url);
      else if (url.pathname.startsWith('/downloads/')) {
        if (!['GET', 'HEAD'].includes(request.method)) response = fail('Метод не поддерживается.', 405);
        else {
          const match = url.pathname.match(/^\/downloads\/(android|windows)\/([a-f0-9]{64})\/(Troika-[A-Za-z0-9.+_-]+\.(apk|zip))$/);
          const object = match && await env.BUCKET?.get(`releases/${match[1]}/${match[2]}/${match[3]}`);
          response = object ? new Response(request.method === 'HEAD' ? null : object.body, { headers: { 'Content-Type': 'application/octet-stream', 'Content-Length': String(object.size), 'Content-Disposition': `attachment; filename="${match[3]}"`, ETag: object.httpEtag, 'Cache-Control': 'public, max-age=31536000, immutable' } }) : fail('Файл не найден.', 404);
        }
      } else {
        const path = url.pathname;
        if (!['GET', 'HEAD'].includes(request.method)) response = fail('Метод не поддерживается.', 405);
        else if (ASSETS[`${path}/`]) response = new Response(null, { status: 308, headers: { Location: `${path}/${url.search}` } });
        else {
          const asset = ASSETS[path] || ASSETS['/404/'];
          const cache = path.startsWith('/assets/') ? 'public, max-age=300' : 'no-cache';
          response = new Response(request.method === 'HEAD' ? null : asset.base64 ? unb64(asset.body) : asset.body, { status: ASSETS[path] ? 200 : 404, headers: { 'Content-Type': asset.type, 'Cache-Control': cache } });
        }
      }
    } catch (error) {
      const clientError = error instanceof SyntaxError || ['Ожидается JSON', 'Пустой запрос', 'Слишком большой запрос', 'Некорректный запрос'].includes(error.message);
      response = fail(clientError ? 'Проверьте данные запроса.' : 'Сервис временно недоступен. Повторите позже.', clientError ? 400 : 503);
    }
    return secure(response);
  },
};
