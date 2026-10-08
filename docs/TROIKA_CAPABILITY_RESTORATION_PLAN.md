# Восстановление возможностей Troika

Обновлено 2026-10-07. Подчиняется [Word-плану](Troika_1.0_Launch_Plan_Final_Updated.docx)
и согласованным дополнениям в [основном плане](../PRODUCTIZATION_PLAN.md).
Текущие результаты и поломки находятся в [аудите функций](TROIKA_FUNCTIONAL_AUDIT.md).
Этот документ описывает границы и условия восстановления, без второй очереди статусов.

## Реализованная основа и ограничения

| Область | Есть в коде | Что требуется до полного обещания |
|---|---|---|
| Голос | Android local recognition/wake, hosted STT/agent/TTS, barge-in; Windows push-to-talk. | E2E установленной версии, Bluetooth/OEM/standby, фоновая авторизация после истечения access token, provider fallback. |
| Помощник | Проекты, задачи, заметки, сроки, opt-in inbox и quiet hours. | Push token lifecycle и доставка без открытого/синхронизированного клиента. |
| Напоминания | Owner-scoped schedule, snapshots и Android AlarmManager. | Телефонная проверка актуального APK; разрешения notifications/exact alarms; Windows background delivery. |
| Документы | Hosted DOCX/PDF/PPTX; локальные DOCX/PPTX; workspace text/HTML artifacts. | Импорт/редактирование существующих Office-файлов, XLSX, визуальное качество и E2E открытие/сохранение. |
| Память и аккаунт | Owner-scoped CRUD, export/delete, device revoke, access/refresh tokens. | Recovery/email verification; production object/backup lifecycle. |
| Одноразовый экран Android | MediaProjection, TTL/nonce, owner/device guard, Stop, frame cap; прежний Samsung E2E. | Beta build и оба server flags; opt-in external vision. Это не live vision. |
| Windows | Локальные allowlist actions, Compact/Command Center, hotkey, approved screenshot. | Installed-client E2E и отдельный Companion для расширенного управления. |

## Неподключённые возможности

Владелец согласовал режим разработки 6 октября и расширил его 8 октября:
перед проверкой спрашивать «на телефоне или выбранном ПК». Создание ZIP,
проверка, до трёх исправлений по настоящему отчёту и Stop реализованы на Android
и ПК. Телефон использует встроенные offline Python/unittest и переносимый
CommonJS; выбранный ПК принимает проект только после локального opt-in и
подтверждения. API — RAM relay с TTL, без запуска кода на облачном host.
Работа с существующим repository, произвольные сборки, зависимости и общий
phone-to-PC Companion остаются этапом 4. APK и WPF установлены, relay API
развёрнут; полный установленный облачный цикл ещё требует E2E. Доказательства:
[аудит разработки](audit/DEVELOPMENT_WORKFLOW_2026_10_08.md).

Live WebRTC screen assist, live CameraX vision, полный Accessibility control,
автономный PC-agent общего назначения, GROUND, legacy DAEMON, Kali, self-improvement, video
generation, экзотические messenger tools не входят в обычный Troika 1.0.
Default-off flags в `troika_product/feature_policy.py` не означают, что
установка флага автоматически даёт рабочую и проверенную интеграцию.

## Общие условия восстановления

- Отдельная capability для `screen.snapshot`, `screen.live`, `camera.live`, `ui.read`, `ui.control`; просмотр не даёт управление.
- Токен привязан к owner/device/session, ограничен TTL и nonce; logout/revoke/Stop закрывают канал.
- На устройстве видны preview, режим, таймер и остановка. Камера/микрофон не включаются неявно.
- Raw media не сохраняются в БД, логах, crash dumps или backups. Содержимое кадра считается недоверенными данными.
- Permission/password/OTP/payment screens блокируются локально. Secure-window protection не обходится.
- Model output не исполняется напрямую. Локальная policy может отклонить серверное предложение.
- Внешний vision provider требует отдельного opt-in; неизвестный approval channel закрывает доступ.
- Нужны failure handling, backpressure, auto-stop, operator kill switch и privacy-safe counters.

## Следующие технические gates

1. Для текущего голоса/напоминаний проверить реальную установленную версию, expiry, сеть, permissions, reboot и Stop.
2. Для файлов проверить ownership, скачивание/открытие, новую версию вместо перезаписи и отказ повреждённого input.
3. Для production storage реализовать version-aware purge, durable deletion ledger, restore scrubber и disaster-recovery rehearsal.
4. Для live vision отдельно решить внешний provider, максимальную длительность, камеры, частоту preview и список blocked apps; провести новый threat model.
5. Для Companion подписать приложение/updates, разделить разрешения окна/файла/ввода/запуска; использовать исходящий WSS, локальные approvals и revoke.

## Обязательные проверки media/control

Cross-tenant/session/device подмена; replay token/nonce; expiry/logout/revoke;
неверный TLS; oversized/malformed frames; сеть/restart/heartbeat;
screen lock/background/permission revoke; prompt injection в кадре;
sensitive screens; отсутствие raw media во всех stores; bounded queues;
Stop и server kill switch. Review одноразового screenshot не закрывает live review.

Подробные ранние варианты media architecture и фаз 0–10 находятся в
[архиве](archive/CAPABILITY_PLAN_BEFORE_2026_10_05.md). Их сентябрьские статусы
не используются как сегодняшнее доказательство работоспособности.
