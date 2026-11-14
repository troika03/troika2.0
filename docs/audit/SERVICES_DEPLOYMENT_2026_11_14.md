# Развёртывание: Скиллы, MCP и подключение сервисов — 14 ноября 2026

Решение владельца в чате: «Да, развернуть».

Образ `troika-production:services-20261114` (`sha256:95bd48f3…f694ab`) собран
поверх работавшего `identity-20261105-3` (`0cb9bbe53c5f`, тег
`services-20261114-parent` для отката). В образ добавлены только файлы этой
задачи; незавершённые изменения других сессий не переносились:

- новые: `troika_product/extensions.py`, `mcp_connector.py`,
  `mcp_directory.yaml`, `service_connections.py`;
- `capability_api.py` — серверная версия совпадала с HEAD, взят рабочий файл;
- `capabilities.py`, `context_guidance.py`, `access.py`,
  `gateway/platforms/api_server.py` — правки задачи наложены на серверные
  версии по якорям (каждый ровно один раз); разница с сервером: +32/−3, +1,
  +7, +28 строк.
- Пакеты из `uv.lock` (`--no-deps`): mcp 1.26.0, httpx-sse 0.4.3,
  pydantic-settings 2.13.1, python-multipart 0.0.27, sse-starlette 3.3.2,
  starlette 0.52.1, uvicorn 0.41.0, click 8.3.1. `uv pip check`: совместимо.

Проверки до переключения в одноразовом контейнере без production-томов:
каталог 178 навыков / 42 MCP; перезагрузка OAuth-токенов в SDK 1.26; живой
вызов DeepWiki `read_wiki_structure`; тесты `test_extensions.py` +
`test_service_connections.py` — 12 из 13 (одна проверка использует
локальную функцию другой сессии, отсутствующую на сервере).

Переключение: резервные копии `troika_access.db` (SQLite backup) и `.env` в
`/srv/troika/backups/services-20261114` (700/600). В `/srv/troika/data/.env`
добавлены `TROIKA_PRODUCT_SERVICE_KEY` (Fernet, создан на сервере, не
выводился) и `TROIKA_PRODUCT_PUBLIC_URL=https://api.zhulebino-teahouse.ru`.
Пересоздан только `api` (`--no-deps`) со всеми прежними override-файлами и
новым `activation-pinned-image.override.yaml`; `rollback-pinned-image.override.yaml`
указывает на прежний образ. STT, SearXNG, Telegram не перезапускались.

После переключения: API healthy, 0 перезапусков, ошибок в логах нет;
публичный `/health` 200; `/v1/account/extensions` и
`/v1/account/services/*/connect` без входа — 401 (маршруты есть);
`/v1/account/services/oauth/callback` с чужим `state` — 400 и страница
«Вход не завершён».

Не проверено: работа с настоящим аккаунтом (временный аккаунт на production
не создавался без отдельного разрешения), реальный вход в GitHub/Notion и
вызовы инструментов сервисов, подтверждение действий на телефоне.

Откат: пересоздать `api` с прежним списком config-файлов
(`previous-config-files.txt`) и `rollback-pinned-image.override.yaml`; при
необходимости вернуть `.env` из `env.before`. Таблица
`troika_service_connections` безопасна для прежнего образа (не читается).

## Исправление 14.11: Тройка не находила GitHub

Владелец подключил GitHub токеном, но на просьбу показать проекты Тройка
отвечала про локальные файлы, затем «нет доступа». В логах API:
`troika_tool_search` → `invalid_discovery_arguments` и четыре
`troika_tool_call` → `tool_not_allowed` (модель угадывала имена). Подключение
GitHub в базе было (1 запись `github/token`); переписка не читалась.

Исправление `267d2af`: имя сервиса в `capability` ведёт в MCP-поиск этого
сервера; неизвестные capability/инструменты возвращают подсказку; у серверов
с множеством инструментов сначала краткий список имён, полная схема — по
`tool=<server>/<name>`; описание `troika_tool_search` называет GitHub, Notion,
Jira, Stripe. Образ `troika-production:services-20261114-2`
(`sha256:6301860d…ded5c2`) поверх `services-20261114`, пересоздан только
`api`, healthy, 0 перезапусков. Повторная проверка в приложении владельца
ещё не выполнена.

## Второе исправление 14.11: короче путь к инструментам GitHub

После первого исправления Тройка написала «использую поиск репозиториев» и
остановилась без вызова. Подключение проверено служебным `tools/list`
(только названия): GitHub отдаёт 46 инструментов, признаки read-only верные.
`c3437d6`: для GitHub первая выдача содержит полные схемы 8 основных
инструментов (`get_me`, `search_repositories`, `get_file_contents`,
`list_issues`, `list_pull_requests`, `list_commits`, `search_code`,
`issue_write`), остальные 38 — названиями, и подсказку `usage`; ответ ~21 КБ.
Образ `troika-production:services-20261114-3` (`sha256:b04f3b01…c94953`),
пересоздан только `api`, healthy. Ответ модели в приложении не перепроверен.

## Pro: скиллы, MCP и модель DeepSeek — 14.11

Решение владельца: бесплатная модель выдумывала ответы про GitHub (трасса
вызовов: угаданные имена инструментов, ответы без вызовов), поэтому скиллы и
MCP — только Pro, Pro — более сильная модель; Free и Plus без изменений,
кроме скиллов/MCP.

Сравнение на сервере (реальные инструкции и схемы GitHub, подставной
владелец, 3 прогона): nemotron-3.5-lightning:free 0/4; DeepSeek V4.1 Flash
1017, Qwen 3.8 Flash, Claude Haiku 5.5, GPT-5.6 Luna — 4/4. Цена запроса
≈ $0.0016 / 0.004 / 0.0045 / 0.006. Выбран DeepSeek.

`b3f129c`: Free/Plus видят каталог с пометкой Pro, подключение — 402,
вызовы — `pro_required`; Pro использует `product_pro_model` с бесплатной
моделью как запасной. В серверный `config.yaml` добавлены
`product_pro_model` и цена DeepSeek (premium, 138 ₽/$: 5.244 / 69 / 1.38 ₽
за 1M); бюджет Pro списывается по стоимости (≈0.22 ₽ за запрос). Резервная
копия — `config.before.yaml` в `releases/services-20261114-4`. Образ
`services-20261114-4` (`sha256:0004d47a…04d6c7`), пересоздан только `api`,
healthy. Баланс OpenRouter на момент включения −$0.10: без пополнения
платные запросы будут уходить на запасную бесплатную модель.
