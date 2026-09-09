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

## Известные критические проблемы baseline

- Не реализованы учётные записи, pairing устройств, entitlement и quota ledger: один API-key пока не является моделью подписок.
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

## Ближайший порядок работы

1. Провести чистую инвентаризацию текущих локальных изменений и разделить их на коммиты/удаление.
2. Настроить воспроизводимую среду и минимальный зелёный CI baseline.
3. Спроектировать `User → Device → Session → Entitlement → Usage` и user-scoped storage до реализации UI/billing.
4. Убрать опасные/персональные defaults из public configuration.
5. Реализовать auth, tenant isolation, quota ledger, audit log и privacy controls.
6. Затем стабилизировать Android core loop и закрытую beta.

## Правила изменения проекта

- Не редактировать `D:\troikahermes`.
- Перед изменением проверять `git status`; не смешивать product/security/refactor в один коммит.
- Не добавлять secrets в Git, APK, Docker images, документацию или логи.
- Новая внешняя интеграция должна иметь: owner, failure mode, cost cap, privacy assessment, tests и feature flag.
- Новые dangerous tools не попадают в default toolset.
- При завершении задач обновлять этот файл: что изменилось, что проверено, что следующее.

## Текущий статус

- [x] Создана изолированная рабочая копия.
- [x] Скопирован актуальный код и WIP из исходного репозитория.
- [x] Зафиксирован план productization.
- [x] Создана отдельная продуктовая ветка.
- [ ] Стабилизирован Git baseline новой копии и опубликован в новом GitHub repo.
- [x] Запущена P0 security foundation.
- [ ] Восстановлены Flutter/TUI проверки.
- [ ] Спроектированы и реализованы account/device/pairing foundation.
