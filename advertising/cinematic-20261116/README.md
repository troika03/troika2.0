# Тройка. Кинематографический ролик

Восемь сцен о работе ассистента на Windows и Android. Интерфейсы нарисованы для демонстрации. Геометрия знака взята из `design/app-icon-20261115/icon.svg`.

- Формат 1920 × 1080, 60000/1001 кадра/с, 724 кадра, H.264/AAC.
- Монтажные точки на шкале 30000/1001 кадра/с — 72, 101, 159, 187, 215, 245, 301.
- Длительность воспроизведения 12,075 с. Финальный кадр укорочен списком воспроизведения MP4. Частота выборки и все 724 изображения сохранены.
- Музыка — [Rising Forest, Diego Nava](https://mixkit.co/free-stock-music/edm/), [Mixkit Stock Music Free License](https://mixkit.co/license/modal/musicFree/). Звуки интерфейса синтезированы для ролика.

## Сборка

Нужны PowerShell 7, Node.js с Playwright и Chromium, Python с NumPy и SciPy, FFmpeg с libx264 и ffprobe. Сборку можно выполнять в отдельной папке, скопировав туда эти файлы. На последовательность PNG нужно примерно 350 МБ плюс место для профиля браузера.

```powershell
curl.exe -fLsS https://raw.githubusercontent.com/rsms/inter/v4.1/docs/font-files/InterVariable.woff2 -o InterVariable.woff2
curl.exe -fLsS https://raw.githubusercontent.com/rsms/inter/v4.1/LICENSE.txt -o Inter-OFL.txt
curl.exe -fLsS https://assets.mixkit.co/music/471/471.mp3 -o rising-forest.mp3
ffmpeg -i rising-forest.mp3 -ac 2 -ar 48000 -c:a pcm_f32le music-source.wav
python sound.py
node render.cjs
node render.cjs --master
./encode.ps1
```

`node render.cjs` собирает автономный HTML и выводит f40, f86, f150 и f230. HTML принимает `window.seek(t)` после `window.timelineReady`, где `t` — дробный номер кадра на монтажной шкале.

`TROIKA_FRAME_DIR` задаёт папку для PNG. При таком переопределении передайте этот путь в `encode.ps1 -FrameDirectory`. Для продолжения прерванного рендера с той же версией исходника есть `--resume`. `TROIKA_CHROME` позволяет указать установленный Chrome.

Готовый файл сохраняется как `Troika-Cinematic-1080p.mp4`.
