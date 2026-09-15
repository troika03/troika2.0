# Постоянный контекст работы — Тройка

Этот файл — долговременная память проекта. Его нужно читать перед любой новой задачей и обновлять при принятии решений, изменении приоритетов или завершении фазы.

## Маршрут новой сессии

Если новая сессия открылась в `D:\troikahermes`, это не рабочая папка продукта.
Нужно сразу перейти в `D:\troika-product`. Нельзя создавать план или вносить
изменения в `D:\troikahermes`: эта папка используется только для чтения и
сравнения со старой версией.

Перед работой читать в таком порядке:

1. `D:\troika-product\AGENTS.md` — обязательные правила работы.
2. `D:\troika-product\PROJECT_MEMORY.md` — актуальное состояние и следующий шаг.
3. `D:\troika-product\PRODUCTIZATION_PLAN.md` — общий план превращения прототипа
   в продукт.
4. `D:\troika-product\docs\TROIKA_CAPABILITY_RESTORATION_PLAN.md` — подробный
   план возврата голоса, инициативности, управления, документов и безопасного
   просмотра экрана/камеры.
5. `D:\troika-product\docs\TROIKA_CLOSED_BETA_SETUP.md` — запуск закрытой беты и
   выдача доступа устройству.

Глобальное правило маршрутизации также записано в
`C:\Users\kiqu\.codex\AGENTS.md`, поэтому оно доступно новой сессии до перехода
в рабочий репозиторий. Если пути нет, нельзя молча создавать замену в старой
папке — нужно сообщить пользователю.

## Рабочая область

- **Единственная рабочая копия для productization:** `D:\troika-product`
- **Исходная копия, которую не редактируем:** `D:\troikahermes`
- **Рабочая ветка новой копии:** `codex/product-foundation`
- **Новый GitHub remote:** `https://github.com/troika03/troika2.0.git`
- Новая копия создана 2026-09-09 из актуального `troikahermes`, включая текущие незакоммиченные наработки. Build caches исключались, Git history новой копии сохранена.
- Любые новые изменения, планы, тесты и коммиты делаем только в `D:\troika-product`.

## Цель

Превратить личный форк Hermes в безопасный подписочный продукт «Тройка»: русскоязычный персональный AI-ассистент для текста, голоса, задач и документов.

Не строить «всё сразу». Сначала public MVP, затем закрытая бета, затем платный запуск. Полный план: [PRODUCTIZATION_PLAN.md](PRODUCTIZATION_PLAN.md).

## Зафиксированные продуктовые решения

1. Базовый продукт — hosted subscription service. Пользователь не вводит ключи моделей для обычного тарифа.
2. PC control — отдельный локальный Troika Companion, а не default cloud tool.
3. Любое действие с внешним эффектом требует явного подтверждения и аудита.
4. Multi-tenancy и приватность — P0 до любых продаж.
5. Никаких общих секретов, `phone-misha`, единой памяти или публичного HTTP в production.
6. На текущем этапе пользовательские и тарифные лимиты выключены по решению
   владельца. Остаются только технические safety-границы. Перед продажами
   тарифы и cost caps проектируются отдельно; публичное обещание «безлимита»
   пока не даём.
7. Если решение меняет назначение функции, доступы, пользовательские данные или видимое клиенту поведение, сначала запросить решение владельца продукта. Не угадывать требования.

## Известные критические проблемы baseline

- Закрытая beta имеет users/devices/tokens/entitlements/quota ledger, но ещё нет self-service регистрации, pairing UI, billing, платежей и поддержки подписок.
- Точный device context требует отдельного opt-in и автоматически очищается
  через 24 часа owner-scoped retention worker. Внешний reverse-geocoding
  остаётся за feature flag и требует отдельного consent.
- PC tools включены в core toolset; `tools/pc_tool.py` и `troika_voice_daemon.py` были незакоммичены в исходной копии.
- PC/voice зависимости (`mss`, `pyautogui`, `scipy`, `pyttsx3`) не описаны в dependency manifest.
- Flutter-проверки восстановлены. TUI dependencies и TUI build ещё не проверены.
- Android debug APK собирается, но Flutter предупреждает о будущем minimum:
  Android Gradle Plugin 8.11.1 и Kotlin 2.2.20; обновлять отдельным коммитом.
- Web dashboard собирался успешно, но имеет крупный main bundle.

## Выполнено: P0 initial security foundation (2026-09-09)

- Убран public VPS URL и общий API key из Android defaults, документации и голосовых клиентов.
- Installer теперь генерирует уникальный 256-bit API key при пустом вводе; API/STT proxy отклоняют опубликованный `hermes-2024` и шаблоны.
- Голос и текст используют случайный persistent session ID на установку; статические `phone-misha` IDs убраны из маршрутов сессий и background jobs.
- `model_tools` принудительно передаёт текущий session scope каждому tool call и игнорирует подставленный моделью ID.
- Location fingerprints, list и delete изолированы по session scope; миграция старой SQLite-схемы сохраняет старые записи в scope `legacy`.
- Убрана небезопасная общая доставка reminders: создание временно честно отклоняется до реализации личного push/in-app channel.
- Проверено: 4 targeted pytest tests passed; Python compilation passed; Dart files formatted. Flutter test ещё не запускался из-за отсутствующих packages.

## Выполнено: P0 beta access foundation (2026-09-09)

- Добавлен `troika_product.access`: SQLite registry для users, devices, digest-only device tokens и ownership сессий.
- В product mode (`TROIKA_PRODUCT_AUTH_ENABLED=true`) gateway принимает только `trk_live_…` токены устройств, принудительно выводит memory scope на сервере и запрещает чужие session IDs.
- STT proxy использует тот же registry, поэтому голосовой путь не возвращается к общему API key.
- Добавлен операторский CLI: `python -m troika_product --database … provision …`; пошаговый runbook — `docs/TROIKA_CLOSED_BETA_SETUP.md`.
- В product mode отключены legacy global jobs и небезопасный single-phone
  bridge. Device-bound замена реализована отдельным этапом ниже.
- Проверено: 9 focused pytest tests passed, включая token revocation, session isolation, API integration и provisioning CLI. Android `hermes_config_test.dart`: 2/2 passed. Полный `flutter analyze` не завершился в лимит текущей среды.

## Выполнено: usage cap для закрытой beta (2026-09-09)

- Добавлены сущности `Entitlement → Usage`: у каждого beta-пользователя есть план и дневной лимит запросов; по умолчанию — 50 запросов в сутки UTC.
- Списание для `/v1/runs` и `/v1/chat/completions` атомарно в SQLite. Одновременно запущенные запросы не могут потратить один и тот же последний лимит; при исчерпании агент не запускается и получает `429`.
- Оператор может задать план и лимит при выдаче доступа или изменить их через `python -m troika_product … set-limit …`; это cost cap beta, не биллинг и не обещание безлимита.
- Запущенные runs теперь принадлежат user/device: другой токен не может читать status/SSE, подтверждать действие или останавливать чужой run.
- Legacy `/v1/responses` отключён в product mode, пока его глобальное хранилище не будет заменено tenant-owned storage; этим нельзя обойти лимит или изоляцию.
- Проверено: `14 passed` focused pytest; `compileall` и targeted `ruff check` прошли.

## Выполнено: privacy-safe audit beta (2026-09-09)

- Добавлен append-only `troika_audit_events`: user/device, event type, хэши session/run и короткие технические details. Текст переписки, API token, prompt и raw session ID отклоняются.
- Gateway фиксирует claim/denial сессии, начало запроса, исчерпание квоты, создание/stop run и approval. Доступ к raw SQLite остаётся ограничением beta: это не WORM-хранилище.
- Добавлен операторский просмотр `python -m troika_product … audit --user-id …`; тесты проверяют отсутствие raw session/run и запрет prompt в audit details.

## Выполнено: безопасный tool boundary product API (2026-09-09)

- Product mode принудительно использует `troika-product` toolset, а не конфиг
  оператора. Terminal, server files, PC control и dynamic routers
  `find_tool`/`run_tool` недоступны пользователю подписки. Документы и узкий
  device-bound Android slice добавлены позже только через отдельные безопасные
  product tools и явный approval.

## Выполнено: consent location beta (2026-09-09)

- Android по умолчанию не передаёт GPS/Wi-Fi/Bluetooth context. Android permission не равен consent: пользователь включает отдельный переключатель.
- Product API принимает device context только с `X-Troika-Device-Context-Consent: granted`; при `revoked` очищает временный контекст и пишет audit event.
- Reverse geocoding наружу выключен feature flag `TROIKA_EXTERNAL_GEOCODING_ENABLED=false`. Точные координаты не покидают сервер без будущего отдельного consent flow.

## Выполнено: безопасный paired-phone slice (2026-09-09)

- Legacy single-phone bridge не включён для product mode. Новый `ProductPhoneBridge` привязывает WebSocket и каждую команду к device ID, полученному только из действующего `trk_live_…` токена.
- Product mode возвращает лишь безопасный первый набор: status, battery, network и подтверждаемые действия открыть приложение/поиск/будильник/таймер/навигация/громкость/яркость/фонарик/камера. SMS, звонки, файлы, экран, clipboard и календарь остаются выключенными до отдельной модели данных и privacy review.
- Любое изменяющее действие требует отдельного выбора «Разрешить один раз» в Android-приложении. Consent не переносится на другие действия; API отклоняет `session`, `always` и bulk-approval для product action.
- Android обработал SSE `approval.request` и показывает понятный диалог. Если UI/канал подтверждения недоступен, действие отклоняется.
- Проверено: 35 focused Python tests; `ruff` и `compileall` прошли; Flutter test 3/3 прошёл; `flutter analyze` без ошибок (40 прежних informational suggestions).

## Выполнено: физический Android E2E и consent управления (2026-09-10)

- На Samsung Galaxy A22 (Android 33) поверх старой версии установлена актуальная
  debug APK без очистки данных. Приложение использует отдельный product runtime
  `127.0.0.1:8765` через USB `adb reverse`; старый сервер на `8642` не затронут.
- Текстовый чат физически проверен: Android отправил запрос в `/v1/runs`,
  бесплатная агентная модель ответила, результат появился в приложении.
- Исправлен отсутствовавший consent UI для phone bridge. Новый переключатель
  «Разрешить управление телефоном» по умолчанию выключен, сохраняет явное
  решение пользователя и сразу подключает или отключает WebSocket.
- Исправлена process-global cache выдачи Android tools: доступность теперь
  проверяется отдельно для текущего device ID и не может наследоваться от
  другого пользователя или старого состояния соединения.
- Реальный безопасный tool E2E пройден: модель вызвала `android_status`, телефон
  получил WebSocket-команду `status` и вернул Samsung Galaxy A22, Android 33,
  состояние Accessibility и файлового разрешения.
- Проверено: Flutter tests `4 passed`; debug APK собрана; `16 passed` focused
  product auth/phone tests. `flutter analyze` не нашёл ошибок, остались прежние
  informational замечания. Секрет токена в Git, лог и память не записывался.

## Выполнено: сохранение личных файлов на Android (2026-09-10)

- В «Файлы Тройки» добавлена заметная кнопка скачивания и пункт «Сохранить на
  телефон». Файл сначала проходит обычную проверенную загрузку artifact API,
  затем сохраняется через Android Storage Access Framework в папку и имя,
  выбранные пользователем.
- Используется `file_picker` с байтами только текущего файла. Разрешение
  `MANAGE_EXTERNAL_STORAGE` не требуется, серверный artifact и private cache
  остаются защищёнными. Ошибка сети, отмена выбора и ошибка записи показываются
  отдельно; успешное сохранение подтверждается SnackBar.
- Проверено: Flutter tests `4 passed`, `flutter analyze --no-fatal-infos`
  без ошибок (31 прежнее informational замечание), debug APK собрана и
  установлена поверх прежней версии. Полный physical tap тест сохранения пока
  не завершён: ADB нестабильно теряет подключение Samsung A22 во время UI
  действий. Сам чат/phone bridge ранее уже прошли physical E2E.

## Выполнено: личные документы DOCX/PDF/PPTX (2026-09-10)

- Старый Android-экран обращался к отсутствующему общему `/v1/files` и не
  работал. Он заменён на tenant-owned `/v1/artifacts`: список, проверенное
  скачивание и удаление доступны только владельцу `trk_live_…` токена.
- Добавлены product tools `troika_create_docx`, `troika_create_pdf` и
  `troika_create_pptx`. Файлы создаются в памяти без server filesystem tools,
  удалённых картинок и путей от модели; перед сохранением требуется разовое
  подтверждение пользователя.
- Storage использует opaque artifact ID/имя, user/device ownership, атомарную
  запись и SHA-256 integrity check. Физические пути и имена хранения не
  возвращаются модели или клиенту. Audit не хранит имя или содержимое файла.
- Product API больше не подмешивает локальный `ACTIVE_PROJECT` оператора в
  пользовательский system context: старый блок содержал имя и путь проекта и
  мог раскрыть серверные данные подписчику.
- Android умеет открыть, поделиться и после отдельного диалога удалить файл.
  Native share принимает только файлы из private cache/files приложения и
  только PDF/DOCX/PPTX через FileProvider.
- Пользовательские quota-ограничения временно выключены через
  `TROIKA_PRODUCT_QUOTAS_ENABLED=false`; quota ledger сохранён для будущего.
  Жёсткие границы HTTP и 50 MB на один артефакт остаются только защитой от
  аварии/заполнения диска.
- Добавлены `python-docx` и `reportlab`, Docker-образ получает DejaVu для
  кириллицы в PDF. `uv.lock` обновлён.
- Проверено: 35 focused Python tests, `ruff`, `compileall`; Flutter test 4/4;
  `flutter analyze --no-fatal-infos` без ошибок/предупреждений (31 прежний
  informational suggestion); debug APK успешно собран. Дополнительно прошёл
  171 API regression test (1 skipped). Зависимость API-теста от личного
  `~/.troika/active_project.json` позже устранена autouse-изоляцией.

## Выполнено: восстановлена идентичность Тройки (2026-09-10)

- В исходной копии `D:\troikahermes\docker\SOUL.md` найден старый промт
  Тройки. Из него оставлены личность, живой русский стиль, собственное мнение,
  инициативность, эмоциональные метки для голоса, честность и safety-правила;
  устаревшие внутренние инструкции, серверные пути, конкретные команды и
  перечисления инструментов убраны.
- `docker/SOUL.md` теперь содержит компактную продуктовую личность Тройки,
  без дефолтного Hermes identity. `troika_product/persona.py` даёт безопасный
  fallback, если исходный файл недоступен.
- В product mode system-prompt принудительно использует личность Тройки,
  пропускает upstream Hermes help guidance и не зависит от старого
  `HERMES_HOME/SOUL.md`. Существующий сохранённый system prompt с Hermes
  автоматически перестраивается один раз и сохраняется уже с Тройкой.
- Docker upgrade заменяет только точный дефолтный upstream `SOUL.md`; свой
  пользовательский prompt не перезаписывается. Локальный `data/test-runtime`
  также обновлён для текущего тестового сервера; runtime-файлы не коммитятся.
- Проверено: `tests/agent/test_troika_product_persona.py` и
  `tests/agent/test_system_prompt_restore.py` — 12 passed; compileall и
  `git diff --check` прошли. После перезапуска локального product API на
  `127.0.0.1:8765` живой запрос «Как тебя зовут?» вернул «Я Тройка».

## Выполнено: безопасный голосовой контур (2026-09-11)

- Product Android использует тот же origin, HTTPS/порт и tenant-owned session
  для чата и `/v1/audio/transcriptions`; отдельный legacy-порт `8643` сохранён
  только для старых установок без `trk_live_` token.
- STT worker запускается отдельным процессом только на `127.0.0.1:8766` через
  `python -m troika_product.voice_proxy`. Gateway принимает голос только после
  device-token auth и session ownership, затем сам пересылает его worker.
- Upload и ответы ограничены 10 МБ; есть 90-секундный deadline, одна локальная
  inference slot, server kill switch и повторная проверка token каждые 250 мс.
  Revoke, отключение функции, timeout и недоступный worker покрыты тестами.
- STT, Edge TTS и Android MediaPlayer работают в памяти. Временные audio-файлы
  на сервере не создаются; старый Android TTS cache удаляется при запуске.
- Транскрипты и TTS-текст не пишутся в operator logs. Product agent пишет
  `msg='<redacted>'`; тела ошибок provider не попадают в ответы и логи.
- Wake word по умолчанию выключен. Разрешения микрофона, фоновой работы,
  overlay и уведомлений запрашиваются только после отдельного opt-in. Ручной
  push-to-talk не оставляет постоянно слушающий sticky service.
- На Samsung A22 установлен актуальный debug APK. Физически пройден полный
  цикл push-to-talk → локальный faster-whisper → общая product session →
  OpenRouter → Edge TTS → последовательное воспроизведение нескольких фраз из
  памяти. Повторная проверка barge-in и потери соединения выполнена 2026-09-15;
  актуальные результаты зафиксированы ниже.
- Проверено: product/API regression — `209 passed, 1 skipped`; Flutter — 6/6;
  `ruff`, `compileall`, `flutter analyze --no-fatal-infos` и debug APK build.
  Analyze сообщает только 31 прежнюю informational-рекомендацию.

## Выполнено: полезный помощник и фоновый event engine (2026-09-13)

- Добавлено tenant-owned SQLite-хранилище проектов, активного проекта, заметок,
  задач и in-app inbox. Изоляция пользователя, ownership и idempotency
  проверяются на каждом изменении.
- Product tool `troika_assistant` понимает операции с проектами, заметками,
  задачами, явно запрошенными напоминаниями и follow-up. Активный проект с
  ограниченным числом записей безопасно добавляется в контекст агента, поэтому
  просьбы «запомни в проект» переживают новые диалоги и перезапуск.
- Напоминания создаются для задач со сроком. Проактивные сообщения разрешены
  только с конкретной причиной и связью с проектом/задачей; общие приветствия и
  проверки «как дела» отклоняются. Действия с внешним эффектом хранятся только
  как предложения и требуют отдельного подтверждения перед будущим выполнением.
- Фоновый детерминированный event engine проверяет приближение срока, блокировку
  дольше суток, ожидаемое решение и активный проект без обновлений неделю. Он
  работает только при proactive opt-in и наличии действующего device token,
  создаёт не больше трёх ожидающих сообщений и не вызывает модель для поиска
  повода.
- Доставка происходит при чтении in-app inbox и повторно проверяет opt-in,
  тихие часы и лимит не более трёх проактивных сообщений за 24 часа. Push пока
  не включён: сначала нужна пользовательская политика retention/account deletion
  и отдельная проверка push token lifecycle.
- Android получил экран «Помощник»: inbox с причиной сообщения, проекты,
  задачи, сроки и настройки reminders/proactive/quiet hours. Срок теперь
  отправляется как UTC timestamp с часовым поясом; задачи можно переводить в
  работу, блокировать, завершать и отменять. Тихие часы можно выбрать через
  системный time picker с часовым поясом Android.
- Повторная проверка 2026-09-13 устранила смешение явных reminders и
  автоматической проактивности. `reminder_schedule` работает при reminders
  opt-in даже с выключенной проактивностью и сообщает агенту, включена ли
  доставка. Фильтр отклоняет повторяющиеся и смешанные пустые приветствия.
- Проверено: `80 passed` для связанного product/API среза; `ruff`, `py_compile`
  и `git diff --check`; Flutter tests 6/6; полный
  `flutter analyze --no-fatal-infos` без ошибок и с 31 прежним
  informational-замечанием; debug APK собрана.
- Physical E2E на Samsung SM-A225F пройден 2026-09-13. Временный проект и задача
  со сроком создали детерминированное сообщение `decision_needed`: UI показал
  конкретную задачу, проект, причину «до срока меньше суток» и предупреждение,
  что действие не выполнится без отдельного подтверждения. `requires_approval`
  был `true`. После проверки fixture удалён, исходные reminders/proactive/quiet
  hours восстановлены, inbox и список проектов снова пусты.

## Реализовано: безопасная основа screen.snapshot (2026-09-13)

- Добавлено metadata-only хранилище `troika_vision_sessions`. Сессия живёт не
  более 120 секунд, привязана к аутентифицированным user/device/token и
  capability `screen.snapshot`, хранит только SHA-256 nonce и расходуется один
  раз. Чужой owner, replay, expiry и revoked token отклоняются атомарно.
- Android получил отдельный MediaProjection foreground service. Разрешение
  выдаётся только системным диалогом, живёт две минуты или один снимок,
  отображает постоянное уведомление и имеет Stop в уведомлении и экране
  «Помощник». Старый скрытый Accessibility screenshot в product toolset не
  добавлялся.
- Перед кадром локальный guard требует имя активного package и блокирует system
  permission UI, notification shade/settings, банки, кошельки, authenticator и
  password managers. Android secure-window запреты не обходятся; список package
  можно расширить локальной настройкой.
- Кадр уменьшается до 1280 по длинной стороне, максимум 1280×720 пикселей и
  600 KiB JPEG. WebSocket payload остаётся ниже 1 MiB. Сервер сверяет session
  echo, лимит base64, размеры, JPEG signature и передаёт кадр vision только в
  памяти. Raw image не попадает в tool-result, SQLite, debug logs или историю
  агента; после вызова ссылки очищаются.
- Видимый текст считается недоверенным: отдельный system prompt запрещает
  исполнять команды, QR и ссылки из изображения и раскрывать пароль, OTP,
  платёжные данные, recovery phrase или private key. Sensitive response
  закрывается policy block.
- `troika_screen_snapshot` находится только в `troika-screen-snapshot`.
  `product_screen_snapshot_enabled` и
  `product_screen_external_vision_enabled` выключены по умолчанию; tool
  появляется только при обоих flags и всё равно требует отдельного approval,
  прямо сообщающего об отправке настроенной vision-модели.
- Проверено: 108 связанных Python security/API тестов, Ruff, Flutter tests 6/6,
  Flutter analyze без ошибок (31 прежнее info), debug APK build. Physical E2E
  MediaProjection на Samsung затем пройден отдельно; детали ниже.

## Проверено: physical E2E screen.snapshot на Samsung (2026-09-13)

- На Samsung SM-A225F установлен актуальный debug APK. Физически проверены
  системный MediaProjection consent, foreground service и кнопка «Остановить»:
  Stop отзывает projection до отправки и удаляет `ScreenCaptureService`.
- Полный product API путь прошёл успешно: личный device token, WebSocket,
  `/v1/runs`, отдельный approval `once`, один JPEG-кадр, внешний opt-in
  vision provider и финальный текстовый анализ. Модель точно распознала экран
  «Помощник», его задачи и настройки; после кадра MediaProjection и capture
  service остановились автоматически.
- Physical fail-closed также подтверждён: при выключенном или отвязанном
  Accessibility guard команда вернула
  `accessibility_required_for_sensitive_screen_guard` и не передала кадр.
  После явного включения сервиса безопасный экран был обработан.
- В интеграции найден и исправлен дефект регистрации: async handler был без
  `is_async=True`, поэтому основной tool loop получал coroutine вместо JSON.
  Добавлен регрессионный тест; связанный security/API набор после исправления:
  `24 passed` (2 прежних DeprecationWarning вне нового кода).
- В `troika_vision_sessions` после успешного вызова есть только metadata и
  статус `consumed`; колонок изображения нет. Поиск в runtime-логах не нашёл
  data URL или JPEG base64. Nonce и device token в вывод не попадали.
- Physical sensitive-screen fixture с fake password node и подписью
  «Одноразовый код» вернул `sensitive_screen_blocked` до vision; session получила
  `cancelled`, raw frame и base64 в логах отсутствуют. Threat-model review
  зафиксирован в `docs/SCREEN_SNAPSHOT_THREAT_MODEL.md`.
- Фаза 3 закрыта для закрытой beta с обоими server flags по умолчанию `false`.
  Это не разрешение на `screen.live`, UI control или CameraX live: для них нужны
  отдельные threat models, consent и production transport.

## Выполнено: local account deletion lifecycle (2026-09-14)

- Product API получил `DELETE /v1/account` с обязательной точной confirmation.
  Запрос сначала переводит пользователя в crash-recoverable состояние
  `deleting`, отзывает токены всех его устройств и закрывает их WebSocket.
- После остановки активных run удаляются transient run outputs/approvals,
  SessionDB и transcript-файлы, проекты, задачи, заметки, inbox, notification
  preferences, entitlement/usage, audit, metadata vision sessions, документы и
  их opaque storage bucket. Saved location fingerprints и временный device
  context удаляются для каждого device scope.
- Очистка внешних локальных хранилищ идёт до атомарного удаления product SQLite
  rows. При сбое токены остаются отозванными, tombstone сохраняет ссылки для
  повторной очистки; gateway автоматически возобновляет её после перезапуска.
- Android показывает опасную операцию только для product token, требует ввести
  `УДАЛИТЬ`, честно предупреждает о необратимости и сохранённых на телефоне
  копиях, затем очищает token/session/consent и закрывает приложение.
- Общие Hermes `MEMORY.md/USER.md` больше не загружаются в product agent:
  они не имеют tenant ownership и удаления scope. Личный контекст закрытой beta
  берётся из owner-scoped проектов, задач, заметок и отдельной личной памяти.
- Автоматический тест удаляет данные одного пользователя во всех перечисленных
  локальных хранилищах и одновременно доказывает сохранность второго. Прошли 77
  связанных Python-тестов, Ruff, `py_compile`, `git diff --check` и Flutter
  config tests 6/6. Полный Flutter analyze не нашёл ошибок, остались 28 прежних
  info в других UI-файлах; debug APK успешно собрана. Физическая проверка этого
  экрана не выполнена: во время финальной проверки ADB-устройство не подключено.
- Production launch gate ещё не закрыт: нужны реальное удаление из
  backup/object storage и disaster-recovery rehearsal.

## Выполнено: owner-scoped экспорт и retention/backup policy (2026-09-14)

- Добавлен `GET /v1/account/export`. Endpoint не принимает `user_id`: владелец
  выводится только из действующего product token и повторно проверяется внутри
  транзакции.
- ZIP содержит профиль, устройства, безопасные token metadata, настройки,
  проекты, задачи, заметки, inbox, usage/audit metadata, диалоги, location
  context/fingerprints, vision metadata и исходные bytes всех artifacts
  владельца. Архив создаётся в памяти ответа и не сохраняется сервером.
- Credential digests, vision nonce digests, physical storage paths, server
  system prompts и private model reasoning исключены. Android получил кнопку
  экспорта и сохраняет ZIP через системный выбор файла.
- Интеграционный тест наполняет хранилища двух пользователей и проверяет весь
  ZIP первого: чужие ID, email, проекты, сообщения, location и artifact bytes
  отсутствуют.
- В `docs/DATA_RETENTION_AND_DELETION_POLICY.md` утверждены верхние сроки для
  диалогов, файлов, проектов, inbox, location, vision metadata, audit и usage.
  Там же зафиксированы требования к будущим object purge, backup deletion
  ledger и restore scrubber.
- Production object storage, selective backup deletion и disaster-recovery
  rehearsal ещё не реализованы и не проверены. Нельзя утверждать, что удаление
  из резервных копий работает.
- Проверено: 16/16 targeted export/auth tests; связанный набор дал 40 passed,
  затем 5/5 artifact tests прошли отдельным повтором после первого медленного
  импорта `python-pptx`; Ruff и compileall прошли. Flutter tests 8/8 и полный
  analyze прошли без ошибок, debug APK собрана; остались 28 прежних info в
  других UI-файлах. Дополнительно `test_api_server.py` и
  `test_api_server_runs.py`: 172 passed.

## Выполнено: owner-scoped личная память (2026-09-14)

- Добавлена таблица `troika_memories`: каждая операция повторно проверяет
  действующий token/device/account и фильтрует `user_id`, полученный только из
  серверной principal. Поддерживаются факты, предпочтения и правила общения.
- `GET/POST /v1/memories` и `PATCH/DELETE /v1/memories/{memory_id}` дают
  просмотр, создание, исправление и удаление. Запросы не принимают `user_id`,
  а чужой ID возвращает `404`.
- Product agent по-прежнему запускается с `skip_memory=True` для глобальных
  Hermes-файлов. В ephemeral prompt добавляются не более 12 последних записей
  только текущего владельца; блок явно помечен как недоверенные данные.
- `troika_assistant` получил явные memory actions. Сохранять долговременную
  память разрешено только по просьбе/подтверждению пользователя; authentication
  и payment secrets запрещены.
- Android получил экран «Помощник → Память» с empty/loading/error states,
  созданием, правкой и подтверждаемым удалением. Память включена в ZIP-экспорт
  и локальное удаление аккаунта.
- Тесты с двумя пользователями проверяют store, HTTP, prompt, tool, экспорт и
  account deletion. Чужую запись нельзя увидеть, исправить или удалить; её
  заголовок и текст отсутствуют в prompt и ZIP другого владельца.
- Retention памяти ограничен 730 днями после изменения и применяется локальным
  worker. Production object purge, backup deletion ledger и restore scrubber
  ещё не реализованы и не проверены. Удаление из резервных копий не заявляется.
- Проверено: связанный Python-срез — 265 passed, 1 skipped; Ruff и compileall
  прошли. Flutter tests — 9/9, analyze — без ошибок и с 28 прежними info в
  других UI-файлах, debug APK собрана.

## Выполнено: автоматический retention локальных данных (2026-09-15)

- `troika_product.retention.RetentionWorker` применяет утверждённые сроки к
  текущим product SQLite, SessionDB, локальным transcripts/artifacts, transient
  device context и location fingerprints. Решения принимаются по переданному
  времени; dry-run использует те же выборки без изменения данных.
- Gateway запускает owner-scoped worker при старте и затем каждые шесть часов.
  Есть флаги enabled/dry-run/interval и операторская команда
  `python -m troika_product ... retention`; отчёт содержит только счётчики
  категорий и коды ошибок без user ID и содержимого.
- Просроченный token digest удаляется. У отозванного устройства очищаются имя
  и platform, а непрозрачный ID остаётся только как внешний ключ к данным с
  более длинным сроком. Миграция добавляет `revoked_at` без потери старых rows.
- Строгий artifact purge считает удаление успешным только после удаления
  локальных bytes. Session metadata, SessionDB row и transcript очищаются до
  удаления owner mapping. Все SQL-изменения содержат owner scope.
- Тест с управляемым временем сначала подтверждает неизменность dry-run, затем
  очищает просроченные данные одного владельца и сохраняет свежие данные этого
  владельца и просроченные данные второго. Отдельно проверен lifecycle фоновой
  задачи gateway.
- Проверено: product/retention Python-срез — 98 passed; общие API server tests —
  172 passed; retention tests — 3/3. Ruff, compileall и `git diff --check`
  прошли. Flutter tests — 9/9, analyze — без ошибок и с 28 прежними info.
- Production object storage и backup pipeline не подключены. Version-aware
  object purge, deletion ledger, restore scrubber и DR rehearsal не реализованы
  и не проверены; удаление из резервных копий не заявляется.

## Проверено: Samsung barge-in и потеря соединения (2026-09-15)

- На Samsung SM-A225F product-приложение прошло повторный голосовой сценарий с
  локальным authenticated gateway и отдельным приватным STT worker. Во время
  активного TTS русская тестовая реплика дала события `BargeIn calibrated` и
  `barge-in detected`, то есть сервис выполнил штатный путь перебивания.
- Удаление `adb reverse` не завершило уже открытый SSE-поток, поэтому активное
  соединение дополнительно оборвано остановкой тестового gateway. Android
  показал error state без зависания; после запуска gateway следующий запрос в
  том же приложении получил обычный ответ.
- Тестовые gateway/STT процессы и USB reverse остановлены, громкость телефона
  возвращена к исходному уровню. Экран удаления не открывался, настоящий
  аккаунт не удалялся.

## Ближайший порядок работы

1. После выбора production storage добавить object purge, deletion ledger,
   restore scrubber и disaster-recovery rehearsal.
2. Перед реализацией WebRTC screen assist отдельно спроектировать signaling,
   TURN, hardware-backed device keys, heartbeat/revoke и изолированный vision
   worker. Закрытая snapshot beta не расширяет разрешение до live vision.
3. Расширять paired-phone control после отдельного privacy review каждой
   capability. Просмотр экрана, управление UI, камера, микрофон, clipboard,
   календарь, файлы, звонки и SMS не объединять в одно разрешение.
4. Настроить воспроизводимую среду и минимальный зелёный CI baseline; отдельно
   обновить Android Gradle/Kotlin до будущих требований Flutter.
5. Заменить legacy response store на tenant-owned storage либо оставить endpoint
   выключенным до этой миграции.
6. Спроектировать subscription billing: продукты, платежные периоды, webhooks,
   отмена, возвраты и поддержка.

## Проверенный рабочий срез и бесплатная модель (2026-09-10)

- Для новой копии создан отдельный локальный runtime:
  `D:\troika-product\data\test-runtime`. Он игнорируется Git и не использует
  профиль старой Тройки. Секреты в репозиторий не добавлялись.
- Основная тестовая модель переключена на `openrouter/free` через OpenRouter.
  Это бесплатный router, который при передаче tools отбирает совместимые с
  tool calling модели. В конфиге принудительно включён agent tool-use и
  безопасный `troika-product` toolset. Воспроизводимый вариант без секретов:
  `config.troika-product-test.yaml.example`.
- Реальный прямой smoke-test ядра завершён: модель сама вызвала
  `troika_create_docx`, получила результат инструмента и сформировала финальный
  ответ. Это подтверждает не только чат, но и агентный tool loop.
- Реальный end-to-end smoke-test product API завершён на локальном
  `127.0.0.1:8765`: health → выдача индивидуального `trk_live_…` токена →
  `/v1/runs` → разовое approval → создание DOCX → появление файла в личном
  `/v1/artifacts`. Итог: `completed`, создан DOCX размером 36 804 байта.
- Порт `8642` уже занят старой локальной Тройкой (`pythonw cli.py --gateway`,
  процесс работает с 2026-09-07). Он не останавливался и не изменялся. Новая
  копия использует порт `8765`, чтобы версии не конфликтовали.
- Пользовательские/тарифные квоты в тестовом product runtime выключены.
  Технические ограничения размера запроса/файла и проверки безопасности
  сохранены.

### Что сейчас действительно работает

- backend и health endpoint;
- бесплатный агентный ответ через OpenRouter;
- общий безопасный voice route: push-to-talk, локальный STT и потоковый Edge
  TTS в памяти;
- вызов product tools моделью;
- индивидуальная авторизация пользователя/устройства и изоляция сессии;
- разовое подтверждение действий;
- создание и личное хранение DOCX/PDF/PPTX;
- узкий безопасный набор управления привязанным Android-телефоном;
- личные notification preferences, quiet hours, проекты, задачи, очередь,
  in-app доставка и Android-экран «Помощник»;
- owner-scoped личная память с Android CRUD и безопасным prompt context;
- owner-scoped ZIP-экспорт серверных данных и artifacts через API и Android;
- Android debug APK, Flutter tests и анализ из предыдущего этапа.

### Что ещё не является готовым продуктом

- Нет self-service регистрации, входа, восстановления доступа и управления
  аккаунтом из приложения.
- Нет подписок, платежей, webhook-биллинга, отмен и возвратов.
- Проактивность работает через связанный с проектами/задачами in-app inbox и
  безопасный фоновый event engine. Push ещё не реализован до завершения retention
  и push token lifecycle.
- Зрение с камеры или экрана в реальном времени ещё не реализовано. Есть старые
  screenshot/read-screen заготовки и безопасное открытие camera app, но они не
  дают product live vision. Целевая архитектура, consent и security gates
  зафиксированы в `docs/TROIKA_CAPABILITY_RESTORATION_PLAN.md`.
- Физический Android-телефон успешно авторизован через ADB; актуальный debug APK
  установлен, текстовый чат, `android_status`, голосовой цикл, barge-in и
  восстановление после потери соединения проверены.
  Текущий USB-туннель — только dev-транспорт: production потребует домен,
  HTTPS/WSS и нормальный pairing/login без ADB.
- Accessibility на тестовом телефоне выключен. Поэтому `status`, battery и
  network работают, но нажатия, свайпы и ввод в другие приложения потребуют
  отдельного включения Тройки в Спец. возможностях Android.
- SMS, звонки, clipboard, экран, файлы телефона и календарь намеренно не
  включены в подписочный toolset до отдельного privacy/security review.
- Нет production deployment с доменом, HTTPS, мониторингом, резервными копиями
  и процедурой восстановления. Удаление из backup/object storage не
  реализовано и не проверено.
- TUI checks и полностью зелёный hermetic CI baseline ещё не восстановлены.
- Бесплатный OpenRouter router подходит для разработки и demo, но не даёт
  production SLA: доступны ограниченные запросы, плавающая модель и возможны
  задержки/временная недоступность.

## Правила изменения проекта

- Не редактировать `D:\troikahermes`.
- Перед изменением проверять `git status`; не смешивать product/security/refactor в один коммит.
- Не добавлять secrets в Git, APK, Docker images, документацию или логи.
- Новая внешняя интеграция должна иметь: owner, failure mode, cost cap, privacy assessment, tests и feature flag.
- Новые dangerous tools не попадают в default toolset.
- При неясном продуктовом решении сначала задать владельцу продукта вопрос, а не делать предположение.
- В начале каждой сессии читать этот файл. После каждой завершённой задачи до
  финального ответа обновлять: что изменилось, что реально проверено, что ещё
  не готово и какой следующий безопасный шаг. Это актуальный срез, а не
  бесконечный журнал: устаревшее, заменённое, повторяющееся и противоречивое
  сразу удалять или переписывать. Секреты и содержимое личных сообщений здесь
  не хранить.

## Текущий статус

- [x] Создана изолированная рабочая копия.
- [x] Скопирован актуальный код и WIP из исходного репозитория.
- [x] Зафиксирован план productization.
- [x] Создана отдельная продуктовая ветка.
- [x] Стабилизирован Git baseline новой копии и опубликован в новом GitHub repo.
- [x] Запущена P0 security foundation.
- [x] Восстановлены Flutter test/analyze и Android debug build.
- [ ] Восстановлены TUI проверки.
- [x] Реализованы beta account/device/session/entitlement/usage foundation.
- [x] Возвращены безопасные личные DOCX/PDF/PPTX и рабочий Android files UI.
- [x] Добавлено сохранение artifact-файлов на телефон через системный выбор
      папки.
- [x] Настроена и реально проверена бесплатная агентная модель `openrouter/free`.
- [x] Пройден локальный product API smoke-test с token, approval и DOCX artifact.
- [x] Пройден ручной end-to-end тест на физическом Android-телефоне: текстовый
      чат, device-token auth, WebSocket и `android_status`.
- [x] Пройден физический голосовой E2E: push-to-talk, tenant-owned session,
      локальный STT, модель и потоковый TTS без audio-файлов.
- [x] Повторно проверены на Samsung barge-in и реальный обрыв активного
      соединения с последующим успешным запросом после восстановления gateway.
- [x] Реализован первый срез Фазы 2: tenant-owned проекты, заметки, задачи,
      сроки, idempotent reminders, in-app inbox, quiet hours, opt-in и лимит
      проактивных сообщений.
- [x] Android получил экран «Помощник» с inbox, причинами сообщений, проектами,
      задачами, изменением статуса и настройкой времени reminders/proactive/quiet
      hours. Push намеренно не включён.
- [x] Пройден physical E2E Android-экрана «Помощник» и фонового event engine:
      конкретный `decision_needed`, причина, проект/задача и обязательный
      approval показаны на Samsung.
- [ ] Пройден physical tap тест сохранения artifact в выбранную папку Android
      (APK установлена, но ADB нестабилен во время UI-проверки).
- [x] Зафиксирован подробный план восстановления возможностей и безопасного
      live vision для экрана/камеры.
- [x] Реализована default-off основа `screen.snapshot` с одноразовой
      user/device session, MediaProjection consent, Stop, size cap, policy guard
      и отдельным toolset.
- [x] Пройден physical E2E `screen.snapshot` на Samsung: реальный consent,
      Stop, fail-closed Accessibility guard, один кадр и opt-in vision provider.
- [x] Пройден physical sensitive-screen fixture и зафиксирован threat-model
      review для одноразового snapshot.
- [ ] Реализованы и проверены WebRTC screen assist и CameraX live vision.
- [x] Фоновый event engine создаёт осмысленные follow-up по срокам, блокировкам,
      решениям и прогрессу только при opt-in и действующем device token.
- [x] Добавлен owner-scoped ZIP-экспорт данных с Android save flow и тестом,
      доказывающим отсутствие данных второго пользователя.
- [x] Определены retention-периоды и политика будущего удаления из
      backup/object storage с явной отметкой о нереализованных гарантиях.
- [x] Добавлена owner-scoped личная память: API, Android CRUD, prompt context,
      tool actions, экспорт, account deletion и cross-tenant тесты.
- [x] Реализован и проверен автоматический owner-scoped retention worker для
      текущих локальных SQLite/filesystem stores, включая dry-run.
- [ ] Реализованы и проверены production object purge, backup deletion ledger,
      restore scrubber и disaster-recovery rehearsal.
- [ ] Push для проактивности не включён до проверки push token lifecycle;
      in-app доставка работает.
