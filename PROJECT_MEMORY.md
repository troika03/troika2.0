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
6. Никаких обещаний безлимитного agentic AI; тарифы ограничены usage/cost caps.
7. Если решение меняет назначение функции, доступы, пользовательские данные или видимое клиенту поведение, сначала запросить решение владельца продукта. Не угадывать требования.

## Известные критические проблемы baseline

- Закрытая beta имеет users/devices/tokens/entitlements/quota ledger, но ещё нет self-service регистрации, pairing UI, billing, платежей и поддержки подписок.
- Точный device context всё ещё требует отдельного opt-in, политики хранения и удаления. Его внешний reverse-geocoding вызов нужно убрать за consent/feature flag.
- PC tools включены в core toolset; `tools/pc_tool.py` и `troika_voice_daemon.py` были незакоммичены в исходной копии.
- PC/voice зависимости (`mss`, `pyautogui`, `scipy`, `pyttsx3`) не описаны в dependency manifest.
- Flutter dependencies не установлены; TUI dependencies не установлены.
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

## Ближайший порядок работы

1. Добавить создание и доставку документов/презентаций через отдельное user-owned storage, не через server filesystem или legacy push-file.
2. Расширять paired-phone slice только после явного privacy review каждой категории (calendar, files, screen, calls/SMS).
3. Вернуть проактивного личного ассистента через личные notification preferences и quiet hours, без global jobs.
2. Настроить воспроизводимую среду и минимальный зелёный CI baseline.
3. Заменить legacy response store на tenant-owned storage либо оставить endpoint выключенным до этой миграции.
4. Добавить lifecycle удаления данных: saved locations, диалоги, memory и account deletion.
5. Спроектировать subscription billing: продукты, платежные периоды, webhooks, отмена, возвраты и поддержка.

## Правила изменения проекта

- Не редактировать `D:\troikahermes`.
- Перед изменением проверять `git status`; не смешивать product/security/refactor в один коммит.
- Не добавлять secrets в Git, APK, Docker images, документацию или логи.
- Новая внешняя интеграция должна иметь: owner, failure mode, cost cap, privacy assessment, tests и feature flag.
- Новые dangerous tools не попадают в default toolset.
- При неясном продуктовом решении сначала задать владельцу продукта вопрос, а не делать предположение.
- При завершении задач обновлять этот файл: что изменилось, что проверено, что следующее.

## Текущий статус

- [x] Создана изолированная рабочая копия.
- [x] Скопирован актуальный код и WIP из исходного репозитория.
- [x] Зафиксирован план productization.
- [x] Создана отдельная продуктовая ветка.
- [x] Стабилизирован Git baseline новой копии и опубликован в новом GitHub repo.
- [x] Запущена P0 security foundation.
- [ ] Восстановлены Flutter/TUI проверки.
- [x] Реализованы beta account/device/session/entitlement/usage foundation.
