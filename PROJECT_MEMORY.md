# Постоянный контекст работы — Тройка

Этот файл — долговременная память проекта. Его нужно читать перед любой новой задачей и обновлять при принятии решений, изменении приоритетов или завершении фазы.

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
- В product mode отключены legacy global jobs и phone-control, пока они не получат user/device routing и audit log.
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

- Product mode принудительно использует `troika-product` toolset, не конфиг оператора. Доступны только web/vision/image generation.
- Terminal, server files, PC/Android control и dynamic routers `find_tool`/`run_tool` недоступны пользователю подписки. Для них нужен отдельный paired companion и модель явного approval.

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
  171 API regression test (1 skipped); один legacy-тест system prompt зависит
  от глобального `~/.troika/active_project.json`, поэтому для чистого прогона
  его нужно сделать hermetic.

## Ближайший порядок работы

1. Вернуть проактивного личного ассистента через личные notification preferences и quiet hours, без global jobs.
2. Расширять paired-phone slice только после явного privacy review каждой категории (calendar, phone files, screen, calls/SMS).
3. Настроить воспроизводимую среду и минимальный зелёный CI baseline; отдельно обновить Android Gradle/Kotlin до будущих требований Flutter.
4. Заменить legacy response store на tenant-owned storage либо оставить endpoint выключенным до этой миграции.
5. Добавить lifecycle удаления данных: artifacts, saved locations, диалоги, memory и account deletion.
6. Спроектировать subscription billing: продукты, платежные периоды, webhooks, отмена, возвраты и поддержка.

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
- вызов product tools моделью;
- индивидуальная авторизация пользователя/устройства и изоляция сессии;
- разовое подтверждение действий;
- создание и личное хранение DOCX/PDF/PPTX;
- узкий безопасный набор управления привязанным Android-телефоном;
- Android debug APK, Flutter tests и анализ из предыдущего этапа.

### Что ещё не является готовым продуктом

- Нет self-service регистрации, входа, восстановления доступа и управления
  аккаунтом из приложения.
- Нет подписок, платежей, webhook-биллинга, отмен и возвратов.
- Проактивные личные сообщения/начало разговора ещё не возвращены в безопасной
  multi-user модели.
- Физический Android-телефон подключён по USB и обнаружен Android SDK, но ADB
  пока показывает `unauthorized`: на телефоне ещё не подтверждено доверие этому
  компьютеру. APK не установлен. После подтверждения нужно выполнить установку
  и `adb reverse tcp:8765 tcp:8765`; открывать сервер в Wi-Fi не требуется.
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
- [x] Настроена и реально проверена бесплатная агентная модель `openrouter/free`.
- [x] Пройден локальный product API smoke-test с token, approval и DOCX artifact.
- [ ] Пройден ручной end-to-end тест на физическом Android-телефоне (сейчас
      блокирует неподтверждённая USB-отладка).
- [ ] Готов production deployment и self-service подписочный контур.
