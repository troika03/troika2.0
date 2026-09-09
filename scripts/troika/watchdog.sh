#!/usr/bin/env bash
# Тройка watchdog — раз в 2 часа проверяет что сервер живой и мозг отвечает.
# Если что-то сломано — рестартит контейнер и шлёт уведомление в Telegram.
#
# Установка (на сервере под root):
#   cp /root/troika/scripts/troika/watchdog.sh /root/troika/watchdog.sh
#   chmod +x /root/troika/watchdog.sh
#   crontab -l | grep -v watchdog.sh > /tmp/cron.$$; \
#     echo '0 */2 * * * /root/troika/watchdog.sh >> /var/log/troika-watchdog.log 2>&1' \
#     >> /tmp/cron.$$; crontab /tmp/cron.$$; rm /tmp/cron.$$
#
# Переменные окружения (можно положить в /root/troika/.env, watchdog его подхватит):
#   TROIKA_URL              — базовый URL сервера (default: http://localhost:8642)
#   TROIKA_STT_URL          — URL STT-прокси (default: http://localhost:8643)
#   TROIKA_API_KEY          — API ключ (обязателен для production-проверок)
#   TROIKA_CONTAINER        — имя контейнера (default: gateway-default)
#   TROIKA_BRAIN_TIMEOUT    — секунды ожидания ответа от мозга (default: 60)
#   TROIKA_TG_BOT_TOKEN     — токен Telegram-бота для уведомлений
#   TROIKA_TG_CHAT_ID       — chat_id куда слать (обычно ваш ID)
#   TROIKA_LOG              — путь к лог-файлу (default: /var/log/troika-watchdog.log)

set -u

# Env-файл со стороны сторожа. По умолчанию берём ~/.troika-watchdog.env
# (обычно /home/troika/.troika-watchdog.env), т.к. основной /root/troika/.env
# root-only и non-root сторож его не прочитает.
ENV_FILE="${TROIKA_ENV_FILE:-$HOME/.troika-watchdog.env}"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

URL="${TROIKA_URL:-http://localhost:8642}"
STT_URL="${TROIKA_STT_URL:-http://localhost:8643}"
KEY="${TROIKA_API_KEY:-${API_SERVER_KEY:-}}"
CONTAINER="${TROIKA_CONTAINER:-troika}"
BRAIN_TIMEOUT="${TROIKA_BRAIN_TIMEOUT:-60}"
LOG="${TROIKA_LOG:-$HOME/troika-watchdog.log}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

notify() {
    local msg="$1"
    log "NOTIFY: $msg"
    if [ -n "${TROIKA_TG_BOT_TOKEN:-}" ] && [ -n "${TROIKA_TG_CHAT_ID:-}" ]; then
        curl -sS --max-time 10 \
            "https://api.telegram.org/bot${TROIKA_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TROIKA_TG_CHAT_ID}" \
            -d "text=🚑 Тройка watchdog: ${msg}" \
            -o /dev/null || log "telegram send failed"
    fi
}

restart_container() {
    local reason="$1"
    log "RESTART $CONTAINER (reason=$reason)"
    if docker restart "$CONTAINER" >/dev/null 2>&1; then
        notify "рестарт $CONTAINER: $reason"
        # Дадим 20с прогреться прежде чем следующая проверка.
        sleep 20
        return 0
    else
        notify "НЕ УДАЛОСЬ рестартить $CONTAINER: $reason"
        return 1
    fi
}

check_container() {
    if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
        log "container $CONTAINER not running"
        notify "контейнер $CONTAINER лежит — пробую поднять"
        docker start "$CONTAINER" >/dev/null 2>&1 && sleep 20
        return 1
    fi
    return 0
}

check_health() {
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$URL/health" 2>/dev/null || echo 000)"
    if [ "$code" = "200" ]; then
        log "health OK"
        return 0
    fi
    log "health FAIL http=$code"
    return 1
}

check_brain() {
    # Реальный тест: посылаем короткую reply-задачу, ждём осмысленный ответ.
    # Если модель на 429 / OpenRouter упал / Tor лёг — мозг молчит, контейнер жив.
    local body='{"model":"troika-agent","stream":false,"messages":[{"role":"user","content":"скажи цифрой сколько будет два плюс два"}]}'
    local resp code
    resp="$(curl -sS --max-time "$BRAIN_TIMEOUT" \
        -H "Authorization: Bearer $KEY" \
        -H "Content-Type: application/json" \
        -X POST "$URL/v1/chat/completions" \
        -d "$body" 2>&1)" || {
        log "brain FAIL curl-error: $resp"
        return 1
    }
    # Достаточно чтобы choices[0].message.content не был пустой.
    if echo "$resp" | grep -Eq '"content"\s*:\s*"[^"]+"' ; then
        log "brain OK"
        return 0
    fi
    log "brain FAIL empty/malformed response: $(echo "$resp" | head -c 240)"
    return 1
}

check_stt() {
    # Реальный тест: строим 100мс WAV-тишины и отправляем на транскрипцию.
    # Ловит случай когда контейнер STT жив, но faster-whisper внутри умер
    # (например, /opt/data/pylib исчез после `up -d` — известный сценарий).
    local wav="/tmp/troika-watchdog-silent.wav"
    # 44 байта WAV-header + 3200 байт PCM (100мс, 16kHz mono s16le).
    # RIFF\x24\x0c\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00
    # \x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x0c\x00\x00
    python3 - "$wav" <<'PY' 2>/dev/null || { log "stt SKIP: python3 unavailable"; return 0; }
import struct, sys, wave
p = sys.argv[1]
with wave.open(p, 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b'\x00\x00' * 1600)
PY
    local resp
    resp="$(curl -sS --max-time 15 \
        -H "Authorization: Bearer $KEY" \
        -F "language=ru" \
        -F "file=@${wav};type=audio/wav" \
        "$STT_URL/v1/audio/transcriptions" 2>&1)" || {
        log "stt FAIL curl-error: $(echo "$resp" | head -c 200)"
        rm -f "$wav"
        return 1
    }
    rm -f "$wav"
    if echo "$resp" | grep -q '"text"'; then
        log "stt OK"
        return 0
    fi
    log "stt FAIL malformed response: $(echo "$resp" | head -c 200)"
    return 1
}

check_mic_permissions_note() {
    # Микрофон физически живёт на телефоне — с сервера проверить нельзя.
    # Andoird-сторож (HermesListenerService.selfCheck) пишет в /data/data/
    # com.troika.hermes_assistant/files/watchdog.log — читать через adb pull.
    :
}

# ─── main ───────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG")"
log "=== watchdog run ==="

if [ -z "$KEY" ]; then
    log "CONFIG ERROR: set TROIKA_API_KEY (or API_SERVER_KEY) before running production checks"
    notify "watchdog не настроен: нет API ключа"
    exit 2
fi

check_container || {
    check_container || exit 1
}

if ! check_health; then
    restart_container "no /health"
    check_health || {
        notify "после рестарта /health всё ещё лежит — нужна ручная проверка"
        exit 1
    }
fi

if ! check_brain; then
    restart_container "brain silent"
    # Второй шанс после рестарта — мозг мог зависнуть, а не сам сервер.
    check_brain || notify "после рестарта мозг всё ещё не отвечает — проверить провайдера (Groq/OpenRouter/Tor)"
fi

if ! check_stt; then
    notify "STT (faster-whisper) не отвечает — рестартю $CONTAINER"
    restart_container "stt dead"
    check_stt || notify "STT всё ещё лежит после рестарта — проверить /opt/data/pylib и PYTHONPATH"
fi

log "=== done ==="
