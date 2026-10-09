# Troika: текущая память проекта

Обновлено 2026-10-08. Краткий рабочий срез; история находится в Git и
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
- Live screen/camera, полный Accessibility, автономный PC-agent общего назначения, GROUND/DAEMON/Kali/self-improvement не входят в ordinary 1.0.
- Владелец прямо подтвердил 2026-10-05: сохранить `hermes_cli`. Удалять только подтверждённо ненужные материалы; имена runtime мигрировать с совместимостью.
- Решение 2026-10-06: облачный ИИ сохраняется; готовые новые документы/презентации/проекты с кодом должны храниться на устройстве без постоянной серверной файловой копии. Account history/memory/tasks пока остаются серверными; автоматического облачного восстановления локальных файлов нет.
- Основной порядок ремонта — `PRODUCTIZATION_PLAN.md`, 8 этапов с критериями. Добавлен согласованный scope разработки: код, локальные проверки на ПК, отчёт и исправленная версия. Напоминания параллельно чинятся в другой сессии; её незавершённые правки не включать в эту задачу.
- Решение 2026-10-08: самостоятельный ПК-клиент с нуля, без сборки мобильного UI, с одним небольшим окном, заметными функциями и неоновым оформлением. Компактный режим меняет размер того же окна; панели остаются внутри него.

- Решение 2026-10-08: разработка доступна на телефоне и ПК; перед проверкой спрашивать «на телефоне или выбранном ПК». Разрешён цикл создания и до трёх исправлений по настоящим проверкам с Stop и сохранением новых версий.

## Реализация

Есть индивидуальные register/login/access/refresh/device revoke, owner-scoped
sessions/history/memory/tasks/inbox/workspace/artifacts, account export/delete,
local SQLite/filesystem retention. Profile-global MEMORY/USER не используются
как личная product memory. Данные другого аккаунта не добавляются в prompt.

Android Flutter содержит voice-first Home, Text, Дела, Файлы, Профиль;
исторический Flutter Windows сохраняется, но новая ПК-версия реализована
отдельно в `troika-desktop` на WPF/.NET Framework 4.8. Есть локальные allowlist-команды, local DOCX/PPTX,
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

Каталог «Возможности» добавлен в Android и отдельный WPF-клиент. Есть вкладки
плагинов, навыков и инструментов; переключатели относятся к аккаунту и входят
в export/delete. Hosted agent получает две постоянные схемы gateway и загружает
исходные схемы по необходимости. История, память и личность не обрезаются.
Локальный замер схем: 4 377 против 299 токенов (`cl100k_base`), около 93%; это
не счётчик всего запроса и не замер production billing. Проверки владельца,
approval, sources, receipts и device file delivery сохранены. Legacy media
tools с общим phone bridge исключены из ordinary product; проверенные
возможности сохранены. Детали и проверки: `docs/TROIKA_CAPABILITIES_AUDIT_20261008.md`.
Серверная часть каталога развёрнута 2026-10-08 поверх текущего development API.
Новый образ — `troika-production:capabilities-20261008`; добавлены 12 runtime
файлов и закреплённые зависимости JSON Schema. Серверные исправления разработки
сохранены. Пересоздан только API через production Compose; STT и SearXNG не менялись.
В отдельном контейнере прошли 25 тестов. Live HTTP: health 200, каталог 200
с девятью разделами, без авторизации 401; настройки сохраняются и изолированы
по аккаунтам, неверный patch отклоняется. Временные аккаунты удалены.
На телефоне каталог в момент проверки не был открыт; его загрузка на устройстве
и фактические provider usage ещё требуют проверки. Детали:
`docs/audit/CAPABILITIES_DEPLOYMENT_2026_10_08.md`.

Текущий APK на Samsung — объединённая release сборка с разработкой,
установленная 2026-10-08 через `adb install -r`, без сброса данных:
`_logs/development-20261008/artifacts/Troika-2026-10-08.apk` (114 465 549 байт).
SHA-256 установленного base.apk совпадает:
`4855f74f924516077b909259189a24b65e09ae5d9f11b6515f6b0e376e8ab97d`.
Версия 1.0.0+1, прежняя Android Debug key, MainActivity уже работает.
Сборка содержит актуальные native reminder правки другой сессии; они не
включены в commit разработки и не объявляются проверенными этой задачей.
Предыдущая чистая APK каталога `11a3cc8` сохранена как архив и не является
текущей установленной версией. Полный установленный Android E2E не закрыт.

## Реальная среда на 2026-10-08

Production API использует `troika-production:capabilities-20261008`
(добавочный слой поверх `development-20261008`, с сохранением runtime fixes), STT —
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
2026-10-08 по прямому запросу владельца одному существующему активному аккаунту
вручную выдан Pro с лимитом 10 000 запросов/сутки через `set_entitlement`.
Тариф и лимит повторно проверены в production; текущий расход не сбрасывался.
Новый профиль показывает тариф, расход, остаток и локальное время обновления,
обновляется после облачного запроса/возврата приложения и раз в минуту;
ошибка загрузки скрывает устаревший остаток. Светлая/тёмная темы просмотрены.
Целевые Python: 355 passed, 1 skipped в текущем checkout, включая 9 тестов
незавершённой работы с напоминаниями. Собственные quota/access tests — 41 passed.
Изолированный клиент с этим исправлением: 74 passed, 2 skips; analyze —
0 errors/warnings, 38 info. Android debug/release и Windows debug собраны из
изолированного клиента; profile/limits включены в текущую общую APK.
Установленный E2E лимитов и native/reminder правок требует отдельной проверки.
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

Исторический Flutter Windows установлен в `C:\Users\kiqu\Troika` из объединённой сборки
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
Текущая установленная APK указана выше; прежние APK сохранены для отката.
Свежий телефонный поиск/голосовой E2E этой сессией не завершён.

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

## Самостоятельный ПК-клиент: 2026-10-08

`troika-desktop` содержит независимый WPF-клиент с бирюзовой/фиолетовой
неоновой сферой. Обычное окно 960 × 680, минимум 780 × 540, компактное
480 × 600. История, возможности, дела, файлы, память, разработка и аккаунт
открываются внутри одного окна. Повторный запуск активирует существующее
окно. Ctrl+Alt+T вызывает голос, Escape останавливает действие.

Есть register/login/refresh/DPAPI, SSE без private reasoning, подтверждения,
источники поиска, локальная доставка файлов с SHA-256/save-before-ACK,
проекты/задачи/заметки, memory CRUD, тариф/остаток, устройства/revoke,
экспорт/удаление аккаунта, запись WAV/STT/TTS и allowlist-команды Windows.
Разработка распаковывает выбранный ZIP в новую папку, после подтверждения
запускает ограниченные Python/JS проверки и останавливает группу процессов.
Новый режим спрашивает место проверки, создаёт проект напрямую через облачный
агент, затем выполняет до трёх исправлений по настоящим ошибкам. Приём с телефона
включается локально; первый проект подтверждается на ПК (до четырёх версий за
10 минут). Это ограниченный relay, а не общий Companion.

Текущая версия установлена в `D:\TroikaDesktop\releases\4a38d53c299a`;
ярлык «Тройка ПК» обновлён. SHA-256 EXE:
`4a38d53c299aa76006a672a32ada115ccee2c9289dde16021db3de3d7b30bae8`.
Открытая старая версия не закрывалась принудительно; новый клиент открывается
через обновлённый ярлык.
Старый Flutter-каталог и настройки сохранены. Новый клиент использует
свою DPAPI-сессию; автоматического импорта Flutter credentials нет.

Сборка и 30 собственных проверок прошли, включая реальные Python
failure/fix/pass, Stop, потерянный ACK, ошибки SSE и изоляцию аккаунтов.
Просмотрены обычное, минимальное, компактное, светлое окно и панель
возможностей; основные элементы не выходят за границы. Установленное
окно просмотрено; повторный запуск оставляет один процесс.
Живой smoke подтвердил register, subscription/devices/tasks, SSE/history,
создание DOCX, локальную контрольную сумму/ACK и ответ TTS; временный
аккаунт удалён. Расширенный smoke с login/memory/notes/export/prefs
прервался из-за TLS EOF, поэтому эти сценарии не объявлены live-verified.
Микрофон, воспроизведение и полный установленный voice/file E2E не подтверждены.
Подробности: [проверки ПК-клиента](docs/TROIKA_DESKTOP_REBUILD_2026_10_08.md).

Напоминания этого клиента работают только при открытом/свёрнутом окне,
без фоновой службы после закрытия. Это не заменяет незавершённую работу
другой сессии над native Flutter reminders. Wake word/live screen/camera,
подписанный installer/updates, sandbox проверок, произвольный repository
build и общий phone-to-PC Companion отсутствуют. Ограниченные проверки с телефона
поддерживаются новым development relay; полного установленного E2E пока нет.

## Завершённая ревизия документации

В текущем source добавлены expiring RAM handoff с owner/device guard,
контрольной суммой и подтверждением после локального сохранения; локальный
список файлов и восстановление пропущенной передачи в пределах TTL 10 минут.
Обновлённый Flutter запрашивает device delivery; native voice подготавливает
файл, для сохранения нужно открыть «Файлы» до expiry. Старые cloud artifacts
остаются доступны. Runtime `e0254f5` включён в текущий API, клиент Windows
обновлён; APK с теми же возможностями установлена на Samsung. Device-file E2E
не закрыт.

Режим «Разработка» исправлен: запрос с `index.js` не открывает X. Android
спрашивает «на телефоне или выбранном ПК»; Python/Pyodide и переносимые CommonJS
тесты встроены в APK, работают offline в WebWorker без доступа к файлам телефона
или внешней сети. WPF и исторический Flutter Windows принимают проверки после
локального opt-in и подтверждения. API передаёт исходники/отчёты только в RAM
с TTL 10 минут, owner/device guard и отзывом; код на сервере не выполняется.
Проверено: Flutter 98 passed/2 skips, analyze 0 errors/warnings; ПК 30 passed,
WASM worker 5 passed, Kotlin matcher 3 passed, backend relay 9 passed.
Эмуляторный integration сорвался на системном AppOps/Activity; физический
повтор — при CMake из-за заполненного C. Phone integration не закрыт.
Полный Python attempt: exit 1 без итогового aggregate, последний счётчик
17 385 passed/295 failed; baseline не зелёный. Подробности:
[аудит разработки](docs/audit/DEVELOPMENT_WORKFLOW_2026_10_08.md).
Полные repository builds, зависимости и общий Companion не реализованы.
На ПК код получает права пользователя, отдельной ОС-песочницы нет.
Живой production smoke подтвердил готовность ПК, точную передачу исходников
и образца отчёта, owner/device isolation, replay, Stop и revoke. Временные
аккаунты удалены. Это подтверждение транспорта, не полного установленного
цикла генерации и исправления.

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

Проверить каталог возможностей в установленных клиентах, переключение
между устройствами и фактические provider usage для обычного разговора и задачи
с инструментом. Это отдельный установленный E2E, которого пока нет.

Проверить микрофон, озвучивание и получение/открытие файла в установленном
независимом ПК-клиенте; повторить расширенный account smoke при стабильном TLS.
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

Проверена жалоба на пустой ZIP из раздела разработки. Агент использует
`openrouter/free`; в прямом диагностическом запуске он выбрал упаковщик, но
передал веб-проект без README и тестов. Упаковщик теперь отклоняет неполный
проект до передачи на устройство, а системная подсказка и Android/Windows
сценарии объясняют, что инструмент упаковывает уже написанный код. Это не
доказывает, что модель способна завершить запрос: диагностический запуск не
выдал ZIP. Серверная проверка не запускает исходники. Изменения сервера
развёрнуты и health проходит; Android release APK собран, но не установлен.
Устройство не подключено, поэтому сообщение о переходе из «Файлы» в обычный
чат не воспроизведено. Целевые Python-тесты, Flutter (98 passed, 2 skipped),
Flutter analyze (0 errors/warnings) и ПК-клиент (30 passed) прошли. Полный
Python baseline остаётся красным; подробности и границы проверки — в
`docs/audit/DEVELOPMENT_PROJECT_QUALITY_2026_10_09.md`.
