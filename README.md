# Troika 1.0

Персональный AI-ассистент для Android и Windows. Главный интерфейс — голос;
текст служит дополнительным вводом. Цель: выполнить задачу, сохранить результат
и использовать личный контекст под контролем пользователя.

Целевое обещание Troika 1.0: «Скажи Тройке, что нужно сделать. Она поймёт
задачу, сама выберет нужные инструменты, выполнит работу, сохранит результат
и будет помнить контекст в следующий раз». Это цель релиза, а не утверждение
о готовности всех сценариев текущей версии.

Аудитория главного плана:

- Студент: задания, объяснения и учебные документы.
- Начинающий специалист: отчёты, сравнения и рабочая рутина.
- Разработчик или power user: research, файлы и coding при настроенном backend.
- Обычный пользователь: понятные команды, задачи и напоминания.

Продукт находится в разработке. Публичная платная версия ещё не готова.
[Аудит функций](docs/TROIKA_FUNCTIONAL_AUDIT.md) отделяет работающий foundation,
подтверждённые дефекты, отсутствующие функции и непроверенные сценарии.

## Начать здесь

- [Документация](docs/README.md): один вход во все планы, runbooks и reviews.
- [Главный план](docs/Troika_1.0_Launch_Plan_Final_Updated.docx): требования и Definition of Done.
- [Трекер](docs/TROIKA_1_0_EXECUTION_TRACKER.md): прогресс разделов 1–20.
- [Память проекта](PROJECT_MEMORY.md): краткое текущее состояние.
- [Карта репозитория](docs/REPOSITORY_MAP.md): назначение всех каталогов и выполненная очистка.

## Текущие возможности

В коде есть локальные Android/Windows allowlist-команды, voice-first UI,
hosted agent/tool loop, индивидуальные аккаунты/устройства, общая история,
owner-scoped память, проекты/задачи/inbox, создание DOCX/PDF/PPTX и личные
artifacts. Локально создаются DOCX/PPTX. Напоминания на Android требуют
синхронизации и системных permissions; Windows background delivery отсутствует.

Нет password recovery, email verification, billing/checkout/credits,
production backup/restore и полного offline-first sync. Live screen/camera,
автономный PC и прочие эксперименты не входят в обычный продукт.
Реальный результат и установленная версия проверяются отдельно от сборки.

## Локальная разработка на Windows

Рабочая копия: `D:\troika-product`. Не запускать новый runtime в историческом
`D:\troikahermes` и не использовать его профиль. После установки locked
Python dependencies подготовить отдельный `data/test-runtime`, скопировать
`config.troika-product-test.yaml.example` в его `config.yaml`, хранить нужные
provider credentials только в его `.env`.

В PowerShell, из корня продукта:

```powershell
$env:HERMES_HOME = Join-Path $PWD 'data/test-runtime'
$env:API_SERVER_ENABLED = 'true'
$env:API_SERVER_HOST = '127.0.0.1'
$env:API_SERVER_PORT = '8765'
$env:TROIKA_PRODUCT_AUTH_ENABLED = 'true'
$env:TROIKA_PRODUCT_AUTH_DB = Join-Path $env:HERMES_HOME 'troika_access.db'
$env:TROIKA_PRODUCT_ARTIFACT_ROOT = Join-Path $env:HERMES_HOME 'artifacts'
$env:TROIKA_PRODUCT_WORKSPACE_ROOT = Join-Path $env:HERMES_HOME 'workspaces'
./.venv/Scripts/python.exe -m hermes_cli.main gateway run
```

Если нужен hosted STT fallback, после создания access DB запустить отдельный
процесс в другом PowerShell:

```powershell
./.venv/Scripts/python.exe -m troika_product.voice_proxy --hermes-home ./data/test-runtime --host 127.0.0.1 --port 8766 --backend groq
```

Корневого `stt_proxy_server.py` нет. Product wrapper использует
`hermes-android/stt_proxy_server.py`. Не копировать legacy shared API key в
обычный клиент. Для пользователя доступен register/login; ручной provisioning
описан в [beta runbook](docs/TROIKA_CLOSED_BETA_SETUP.md).

Проверка `http://127.0.0.1:8765/health` относится только к запущенному product
gateway. Порт может занимать посторонний процесс; HTTP 404 не подтверждает
здоровье Тройки. Production использует HTTPS и
[единственный deployment path](docs/TROIKA_PRODUCTION_SERVER.md).

## Проверки

```powershell
& 'C:/Program Files/Git/bin/bash.exe' scripts/run_tests.sh -j 6
```

В `hermes-android/`: `flutter test`, `flutter analyze --no-fatal-infos`,
`flutter build apk --debug --no-pub`, `flutter build windows --debug --no-pub`.
В `web/`: `npm run build`, `npm run lint`.
В `ui-tui/`: `npm run type-check`, `npm test`, `npm run build`.
Integration/e2e/docker требуют отдельного запуска и соответствующей среды.
Для integration tests после `--` явно передавать `-m integration`, иначе
default configuration может исключить все tests даже при указанном пути.

## Лицензия и совместимость

[MIT LICENSE](LICENSE). Troika основана на
[Nous Research Hermes-Agent](https://github.com/NousResearch/Hermes-Agent).
Copyright и notices сохраняются. Исторические имена Python, CLI, каталога
клиента, Android package/headers/preferences пока являются зависимостями
и совместимостью; их удаление требует [миграции](docs/TROIKA_NATIVE_REBRAND_MIGRATION.md).
