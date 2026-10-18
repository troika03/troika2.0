# Troika — безопасность, инфраструктура и выпуск

ID: `08-security-release`. Роль в общем исправлении Troika от 18 октября 2026 года.

Сначала прочитай [MASTER_PROMPT](../MASTER_PROMPT.md) полностью. Все общие
правила обязательны. Прочитай переданный владельцем
`D:\troika-product\docs\development\VOICE_DEVELOPMENT_WORKSPACE_PROMPT.md`.
Команды продукта выполняй только с рабочей папкой `D:\troika-product`.
`D:\troikahermes` — исключительно для чтения, даже если оттуда запущена сессия.

## Зона ответственности

- deploy/production/**
- CI/release/install скрипты своей области
- .github/workflows/**
- troika_product/retention.py
- security/backup/restore новые модули
- inherited runtime — candidate patches по контракту
- свои tests

Границы задают владельца candidate-изменений, а не разрешение одновременно
редактировать общий checkout. Реализуй в своём каталоге work; передай patch,
base hashes и отчёт. Прямые общие изменения/commit/push делает только 09.
Чужой staged/unstaged WIP не включай в свой patch без явного анализа происхождения.

## Задачи

1. Проверь все load-bearing границы: owner/device/session для sessions/runs/memory/tasks/files/workspaces/checkpoints/extensions/MCP; replay/TTL/logout/revoke/Stop. Расширение не получает прав сверх пользователя и parent Run.
2. Проверь approval и consent между UI/API/специалистом/local executor. Read не даёт write/control; неизвестный approval channel закрывает доступ. Нет shell/Docker socket/credentials на основном API.
3. Проверь private payload в application logs/analytics/crash/backups/temp, raw media, secret detection, document/ZIP/path/symlink traversal, browser/page prompt injection и безопасные diagnostics.
4. Доведи production storage/queue, encryption at rest, version-aware deletion, durable deletion ledger, restore scrubber и backup/restore rehearsal до проверяемого проекта. Прежде миграции — backup/rollback и совместимость, без уничтожения реальных данных.
5. Проверь единственный production compose path, readiness/health/timeouts/retries, staging/secrets, metrics/alerts/status, устойчивое recovery. Не разворачивай production и не перезапускай действующие сервисы по этому запуску.
6. Проверь release/подпись/installer/update/rollback Android и WPF, dependency upper bounds/SHA pins, packaging и необходимые inherited Hermes runtime. Не удаляй зависимости по старому имени.
7. Разбери доступные Python/dashboard/TUI/website baseline failures: продуктовый bug, платформа, fixture, provider/service. Рабочие исправления в candidate с paired checks; полный зелёный baseline не придумывай.
8. Сверь общие 20 Word-разделов и release gates: beta/observability/support/legal/public launch. Подготовь измеримые критерии и отказ при незавершённых обязательных gates.

## Зависимости

- Account/delete — 04
- Ledger/anti-abuse — 06
- Новые инструменты/MCP — 01
- Общую интеграцию выполняет 09

Не жди пассивно: подготовь собственную реализацию и contract fixtures для
независящих частей. Отдельно пометь, где проверка fixture ещё не является E2E.

## Приёмка

- Негативные security tests покрывают новый workspace/MCP/plugin и старые data paths без побочного доступа к профилю.
- Restore rehearsal на синтетической копии не возвращает удалённые данные; deletion/export/revoke закрывают новые хранилища.
- Чистая сборка и upgrade paths проверены; source/build/installed/production доказательства различаются.
- Нет live deployment/платежа/сброса данных; подготовлен конкретный безопасный состав интеграции и отката.

## Результат текущей сессии

Каталог candidate/patch: `D:\troika-product\work\product-repair-2026-10-18\08-security-release\`.
Единственный свой отчёт: `D:\troika-product\docs\development\repair-2026-10-18\reports\08-security-release.md`.

Выполни доступную работу целиком. Сохрани матрицу функций, найденные причины,
контракты, точный состав patch и фактические проверки. Не завершай одним
обещанием, списком идей или неподтверждённым «всё работает». Если нужен
внешний доступ или решение владельца, сначала доведи независимую часть
до конкретного reviewable результата и укажи единственный нужный следующий шаг.
