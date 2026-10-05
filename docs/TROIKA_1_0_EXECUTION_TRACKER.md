# Troika 1.0: трекер реализации

Обновлено 2026-10-05. Требования: [главный Word-план](Troika_1.0_Launch_Plan_Final_Updated.docx).
Проверки и дефекты: [аудит функций](TROIKA_FUNCTIONAL_AUDIT.md).

## Правило статуса

`[x]` — критерии конкретного этапа ранее проверены; это не обещание текущего
installed-client E2E или релизной готовности. `[-]` — часть реализована,
остаются критерии или регрессии. `[ ]` — раздел целиком ещё не принят,
даже если часть foundation уже существует. Работать целыми разделами 1–20;
исправление жалобы владельца не закрывает автоматически следующий раздел.

## Прогресс

| Раздел | Статус | Текущее положение |
|---|---|---|
| 1. Видение | [x] | Voice-first home, short statuses/results, owner memory и risk-based approvals реализованы. |
| 2. Продукт и аудитория | [x] | Product copy ориентируется на результат; экспериментальные инструменты не продаются как готовые. |
| 3. Границы 1.0 | [x] | Product allowlist/default-off policy реализованы. Незавершённые обязательные области остаются в следующих разделах. |
| 4. Voice-first дизайн | [x] | Orb states, secondary text, result cards, approval modal и темы покрыты Flutter tests. |
| 5. Android | [-] | UI и голос реализованы, прежние Samsung проверки сохранены. Фоновый native refresh access token и свежий reminder/standby E2E не закрыты. |
| 6. Windows | [-] | Compact/Command Center/hotkey/allowlist реализованы. Свежий installed-client voice/file/screenshot E2E и background reminders не закрыты. |
| 7. Сайт и аккаунт | [-] | Статический приватный сайт есть. Account form — demo; публичные download/registration/support/status/legal и activation funnel не готовы. |
| 8. Billing/credits | [ ] | Subscription-status foundation есть; cost engine, checkout/webhook/cancel/refund отсутствуют. |
| 9. Backend | [ ] | Auth, owner stores, runs и tools существуют; весь раздел ещё не принят. |
| 10. Голос/память/runtime | [ ] | Есть текущий agent loop и completion receipts; единый single/delegate/parallel/durable/verified Runtime не завершён. |
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

## Следующий шаг

Сначала воспроизводимые дефекты текущих сценариев из аудита по запросу
владельца. Затем завершить раздел 7 и двигаться по Word-плану. Не начинать
новый эксперимент вместо восстановления обещанных базовых сценариев.

Старый подробный трекер с историческими числами тестов сохранён в
[архиве](archive/EXECUTION_TRACKER_BEFORE_2026_10_05.md). Историческая
физическая проверка Android не отменяется; свежая проверка требуется для
новых изменений и выявленных пробелов, а не для повторения принятого этапа.
