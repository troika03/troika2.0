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
  --email user@example.com --device-name "Pixel 9" --platform android
```

Передай значение `token=` пользователю безопасным каналом. Он вводит его в
Android-приложении в «Настройки → API ключ». База хранит только SHA-256 digest
токена, поэтому восстановить его после выдачи нельзя.

## Ограничения beta

- Нет публичной регистрации, платежей, восстановления доступа или push-delivery.
- История чата и location fingerprints изолированы по user/device token.
- Глобальные jobs и управление телефоном намеренно отключены до появления
  адресной маршрутизации конкретного устройства и audit log.
