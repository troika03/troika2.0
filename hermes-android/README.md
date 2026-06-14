# Hermes Android — голосовой ассистент

Работает как Siri/Gemini: сказал "Hermes" → он ответил голосом.

## Как работает

```
Телефон (APK)
  └─ Слушает в фоне → услышал "Hermes" / "Гермес"
  └─ Записывает вопрос
  └─ Отправляет аудио → Hermes PC (через Tailscale)
  └─ Получает текстовый ответ
  └─ Произносит ответ Android TTS (русский голос)
```

---

## 1. Настройка Tailscale (один раз)

**На Windows PC:**
1. Скачай: https://tailscale.com/download → установи → войди в аккаунт
2. Запомни IP в трее Tailscale, вид `100.x.x.x`

**На Android:**
1. Play Store → **Tailscale** → установить → войди в тот же аккаунт

---

## 2. Запустить Hermes API Server на PC

```powershell
cd "D:\Project\Hermes 0.2"
python cli.py --gateway
```

Hermes будет слушать на `http://100.x.x.x:8642`.
Проверить: открой `http://100.x.x.x:8642/health` в браузере.

---

## 3. Установить APK

```bash
# Собрать
flutter build apk --debug

# Установить через ADB
adb install build/app/outputs/flutter-apk/app-debug.apk
```

Или скопируй APK на телефон вручную и установи.

---

## 4. Первый запуск

1. Открой **Hermes** → ⚙️ Настройки
2. URL: `http://100.x.x.x:8642` (твой Tailscale IP)
3. **Проверить соединение** → должно быть ✅
4. Сохранить

---

## 5. Использование

| Действие | Результат |
|----------|-----------|
| Сказать "Hermes" или "Гермес" | Просыпается, говорит "Слушаю" |
| Задать вопрос | Записывает, отправляет, отвечает голосом |
| Нажать на сферу | Начать запись вручную |
| Нажать ещё раз | Отправить |
| Написать текст внизу | Текстовый режим |

---

## Getting Started (оригинал)

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Lab: Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Cookbook: Useful Flutter samples](https://docs.flutter.dev/cookbook)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.
