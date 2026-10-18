# Troika — подписка, ресурс, модели и личный API

ID: `06-subscription`. Роль в общем исправлении Troika от 18 октября 2026 года.

Сначала прочитай [MASTER_PROMPT](../MASTER_PROMPT.md) полностью. Все общие
правила обязательны. Прочитай переданный владельцем
`D:\troika-product\docs\development\VOICE_DEVELOPMENT_WORKSPACE_PROMPT.md`.
Команды продукта выполняй только с рабочей папкой `D:\troika-product`.
`D:\troikahermes` — исключительно для чтения, даже если оттуда запущена сессия.

## Зона ответственности

- troika_product/subscription_policy.py
- troika_product/resource_ledger.py
- troika_product/resource_runtime.py
- troika_product/billing.py
- troika_product/llm_metering.py
- troika_product/service_metering.py
- troika_product/own_provider.py
- troika_product/token_diagnostics.py
- agent/provider_metering.py
- provider/auxiliary изменения только своей области
- свои tests

Границы задают владельца candidate-изменений, а не разрешение одновременно
редактировать общий checkout. Реализуй в своём каталоге work; передай patch,
base hashes и отчёт. Прямые общие изменения/commit/push делает только 09.
Чужой staged/unstaged WIP не включай в свой patch без явного анализа происхождения.

## Задачи

1. Проверь текущие Free/Plus/Pro grants/periods/quotas/concurrency и месячный ledger. Не меняй согласованные цены/токены. Учти весь SDK input+output, cache/reasoning без двойного прибавления и все дочерние вызовы.
2. Проверь reserve/commit/reconcile, тайм-аут после отправки, unknown usage, повтор/idempotency, refunds/compensation и общий Run budget. Не возвращай резерв автоматически после потенциально состоявшегося provider вызова.
3. Обеспечь одинаковые entitlement/capability guards для chat, прямой development формы, specialists и fallback. Закрой расхождение image/vision «доступно в каталоге» и неизбежный metering refusal либо передай фактический отказ как capability status.
4. Проверь личный API по main/auxiliary/native/voice/checker routes: серверное хранение только в запросе, ошибочный key без company fallback, отсутствие корпоративного balance не ломает допустимый personal inference. Тарифные права остаются.
5. Бесплатный autopilot route сохраняет проверку официальной нулевой цены/структурированного вывода. Нужны понятные 429/provider unavailable/unsupported model состояния; не добавляй платную замену или обещание гарантированной задержки.
6. Проверь оценки бюджета/остаток/обновление/исчерпание на двух устройствах. После исчерпания local actions/history и предусмотренные функции продолжают работать; отказ объясняет конкретную причину.
7. Заверши checkout/webhook/cancel/refund lifecycle в выключенном режиме и изолированной тестовой среде. Проверяй двойные события, period change, partial refunds/prorating и deletion/pending financial records. Production оплату/почту не включай.
8. Проверь стоимость STT/TTS/vision/search/external tools и global free budget/anti-abuse. Не используй неизвестную цену как нулевую. Отчётные counters не содержат prompts/keys.

## Зависимости

- Все model/tool вызовы — contract с 01/05
- Account/recovery — 04
- Website/Telegram — 07

Не жди пассивно: подготовь собственную реализацию и contract fixtures для
независящих частей. Отдельно пометь, где проверка fixture ещё не является E2E.

## Приёмка

- Обычный, personal и ошибочный personal запрос подтверждают корректное списание и отсутствие fallback.
- Конкурентные Run с specialists не превышают ресурс; timeout/duplicate/смена периода не дают двойного списания.
- Выключенная capability отклоняется одинаково из всех входов; UI получает фактическую причину недоступности.
- Billing tests проходят без настоящей покупки; live flags и согласованная экономика сохранены.

## Результат текущей сессии

Каталог candidate/patch: `D:\troika-product\work\product-repair-2026-10-18\06-subscription\`.
Единственный свой отчёт: `D:\troika-product\docs\development\repair-2026-10-18\reports\06-subscription.md`.

Выполни доступную работу целиком. Сохрани матрицу функций, найденные причины,
контракты, точный состав patch и фактические проверки. Не завершай одним
обещанием, списком идей или неподтверждённым «всё работает». Если нужен
внешний доступ или решение владельца, сначала доведи независимую часть
до конкретного reviewable результата и укажи единственный нужный следующий шаг.
