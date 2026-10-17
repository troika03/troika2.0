# Troika Product: правила работы

## Маршрут и источники истины

- Единственная writable копия продукта: `D:\troika-product`.
- `D:\troikahermes` используется только для чтения; не писать там код, планы, runtime data или commits.
- Ожидаемая ветка: `codex/product-foundation`; remote: `https://github.com/troika03/troika2.0.git`.
- До решений и изменений читать по порядку:
  1. Этот `AGENTS.md`.
  2. `docs/Troika_1.0_Launch_Plan_Final_Updated.docx`.
  3. `docs/TROIKA_1_0_EXECUTION_TRACKER.md`.
  4. `PROJECT_MEMORY.md`.
  5. `PRODUCTIZATION_PLAN.md`.
  6. `docs/TROIKA_CAPABILITY_RESTORATION_PLAN.md`.
- DOCX задаёт scope, UX, целевые цены, разделы 1–20 и Definition of Done. Остальные документы не переопределяют решения владельца.
- Решение владельца от 2026-10-06 дополняет DOCX: порядок ремонта записан в `PRODUCTIZATION_PLAN.md`; новые готовые документы/презентации/проекты с кодом сохраняются на устройстве без постоянной серверной файловой копии. Разработка включает создание кода и разрешённые локальные проверки на ПК. Остальные требования DOCX сохраняются.
- Решение владельца от 2026-10-13: основной режим разработки пишет полный проект через API, выполняет ревью исходников моделью и исправления. Выбор устройства перед ревью не нужен. Локальный запуск тестов остаётся отдельным действием; ревью модели не означает прохождение тестов.
- Решение владельца от 2026-10-13/14: разработка доступна только в Pro; до пяти активных задач, включая до четырёх фоновых проектов и отдельный разговор. Автопилот сам планирует, выбирает дизайн, создаёт ограниченную команду API-специалистов и сообщает важные этапы голосом, когда разговор свободен. Новый автопилот использует только проверенные бесплатные модели; автоматического платного fallback нет.
- `docs/README.md` — навигация; `docs/TROIKA_FUNCTIONAL_AUDIT.md` — дефекты и доказательства; архив не является инструкцией.
- Если required path отсутствует, сообщить владельцу; не создавать замену в историческом checkout.

## Дисциплина проекта

- Перед изменениями проверить Git status. Не включать чужие незавершённые изменения в свой commit.
- Исполнять Word-план целыми разделами сверху вниз. По запросу владельца исправлять уже существующие функции, не меняя молча scope.
- Сохранять пользовательские данные, tokens, consents и protocol compatibility. Наличие Hermes в имени не означает, что файл лишний.
- `hermes_cli`, `hermes_state.py`, `hermes_constants.py`, `cli.py`, `run_agent.py`, `tui_gateway`, `ui-tui` и `hermes-android` пока нужны runtime/build или установленным клиентам. Не удалять без миграции зависимостей.
- LICENSE, copyright и upstream attribution сохранять.
- После завершённой задачи обновлять `PROJECT_MEMORY.md`: текущая правда, реально выполненные проверки, ограничения и следующий шаг. Удалять устаревшие/дублирующиеся факты; историю хранить в Git или архиве.
- Готовые изменения коммитить и отправлять: `git push origin HEAD:main`. Не делать force push.
- Не хранить secrets, prompts, личные сообщения, private files или raw media в Git, памяти проекта и диагностических отчётах.
- Изменение назначения функции, доступа, пользовательских данных или обещания продукта требует решения владельца, если текущий запрос это ещё не разрешил.

## Границы hosted product

- Нормальный облачный runtime использует только проверенный `troika-product` allowlist.
- Owner определяется сервером по device token. Каждый session/run/memory/task/artifact/workspace проверяет ownership.
- PC/host shell, произвольное выполнение кода, полный Accessibility, Kali, self-improvement и legacy DAEMON не включать в ordinary product.
- Согласованный режим «Разработка» позволяет запуск выбранных проверок проекта на ПК после локального подтверждения. Это не разрешение выполнять код на облачном host или возвращать legacy CLI режимы без ограничений. Разрешённая папка, остановка, отчёт проверки и отсутствие secrets в передаваемом контексте обязательны.
- Screen/camera требуют отдельных capability, consent, TTL, Stop и review. Raw media не сохранять.
- Важные внешние, разрушительные и privacy-sensitive действия требуют approval. Запрошенные обратимые действия малого риска выполняются без лишнего подтверждения.
- Production deployment path: `deploy/production/compose.yaml`. Старые Docker manifests — совместимость/разработка, не второй путь production.
- Пользовательские данные принадлежат аккаунту; сервер — основная копия. Production storage/backup encryption и deletion/restore остаются обязательными gates.
- Исключение с 2026-10-06: готовые новые файлы являются локальными; сервер может временно держать передачу в RAM с TTL. Старые облачные файлы не удалять автоматически. История/память/задачи пока остаются account-scoped на сервере.

## Изменение runtime

При работе с Python, gateway, tools, plugins, CLI или TUI дополнительно читать
`docs/development/RUNTIME_GUIDE.md` и relevant source. Справочник содержит
структуру, registry, loaders, slash commands, skins и extension APIs.

- Custom tools добавлять через plugin API; не хардкодить plugin-specific logic в core.
- Built-in tool регистрировать в `tools/registry.py` pattern и включать в deliberate toolset; handler возвращает JSON string.
- Config defaults добавлять в `hermes_cli/config.py`; config version повышать только для преобразования существующих данных.
- Secrets идут в `.env`; обычные настройки — в `config.yaml`. Учитывать различия CLI/config/gateway loaders.
- Все runtime paths вычислять через `get_hermes_home()`; видимые пути — через `display_hermes_home()`.
- Не ломать prompt caching: прошлую history/toolsets/system state не менять посреди разговора, кроме supported compression/invalidation.
- Не строить второй React chat/composer вместо embedded Ink TUI; supporting panels допустимы.

## Интерфейс

При изменении интерфейса Android или Windows сначала читать
`docs/development/UI_IMPLEMENTATION_GUIDE.md`: утверждённые макеты, шрифт,
цвета, голосовые состояния, этапы переноса и критерии сравнения. Запрос владельца
от 16 октября разрешает внедрение макетов. Готовность отдельных страниц
фиксировать по фактическим проверкам; наличие макета не означает готовый клиент.

## Зависимости

- Python dependency: lower и upper bound; post-1.0 `<next_major`, pre-1.0 `<0.(minor+2)`.
- Git dependencies и GitHub Actions закреплять commit SHA; CI-only pip — exact version.
- После изменения `pyproject.toml` обновлять `uv.lock`.

## Проверки

- Python запускать через `scripts/run_tests.sh`, а не напрямую через pytest.
- Текущий runner изолирует файлы в отдельных процессах; `-j` ограничивает параллелизм, args pytest идут после `--`.
- Full default suite: `scripts/run_tests.sh -j 6`. Integration/e2e/docker по умолчанию исключены; отдельный запуск требует их сервисов. Для integration markers явно передавать `-- -m integration`, иначе config может отфильтровать все tests.
- До push выполнить полный доступный набор; честно записывать failures/skips и отсутствие нужной платформы. Native Windows не доказывает POSIX PTY/systemd.
- Для клиента: `flutter test`, `flutter analyze --no-fatal-infos`, сборка затронутой платформы.
- Для dashboard: `npm run build`, `npm run lint`; для TUI: type-check, tests, build.
- Проверять behavior и invariants; не писать tests, зеркалящие изменяемые каталоги моделей или числа элементов.
- Tests не должны писать в настоящий профиль пользователя. Использовать изолированный `HERMES_HOME`.
- Сборка, unit-тест, исторический E2E и свежий E2E установленного клиента — разные уровни доказательства. Не писать «всё работает» по одному из них.
