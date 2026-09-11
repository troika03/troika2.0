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
- Точный device context всё ещё требует отдельного opt-in, политики хранения и удаления. Его внешний reverse-geocoding вызов нужно убрать за consent/feature flag.
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
  памяти. Синтетическая речь через динамик ПК распознаётся нестабильно из-за
  эха; это вопрос настройки VAD/акустики, а не маршрута или авторизации.
- Проверено: product/API regression — `209 passed, 1 skipped`; Flutter — 6/6;
  `ruff`, `compileall`, `flutter analyze --no-fatal-infos` и debug APK build.
  Analyze сообщает только 31 прежнюю informational-рекомендацию. Физическую
  проверку barge-in и реальный обрыв сети ещё нужно повторить человеком; их
  failure/cancel paths уже покрыты автоматическими тестами.

## Выполнено: полезный помощник и фоновый event engine (2026-09-11)

- Добавлено tenant-owned SQLite-хранилище проектов, активного проекта, заметок,
  задач и in-app inbox. Изоляция пользователя, ownership и idempotency
  проверяются на каждом изменении.
- Product tool `troika_assistant` понимает операции с проектами, заметками,
  задачами и follow-up. Активный проект с ограниченным числом записей безопасно
  добавляется в контекст агента, поэтому просьбы «запомни в проект» переживают
  новые диалоги и перезапуск.
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
  задачи, сроки и настройки reminders/proactive/quiet hours.
- Проверено: 79 уникальных Python-тестов нового и связанного product/API среза;
  `ruff`, `py_compile`, `git diff --check`; Flutter tests 6/6; полный
  `flutter analyze --no-fatal-infos` без ошибок; debug APK собрана. Телефон в
  момент проверки не был виден через ADB, поэтому новый экран физически ещё не
  проверен.

## Ближайший порядок работы

1. Повторить на Samsung ручную проверку barge-in и реального обрыва сети;
   настроить VAD/эхоподавление по результату, не меняя security boundary.
2. Физически проверить Android-экран «Помощник» и фоновый event engine. Затем
   добавить пользовательскую политику retention/account deletion; push оставить
   выключенным до отдельной проверки push token lifecycle.
3. Реализовать безопасный `screen.snapshot` через MediaProjection. Только после
   physical E2E и threat-model review переходить к WebRTC screen assist и
   CameraX live vision.
4. Расширять paired-phone control после отдельного privacy review каждой
   capability. Просмотр экрана, управление UI, камера, микрофон, clipboard,
   календарь, файлы, звонки и SMS не объединять в одно разрешение.
5. Настроить воспроизводимую среду и минимальный зелёный CI baseline; отдельно
   обновить Android Gradle/Kotlin до будущих требований Flutter.
6. Заменить legacy response store на tenant-owned storage либо оставить endpoint
   выключенным до этой миграции.
7. Добавить lifecycle удаления данных: artifacts, saved locations, диалоги,
   memory, временные vision-данные и account deletion.
8. Спроектировать subscription billing: продукты, платежные периоды, webhooks,
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
  установлен, текстовый чат, `android_status` и голосовой цикл проверены.
  Текущий USB-туннель — только dev-транспорт: production потребует домен,
  HTTPS/WSS и нормальный pairing/login без ADB.
- Accessibility на тестовом телефоне выключен. Поэтому `status`, battery и
  network работают, но нажатия, свайпы и ввод в другие приложения потребуют
  отдельного включения Тройки в Спец. возможностях Android.
- SMS, звонки, clipboard, экран, файлы телефона и календарь намеренно не
  включены в подписочный toolset до отдельного privacy/security review.
- Нет production deployment с доменом, HTTPS, мониторингом, резервными копиями
  и процедурой восстановления.
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
- [ ] Повторно проверены человеком barge-in и реальный обрыв сети; автоматические
      revoke/kill-switch/timeout/network-failure тесты уже есть.
- [x] Реализован первый срез Фазы 2: tenant-owned проекты, заметки, задачи,
      сроки, idempotent reminders, in-app inbox, quiet hours, opt-in и лимит
      проактивных сообщений.
- [x] Android получил экран «Помощник» с inbox, причинами сообщений, проектами,
      задачами и переключателями reminders/proactive/quiet hours. Push намеренно
      не включён.
- [ ] Пройден physical tap тест сохранения artifact в выбранную папку Android
      (APK установлена, но ADB нестабилен во время UI-проверки).
- [x] Зафиксирован подробный план восстановления возможностей и безопасного
      live vision для экрана/камеры.
- [ ] Реализован и проверен `screen.snapshot` с явным MediaProjection consent.
- [ ] Реализованы и проверены WebRTC screen assist и CameraX live vision.
- [x] Фоновый event engine создаёт осмысленные follow-up по срокам, блокировкам,
      решениям и прогрессу только при opt-in и действующем device token.
- [ ] Push для проактивности не включён до retention/account deletion и проверки
      push token lifecycle; in-app доставка работает.
