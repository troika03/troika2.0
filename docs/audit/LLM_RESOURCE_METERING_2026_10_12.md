# Учёт текстовых вызовов модели: 12 октября 2026

Продолжение [ядра ledger](RESOURCE_LEDGER_2026_10_12.md) и согласованной
[политики подписки](../TROIKA_SUBSCRIPTION_ECONOMICS.md). Это часть второго
этапа раздела 8, а не завершённый billing или переход production на новые лимиты.

## Реализовано

`agent/provider_metering.py` добавляет общий необязательный перехват вызова
провайдера. Основной runtime и центральный auxiliary router используют его
для синхронного и асинхронного Chat Completions, включая streaming. Без
активного учёта фабрики возвращают исходные клиенты; прежние SDK retries
в этом режиме сохраняются. В учитываемом режиме скрытые SDK retries отключены.

`troika_product/llm_metering.py` связывает перехват с серверным owner/device/token,
общим ResourceLedger и каталогом версионированных all-in цен в рублях. До
отправки резервируется консервативная оценка полного сериализованного контекста
и ограниченного ответа. После подтверждённого usage списывается только
фактический расход; возвращается неиспользованный резерв. Оценка по UTF-8
байтам с запасом не является точным tokenizer или гарантией provider bill.
Превышение оценки останавливает вызовы и требует сверки.

Учитывается весь provider input, включая системный контекст, память, историю,
схемы инструментов и результаты tools. Cached input и cache write отделены
от обычного input. Reasoning входит в output и не списывается второй раз.
В ledger сохраняются числовые счётчики и версия цены, без содержимого prompts.

Счётчик не принимает стоимость, остаток, owner или Run ID из тела запроса.
Оба hosted execution path — chat и `/v1/runs` — привязывают scope до создания
агента. API workers, background title/review и существующие delegate workers
переносят текущий scope через ContextVars. Это не реализация новой архитектуры
workers, ограничения concurrency или проверка всего Worker Runtime.

Неизвестная цена, неподдерживаемый native transport, мультимодальный input,
несколько вариантов ответа, подмена параметров через extra_body и внутренние
SDK retries блокируют учитываемую отправку. Изменённый scope и отозванный
principal не могут списывать ресурс другого аккаунта. Premium model требует
разрешения тарифа; докупка ресурса не заменяет это разрешение.
Вспомогательные клиенты кешируются только внутри текущего Run; глобальный
legacy cache не получает клиенты с привязанным аккаунтом. Итоговый запрос
после лимита итераций также проходит через учитываемый request boundary.

Обрыв, отсутствующий usage, некорректные счётчики и watchdog timeout сохраняют
отправленный резерв. Повторы, fallback и продолжение частичного ответа не
запускают новые вызовы в таком Run. Закрытие потока без final usage также
останавливает дальнейшие вызовы. Поздний настоящий receipt может завершить
исходную операцию; автоматическая сверка и компенсация ещё не реализованы.

## Проверки

Новые проверки используют настоящий SQLite ledger и поддельный network client;
платные запросы и настоящий профиль пользователя не используются. Проверены
полный input приветствия, cache/write/reasoning, общий расход нескольких вызовов,
reservations до network, ошибки/Stop, native route, premium, revoke, scope cleanup,
sync/async streaming, вспомогательная фабрика, перенос контекста в worker,
основные runtime threads и оба hosted execution path. Локальный HTTP test
подтверждает, что body-поля owner, Run ID и resource amount не влияют на учёт.

Целевые проверки: первоначальные 46 adapter, 12 runtime/hosted и 176 legacy
auxiliary tests дали 234 passed, 0 failed, exit 0. После добавления проверки
скрытых операторских настроек итоговый набор proposed Git tree без чужого WIP
дал 497 passed, 0 failed, exit 0 в девяти файлах. Он включает 46 adapter,
13 runtime/hosted, 176 auxiliary, 31 ledger, 25 auth, 26 runs, 5 client lifecycle,
40 streaming и 135 delegate checks. Все девять файлов имеют успешный результат;
индикатор процента runner для путей вложенного snapshot показал 0% ошибочно.
Проверены итоговый ответ после лимита итераций и изоляция cache двух аккаунтов.
Ruff check/format нового кода и compileall затронутых Python modules passed.

Общий default Python обнаружил 1 246 файлов. Запуск завершил записи результатов
940 файлов, после чего процесса runner уже не было, итоговый summary и exit
не записались. Последний частичный счётчик: 18 462 passed, 306 failed. Оставшиеся
306 файлов проверены отдельно: полный summary 6 894 passed, 124 failed,
100% complete за 302,9 секунды, -j 6, file timeout 90 секунд. Один файл остатка
не выполнил тесты. Обёртка получила KeyboardInterrupt после записи полного
summary; успешный exit остатка не заявляется. Объединение записей покрывает
все default file paths, включая неуспешные/недоступные файлы. Это два запуска
общего checkout, не один зелёный прогон изолированного commit.

Из 264 показанных failure identifiers первого запуска 257 совпадают с прежними
логами. Остальные не объявляются автоматически прежними. Найденная регрессия
от нового раздела defaults — один флаг платформы в обычном экране параметров —
исправлена: operator-owned platforms исключены из assistant preferences.
Восемь schema tests прошли отдельно, новая проверка включена в 497 checks.
Другой отказ web server связан с Windows profile deletion; оставшиеся
неразобранные failures не закрывались этой задачей. Общий baseline красный.

## Ограничения и следующий шаг

Config: `platforms.api_server.extra.product_resource_text_enabled` по умолчанию
false, `product_resource_prices` — пустой server-owned mapping. Каждая запись
модели задаёт provider (OpenRouter по умолчанию), version и input/output/cache-read/cache-write цены
за миллион токенов; output bound и premium задаются сервером. Публичного API
редактирования каталога нет. Production config, provider/model, entitlements
и установленный клиент этим этапом не менялись. Прежний дневной guard действует.

Флаг предназначен для изолированных испытаний текста. Не включать его как
месячный продуктовый cost engine до подключения STT/TTS, native/vision и
других прямых paid APIs/tools. Следующие обязательные работы: actual bill
reconciliation, подтверждённые FX/fees, company-paid retries и освобождение
доказанно неоплаченных holds; единая предметная квота успешного Run, concurrency
1/1/3, бюджет задачи и approval; subscription API/UI; проверенные billing events,
anti-abuse/global Free cap, lifecycle реальных async SDK pools, migration и
свежий установленный E2E.

Локальные логи: `_logs/resource-20261012/metering-targeted-final.log`,
`metering-candidate-checks.log`, `metering-config-schema.log`,
`metering-full-suite.log`, `metering-remaining-suite.log` и
`metering-baseline-comparison.json`. Чужие изменения
Android/WPF/сайта/напоминаний не входят в этот этап.
