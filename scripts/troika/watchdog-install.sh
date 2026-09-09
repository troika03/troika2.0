#!/usr/bin/env bash
# Установка watchdog в crontab. Запускать на сервере под root.
#   bash scripts/troika/watchdog-install.sh
# По умолчанию — каждые 2 часа. Меняется первым аргументом (cron-выражение):
#   bash scripts/troika/watchdog-install.sh '0 */3 * * *'   # каждые 3 часа
#   bash scripts/troika/watchdog-install.sh '*/30 * * * *'  # каждые 30 минут

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WATCHDOG="$SCRIPT_DIR/watchdog.sh"
CRON_EXPR="${1:-0 */2 * * *}"
# Лог: по умолчанию в home пользователя, для root — в /var/log.
# Можно переопределить: TROIKA_LOG=/path/to.log bash watchdog-install.sh
if [ -n "${TROIKA_LOG:-}" ]; then
    LOG="$TROIKA_LOG"
elif [ "$(id -u)" = "0" ]; then
    LOG="/var/log/troika-watchdog.log"
else
    LOG="$HOME/troika-watchdog.log"
fi

if [ ! -x "$WATCHDOG" ]; then
    chmod +x "$WATCHDOG"
fi

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
touch "$LOG" 2>/dev/null || {
    echo "Не могу писать в $LOG — запусти с sudo или задай TROIKA_LOG=~/troika-watchdog.log" >&2
    exit 1
}

# Убираем старую запись и добавляем свежую.
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'troika/watchdog.sh' > "$TMP" || true
echo "$CRON_EXPR $WATCHDOG >> $LOG 2>&1" >> "$TMP"
crontab "$TMP"
rm "$TMP"

echo "Установлено: $CRON_EXPR $WATCHDOG"
echo "Лог: $LOG"
echo
echo "Первый прогон вручную (проверить что всё работает):"
echo "  $WATCHDOG"
