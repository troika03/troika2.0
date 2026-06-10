# Тройка 🎙️

**Тройка — личный голосовой AI-ассистент, который работает 24/7.**

Скажи «**тройка**» — и она слушает. Распознаёт речь, отвечает живым голосом, выполняет задачи и помнит контекст между разговорами. Запущена на ноутбуке/мини-ПК и доступна с телефона из любой точки через Tailscale.

Это форк [Hermes Agent](https://github.com/NousResearch/Hermes-Agent) от Nous Research — с собственной личностью, русским голосом, wake-word «тройка» и набором инструментов под повседневные задачи.

---

## Что умеет Тройка

| | |
|---|---|
| 🗣️ **Голос целиком** | Слушает wake-word на телефоне, распознаёт речь (Groq Whisper, ~0.8с), отвечает естественным голосом (Edge TTS). Личность с лёгкой иронией. |
| 🧠 **Помнит тебя** | Постоянная память + дневник по дням. Семантический поиск по фактам. Узнаёт тебя глубже от сессии к сессии. |
| 💻 **Делегирует код** | «Сделай сайт / приложение» → автопилот-кодер (Gemini CLI) пишет проект в фоне и присылает результат. Фазы vision → SRS → архитектура → задачи → код. |
| 🎨 **Генерит дизайн** | Google Stitch (на Gemini 3) делает production-grade UI-макеты: палитра, типографика, layout — потом по ним кодит. |
| 🖼️ **Создаёт медиа** | Бесплатная генерация изображений (FLUX/SDXL) и видео (LTX) через HuggingFace Spaces — без API-ключей. |
| 🔎 **Ищет в вебе** | Голосовой web-research: одним запросом находит, читает источники и отвечает коротко вслух. |
| 📱 **Управляет телефоном** | Будильники, таймеры, напоминания, календарь — через Android-приложение. |
| ⚙️ **Улучшает сама себя** | Правит собственный код через git-ветки (применяет только владелец), создаёт навыки из опыта. |
| ⏰ **Работает 24/7** | Автозапуск на ноутбуке (Планировщик Windows), keep-alive, работа с закрытой крышкой на зарядке. |

---

## Как это устроено

Тройка — это **два процесса** на машине + Android-приложение на телефоне:

- **Gateway** (порт 8642) — мозг: LLM, инструменты, TTS.
- **STT-прокси** (порт 8643) — распознавание речи.
- **Телефон** ловит «тройка», шлёт аудио на STT, получает текст → gateway → голосовой ответ.

Связь телефон ↔ ноутбук — по [Tailscale](https://tailscale.com) (приватная сеть), работает откуда угодно.

### Запуск

```powershell
python cli.py --gateway                      # gateway (8642)
cd hermes-android; python stt_proxy_server.py # STT-прокси (8643)
```

24/7-режим (автозапуск + keep-alive) настраивается скриптами в [`scripts/troika/`](scripts/troika/).

---

## Основа: Hermes Agent

Тройка построена на **[Hermes Agent](https://github.com/NousResearch/Hermes-Agent)** — самоулучшающемся AI-агенте от [Nous Research](https://nousresearch.com) с встроенным циклом обучения (создаёт навыки из опыта, улучшает их в работе, ищет по прошлым диалогам, строит модель пользователя). Hermes поддерживает любые LLM-провайдеры (Nous Portal, OpenRouter, OpenAI и др.), мессенджеры (Telegram, Discord, Slack, WhatsApp), терминальные бэкенды и MCP.

Полная документация апстрима: **[hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)**

### Установка базы (из апстрима)

**Linux / macOS / WSL2:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

**Windows (PowerShell):**
```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)
```

Установщик ставит uv, Python 3.11, Node.js, ripgrep, ffmpeg и портативный Git Bash. После установки команды CLI начинаются с `hermes` (`hermes`, `hermes model`, `hermes tools`, `hermes gateway`, `hermes doctor`).

---

## Лицензия

MIT — см. [LICENSE](LICENSE).

Построено на [Hermes Agent](https://github.com/NousResearch/Hermes-Agent) от [Nous Research](https://nousresearch.com).
