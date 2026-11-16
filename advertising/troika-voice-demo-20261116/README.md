# Тройка. Пять минут до созвона

Вертикальная реклама голосовой помощницы. 28,8 секунды, 1080 × 1920, 30 кадров/с, H.264 и AAC. В истории герой готовится к созвону. Он просит включить фонарик, найти официальную инструкцию по записи экрана Windows и собрать по ней три слайда.

| Время | Сцена |
|---|---|
| 00:00–00:04,26 | Созвон через пять минут. Флешка под столом. |
| 00:04,26–00:08,95 | Запрос Тройке на Android, свет и найденная флешка. |
| 00:08,95–00:15,55 | Запрос о записи экрана. Ответ со ссылкой на справку Microsoft. |
| 00:15,55–00:22,45 | Просьба о презентации, три слайда и карточка файла. |
| 00:22,45–00:28,80 | Логотип, экраны Android и Windows, вопрос зрителю. |

Приём из приложенного референса — короткий диалог пользователя с ассистентом и смена плана на ответе. В ролике оригинальные кадры, текст и озвучка. Главные экраны — тестовые рендеры действующего дизайна клиентов из `design/troika-ui-2026-11-13/`. Фотографические вставки с героем сгенерированы отдельно. Результат поиска и три слайда показаны для примера. Время выполнения задано монтажом.

Сочетание Win + Shift + R и шаги записи сверены со справкой Microsoft. Для подачи команды и результата также изучены Luxify Assistant, разборы Gemini Live и Pingo AI. Прямой профиль @sevanklav был недоступен в веб-просмотре. [Справка Microsoft](https://support.microsoft.com/en-us/windows/apps/use-snipping-tool-to-capture-screenshots) · [Luxify Assistant](https://luxify-assistant.com/) · [Gemini Live](https://viralhooks.org/database/43595-creator-demonstrates-ai-workflow-automat/) · [Pingo AI](https://viralhooks.org/ugc-library-viral-videos/tt-7604520088867245326/) · [@sevanklav](https://www.tiktok.com/@sevanklav)

Мужская речь — Fish Audio S2.1 Pro Free через OpenRouter, голос «Михаил». Реплики Тройки — локальный русский голос Windows. Музыка и эффекты синтезируются в `sound.py`. Лицензия Golos Text находится в `public/OFL.txt`.

## Пересборка

Локальный архив содержит исходники, звуковые реплики и изображения. Нужны Node.js, Python с NumPy и Playwright, FFmpeg, Edge или Chrome.

```sh
npm ci
python sound.py
python render.py
```

Выход — `final/Troika-Voice-Demo.mp4`. Для просмотра композиции откройте адрес, который выводит `python render.py --preview`. Монтаж находится в `src/troika.tsx`, речевые тексты — в `narration.json` и `replies.json`. Скрипт `narrate.py` использует общий синтез речи из `advertising/release-20261115` и запускается из checkout. Реплики Windows можно заново собрать командой `powershell.exe -NoProfile -File record-replies.ps1`.
