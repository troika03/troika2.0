# Troika client

Общий Flutter-клиент Troika для Android и Windows. Главный интерфейс — голос.
Чат служит дополнительным вводом и экраном деталей.

> Скажи, что нужно сделать. Тройка выполнит задачу, сохранит результат и будет
> помнить полезный контекст в следующий раз.

## Основной сценарий

```text
Открыть Troika
  → сказать задачу
  → увидеть короткий статус
  → получить действие, файл, задачу или короткий ответ
  → при необходимости открыть детали
```

Примеры: разобрать учебное задание, подготовить рабочий отчёт, помочь с кодом,
найти информацию, открыть приложение или создать напоминание.

## Обычный интерфейс

- Home: voice orb, короткий статус и до трёх актуальных результатов.
- Text: дополнительный текстовый ввод и полный transcript.
- Tasks: проекты, задачи, напоминания и личный inbox.
- Files: owner-scoped документы и презентации.
- Memory: просмотр, изменение и удаление сохранённых фактов.
- Settings: Voice, Memory, Permissions, Account and data, Advanced.

Пользователь не выбирает model, provider, tool, worker или agent framework.
Чувствительные действия требуют понятного одноразового подтверждения.

## Ограничения текущей версии

Android планирует напоминания по полученным с сервера данным через AlarmManager.
Фоновое пробуждение, обновление сеанса при заблокированном экране и звук после
перезагрузки требуют проверки установленной APK. Локальный конструктор DOCX/PPTX
принимает структуру документа. Результаты проверок клиента собраны в
[аудите функций](../docs/TROIKA_FUNCTIONAL_AUDIT.md).

## Первый запуск

Обычный onboarding запрашивает только микрофон. Остальные разрешения включаются
позже по необходимости в профиле. Server URL, API key и диагностика доступны
только в явной developer-сборке. Обычный пользователь входит через аккаунт.

## Developer build

Исторические пути, MethodChannel и compatibility keys пока сохраняются, чтобы
не потерять данные установленных клиентов. Внутренние диагностические экраны
можно включить отдельно:

```bash
flutter run --dart-define=TROIKA_DEVELOPER_DIAGNOSTICS=true
```

Этот флаг не предназначен для обычной product-сборки.

## Проверка и сборка

```bash
flutter pub get
flutter test
flutter analyze --no-fatal-infos
flutter build apk --debug
```

## Структура

| Путь | Назначение |
|---|---|
| `lib/screens/` | Voice-first Home, Text, Tasks, Files, Memory и Settings. |
| `lib/services/` | Product API, voice, STT/TTS, локальные команды и results. |
| `lib/config/` | Product и compatibility configuration. |
| `android/app/src/main/kotlin/` | Wake word, foreground service, TTS и device bridge. |

Канонический scope клиента задаёт
[`docs/Troika_1.0_Launch_Plan_Final_Updated.docx`](../docs/Troika_1.0_Launch_Plan_Final_Updated.docx).
