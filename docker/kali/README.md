# Деплой Kali-стола Тройки — пошагово

Готовый набор для запуска второго «рабочего стола» Тройки (Kali) на сервере.
Код tool'а уже в репо (`tools/workspace_tool.py`, коммит e38f086). Здесь —
образ + что прописать на сервере. Делается один раз.

Дизайн и границы — см. `docs/TROIKA_KALI_WORKSPACE_PLAN.md`.

---

## Шаг 1. Собрать Kali-образ на сервере

На VPS, в каталоге репозитория Тройки:
```bash
docker build -t troika-kali:latest docker/kali/
```
Качается ~2-3 ГБ (полный headless-арсенал). Если долго/жирно — в `Dockerfile`
есть облегчённый вариант (точечный список инструментов), раскомментируй его.

Проверка, что образ собрался:
```bash
docker run --rm troika-kali:latest nmap --version
```
Должна вывестись версия nmap.

---

## Шаг 2. Дать Тройке доступ к Docker (docker-in-docker)

Тройка сама работает в контейнере. Чтобы она могла поднять Kali-контейнер, ей
нужен docker-сокет хоста. В `docker-compose.troika.yml`, в сервис `troika`,
секцию `volumes` добавить одну строку:

```yaml
    volumes:
      # Все данные Тройки: конфиг, память, сессии, авторизация кодеров
      - troika-data:/opt/data
      # Доступ к docker хоста — чтобы Тройка поднимала Kali-стол (DinD)
      - /var/run/docker.sock:/var/run/docker.sock
      # Том рабочей папки Kali (результаты сканов переживают recreate)
      - troika-kali-work:/opt/data/kali_work
```

И в самый низ файла, в `volumes:`, добавить том:
```yaml
volumes:
  troika-data:
    driver: local
  troika-kali-work:
    driver: local
```

⚠️ Доступ к docker-сокету = по сути root на хосте. Это нормально для своего
сервера, но учитывай: кто управляет Тройкой, тот управляет хостом. Изоляция
секретов Тройки от Kali-контейнера при этом сохраняется (ключи не пробрасываются).

---

## Шаг 3. Прописать env-переменные стола

В host `.env` Тройки (тот, что монтируется как `/opt/data/.env`, или твой
`/root/troika/.env`) добавить:

```bash
# === Kali-стол ===
WORKSPACE_KALI_IMAGE=troika-kali:latest
# Том /work внутри Kali. Путь — как в compose выше:
WORKSPACE_KALI_VOLUME=/opt/data/kali_work
# Режим «без лимитов»: cap-add для raw-сокетов (SYN-сканы nmap, masscan).
# Если нужно совсем всё (редко) — замени на ["--privileged"].
WORKSPACE_KALI_EXTRA_ARGS=["--cap-add","NET_RAW","--cap-add","NET_ADMIN"]

# (необязательно) Постоянные свои цели — по ним даже сессионного вопроса не будет.
# Через запятую: IP, домены, SSID своей точки.
# KALI_TARGET_ALLOWLIST=89.208.105.187,моя-точка

# --- Свой «мозг» на время Kali-сессии (опц.) ---
# Тройка переключит мозг ТОЛЬКО когда работает в Kali-столе. На выходе
# (`workspace_exit`) возвращается к основной модели. Влияет только на текущую
# сессию — DAEMON и параллельные чаты продолжают жить на основном мозге.
#
# Заполняй столько, сколько нужно (минимум WORKSPACE_KALI_BRAIN):
# WORKSPACE_KALI_BRAIN=openrouter/whiterabbitneo-33b
# WORKSPACE_KALI_BRAIN_PROVIDER=openrouter
# WORKSPACE_KALI_BRAIN_API_KEY=sk-...
# WORKSPACE_KALI_BRAIN_BASE_URL=https://openrouter.ai/api/v1
#
# Если PROVIDER/API_KEY/BASE_URL не заданы — используется учётка основного
# мозга (годится, если security-модель хостится там же).
```

---

## Шаг 4. Выкатить код и перезапустить

1. Влить/спуллить ветку с `workspace_tool.py` (или `docker cp` файлов, если
   патчишь живой контейнер — но ПОСЛЕ recreate, recreate стирает /opt/hermes).
   Файлы: `tools/workspace_tool.py`, `gateway/session_context.py`,
   `tools/terminal_tool.py`, `toolsets.py`,
   `skills/productivity/voice-task-routing/`, `skills/security/security-methodology/`.
2. Пересоздать сервис:
   ```bash
   docker compose -f docker-compose.troika.yml up -d
   ```
3. Синкнуть скилы в `~/.troika/skills/` и убедиться, что они НЕ 0-байтные
   (0-байтные синк не лечит — см. аудит tools).
4. Рестарт gateway внутри контейнера (если не пересоздавал):
   ```bash
   docker exec troika /command/s6-svc -r /run/service/gateway-default
   ```

---

## Шаг 5. Проверка вживую

Голосом или текстом Тройке:
1. «перейди в кали» → должна подтвердить вход и спросить про авторизацию.
2. «да, всё моё» → `workspace_confirm`, дальше молча.
3. «покажи версию nmap» → версия ИЗ Kali-контейнера.
4. «вернись обратно» → выход.

Проверки изоляции:
- Вне стола «версия nmap» → его нет (значит переключение реально работает).
- `docker exec troika cat /opt/data/kali_audit.log` → строки enter/authorize/exit.
- `docker ps` → виден поднятый `hermes-*` контейнер из образа troika-kali.

Если `docker run` изнутри падает с «permission denied / cannot connect to docker
daemon» — не примонтирован сокет (Шаг 2) или у процесса нет прав на него.
