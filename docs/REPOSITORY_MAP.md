# Карта репозитория Тройки

| Что нужно найти | Где искать |
|---|---|
| Серверные функции продукта, аккаунты и правила доступа | [troika_product](../troika_product/) |
| HTTP API и связь с устройствами | [API-сервер](../gateway/platforms/api_server.py), [мост телефона](../gateway/platforms/phone_bridge.py) |
| Диалог с моделью и вызов инструментов | [run_agent.py](../run_agent.py), [agent](../agent/), [tools](../tools/), [toolsets.py](../toolsets.py) |
| Приложения | [Flutter-клиент Android и Windows](../hermes-android/README.md), [отдельный WPF-клиент Windows](../troika-desktop/README.md) |
| Сайт продаж и личный кабинет | [troika-site](../troika-site/README.md) |
| Внутренняя веб-панель, терминал и документация Hermes | [web](../web/), [ui-tui](../ui-tui/), [tui_gateway](../tui_gateway/), [website](../website/) |
| Расширения и инструкции модели | [plugins](../plugins/), [providers](../providers/), [skills](../skills/), [optional-skills](../optional-skills/), [optional-mcps](../optional-mcps/) |
| Развёртывание production | [Compose](../deploy/production/compose.yaml) и [Dockerfile](../deploy/production/Dockerfile) |
| Требования, прогресс и результаты проверок | [Навигация по документации](README.md) |
| Проверки | [Серверные тесты продукта](../tests/troika_product/), [Flutter](../hermes-android/test/), [WPF](../troika-desktop/tests/), [сайт](../troika-site/tests/) |
| Макеты, фирменные материалы и реклама | [design](../design/), [brand](../brand/), [advertising](../advertising/) |

## Связи между каталогами

Команда запуска сервера `hermes gateway run` использует точку входа в
`hermes_cli`. Корневые Python-модули входят в упаковку через [pyproject.toml](../pyproject.toml).
Сервис распознавания речи загружает [серверный скрипт](../hermes-android/stt_proxy_server.py)
из каталога Flutter-клиента. Эту зависимость задаёт [voice_proxy.py](../troika_product/voice_proxy.py).

HTTP-обработчики аккаунтов, оплаты, памяти и диалога собраны в одном API-сервере.
При переносе группы обработчиков её внешние маршруты и проверки владельца должны
сохраняться. У приложений общий API, но собственные сборки и локальное хранение.

## Локальная рабочая папка

`work/` содержит черновики, результаты сборок и вложенные рабочие копии.
Список связанных с репозиторием копий показывает `git worktree list`; у каждой
свой Git status. Внутри могут находиться и самостоятельные репозитории.
В `_logs/` встречаются копии исходников и сборочные окружения. Перед очисткой
важно проверить содержимое конкретного подкаталога. Данные аккаунтов в `data/`
и локальные настройки хранятся отдельно.

Список файлов текущей версии показывает `git ls-files`. Для сравнения с ранней
ревизией сохранён [снимок от 5 октября 2026 года](audit/REPOSITORY_FILES.tsv).
