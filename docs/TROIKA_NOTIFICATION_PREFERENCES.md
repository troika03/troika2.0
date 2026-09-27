# Личные настройки уведомлений

**Статус:** реализованы настройки, тихие часы и owner-scoped in-app доставка.

Product API хранит личные настройки уведомлений, а `troika_product.proactive` использует их при выдаче напоминаний и follow-up сообщений во встроенный inbox. Gateway запускает фоновый event engine, который создаёт детерминированные owner-scoped события без внешних side effects. Android Assistant Hub читает inbox, проекты/задачи и эти настройки, а также умеет отмечать сообщения прочитанными.

Это **не** означает готовый production push: внешняя доставка при закрытом приложении и полноценный push transport остаются отдельной задачей.

## API

В product mode доступны два маршрута с индивидуальным device bearer token:

- `GET /v1/notification-preferences` возвращает текущие настройки аккаунта.
- `PUT /v1/notification-preferences` целиком заменяет настройки аккаунта.

Владельца сервер определяет из действующего токена. Поля `user_id`, `device_id` и любые неизвестные поля отклоняются. Настройки общие для устройств одного аккаунта и недоступны другому аккаунту. Legacy shared key не даёт доступ к этому API. Успешные ответы имеют `Cache-Control: no-store`.

Полное тело настроек:

```json
{
  "reminders_enabled": false,
  "proactive_enabled": false,
  "quiet_hours_enabled": false,
  "timezone": "UTC",
  "quiet_start": "22:00",
  "quiet_end": "08:00"
}
```

Все шесть полей обязательны при PUT. Строки вместо boolean, неизвестные IANA time zones и неверное время отклоняются. Равные начало и конец не допускаются. Напоминания и инициативные сообщения включаются независимо и по умолчанию выключены.

## Хранение и аудит

`troika_notification_preferences` хранится в owner-aware product SQLite. Изменение настроек и `notifications.preferences_updated` фиксируются атомарно. Privacy-safe audit не сохраняет текст сообщений, токены или расписание тихих часов.

Перед сохранением повторно проверяются принадлежность токена, отзыв, срок действия и активность устройства/аккаунта.

## In-app delivery

`NotificationPreferences.allows_delivery(kind, now=...)` применяется для `reminder` и `proactive` и учитывает opt-in, часовой пояс и тихие часы.

`ProactiveStore.generate_due_events()` создаёт owner-scoped события для сроков, заблокированных задач и полезных follow-up. Gateway запускает этот генератор фоновым task. `ProactiveStore.list_inbox()` выдаёт только события владельца, которые разрешены текущими preferences, и Android показывает их в Assistant Hub.

Текущая доставка ограничена встроенным inbox: она не является глобальным job runner и не даёт скрытых внешних действий от имени пользователя.

## Что ещё не завершено

- production push/background transport при закрытом клиенте;
- адресная push-доставка по устройствам и lifecycle push token;
- отдельные production SLA/monitoring для такой доставки;
- окончательная retention policy именно для внешней delivery инфраструктуры, когда она появится.

Для обычного нового сеанса этот файл читать не нужно; текущий короткий статус находится в `CURRENT.md`.
