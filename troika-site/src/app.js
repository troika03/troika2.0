(() => {
  'use strict';
  const page = document.body.dataset.page;
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const date = value => { const d = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value); return Number.isNaN(d.getTime()) ? 'Не указано' : d.toLocaleString('ru-RU'); };
  const number = value => Number(value || 0).toLocaleString('ru-RU');
  let refreshing;
  async function request(path, options = {}, retry = true) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
    if (response.status === 401 && retry && !path.startsWith('/api/auth/')) {
      if (!refreshing) {
        const rotate = async () => {
          // Another tab may already have rotated the shared cookie.
          const check = await fetch('/api/subscription', { credentials: 'same-origin', cache: 'no-store' });
          if (check.ok) return;
          if (check.status !== 401) throw new Error('Не удалось проверить сеанс. Повторите позже.');
          const result = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' });
          if (!result.ok) throw new Error('Сеанс завершён. Войдите снова.');
        };
        refreshing = (navigator.locks ? navigator.locks.request('troika-session-refresh', rotate) : rotate()).finally(() => { refreshing = null; });
      }
      await refreshing;
      return request(path, options, false);
    }
    if (options.binary && response.ok) return response.blob();
    let data;
    try { data = await response.json(); } catch { throw new Error('Сервер не ответил. Проверьте соединение и повторите.'); }
    if (!response.ok) {
      const error = typeof data.error === 'string' ? data.error : data.error?.message;
      throw new Error(response.status === 401 ? 'Войдите в аккаунт.' : response.status === 404 ? 'Действие пока недоступно на сервере.' : error || 'Не удалось выполнить действие. Повторите позже.');
    }
    return data;
  }
  const mutate = (path, method, data) => request(path, { method, ...(data ? { body: JSON.stringify(data) } : {}) });
  function message(element, text, error = false) { element.textContent = text; element.className = `form-message ${error ? 'error' : 'success'}`; }
  async function busy(button, action, output) {
    button.disabled = true;
    try { await action(); } catch (error) { if (output) message(output, error.message, true); else showError(error.message); }
    finally { if (button.isConnected) button.disabled = false; }
  }
  function showError(text) { const output = document.querySelector('#account-message'); if (output) message(output, text, true); }
  const toggle = document.querySelector('.nav-toggle');
  toggle?.addEventListener('click', () => { const open = document.querySelector('.nav-links').classList.toggle('open'); toggle.setAttribute('aria-expanded', String(open)); toggle.textContent = open ? 'Закрыть' : 'Меню'; });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && toggle?.getAttribute('aria-expanded') === 'true') toggle.click(); });
  try { if (!localStorage.getItem('troika_notice_v2')) document.querySelector('[data-notice]').hidden = false; } catch { /* Browsing remains available with storage disabled. */ }
  document.querySelector('[data-notice-close]')?.addEventListener('click', () => { document.querySelector('[data-notice]').hidden = true; try { localStorage.setItem('troika_notice_v2', 'seen'); } catch {} });
  let demoTimer;
  document.querySelector('[data-demo]')?.addEventListener('click', ev => {
    const button = ev.currentTarget, active = button.getAttribute('aria-pressed') !== 'true';
    clearTimeout(demoTimer); button.setAttribute('aria-pressed', String(active)); button.classList.toggle('is-active', active);
    document.querySelector('[data-demo-title]').textContent = active ? 'Создаёт…' : 'Презентация готова';
    document.querySelector('[data-demo-text]').textContent = active ? 'Собирает слайды.' : 'Сохрани и открой на своём устройстве.';
    if (active) demoTimer = setTimeout(() => button.click(), 2600);
  });
  async function releases() {
    try {
      const { releases } = await request('/api/releases');
      for (const platform of ['android', 'windows']) {
        const box = document.querySelector(`[data-release="${platform}"]`), release = releases[platform];
        if (!release) { box.innerHTML = '<p class="notice">Файл ещё не опубликован. Попробуйте позже.</p>'; continue; }
        const link = /^\/downloads\/(android|windows)\/[a-f0-9]{64}\/Troika-[A-Za-z0-9.+_-]+\.(apk|zip)$/.exec(release.url);
        if (!link || link[1] !== platform || link[2] !== (platform === 'android' ? 'apk' : 'zip')) {
          box.textContent = 'Не удалось проверить ссылку на файл.';
          continue;
        }
        box.innerHTML = `<p>Версия ${e(release.version)}. ${number((release.size / 1024 / 1024).toFixed(1))} МБ.</p><a class="button" href="${e(release.url)}" download>Скачать ${platform === 'android' ? 'APK' : 'для Windows'}</a><code class="checksum">SHA-256: ${e(release.sha256)}</code><button class="button secondary small" type="button" data-copy-hash>Скопировать SHA-256</button><p class="fine-print">Опубликовано: ${e(date(release.published_at))}</p>`;
        const copyButton = box.querySelector('[data-copy-hash]');
        copyButton.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(release.sha256);
            copyButton.textContent = 'Скопировано';
          } catch {
            copyButton.textContent = 'Выделите SHA-256 выше';
          }
        });
      }
    } catch (error) { document.querySelectorAll('[data-release]').forEach(box => { box.textContent = error.message; }); }
  }
  async function status() {
    const view = document.querySelector('#status-view'), button = document.querySelector('[data-refresh-status]');
    view.textContent = 'Проверяем соединение…'; button.disabled = true;
    try { const data = await request('/api/status'); view.innerHTML = `<div class="status-line ${data.available ? 'ok' : 'error'}"><strong>${data.available ? 'API отвечает' : 'API сейчас недоступен'}</strong><p>Проверено: ${e(date(data.checked_at))}</p><p>Время ответа: ${number(data.latency_ms)} мс.</p></div>`; }
    catch (error) { view.textContent = error.message; }
    finally { button.disabled = false; }
  }
  const view = document.querySelector('#account-view');
  function auth(mode = 'login', notice = '') {
    const register = mode === 'register';
    view.innerHTML = `<div class="auth-card"><div class="tabs" role="tablist" aria-label="Вход или регистрация"><button type="button" role="tab" aria-selected="${!register}" data-auth="login">Вход</button><button type="button" role="tab" aria-selected="${register}" data-auth="register">Регистрация</button></div><h2>${register ? 'Начать с Free' : 'Войти в Тройку'}</h2><form id="auth-form"><label class="field"><span>Почта</span><input name="email" type="email" maxlength="254" autocomplete="email" required></label><label class="field"><span>Пароль</span><input name="password" type="password" minlength="10" maxlength="128" autocomplete="${register ? 'new-password' : 'current-password'}" required></label><p class="fine-print">От 10 до 128 символов.</p>${register ? '<label class="check"><input name="consent" type="checkbox" required><span>Согласен с <a href="/terms/" target="_blank" rel="noopener">условиями</a> и <a href="/privacy/" target="_blank" rel="noopener">политикой конфиденциальности</a>.</span></label>' : ''}<button class="button" type="submit">${register ? 'Создать аккаунт' : 'Войти'}</button><p id="auth-message" class="form-message" role="status">${e(notice)}</p></form>${!register ? '<details><summary>Не помню пароль</summary><p>Автоматическое восстановление по почте ещё не подключено. Используйте действующий вход в приложении. Не отправляйте пароль в поддержку.</p></details>' : '<p class="fine-print">Бесплатно. Почта и пароль подойдут для приложения.</p>'}</div>`;
    view.querySelectorAll('[data-auth]').forEach(button => button.addEventListener('click', () => auth(button.dataset.auth)));
    view.querySelector('#auth-form').addEventListener('submit', ev => {
      ev.preventDefault(); const form = ev.currentTarget, button = form.querySelector('button[type=submit]'), output = form.querySelector('#auth-message');
      busy(button, async () => { const data = Object.fromEntries(new FormData(form)); data.consent = data.consent === 'on'; message(output, 'Подключаем аккаунт…'); await mutate(`/api/auth/${mode}`, 'POST', data); form.reset(); await account(); }, output);
    });
  }
  async function section(path, target, renderer) {
    try { const data = await request(path); target.innerHTML = renderer(data); return data; }
    catch (error) { target.innerHTML = `<p class="error">${e(error.message)}</p>`; return null; }
  }
  async function account() {
    let session;
    try { session = await request('/api/session'); } catch (error) { auth('login', error.message); return; }
    if (!session.signed_in) { auth(new URLSearchParams(location.search).get('mode') === 'register' ? 'register' : 'login'); return; }
    view.innerHTML = `<div class="account-heading"><div><h2>${e(session.email)}</h2><a href="/download/">Скачать приложение</a></div><button class="button secondary" type="button" data-logout>Выйти</button></div><p id="account-message" class="form-message" role="status"></p><div class="account-grid"><section class="panel"><h2>Тариф и ресурс</h2><div id="subscription-view">Загружаем…</div><div id="billing-view"></div></section><section class="panel"><h2>Устройства</h2><div id="devices-view">Загружаем…</div><button class="button secondary small" type="button" data-logout-all>Завершить все сеансы</button></section><section class="panel wide"><h2>Память</h2><div id="memory-preferences"></div><div id="memories-view">Загружаем…</div><button class="button secondary" type="button" data-add-memory>Добавить запись</button></section><section class="panel wide" id="support"><h2>Поддержка</h2><p class="fine-print">Опишите проблему. Пароли и ключи не отправляйте.</p><form id="support-form"><div class="account-grid"><label class="field"><span>Категория</span><select name="category"><option value="technical">Приложение и сайт</option><option value="account">Аккаунт</option><option value="billing">Оплата и доступ</option><option value="security">Безопасность</option></select></label><label class="field"><span>Тема</span><input name="subject" minlength="3" maxlength="150" required></label></div><label class="field"><span>Что произошло?</span><textarea name="message" minlength="10" maxlength="5000" required></textarea></label><button class="button" type="submit">Создать обращение</button><p class="form-message" role="status" id="support-message"></p></form><div id="support-view">Загружаем обращения…</div><button class="button secondary small support-export" type="button" data-support-export>Скачать мои обращения</button></section>${session.support_admin ? '<section class="panel wide"><h2>Рабочая очередь поддержки</h2><div id="support-admin-view">Загружаем…</div></section>' : ''}<section class="panel wide"><h2>Данные аккаунта</h2><p>Экспорт включает серверные данные Тройки. Готовые локальные файлы копируются отдельно на устройстве.</p><button class="button secondary" type="button" data-export>Скачать данные Тройки</button><details class="danger-zone"><summary>Удалить аккаунт</summary><p>Будут удалены аккаунт, серверные данные Тройки и обращения сайта. Устройства потеряют доступ. Локальные файлы останутся на устройствах.</p><form id="delete-form"><label class="field"><span>Введите УДАЛИТЬ для подтверждения</span><input name="confirmation" required autocomplete="off"></label><button class="button danger" type="submit">Удалить аккаунт и данные</button></form></details></section></div>`;
    view.querySelector('[data-logout]').addEventListener('click', ev => busy(ev.currentTarget, async () => { await mutate('/api/auth/logout', 'POST'); auth('login','Вы вышли. Доступ этого веб-устройства отключён.'); }));
    view.querySelector('[data-logout-all]').addEventListener('click', ev => { if (confirm('Завершить все сеансы Тройки на всех устройствах? Потребуется повторный вход.')) busy(ev.currentTarget, async () => { await mutate('/api/logout-all', 'POST'); auth('login','Все сеансы завершены.'); }); });
    view.querySelector('[data-export]').addEventListener('click', ev => busy(ev.currentTarget, async () => { downloadBlob(await request('/api/export', { binary: true }), 'Troika-account-export.zip'); message(document.querySelector('#account-message'),'Экспорт подготовлен. Сохраните файл.'); }));
    view.querySelector('[data-support-export]').addEventListener('click', ev => busy(ev.currentTarget, async () => { downloadBlob(new Blob([JSON.stringify(await request('/api/support'),null,2)], {type:'application/json'}), 'Troika-support.json'); }));
    view.querySelector('#delete-form').addEventListener('submit', ev => { ev.preventDefault(); const form = ev.currentTarget; if (form.elements.confirmation.value.trim() !== 'УДАЛИТЬ') { showError('Введите УДАЛИТЬ полностью.'); return; } busy(form.querySelector('button'), async () => { const result = await mutate('/api/account','DELETE',{confirmation:'DELETE_MY_ACCOUNT'}); auth('login', result.status === 'deletion_pending' ? 'Доступ закрыт. Сервер завершает удаление данных.' : 'Аккаунт и данные удалены.'); }); });
    view.querySelector('[data-add-memory]').addEventListener('click', () => editMemory());
    view.querySelector('#support-form').addEventListener('submit', ev => { ev.preventDefault(); const form = ev.currentTarget, output = view.querySelector('#support-message'); busy(form.querySelector('button'), async () => { await mutate('/api/support','POST',Object.fromEntries(new FormData(form))); form.reset(); message(output,'Обращение сохранено. Ответ появится здесь.'); await support(); }, output); });
    await subscription(); await devices(); await memories(); await support();
    if (session.support_admin) await adminSupport();
    if (location.hash === '#support') document.querySelector('#support')?.scrollIntoView();
  }
  async function subscription() {
    await section('/api/subscription',view.querySelector('#subscription-view'),({subscription:s})=>{
      const monthly = s.resource_enforced === true && s.unit === 'calculated_ai_tokens', max = monthly ? s.monthly_limit : s.daily_limit, used = monthly ? s.spent : s.used;
      return `<p class="metric">${e(String(s.plan || 'Free').replace(/^./,c=>c.toUpperCase()))}</p><p>Осталось <strong>${number(s.remaining)}</strong> ${monthly ? 'расчётных AI-токенов' : 'AI-запросов сегодня'}.</p><meter min="0" max="${e(Math.max(1,max||1))}" value="${e(Math.max(0,Math.min(max||0,used||0)))}" aria-label="Использованный ресурс"></meter><p class="fine-print">Использовано ${number(used)} из ${number(max)}. ${monthly ? `В обработке: ${number(s.reserved)}.` : 'Сейчас действует дневной лимит сервера.'}</p><p class="fine-print">Обновление: ${e(date(s.resets_at))}</p>`;
    });
    const box = view.querySelector('#billing-view');
    try { const data = await request('/api/billing'); if (!data.enabled || data.test) { box.innerHTML = '<p class="notice">Оплата ещё не подключена. Здесь не будет списаний.</p>'; return; } box.innerHTML = '<div class="actions"><button class="button small" data-buy="plus">Plus — 790 ₽</button><button class="button small" data-buy="pro">Pro — 1 490 ₽</button><button class="button secondary small" data-buy="top_up">+1 млн — 99 ₽</button></div>'; box.querySelectorAll('[data-buy]').forEach(button=>button.addEventListener('click',()=>busy(button,async()=>{ if (!confirm('Перейти к оплате выбранного тарифа? Стоимость и условия будут показаны платёжной системой.')) return; const key = crypto.randomUUID(); const result = await mutate('/api/billing/checkout','POST',{sku:button.dataset.buy,idempotency_key:key}); const url = new URL(result.confirmation_url); if(url.protocol !== 'https:' || !['yookassa.ru','yoomoney.ru'].some(d=>url.hostname===d||url.hostname.endsWith(`.${d}`))) throw new Error('Не удалось проверить платёжную ссылку.'); location.assign(url.href); }))); }
    catch { box.innerHTML='<p class="fine-print">Оплата ещё не подключена.</p>'; }
  }
  async function devices() {
    const box = view.querySelector('#devices-view');
    const data = await section('/api/devices',box,({devices})=> devices.filter(d=>d.status==='active').map(d=>`<div class="row"><div><strong>${e(d.name)}</strong><p>${e(d.platform)}${d.current?' — этот браузер':''}</p><p>Добавлено: ${e(date(d.created_at))}</p></div><button class="button secondary small" type="button" data-device="${e(d.id)}">Отключить</button></div>`).join('')||'<p>Активных устройств нет.</p>');
    box.querySelectorAll('[data-device]').forEach(button=>button.addEventListener('click',()=>{ const device=data.devices.find(d=>d.id===button.dataset.device); if(confirm(`Отключить «${device.name}»? Устройство потеряет доступ.`)) busy(button,async()=>{ await mutate(`/api/devices/${encodeURIComponent(device.id)}`,'DELETE'); if(device.current) { auth('login','Доступ этого браузера отключён.'); } else await devices(); }); }));
  }
  async function memories() {
    const box = view.querySelector('#memories-view');
    const data = await section('/api/memories',box,({memories})=>memories.length?memories.map(m=>`<article class="row memory-row"><h3>${e(m.title)}</h3><p>${e(m.content)}</p><div class="actions"><button class="button secondary small" data-edit-memory="${e(m.id)}">Изменить</button><button class="button secondary small" data-delete-memory="${e(m.id)}">Удалить</button></div></article>`).join(''):'<p class="muted">Пока нет записей. Скажите Тройке, что нужно запомнить, или добавьте запись здесь.</p>');
    if (!data) return;
    const preferences = view.querySelector('#memory-preferences');
    preferences.innerHTML=`<label class="check"><input type="checkbox" data-auto-memory ${data.preferences?.automatic_enabled?'checked':''}><span>Автоматически запоминать прямо сказанные важные сведения</span></label>`;
    preferences.querySelector('input').addEventListener('change', ev => { const input=ev.currentTarget, next=input.checked; busy(input, async()=>{ try{await mutate('/api/memory-preferences','PUT',{automatic_enabled:next});}catch(error){input.checked=!next;throw error;} }); });
    box.querySelectorAll('[data-edit-memory]').forEach(button=>button.addEventListener('click',()=>editMemory(data.memories.find(m=>m.id===button.dataset.editMemory))));
    box.querySelectorAll('[data-delete-memory]').forEach(button=>button.addEventListener('click',()=>{if(confirm('Удалить эту запись из памяти Тройки?')) busy(button,async()=>{await mutate(`/api/memories/${encodeURIComponent(button.dataset.deleteMemory)}`,'DELETE');await memories();});}));
  }
  function editMemory(item) {
    const dialog=document.createElement('dialog');
    dialog.innerHTML=`<h2>${item?'Изменить запись':'Новая запись памяти'}</h2><form><label class="field"><span>Название</span><input name="title" maxlength="120" required value="${e(item?.title)}"></label><label class="field"><span>Что запомнить</span><textarea name="content" maxlength="4000" required>${e(item?.content)}</textarea></label><div class="actions"><button class="button" type="submit">Сохранить</button><button class="button secondary" type="button" data-close>Отмена</button></div><p class="form-message" role="status"></p></form>`;
    document.body.append(dialog);dialog.showModal();dialog.addEventListener('close',()=>dialog.remove());dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    dialog.querySelector('form').addEventListener('submit',ev=>{ev.preventDefault();const form=ev.currentTarget;busy(form.querySelector('button'),async()=>{const data=Object.fromEntries(new FormData(form)); if(!item)data.kind='fact';await mutate(item?`/api/memories/${encodeURIComponent(item.id)}`:'/api/memories',item?'PATCH':'POST',data);dialog.close();await memories();},form.querySelector('.form-message'));});
  }
  async function support() {
    const box=view.querySelector('#support-view');
    await section('/api/support',box,({tickets})=>tickets.length?tickets.map(t=>`<article class="ticket"><h3>${e(t.subject)}</h3><p class="fine-print">${t.status==='closed'?'Закрыто':'Ожидает ответа'} · ${e(date(t.created_at))}</p><p>${e(t.message)}</p>${t.replies.map(r=>`<div class="reply"><strong>Поддержка</strong><p>${e(r.message)}</p><span class="fine-print">${e(date(r.created_at))}</span></div>`).join('')}<button class="button secondary small" data-delete-ticket="${e(t.id)}">Удалить обращение</button></article>`).join(''):'<p class="muted">Обращений пока нет.</p>');
    box.querySelectorAll('[data-delete-ticket]').forEach(button=>button.addEventListener('click',()=>{if(confirm('Удалить обращение и все ответы?'))busy(button,async()=>{await mutate(`/api/support/${button.dataset.deleteTicket}`,'DELETE');await support();});}));
  }
  async function adminSupport() {
    const box=view.querySelector('#support-admin-view');
    await section('/api/support-admin',box,({tickets})=>tickets.length?tickets.map(t=>`<article class="ticket"><h3>${e(t.subject)}</h3><p class="fine-print">${e(t.email)} · ${e(t.category)} · ${e(t.status)}</p><p>${e(t.message)}</p><form data-answer="${e(t.id)}"><label class="field"><span>Ответ</span><textarea name="message" maxlength="5000" required></textarea></label><label class="field"><span>Статус</span><select name="status"><option value="open">Открыто</option><option value="closed">Закрыто</option></select></label><button class="button small" type="submit">Сохранить ответ</button><p class="form-message" role="status"></p></form></article>`).join(''):'<p>Новых обращений нет.</p>');
    box.querySelectorAll('form').forEach(form=>form.addEventListener('submit',ev=>{ev.preventDefault();busy(form.querySelector('button'),async()=>{await mutate(`/api/support-admin/${form.dataset.answer}`,'POST',Object.fromEntries(new FormData(form)));await adminSupport();await support();},form.querySelector('.form-message'));}));
  }
  function downloadBlob(blob, filename) { const url=URL.createObjectURL(blob), link=document.createElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000); }
  if(page==='download') releases();
  if(page==='status'){status();document.querySelector('[data-refresh-status]').addEventListener('click',status);}
  if(page==='account')account();
})();
