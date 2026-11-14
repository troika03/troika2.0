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
