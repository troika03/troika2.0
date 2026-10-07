# Troika: текущая память проекта

Обновлено 2026-10-07. Краткий рабочий срез; история находится в Git и
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
- Целевые тарифы: Free, Plus 790 ₽/месяц, Pro 1 490 ₽/месяц. По запросу владельца от 7 октября дневной счётчик AI-запросов включён по умолчанию и на production. Billing и месячные credits отсутствуют; безлимит не обещается. Экономические лимиты предложены в `docs/TROIKA_SUBSCRIPTION_ECONOMICS.md`, но ещё не утверждены и не применены.
- Фоновое локальное пробуждение «Тройка» — P0 Android; OEM/Bluetooth/standby/expiry требуют E2E.
- Данные принадлежат аккаунту. Сервер — основная копия; выбрано автоматическое восстановление после входа, а не невосстановимое E2EE. Production stores/backups должны шифроваться at rest.
- Единый Run/Task/Worker runtime с до трёх specialist workers — целевая архитектура; текущий agent loop ещё не закрывает весь этот scope.
- Важные внешние/разрушительные/privacy-sensitive действия требуют approval; обратимые requested low-risk actions выполняются напрямую.
- Live screen/camera, полный Accessibility, автономный PC, GROUND/DAEMON/Kali/self-improvement не входят в ordinary 1.0.
- Владелец прямо подтвердил 2026-10-05: сохранить `hermes_cli`. Удалять только подтверждённо ненужные материалы; имена runtime мигрировать с совместимостью.
- Решение 2026-10-06: облачный ИИ сохраняется; готовые новые документы/презентации/проекты с кодом должны храниться на устройстве без постоянной серверной файловой копии. Account history/memory/tasks пока остаются серверными; автоматического облачного восстановления локальных файлов нет.
- Основной порядок ремонта — `PRODUCTIZATION_PLAN.md`, 8 этапов с критериями. Добавлен согласованный scope разработки: код, локальные проверки на ПК, отчёт и исправленная версия. Напоминания параллельно чинятся в другой сессии; её незавершённые правки не включать в эту задачу.

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
Windows background delivery и native Android refresh добавлены в отдельной
незавершённой работе с напоминаниями; их E2E и commit принадлежат той сессии.
FCM/push отсутствуют. Наличие кода refresh не закрывает проверки expiry/standby.

Одноразовый Android screen snapshot имеет прежний Samsung E2E и threat review.
Нужны beta build и два server flags; оба flags выключены по умолчанию.
Это не доказательство live WebRTC/CameraX.

## Реальная среда на 2026-10-07

Production API использует `troika-production:subscription-limits-20261007`
(поверх `reminder-voice-20261007-v2`, с сохранением других runtime fixes), STT —
`troika-production:bf92c78`; API healthy;
`https://api.zhulebino-teahouse.ru/health` отвечает 200. Deployment path:
`deploy/production/compose.yaml`. API опубликован через loopback 8765/Nginx;
STT — private Docker network. ОС/TLS foundation существуют; остальная
production готовность не закрыта.

Живой quota smoke подтвердил: Free-запрос принят, расход 1/1 виден в
`/v1/subscription`; повторные `/v1/runs` и `/v1/chat/completions` возвращают
429 с `daily_request_limit_exceeded`, остатком, `resets_at` и `Retry-After`.
Доступ к списку устройств после исчерпания сохранён; временный аккаунт удалён.
Существующие entitlements не изменены: при диагностике Free имел 1 запрос/сутки,
Pro — 10 000. Это временный дневной guard, не защита себестоимости подписки.
Новый профиль показывает тариф, расход, остаток и локальное время обновления,
обновляется после облачного запроса/возврата приложения и раз в минуту;
ошибка загрузки скрывает устаревший остаток. Светлая/тёмная темы просмотрены.
Целевые Python: 355 passed, 1 skipped в текущем checkout, включая 9 тестов
незавершённой работы с напоминаниями. Собственные quota/access tests — 41 passed.
Изолированный клиент с этим исправлением: 74 passed, 2 skips; analyze —
0 errors/warnings, 38 info. Android debug/release и Windows debug собраны из
изолированного клиента; новые profile/limits изменения ещё не установлены
на устройстве. Требуется объединение с актуальными native/reminder правками.
Предложение экономики: Free 300, Plus 3 000, Pro 6 000 credits/месяц при
верхней учитываемой себестоимости 0,05 ₽/credit; welcome 700 credits однократно.
Это не применённая политика: cost ledger, hard cap всех внутренних вызовов,
anti-abuse, global Free budget и billing ещё требуют реализации.
Полный default Python обнаружил 1237 файлов и завершился с exit 1; полный
aggregate в сохранённом stdout отсутствует. Baseline остаётся красным;
детали в `docs/audit/SUBSCRIPTION_LIMIT_CHECKS_2026_10_07.md`.

На production единственный загруженный поисковый provider — SearXNG
2026.10.4-d48c4b555, закреплённый digest в Compose. Сервис доступен только
в Docker network; API использует `http://searxng:8080`. Firecrawl, Parallel,
Tavily, Exa, Brave, DDGS и xAI отключены через `plugins.disabled`.
Унаследованный код сохранён для совместимости. Русские/английские запросы
вернули непустую выдачу; настоящий `web_search` вернул три источника;
authenticated chat вернул ссылки, тестовый аккаунт удалён. Search/research
доступны в product toolset, но полное чтение страниц не подключено:
SearXNG возвращает snippets, research может использовать только их.
Google CSE возвращает результаты; Brave/DDG внутри SearXNG ответили rate
limit/CAPTCHA. Проверка не обещает постоянную доступность каждого движка.
SearXNG Docker logs не сохраняются; API informational logs подавлены.
Секрет сервиса находится отдельно в `/srv/troika/data/searxng.env`, вне Git.

Обновлённый клиент показывает компактную строку «Найдено N страниц» со
значками сайтов; по нажатию раскрываются названия, домены, ссылки и статусы
«Найдено», «Открываю», «Прочитано» или ошибка чтения. Источники приходят из
реальных tool results, до 20 уникальных ссылок на ответ, без содержимого страниц
и скрытых рассуждений. SSE и восстановление источников из owner-scoped истории
проверены на production; защитная оболочка внешнего результата сохраняется.
Фоновый native voice запрашивает источники сразу после ответа через историю,
с проверкой текущей сессии и сохранением более новых сообщений; live SSE этого
канала пока нет. На Android и Windows удалён локальный перехват «найди/поищи»
для открытия Google. Поиск передаётся агенту; явное открытие браузера сохранено.

Windows установлен в `C:\Users\kiqu\Troika` из объединённой сборки
`_logs/source-install-20261007`. Предыдущий каталог сохранён локально для
отката; account preferences не сбрасывались. SHA-256 EXE:
`86c3cd6fcda3a35f58de4b53b68a43822b2963c583d1ee165a83ca48b91e3f06`.
В установленной странице «Текст» подтверждена строка «Найдено 7 страниц»
из реальной истории. Свежий поиск/голосовой E2E Windows ещё не завершён.
Проверки объединённого клиента: 74 Flutter tests passed; analyze — 0
errors/warnings, 38 info; Android/Windows release builds прошли. В сборках
сохранены native изменения напоминаний, но они не включены в commit поиска.

APK с поисковыми исправлениями готова в
`_logs/source-install-20261007/hermes-android/build/app/outputs/flutter-apk/app-release.apk`;
SHA-256 `c02066100495302ffc7ff464647735c6c5eff88cf19fff58f30c2961bba7a900`.
После подключения Samsung SM-A225F первая APK установлена через `adb install -r`
без удаления приложения и сброса данных; её установленный hash совпал со
сборкой выше. Запуск приложения и переход на страницу «Текст» подтверждены.
Сессия напоминаний затем установила следующую общую сборку: текущий `base.apk`
имеет SHA-256 `0f6c6e1442c743d7354640a4e6b9849eba9143aef0a351331bc6b7b61173680a`,
lastUpdateTime 2026-10-07 16:21:49, versionName 1.0.0. Проверка установленного
APK подтверждает WebSourcesView и немедленную загрузку voice sources; старые
`_searchQuery`/`SEARCH_VERBS` отсутствуют. Исправления поиска сохранены в общей
сборке. Свежий телефонный поиск/голосовой E2E этой сессией ещё не завершён.

API обновлён слоем девяти committed runtime files `e0254f5` поверх
`reminder-voice-20261007`, сохраняя существующую серверную правку напоминаний.
Это требуется для проверки `features.device_file_delivery` новым клиентом.
Свежий disposable-account smoke подтвердил 10 source rows в SSE и 9 уникальных
ссылок в history; чужой run/history дают 404/403. Оба аккаунта удалены.
Передача просьбы другой сессии объединить сборки разрешена владельцем и выполнена.
Полный fresh voice/reminder/file-save E2E здесь не подтверждён.

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

В текущем source добавлены expiring RAM handoff с owner/device guard,
контрольной суммой и подтверждением после локального сохранения; локальный
список файлов и восстановление пропущенной передачи в пределах TTL 10 минут.
Обновлённый Flutter запрашивает device delivery; native voice подготавливает
файл, для сохранения нужно открыть «Файлы» до expiry. Старые cloud artifacts
остаются доступны. Runtime `e0254f5` включён в текущий API, клиент Windows
обновлён; APK с теми же возможностями установлена на Samsung. Device-file E2E
не закрыт.

Первый режим «Разработка» создаёт ZIP с текстовыми исходниками/README/тестами,
распаковывает в новую папку и запускает на Windows Python syntax/unittest или
JS syntax с локальным подтверждением, тайм-аутом и Stop. Для исправления
передаёт текущие исходники и отчёт ИИ, сохраняет новую версию. Полная работа
с существующим repository, зависимости/сборки и phone-to-PC Companion пока
не реализованы. Проверки используют права пользователя, отдельного sandbox нет.

Проверки собственных изменений на 2026-10-07: последний целевой Python run —
88 passed; gateway protocol — 29 passed. Изолированный Flutter-клиент —
68 passed, 2 endpoint-define skips после объединения с завершёнными web-source
изменениями `4ef13af`; analyze — 0 errors/warnings, 38 info.
Debug сборки Android и Windows прошли. Реальный Python failure/fix/pass,
zero-tests и timeout, локальная запись до ACK и повтор после потерянного ACK
проверены. PDF-пример просмотрен; DOCX/PPTX visual QA и установленный E2E
остаются открытыми. Общий Python baseline не зелёный, детали в аудите.

Создан единый индекс документов, сокращены память/AGENTS/активные планы,
старые конкурирующие планы помещены в явно исторический архив. Исправлены
устаревшие setup/notification/sync/production statements. Удалён 31 лишний
upstream/documentation/automation файл; детали в карте репозитория.
Рабочий runtime, LICENSE, совместимость Android и пользовательские данные сохранены.

Исторический baseline 5 октября содержит 1233 default Python test files;
повтор 6–7 октября содержит 1236. Общий baseline остаётся красным.
Отдельно выполнены Discord voice integration, Flutter checks,
Android/Windows/dashboard/TUI/website builds и живой account/tool smoke.
Физическая проверка Samsung ограничена запуском/UI/mic state старой APK.
Полные counters и неуспешные test files находятся в аудите, а не в этой памяти.

## Следующий шаг

Проверить свежий поиск и голос на обновлённом Samsung, затем проверить сохранение
и открытие документа, создание проекта, запуск проверки и получение исправленной
версии. Для native voice открыть «Файлы» в пределах TTL. Продолжать P0 по
основному плану: чтение веб-страниц, background refresh, голос и напоминания.
Последние чинятся в другой сессии; её изменения требуют своего E2E.
Затем завершать раздел 7 и двигаться по Word-плану. Отдельные сборки и
исторические smokes не означают «всё работает».

Обновлённый клиент перед облачным запросом проверяет `features.device_file_delivery`
в `/v1/capabilities`. Без поддержки просит обновить сервер, чтобы старый
backend не проигнорировал локальный режим и не сохранил файл постоянно.
Сначала обновляется API, затем клиент; исторические клиенты сохраняют legacy
совместимость до отдельной миграции.
