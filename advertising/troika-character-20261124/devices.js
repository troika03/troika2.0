const deviceMarkup = `
  <div id="desktop" aria-hidden="true">
    <div class="desk-stand"></div>
    <div class="desk-base"></div>
    <div class="desk-case"></div>
    <div class="desk-screen">
      <div id="desktop-idle">
        <div class="desk-idle-light"></div>
        <div class="desk-window">
          <div class="desk-window-bar">
            <img src="../../brand/troika/logos/mark-amber.svg" alt="">
            <span>Тройка</span>
            <small>— &nbsp; □ &nbsp; ×</small>
          </div>
          <div class="desk-window-body">
            <div class="desk-nav-list"><b>Главная</b><span>Разговоры</span><span>Дела</span></div>
            <div class="desk-companion">
              <img src="../../brand/troika/logos/mark-amber.svg" alt="">
              <strong>Чем помочь?</strong>
              <span>Нажмите и говорите</span>
            </div>
          </div>
        </div>
        <div class="desk-taskbar">
          <span class="desk-os"><i></i><i></i><i></i><i></i></span>
          <span class="desk-browser-icon"></span>
          <img src="../../brand/troika/logos/mark-amber.svg" alt="">
          <span class="desk-time">21:54</span>
        </div>
      </div>
      <div id="desktop-browser">
        <div class="browser-tabs">
          <span><i></i>Поиск</span><small>+</small>
          <strong>— &nbsp; □ &nbsp; ×</strong>
        </div>
        <div class="browser-tools">
          <span>‹ &nbsp; › &nbsp; ⟳</span>
          <div class="browser-location">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="6.7" cy="6.7" r="4.2"/><path d="m10 10 3.5 3.5" stroke-linecap="round"/>
            </svg>
            <span id="browser-query"></span>
          </div>
        </div>
        <div id="search-results">
          <section><strong>Разовые заказы на фрилансе</strong><span>Начать с тех навыков, которые уже есть.</span></section>
          <section><strong>Подработка на несколько часов</strong><span>Сравнить условия и требования к графику.</span></section>
          <section><strong>Продажа ненужных вещей</strong><span>Посмотреть спрос и выбрать площадку.</span></section>
        </div>
      </div>
      <div id="consent">
        <div class="desk-consent-box">
          <img src="../../brand/troika/logos/mark-amber.svg" alt="">
          <strong>Разрешить управление ПК?</strong>
          <span>Доступ к работе с экраном на время сеанса</span>
          <div><span>Отмена</span><b id="consent-approve">Разрешить</b></div>
        </div>
      </div>
      <div id="session-pill">Тройка управляет компьютером <b>Стоп</b></div>
      <div id="desktop-pointer">
        <svg viewBox="0 0 24 28" fill="#194d38" stroke="#fff" stroke-width="1.8" stroke-linejoin="round">
          <path d="M3 2v20l5-5 4 8 4-2-4-8 8-.1L3 2Z"/>
        </svg>
      </div>
    </div>
  </div>

  <div id="handset" aria-hidden="true">
    <div class="phone-rear"></div>
    <div class="phone-volume"></div>
    <div class="phone-power"></div>
    <div class="phone-rim"></div>
    <div class="phone-screen">
      <section id="mobile-app">
        <div class="mobile-brandbar">
          <img class="mobile-brand-symbol" src="../../brand/troika/logos/mark-amber.svg" alt="">
          <img class="mobile-brand-wordmark" src="../../brand/troika/logos/wordmark-ru-white.svg" alt="Тройка">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round">
            <path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7l-4 4V6a2 2 0 0 1 1-2Z"/>
          </svg>
        </div>
        <div id="mobile-orb">
          <svg viewBox="0 0 128 128" fill="none">
            <defs><linearGradient id="voice-arc-gradient" x1="16" y1="9" x2="100" y2="109" gradientUnits="userSpaceOnUse"><stop stop-color="#aaf5d1"/><stop offset=".5" stop-color="#3ddc97"/><stop offset="1" stop-color="#238f62"/></linearGradient></defs>
            <path d="M18 105V71c0-31 22-53 53-53h34" stroke="url(#voice-arc-gradient)" stroke-width="17" stroke-linecap="round"/>
            <path d="M49 105V78c0-17 12-29 29-29h27" stroke="#3ddc97" stroke-width="17" stroke-linecap="round"/>
            <circle cx="93" cy="92" r="25" fill="#0e1714" stroke="#4b6e60"/>
            <path d="M82 91v3m5-8v12m6-16v20m6-16v12m5-7v3" stroke="#8cf0c4" stroke-width="2.6" stroke-linecap="round"/>
          </svg>
        </div>
        <div id="mobile-state">Слушаю</div>
        <div class="mobile-actions"><span>Файлы</span><span>Разработка</span></div>
        <div class="mobile-composer"><span>Напиши сообщение</span><b>↑</b></div>
        <div class="mobile-nav">
          <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m2 9 8-7 8 7m-13 0v8h10V9m-7 8v-5h4v5"/></svg>Главная</span>
          <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 8a7 7 0 1 1 1 7M2 5v4l4-.5m4-3v5l3 2"/></svg>Разговоры</span>
          <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m2 6 2 2 3-4m4 2h7M2 14l2 2 3-4m4 2h7"/></svg>Дела</span>
          <span><svg viewBox="0 0 20 20" fill="currentColor"><circle cx="4" cy="10" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="16" cy="10" r="1.5"/></svg>Ещё</span>
        </div>
      </section>
      <section id="player">
        <div class="music-bar"><span>‹</span>Сейчас играет<span>···</span></div>
        <div class="music-art"><img id="player-art" src="player-art.svg" alt=""></div>
        <div class="music-meta"><strong>Ночной режим</strong><span>Troika</span></div>
        <div class="music-seek"><div id="seek-fill"></div></div>
        <div class="music-clock"><span id="player-time">0:14</span><span>2:46</span></div>
        <div class="music-controls">
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 5h2v14H5zm3 7 11-7v14z"/></svg>
          <div class="music-toggle">
            <svg id="play-icon" viewBox="0 0 24 24" fill="currentColor"><path d="m9 5 12 7-12 7z"/></svg>
            <svg id="pause-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zm6 0h4v14h-4z"/></svg>
          </div>
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 5h2v14h-2zm-1 7L5 5v14z"/></svg>
        </div>
      </section>
      <div class="phone-topbar"><span>21:54</span><span>
        <svg viewBox="0 0 41 12" fill="currentColor">
          <path d="M1 10h2V8H1zm4 0h2V5H5zm4 0h2V2H9z"/><path d="M15 4q4-4 9 0m-7 2q3-3 5 0m-4 2q1.5-1 2 0" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><rect x="27" y="2.5" width="11" height="7" rx="1.4" fill="none" stroke="currentColor"/><rect x="29" y="4.5" width="7" height="3" rx=".5"/><path d="M40 5v2" stroke="currentColor"/>
        </svg>
      </span></div>
      <span class="phone-camera"></span>
      <div id="handset-island">
        <svg viewBox="0 0 44 30" aria-hidden="true">
          <path class="island-wave" d="M1 15Q11 7 22 15T43 15"/>
          <path class="island-wave" d="M1 15Q11 22 22 15T43 15"/>
          <path class="island-wave" d="M1 15Q11 11 22 15T43 15"/>
        </svg>
        <span id="island-text">Слушаю…</span>
      </div>
      <div class="phone-homebar"></div>
    </div>
  </div>`;
