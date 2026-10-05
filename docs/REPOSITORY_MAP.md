# Карта и очистка репозитория Troika

Инвентаризация 2026-10-05. Проверен полный versioned file list; счётчики ниже
относятся к этому снимку, а не к будущим изменениям. [Полный перечень файлов](audit/REPOSITORY_FILES.tsv)
содержит каждый путь, тип и выполненную статическую проверку. «AST/JSON passed»
не означает, что вся функция работает. Динамические результаты — в [аудите](TROIKA_FUNCTIONAL_AUDIT.md).

## Все versioned каталоги

| Каталог | Файлов в снимке | Назначение и решение |
|---|---:|---|
| `(root)` | 49 | Точки входа, manifests, LICENSE и маршрут продукта. Совместимые Python/CLI имена сохранены. |
| `.github` | 27 | CI/security/product workflows и шаблоны issues; лишняя Gemini automation удалена. |
| `acp_adapter` | 10 | Необязательная интеграция редакторов ACP; Windows failures перечислены отдельно. |
| `acp_registry` | 2 | Metadata ACP-каталога для developer integration. |
| `agent` | 108 | Общий agent runtime: providers, context, completion, routing. Нужная зависимость. |
| `assets` | 2 | Branding assets Troika. |
| `cron` | 3 | Legacy scheduler; не owner-scoped product delivery и не ordinary product route. |
| `datagen-config-examples` | 4 | Примеры dataset-конфигураций разработчика; не пользовательские функции. |
| `deploy` | 5 | Актуальные production Compose/Dockerfile/config; основной deployment path. |
| `docker` | 23 | Унаследованные container helpers для builds/tests; не текущий production manifest. |
| `docs` | 39 | Требования, статус/audit, runbooks, исторический архив и runtime guide. |
| `gateway` | 63 | API/auth/runs/session ownership/phone bridge и optional messaging adapters. |
| `hermes-android` | 192 | Общий Flutter Android/Windows client, native code и STT server; имя сохраняет совместимость. |
| `hermes_cli` | 103 | Нужные gateway/CLI/config/plugins/bootstrap/dashboard; оставлен владельцем. |
| `locales` | 16 | Унаследованные CLI/dashboard translations. |
| `nix` | 11 | Необязательная Nix packaging/environment поддержка. |
| `optional-mcps` | 2 | References настройки optional MCP; не включаются автоматически. |
| `optional-skills` | 300 | Тяжёлые optional skills; наличие source не доказывает зависимости/provider readiness. |
| `packaging` | 2 | Packaging metadata/notices, сохранены с требованиями лицензии. |
| `plugins` | 219 | Provider/tool/web/memory framework и adapters; runtime imports зависят от них. |
| `providers` | 3 | Inference-provider discovery, runtime dependency. |
| `scripts` | 29 | Test runner, installers и developer utilities; зависят от своих платформ/сервисов. |
| `skills` | 575 | Bundled skills; optional services/tools не все доступны product agent. |
| `tests` | 1300 | Behavior/security/unit checks; e2e/integration/docker исключены из default discovery. |
| `tools` | 147 | Реализации tools; hosted product использует reviewed allowlist. |
| `troika-site` | 20 | Приватный статический сайт продаж; forms/download/legal не готовы. Чужой WIP сохранён. |
| `troika_product` | 17 | Account ownership/data/tool policy/completion/voice/retention foundation. |
| `tui_gateway` | 8 | Python JSON-RPC backend для Ink; нужен CLI/dashboard пути. |
| `ui-tui` | 339 | Ink transcript/composer/tests; не лишний дубликат продукта. |
| `web` | 107 | Dashboard supporting UI и embedded terminal; build проходит, lint падает, PTY требует POSIX/WSL. |
| `website` | 722 | Унаследованная документация разработчика, отдельно от sales site; Windows Python discovery сломан. |

Всего: 4447 versioned/new audit paths. Python AST: 2003; strict JSON:
49; JSONC tsconfig: 3. Ошибок AST/strict JSON: 0.
JSONC допускает comments; эти три файла не объявляются повреждённым JSON.

## Что удалено

Удалён 31 ранее tracked файл. Это старые upstream release notes,
дубль китайского README, заметка о Hermes routines, ранние implementation plans,
устаревшая tool-matrix/инфографика и Gemini issue/PR automation для upstream.
Они не являются runtime imports, client assets или обязательными notices.
Пустые `.plans`, `plans`, `scratchpad`, `infographic` и `.github/commands` убраны.
Исходники удалённых файлов доступны в Git history; вместо них не создана вторая
активная документация.

- `.github/commands/gemini-invoke.toml`
- `.github/commands/gemini-plan-execute.toml`
- `.github/commands/gemini-review.toml`
- `.github/commands/gemini-scheduled-triage.toml`
- `.github/commands/gemini-triage.toml`
- `.github/workflows/gemini-dispatch.yml`
- `.github/workflows/gemini-invoke.yml`
- `.github/workflows/gemini-plan-execute.yml`
- `.github/workflows/gemini-review.yml`
- `.github/workflows/gemini-scheduled-triage.yml`
- `.github/workflows/gemini-triage.yml`
- `.plans/openai-api-server.md`
- `.plans/streaming-support.md`
- `README.zh-CN.md`
- `RELEASE_v0.10.0.md`
- `RELEASE_v0.11.0.md`
- `RELEASE_v0.12.0.md`
- `RELEASE_v0.13.0.md`
- `RELEASE_v0.14.0.md`
- `RELEASE_v0.2.0.md`
- `RELEASE_v0.3.0.md`
- `RELEASE_v0.4.0.md`
- `RELEASE_v0.5.0.md`
- `RELEASE_v0.6.0.md`
- `RELEASE_v0.7.0.md`
- `RELEASE_v0.8.0.md`
- `RELEASE_v0.9.0.md`
- `hermes-already-has-routines.md`
- `infographic/kanban-db-corruption-defense/infographic.png`
- `plans/gemini-oauth-provider.md`
- `scratchpad/_tool_matrix.json`

## Что сохранено намеренно

`hermes_cli` оставлен по прямому решению владельца. `cli.py`, `run_agent.py`,
`model_tools.py`, `hermes_state.py`, `hermes_constants.py`, `gateway`, `agent`,
providers/plugins/tools импортируются runtime. Flutter path, native package,
MethodChannel, headers/preferences и CLI entry points пока требуют совместимой
миграции. `ui-tui`/`tui_gateway` используются embedded terminal; удаление этих
каталогов ломает этот путь. LICENSE и upstream attribution сохранены.

Старые планы продукта выведены из активной очереди и явно помечены как архив.
Прежние пути оставлены короткими ссылками, чтобы не ломать существующие references.
Главный DOCX не переписан. Source tree экспериментов сохраняется за default-off
policy; наличие source не является обещанием 1.0.

## Локальные и generated каталоги

`.git` — история; `.venv`, `node_modules`, build/.dart_tool/.gradle/.cxx —
установленные зависимости и outputs, не product source. `data` и локальные
профили могут содержать account stores/secrets; их не читали в отчёт и не удаляли.
Кэши pytest/ruff/Python не удалялись во время активных checks. `_logs`, reports,
tts_samples, .claude, `_gemini_*`, work и другие локальные файлы не становятся
доказанно лишними только из-за имени. Чужие snapshots не удалялись.
Собственные logs этой ревизии лежат в `work/docs-audit-2026-10-05`
и исключены из Git точечным ignore. Временная копия установленной APK
и screenshots телефона после сверки удалены.

Незавершённые изменения `troika-site/dist/*`, существовавшие до ревизии,
сохранены и не включаются в commit очистки. Пользовательские документы,
credentials и APK на телефоне/Windows не заменялись.
