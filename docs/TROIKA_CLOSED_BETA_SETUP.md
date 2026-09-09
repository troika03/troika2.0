# Закрытая beta: доступ пользователей и устройств

Этот режим предназначен для закрытой beta до self-service регистрации и billing.
Он заменяет общий API-ключ индивидуальными токенами устройств и не включает
глобальные cron-задачи или удалённое управление телефоном.

## Запуск сервера

В `.env` на сервере включи:

```env
TROIKA_PRODUCT_AUTH_ENABLED=true
TROIKA_PRODUCT_AUTH_DB=/opt/data/troika_access.db
```

Запусти gateway и STT proxy из корня репозитория. API server и STT proxy будут
принимать только токены вида `trk_live_…`; `API_SERVER_KEY` больше не является
пользовательским ключом в этом режиме.

## Выдача доступа

Для каждого beta-пользователя и его устройства выполни на сервере:

```bash
python -m troika_product --database /opt/data/troika_access.db provision \
  --email user@example.com --device-name "Pixel 9" --platform android \
  --plan beta --daily-request-limit 50
```

Передай значение `token=` пользователю безопасным каналом. Он вводит его в
Android-приложении в «Настройки → API ключ». База хранит только SHA-256 digest
токена, поэтому восстановить его после выдачи нельзя.

Оператор может изменить лимит существующего пользователя без перевыпуска токена:

```bash
python -m troika_product --database /opt/data/troika_access.db set-limit \
  --user-id usr_... --plan pro --daily-request-limit 200
```

## Usage в beta

Каждый запрос в `/v1/runs` и `/v1/chat/completions` атомарно списывает один
запрос из дневного лимита пользователя (UTC). Лимит beta по умолчанию — 50
запросов в сутки; успешный запуск возвращает оставшееся число в заголовках
`X-Troika-Daily-Request-Limit` и `X-Troika-Requests-Remaining`. При исчерпании
сервер возвращает `429` и не запускает агента. Это временный cost cap, а не
финальная биллинговая система: платежи, платежные периоды и возвраты пока не
реализованы.

## Audit beta

База сохраняет append-only события без текста запросов, токенов и raw session
IDs: выдача лимита, запуск и остановка run, approval, отказ доступа, исчерпание
лимита. Для диагностики одного пользователя используй:

```bash
python -m troika_product --database /opt/data/troika_access.db audit \
  --user-id usr_... --limit 100
```

`session_digest` и `run_digest` — односторонние ссылки для корреляции, не исходные
значения. Записи — продуктовый журнал beta, но не WORM-хранилище: доступ
операторов к серверной SQLite-базе должен быть ограничен.

## Ограничения beta

- Нет публичной регистрации, платежей, восстановления доступа или push-delivery.
- История чата и location fingerprints изолированы по user/device token.
- Доступ к status, events, approval и stop конкретного run изолирован по
  user/device token.
- Legacy `/v1/responses` временно отключён: его старое хранилище не имеет
  tenant ownership. Клиент beta использует `/v1/runs` или `/v1/chat/completions`.
- Глобальные jobs и управление телефоном намеренно отключены до появления
  адресной маршрутизации конкретного устройства.
