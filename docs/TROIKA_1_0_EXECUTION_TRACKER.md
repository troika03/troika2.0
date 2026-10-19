# Troika 1.0: трекер реализации

Обновлено 2026-10-15. Требования: [главный Word-план](Troika_1.0_Launch_Plan_Final_Updated.docx),
решение от 6 октября в [основном плане ремонта](../PRODUCTIZATION_PLAN.md)
и [политика подписки](TROIKA_SUBSCRIPTION_ECONOMICS.md), согласованная 12 октября.
Проверки и дефекты: [аудит функций](TROIKA_FUNCTIONAL_AUDIT.md).

## Правило статуса

`[x]` — критерии конкретного этапа ранее проверены; это не обещание текущего
installed-client E2E или релизной готовности. `[-]` — часть реализована,
остаются критерии или регрессии. `[ ]` — раздел целиком ещё не принят,
даже если часть foundation уже существует. Работать целыми разделами 1–20;
исправление жалобы владельца не закрывает автоматически следующий раздел.
Очередь ремонта и согласованных дополнений задаёт основной план; статусы ниже
остаются оценкой полноты разделов запуска.

## Прогресс

| Раздел | Статус | Текущее положение |
|---|---|---|
| 1. Видение | [x] | Voice-first home, short statuses/results, owner memory и risk-based approvals реализованы. |
| 2. Продукт и аудитория | [x] | Product copy ориентируется на результат; экспериментальные инструменты не продаются как готовые. |
| 3. Границы 1.0 | [x] | Product allowlist/default-off policy реализованы. Незавершённые обязательные области остаются в следующих разделах. |
| 4. Voice-first дизайн | [x] | Orb states, secondary text, result cards, approval modal и темы покрыты Flutter tests. |
| 5. Android | [-] | UI и голос реализованы, прежние Samsung проверки сохранены. Фоновый native refresh access token и свежий reminder/standby E2E не закрыты. |
| 6. Windows | [-] | WPF с автопилотом установлен; точный EXE прошёл SDK E2E: API, пауза/продолжение, DPAPI checkpoint, owner isolation, локальный файл и очередь без дубля. Обновлённый source с UI/голосом собирается и проходит проверки. Физический микрофон/звук, настоящее закрытие в tray, background reminders и signed installer остаются отдельными gates. [Аудит](audit/AUTOPILOT_COMPLETION_2026_10_16.md). |
| 7. Сайт и аккаунт | [-] | Сайт опубликован на cm444726.tw1.ru: HTTPS, вход/регистрация, ресурс, устройства, память, export/delete, изолированная поддержка SQLite и локальные загрузки. 12 локальных и 52 проверки Timeweb прошли; оба установщика сверены по SHA-256, тестовые аккаунты удалены. Исходный Sites остался закрытым. Оплата/почта отложены, recovery/verification, legal, подпись и общие release gates открыты. [Аудит](audit/WEBSITE_TIMEWEB_2026_10_16.md). |
| 8. Billing/ресурс | [-] | Месячный runtime и личный API включены 14 октября. Corporate Free: prompt + completion; личный ключ: 0 за модель без corporate fallback. Free 500 тыс., Plus 5 млн, Pro 10 млн; Run/voice/API/Android/WPF, две Pro beta-выдачи, public HTTPS E2E, APK установлен без сброса. Оплата/почта отложены; checkout/verification/refund в коде, flags false. До продаж остаются финансовые lifecycle/unknown bills/anti-abuse. [Проверки](audit/SUBSCRIPTION_RUNTIME_2026_10_13.md), [настройка](development/SUBSCRIPTION_SETUP.md). |
| 9. Backend | [ ] | Auth, owner stores, runs и tools существуют; весь раздел ещё не принят. |
| 10. Голос/память/runtime | [ ] | Есть текущий agent loop, автоматические рабочие сессии с сохранением архива, completion receipts и общая opt-in автопамять с проверенной серверной синхронизацией; обновлённая APK установлена, сохранённый переключатель проверен на Samsung. Полный физический разговор Android/Windows и единый single/delegate/parallel/durable/verified Runtime не завершены. |
| 11. Файлы | [ ] | Creation/download foundation есть; весь набор форматов, качество, edit/version и E2E ещё не принят. |
| 12. Безопасность | [ ] | Есть tenant/approval/revoke/export/delete tests; полный production/backup scope не закрыт. |
| 13. Production | [-] | VPS/API/STT/TLS работают; постоянный домен, production stores, backups/restore, metrics/alerts ещё нужны. |
| 14. Аналитика | [ ] | Полный product/operational metrics набор ещё не реализован. |
| 15. Поддержка/legal | [ ] | Черновики страниц есть; оператор, контакты, support и проверка policies не завершены. |
| 16. Rebrand | [-] | Flutter identity/native strings мигрированы. Python, CLI, пути/headers/native IDs сохраняют совместимость; hard rename не завершён. |
| 17. CI/QA/release | [-] | Часть workflows и сборок работает. Полный Windows Python baseline и dashboard lint не зелёные; installer/update E2E отсутствует. |
| 18. Closed beta | [ ] | Предыдущие device smokes не заменяют закрытую beta на реальных пользователях. |
| 19. Public launch | [ ] | Публичная продажа запрещена до всех gates. |
| 20. Final DoD | [ ] | Сквозной путь site/register/download/voice/result/pay/cancel/delete ещё не проходит. |

## Общий ремонт — checkpoint 19 октября 2026

01 v5 независимо повторена координатором: 412 passed. 04 v3 добавлена в отдельный
candidate; gateway-связка sync/export/revoke/delete прошла 43 tests и 29 tests
поверх копии чужого API WIP. Четыре новых сценария падают на исходном gateway.
Shared runtime, установленные клиенты и production этим этапом не менялись.
Независимая приёмка 10 и общий regression открыты. Статусы разделов 1–20 не повышены.
Полный состав и ограничения: [отчёт 09](development/repair-2026-10-18/reports/09-coordinator.md).

## Следующий шаг

Сначала воспроизводимые дефекты текущих сценариев из аудита по запросу
владельца. Решение от 6 октября добавляет локальные готовые файлы и режим
разработки; эти изменения не закрывают автоматически разделы 5, 6, 10 и 11.
По решению от 13 октября основной режим разработки в новом source — API:
план, запись файлов, ревью модели и до трёх исправлений без выбора устройства.
Ревью не считается запуском тестов. Checkpoints, продолжение и изолированные
проверки Pro-автопилота включены 17 октября. Android/WPF установлены; SDK WPF
прошёл полный транспорт проекта. Обычная Android release APK 18 октября
прошла запуск проекта из UI, native доставку в фоне и финальный голосовой
отчёт без повтора при открытии; владелец услышал звук. OEM standby/reboot
и физический звук WPF остаются отдельными проверками.
Разделы 5, 6, 10 и 11 автоматически не закрываются.
Затем завершить раздел 7 и двигаться по Word-плану.

Старый подробный трекер с историческими числами тестов сохранён в
[архиве](archive/EXECUTION_TRACKER_BEFORE_2026_10_05.md). Историческая
физическая проверка Android не отменяется; свежая проверка требуется для
новых изменений и выявленных пробелов, а не для повторения принятого этапа.
