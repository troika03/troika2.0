# Troika: что работает и что не работает

Проверка 2026-10-05. Checkout `codex/product-foundation`, исходный HEAD `bf92c78`;
production image тоже `bf92c78`. Цель — проверить факты, очистить документацию
и перечислить ограничения. Ревизия документации не является исправлением
всех обнаруженных дефектов или новым production rollout.

## Что сейчас недоступно или сломано

| Приоритет | Функция/контур | Наблюдение | Доказательство и следующий шаг |
|---|---|---|---|
| P0 | Полное чтение сайтов | С 2026-10-06 поиск использует SearXNG; search/research доступны. Полное извлечение страниц не подключено; research использует snippets. | Реальные русские/английские search и wrapper smoke прошли; authenticated chat вернул ссылки. Подключить чтение страниц и проверить его отдельно. |
| P0 | Android background voice после expiry | Native service читает сохранённый access token; native refresh endpoint flow отсутствует. Открытый Flutter-клиент имеет свой refresh flow. | `HermesListenerService.kt`, `SecureTokenStore.kt`, `account_service.dart`. Реализовать service refresh и тест длительного screen-off/expiry/revoke. |
| P0 | Новые Android reminder notifications на текущем телефоне | Установлена прежняя APK, не содержащая последнюю доставку через AlarmManager. Backend reminder snapshot работает. | SHA-256 установленной APK отличается от текущего reminder release APK. Нужны update и device delivery E2E; серверная запись не доказывает сигнал телефона. |
| P1 | Web dashboard lint | Build проходит, lint завершается ошибкой: 22 errors, 4 warnings. | Hooks/refs/static components/refresh exports; `npm run lint` в `web`. Это проблемы качества/CI; не утверждение, что каждая страница падает. |
| P1 | TUI lint | Build/typecheck проходят; lint падает: 30 errors, 92 warnings. | Style/control-regex и другие диагностики; `npm run lint` в `ui-tui`. Отдельный timeout test прошёл при повторе. |
| P1 | Общий Python baseline на native Windows | Полный default test suite не зелёный; есть path/newline/permissions/asyncio/shell/integration failures. | Полный перечень ниже. Разобрать каждый сбой; не выдавать upstream/Linux-specific failures за доказанную поломку клиентского сценария. |
| Ограничение платформы | Dashboard embedded PTY chat на native Windows | `pty_bridge.py` требует fcntl/termios/POSIX; ConPTY implementation отсутствует. | Работает только supported POSIX/WSL путь. Flutter Windows — отдельный клиент и успешно собирается. |
| P1, legacy docs | Skills Hub/LLM documentation generation на Windows | Website prebuild запускает `python3`, exit 9009; пишет пустой skills.json и не генерирует свежий llms.txt. | Это inherited developer website, не sales site. Исправить Python discovery или запускать supported build environment. |

## Ещё не реализовано

- Восстановление пароля и подтверждение почты.
- Реальная оплата Free/Plus/Pro: credits/token-cost ledger, checkout, idempotent webhooks, отмена, past_due/grace и возвраты.
- Полноценные сайт/кабинет/download/activation, live support/status и утверждённые legal страницы. Сейчас account form на sales site — demo.
- FCM/push и доставка на телефон без заранее синхронизированного snapshot; Windows background reminders.
- Production Postgres/object storage/queue, проверенные encrypted backup/restore, object-version purge/deletion ledger/restore scrubber.
- Полная offline-first SQLite/очередь изменений/change feed/tombstones/conflict resolution. Есть server account stores и polling.
- Полный единый Agent Runtime single/delegate/parallel/durable/verified. Текущий completion guard проверяет известные claims/receipts, не любую семантику.
- Безопасный импорт и полноценное редактирование существующих DOCX/PDF/PPTX/XLSX; XLSX с формулами/пересчётом.
- Live WebRTC screen, live CameraX, полный Accessibility и автономный PC Companion. Это default-off будущий scope, не обычные кнопки продукта.
- Production metrics/alerts/cost dashboards, signed installer/update path, fresh-machine E2E и закрытая beta с final launch gates.

Создание HTML artifact — скачиваемый файл. Публичный hosting этим действием
не выполняется. Local DOCX/PPTX constructor — работа по введённой структуре,
не автоматическое исследование и генерация произвольного отчёта без модели.

## Подтверждено в этой ревизии

| Проверка | Результат | Что она не доказывает |
|---|---|---|
| Production containers/HTTPS health | API healthy; API/STT running; public health 200. | Качество каждого пользовательского сценария. |
| Auth/account live smoke | Register, login с общей home session, refresh rotation, список устройств и subscription status прошли. | Recovery, email verification, paid billing. |
| Memory live smoke | Create/list/update прошли на отдельном временном аккаунте. | Полный backup lifecycle и все возможные concurrency conflicts. |
| Agent/tools live smoke | Один Run создал DOCX и HTML, owner-auth downloads вернули 36 760 и 175 bytes; DOCX содержит `word/document.xml`. | Визуальное качество произвольного отчёта/презентации и публичную публикацию HTML. |
| Reminder live smoke | Opt-in preferences и относительное напоминание дали один reminder в snapshot. | Физический сигнал старой APK, offline sync и Windows delivery. |
| Account export/delete live smoke | ZIP signature проверена; тестовый аккаунт удалён, `200/deleted`. | Удаление будущих backups/object stores. |
| Flutter | 50 passed, 2 endpoint-define-only skips; затем все 14 config tests прошли с hosted endpoint define. Analyze: 0 errors/warnings, 20 info. | Mic/audio quality, Bluetooth/OEM/standby и real full voice E2E. |
| Android и Windows | Оба debug builds прошли. | Signed release installer, fresh machine или установленную актуальную APK. |
| Web dashboard | TypeScript/build прошли; bundle около 1.59 MB, lint не зелёный. | Browser E2E всех страниц и Windows PTY. |
| TUI | Type-check/build прошли. Основной run: 853 passed, 8 skipped, 1 timeout; отдельный повтор проблемного файла: 4 passed. | Полностью чистый массовый run при текущей нагрузке; timeout не доказал cursor regression. |
| Discord voice integration | Отдельный запуск с `-- -m integration`: 34 passed. | Android/Windows STT-agent-TTS и фоновую авторизацию. |
| Inherited developer website | Docusaurus English/Chinese build прошёл, но prebuild Python generators вернули 9009; Skills Hub пустой и есть broken-anchor warnings. | Рабочий Skills Hub/LLM export или готовность sales site. |
| Samsung SM-A225F | APK 1.0.0 запускается; Home/Файлы отображаются; mic показывает «Слушаю». Данные и APK не заменялись. | Распознавание человеческой речи, agent/TTS/barge-in, screen-off, exact alarm или сохранение Office-файла на устройство. |
| Все tracked Python sources | 2003 файла разобраны AST без syntax errors. | Отсутствие runtime/logic/platform errors. |
| JSON | 49 strict JSON прошли после удаления устаревшей tool matrix; 3 tsconfig — JSONC с comments, не ошибки JSON. Web tsconfigs проверены build/typecheck. | Все необязательные интеграции. |

Два временных аккаунта для server probes удалены через account API. В итоговые
результаты включён corrected smoke с реальными `/v1/sessions` и `data` списком
artifacts. Первый диагностический probe использовал неверный route/key;
его 404/нулевой count не являются дефектами продукта.

## SearXNG и видимые источники — 2026-10-07

Единственный search provider product-профиля — SearXNG; альтернативные
provider plugins отключены в config, их upstream source не удалён. API image
`troika-production:web-sources-20261007` собран из изолированного дерева этих
изменений и развёрнут; STT остаётся `bf92c78`. SearXNG private, healthy,
закреплён digest; stdout/stderr сервиса не сохраняются Docker.

Flutter Home/Text/Windows compact показывают свёрнутую строку «Найдено N
страниц» и раскрываемые ссылки со статусом. Значки — локальные инициалы домена,
без автоматических запросов favicon к сторонним сайтам. Search snippets
не считаются прочитанной страницей. Полное чтение страниц пока не подключено;
его неуспех отображается отдельно. Native background voice восстанавливает
источники из истории при открытии клиента; live SSE относится к foreground.

Проверки из чистого snapshot: 48 Python tests (15 источников, 26 API runs,
7 research), 54 Flutter tests и 2 endpoint-only skips; отдельный render preview
прошёл. Проверены свёрнутое/раскрытое состояние и ширина 320 px. Analyzer не
имеет errors/warnings, 20 унаследованных infos. Android release APK и Windows
release собираются с production endpoint без credentials.

Живой authenticated run вернул 10 источников через SSE; после загрузки истории
они сохранились. Другой аккаунт получил 404 на run и 403 на историю. Все
временные аккаунты удалены. Это server/widget/build evidence; физический
источниковый E2E установленной APK не проводился. На Samsung уже новая APK
другой сессии; отдельный клиент источников не установлен поверх неё.

Полный доступный default набор покрыт тремя журналами с возобновлением после
прерывания: 1236 уникальных file runs, 24735 passed и 412 failed по распознанным
per-file counters; 148 неуспешных file runs, у 41 нет счётчика failed tests.
Baseline остаётся красным: Windows/POSIX несовместимость, отсутствующие
providers/dependencies, collection/timeouts и ограничения среды. Часть первого
прогона выполнялась до переноса TEMP на D: при заполнении C:. Другие сессии
одновременно меняли рабочее дерево; этот прогон не является clean-commit
baseline. Изменённый runtime проверен отдельно чистым snapshot и live smoke.
Integration/e2e/docker не включены в default suite. Старый audit baseline ниже
сохранён как результат проверки 5 октября и не подменяет этот повтор.

## Полный Python прогон и дополнительные проверки

Проверены все **1233 default test files** через `scripts/run_tests.sh` с
`-j 6`, `--file-timeout 180`, `-- --tb=short`. Первый прогон завершился с exit 1,
но журнал сохранил 938 file results без final summary; оставшиеся 295 файлов
повторены с прямым сохранением stdout/stderr. Coverage составлен из двух журналов,
без двойного подсчёта файлов. Некорректные 0% первого runner не означают 0 tests.
Внешний launcher повторного запуска получил `KeyboardInterrupt`; дочерний runner
сохранил final summary `100% complete` и все 295 file results. Причина прерывания
launcher не установлена; coverage опирается на сохранённые результаты.

Per-file результаты: **25032 passed, 407 failed,
205 skipped, 1 errors, 0 xfailed**.
Неуспешных file runs: **125**; часть не собрала ни одного test.
Это красный baseline. Имена и counters всех файлов находятся в
[PYTHON_CHECKS.tsv](audit/PYTHON_CHECKS.tsv), полный список неуспешных файлов и
сохранившиеся test identifiers — в [PYTHON_FAILURES.md](audit/PYTHON_FAILURES.md).

Для product/auth/assistant/phone/completion/owner stores и product tools в выбранных
22 файлах: 190 passed, 1 failed,
0 skipped, 0 errors. Один failure product positioning
был вызван сокращённым README в этой ревизии. Promise/audience восстановлены;
целевой повтор дал **2 passed**. Исходный failure сохранён в counters для прозрачности,
но не является незакрытой поломкой финального README.

Отдельный Discord voice integration с явным `-- -m integration`: **34 passed**.
Ни обычный default runner, ни этот integration не заменяют physical Android voice E2E.


## Границы проверки

Инвентаризированы все versioned paths и корневые каталоги, разобраны все
Python sources и strict JSON, выполнены доступные builds/tests и живой server
smoke. Каждый файл не объявляется семантически рабочим только по наличию
в дереве. Integration/e2e/docker не входят в default suite и требуют своей среды;
`pyproject.toml` дополнительно задаёт `-m not integration`, поэтому явный путь
к integration file без `-- -m integration` может выполнить 0 tests.
`test_voice_channel_flow.py` проверяет Discord crypto/audio, а не полный
Android/Windows STT-agent-TTS сценарий;
сборка нового Docker image в этой ревизии не выполнялась.

Непроверены полный человеческий voice E2E, Bluetooth/standby/OEM/expiry,
physical reminder delivery, screen/privacy sensitive actions, visual QA всех
DOCX/PDF/PPTX, вся optional-skills/plugin matrix и production recovery.
[Карта](REPOSITORY_MAP.md) и [перечень файлов](audit/REPOSITORY_FILES.tsv)
показывают coverage, не подменяя эти проверки.

## Порядок устранения

1. Подключить полное чтение страниц; поиск через SearXNG уже проверен 2026-10-06.
2. Закрыть native Android refresh и выровнять установленную APK; проверить notification permissions/exact alarms/expiry/voice.
3. Разобрать дефекты из полного Python списка и dashboard/TUI lint; платформенные ограничения документировать отдельно.
4. Проверить реальные открытие/сохранение Office artifacts и доставку reminder на устройстве.
5. Вернуться к Word-плану: завершить раздел 7, затем 8–20. Не открывать продажи по отдельным smokes.
