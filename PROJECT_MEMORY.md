# Troika: текущая память проекта

Обновлено 2026-10-05. Краткий рабочий срез; история находится в Git и
[архиве](docs/archive/README.md). Результаты проверок и дефекты хранятся в
[аудите функций](docs/TROIKA_FUNCTIONAL_AUDIT.md), без дублирования здесь.

## Маршрут

Единственная writable копия — `D:\troika-product`.
`D:\troikahermes` — read-only historical source. Ожидаемая ветка
`codex/product-foundation`; origin `https://github.com/troika03/troika2.0.git`.

До работы читать `AGENTS.md`, главный DOCX, execution tracker, этот файл,
`PRODUCTIZATION_PLAN.md` и capability restoration plan. [Документы](docs/README.md)
содержат точные ссылки. Завершённые изменения коммитить и отправлять
`git push origin HEAD:main`; чужой WIP не включать.

## Решения владельца

- [Word-план](docs/Troika_1.0_Launch_Plan_Final_Updated.docx) — authority для scope/UX/цен/DoD. Порядок разделов 1–20 сохраняется; section 20 — release summary.
- Troika 1.0 — voice-first Android/Windows, текст вторичен. Результат важнее перечисления tools.
- Hosted subscription без model keys у обычного пользователя; BYOK/diagnostics — developer/Advanced scope.
- Целевые тарифы: Free, Plus 790 ₽/месяц, Pro 1 490 ₽/месяц. Billing отсутствует; текущая quota enforcement выключена. Безлимит не обещается.
- Фоновое локальное пробуждение «Тройка» — P0 Android; OEM/Bluetooth/standby/expiry требуют E2E.
- Данные принадлежат аккаунту. Сервер — основная копия; выбрано автоматическое восстановление после входа, а не невосстановимое E2EE. Production stores/backups должны шифроваться at rest.
- Единый Run/Task/Worker runtime с до трёх specialist workers — целевая архитектура; текущий agent loop ещё не закрывает весь этот scope.
- Важные внешние/разрушительные/privacy-sensitive действия требуют approval; обратимые requested low-risk actions выполняются напрямую.
- Live screen/camera, полный Accessibility, автономный PC, GROUND/DAEMON/Kali/self-improvement не входят в ordinary 1.0.
- Владелец прямо подтвердил 2026-10-05: сохранить `hermes_cli`. Удалять только подтверждённо ненужные материалы; имена runtime мигрировать с совместимостью.

## Реализация

Есть индивидуальные register/login/access/refresh/device revoke, owner-scoped
sessions/history/memory/tasks/inbox/workspace/artifacts, account export/delete,
local SQLite/filesystem retention. Profile-global MEMORY/USER не используются
как личная product memory. Данные другого аккаунта не добавляются в prompt.

Flutter содержит voice-first Home, Text, Дела, Файлы, Профиль; Windows —
Compact/Command Center/hotkey. Есть локальные allowlist-команды, local DOCX/PPTX,
hosted DOCX/PDF/PPTX и downloadable text/HTML artifacts. HTML artifact не
является опубликованным сайтом. Completion receipts/persona 4 ограничивают
ложные заявления о выполнении; они не доказывают любое содержание модели.

Reminders: owner-scoped schedule, quiet hours/opt-in, snapshot и Android
AlarmManager. Нужны permissions и успешная предварительная синхронизация;
Windows background notifications и FCM/push отсутствуют. Native Android
voice service пока не обновляет истёкший access token самостоятельно.

Одноразовый Android screen snapshot имеет прежний Samsung E2E и threat review.
Нужны beta build и два server flags; оба flags выключены по умолчанию.
Это не доказательство live WebRTC/CameraX.

## Реальная среда на 2026-10-05

Production API/STT используют `troika-production:bf92c78`, API healthy;
`https://api.zhulebino-teahouse.ru/health` отвечает 200. Deployment path:
`deploy/production/compose.yaml`. API опубликован через loopback 8765/Nginx;
STT — private Docker network. ОС/TLS foundation существуют; остальная
production готовность не закрыта.

На production web backend выбран Firecrawl, его availability check — false.
Поэтому web search/extract/research сейчас недоступны. Наличие этих tools в
source/allowlist не означает доступность у пользователя.

Samsung SM-A225F подключён. Установленная APK 1.0.0 имеет SHA-256
`35f5a43c41f9af35b8e4064256744ea20871d8009e57580c8ee819fcd4ecc336`:
это прежняя completion-guard сборка, а не актуальная reminder release APK
с SHA-256 `f7e56cc6f6c10cd17403488d8af4adb907de4e06fe80e270d1f28eb9af3febc0`.
Приложение запускается, главный экран/Файлы открываются, микрофон переходит
в «Слушаю». APK и данные не заменялись. Полный свежий voice/reminder/file-save
E2E установленного клиента не подтверждён.

Локальный порт 8765 ответил HTTP 404; это не здоровый product gateway.
Нельзя считать localhost health проверенным по одному факту открытого порта.

## Незакрытый scope

Password recovery/email verification; credits/cost/billing/checkout/webhooks/
cancellation/refunds; production Postgres/object/queue; backup deletion ledger/
restore scrubber/rehearsal; metrics/alerts/support/legal; signed installers/
updates; полная offline-first очередь/conflict resolution; существующие Office
import/edit и XLSX. Dashboard PTY chat требует POSIX/WSL, native Windows path
не реализован. Full Python Windows baseline, dashboard/TUI lint не зелёные.
Inherited developer website собирается, но Windows generators/Skills Hub деградируют.

## Завершённая ревизия документации

Создан единый индекс документов, сокращены память/AGENTS/активные планы,
старые конкурирующие планы помещены в явно исторический архив. Исправлены
устаревшие setup/notification/sync/production statements. Удалён 31 лишний
upstream/documentation/automation файл; детали в карте репозитория.
Рабочий runtime, LICENSE, совместимость Android и пользовательские данные сохранены.

Результаты сохранены для всех 1233 default Python test files; общий baseline
остаётся красным. Отдельно выполнены Discord voice integration, Flutter checks,
Android/Windows/dashboard/TUI/website builds и живой account/tool smoke.
Физическая проверка Samsung ограничена запуском/UI/mic state старой APK.
Полные counters и неуспешные test files находятся в аудите, а не в этой памяти.

## Следующий шаг

Воспроизвести пользовательские отказы по установленной версии; восстановить
настроенный web provider, закрыть Android background token refresh и проверить
актуальный reminder APK на телефоне. Затем завершать раздел 7 и двигаться
по Word-плану. Отдельные сборки и исторические smokes не означают «всё работает».
