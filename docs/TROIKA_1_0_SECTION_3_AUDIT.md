# Troika 1.0: аудит границ первой версии

Дата проверки: 2026-09-24. Главный критерий: раздел 3
`Troika_1.0_Launch_Plan_Final_Updated.docx`.

Это исторический аудит этапа 2026-09-24. Свежий статус находится в
[аудите функций](TROIKA_FUNCTIONAL_AUDIT.md). Статусы ниже описывают реализацию того этапа. Они не заменяют подробные критерии
следующих разделов плана.

## Обязательные области

| Область | Статус | Доказательства | Открытый пробел |
|---|---|---|---|
| Account | Частично | `troika_product/access.py`; endpoints регистрации, входа, устройств, экспорта и удаления в `gateway/platforms/api_server.py`; Android UI в `auth_screen.dart` и `settings_screen.dart`; `tests/gateway/test_product_auth.py` | Нет восстановления пароля и подтверждения почты. |
| Voice | Частично | `troika_product/voice.py`, `voice_proxy.py`; Android `stt_service.dart`, `tts_service.dart`, `voice_presets.dart`, `BargeInMonitor.kt`; `tests/troika_product/test_voice.py` | Нет production SLA и полностью проверенного provider fallback. |
| AI | Реализовано для текущего MVP | Product agent принудительно использует `troika-product` в `gateway/platforms/api_server.py`; очищенный run/SSE результат и fallback моделей покрыты gateway/agent тестами | Production provider routing и cost caps проверяются в следующих разделах. |
| Memory | Реализовано | `troika_product/memory.py`, owner-scoped API, `memory_screen.dart`; `tests/troika_product/test_memory.py`, `tests/gateway/test_product_assistant.py` | Production backup lifecycle ещё отсутствует. |
| Web search/research | Реализовано при настроенном провайдере | `tools/web_tools.py`, `tools/web_research_tool.py`; product toolset содержит `web_search`, `web_extract`, `web_research`; `tests/tools/test_web_research.py` | Доступность зависит от настроенного search provider. |
| Documents | Реализовано для DOCX/PDF/PPTX | `troika_product/document_generation.py`, `artifacts.py`; Android `files_screen.dart`, `local_documents_screen.dart`; artifact и document tests | Редактирование существующих файлов и XLSX входят в раздел 11, не в этот минимальный срез. |
| Tasks | Реализовано | `troika_product/proactive.py`, `tools/troika_assistant_tool.py`, `assistant_hub_screen.dart`; `tests/troika_product/test_proactive.py`, `tests/gateway/test_product_assistant.py` | Push не включён; in-app inbox работает. |
| Devices | Частично | Owner-scoped список/отзыв устройств; безопасный Android bridge; локальные allowlist-команды Android/Windows в `local_command_service.dart`; device/phone tests | Отдельный production Windows Companion ещё не выпущен. |
| Subscription | Частично | Entitlement и usage ledger в `troika_product/access.py`; owner-scoped `GET /v1/subscription`; Android показывает тариф и остаток лимита; auth/usage/Flutter tests | Нет Plus/Pro checkout, webhook, отмены и платёжного статуса. Это основной scope раздела 8. |
| Production | Частично | Security headers, health endpoints, locked product CI, tenant isolation и retention tests | Позднее подняты VPS/API/STT/TLS. Object storage, backup/restore и monitoring всё ещё не завершены. Это основной scope раздела 13. |

## Экспериментальные возможности

`troika_product/feature_policy.py` фиксирует единый default-off каталог:
GROUND, старый DAEMON, live screen/WebRTC, live CameraX, полный Accessibility
control, Kali, production self-improvement, video generation, экзотические
мессенджеры, редкие Hermes tools и автономное PC-управление.

Обычный hosted runtime всегда начинается с `troika-product`. Настройки
оператора не могут расширить этот allowlist. Старый код не удалён. Screen
snapshot остаётся отдельной закрытой beta: нужны два серверных флага, а Android
UI появляется только при build-флаге `TROIKA_SCREEN_SNAPSHOT_BETA`.

Проверки: `tests/troika_product/test_feature_policy.py`,
`tests/gateway/test_product_auth.py`, `hermes-android/test/troika_config_test.dart`.
