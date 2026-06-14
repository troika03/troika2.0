#!/usr/bin/env bash
# Тройка — установщик для VPS/Linux
# Использование: curl -fsSL https://raw.githubusercontent.com/troika03/troika/main/install.sh | bash
#
# Что делает:
#   1. Проверяет Docker и Docker Compose
#   2. Скачивает docker-compose.troika.yml + .env.example
#   3. Спрашивает API-ключи и пишет .env (chmod 600)
#   4. Тянет образ и поднимает контейнер
#   5. Ждёт /health и показывает красивый финальный экран с адресом + QR

set -euo pipefail

TROIKA_DIR="${TROIKA_INSTALL_DIR:-$HOME/troika}"
BASE_URL="https://raw.githubusercontent.com/troika03/troika/main"
COMPOSE_URL="$BASE_URL/docker-compose.troika.yml"
ENV_EXAMPLE_URL="$BASE_URL/.env.troika.example"

# ---------- Палитра ----------
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
    RED='\033[0;31m';   GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m';  CYAN='\033[0;36m';  MAGENTA='\033[0;35m'
    GREY='\033[0;90m';  BOLD='\033[1m';     DIM='\033[2m';  NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; MAGENTA=''
    GREY=''; BOLD=''; DIM=''; NC=''
fi

# ---------- ввод/вывод ----------
# Читаем из терминала даже когда скрипт пришёл через `curl | bash` (stdin занят пайпом)
if [ -e /dev/tty ]; then TTY=/dev/tty; else TTY=/dev/stdin; fi

info()    { printf "${CYAN}❯${NC} %b\n" "$*"; }
success() { printf "${GREEN}✓${NC} %b\n" "$*"; }
warn()    { printf "${YELLOW}!${NC} %b\n" "$*"; }
error()   { printf "${RED}✗ %b${NC}\n" "$*" >&2; exit 1; }
step()    { printf "\n${BOLD}${BLUE}[%s/%s]${NC} ${BOLD}%b${NC}\n" "$1" "$TOTAL_STEPS" "$2"; }
rule()    { printf "${GREY}────────────────────────────────────────────────${NC}\n"; }

TOTAL_STEPS=4

# ---------- Спиннер для долгих операций ----------
# spin <команда...>  — крутит спиннер, пишет лог во временный файл,
# при ошибке выводит хвост лога.
spin() {
    local msg="$1"; shift
    local logf; logf="$(mktemp)"
    ( "$@" >"$logf" 2>&1 ) &
    local pid=$!
    local frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    if [ -t 1 ]; then
        while kill -0 "$pid" 2>/dev/null; do
            i=$(( (i+1) % ${#frames} ))
            printf "\r${CYAN}%s${NC} %s " "${frames:$i:1}" "$msg"
            sleep 0.1
        done
    else
        printf "  %s ...\n" "$msg"
    fi
    wait "$pid"; local rc=$?
    if [ "$rc" -eq 0 ]; then
        printf "\r${GREEN}✓${NC} %s    \n" "$msg"
    else
        printf "\r${RED}✗${NC} %s\n" "$msg"
        printf "${GREY}%s${NC}\n" "$(tail -n 15 "$logf")"
        rm -f "$logf"
        exit 1
    fi
    rm -f "$logf"
}

# ---------- Заставка ----------
banner() {
    printf "\n"
    printf "${BOLD}${MAGENTA}    ╔╦╗┬─┐┌─┐┬┌─┌─┐${NC}\n"
    printf "${BOLD}${MAGENTA}     ║ ├┬┘│ │├┴┐├─┤${NC}   ${DIM}голосовой ИИ-ассистент${NC}\n"
    printf "${BOLD}${MAGENTA}     ╩ ┴└─└─┘┴ ┴┴ ┴${NC}   ${DIM}на твоём сервере${NC}\n"
    printf "\n"
    rule
}

banner

# ════════════════════════════════════════════════════════
# Шаг 1 — Проверка окружения
# ════════════════════════════════════════════════════════
step 1 "Проверка окружения"

if ! command -v docker &>/dev/null; then
    error "Docker не найден.\n    Поставь: ${CYAN}curl -fsSL https://get.docker.com | sh${NC}"
fi
if ! docker info &>/dev/null; then
    error "Docker не запущен или нет прав.\n    Запусти: ${CYAN}sudo systemctl start docker${NC}\n    Либо:    ${CYAN}sudo usermod -aG docker \$USER${NC} и перезайди в сессию"
fi

if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif docker-compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    error "Docker Compose не найден.\n    Поставь: https://docs.docker.com/compose/install/"
fi

if ! command -v curl &>/dev/null; then
    error "curl не найден. Поставь: ${CYAN}apt install curl${NC}"
fi

success "Docker      ${DIM}$(docker --version | sed 's/,.*//')${NC}"
success "Compose     ${DIM}$($COMPOSE_CMD version --short 2>/dev/null || echo ok)${NC}"

# ════════════════════════════════════════════════════════
# Шаг 2 — Загрузка конфигурации
# ════════════════════════════════════════════════════════
step 2 "Загрузка конфигурации"

info "Папка установки: ${BOLD}$TROIKA_DIR${NC}"
mkdir -p "$TROIKA_DIR"
cd "$TROIKA_DIR"

spin "Скачиваю docker-compose.troika.yml" curl -fsSL "$COMPOSE_URL" -o docker-compose.troika.yml
spin "Скачиваю шаблон .env"               curl -fsSL "$ENV_EXAMPLE_URL" -o .env.example

# ════════════════════════════════════════════════════════
# Шаг 3 — Настройка ключей
# ════════════════════════════════════════════════════════
step 3 "Настройка API-ключей"

if [ -f .env ]; then
    warn ".env уже есть — пропускаю ввод ключей"
    warn "Чтобы перенастроить: ${CYAN}rm $TROIKA_DIR/.env${NC} и запусти установщик снова"
else
    printf "${DIM}  Ключи нигде не сохраняются кроме локального .env (chmod 600).${NC}\n\n"

    # --- Anthropic (обязательно) ---
    printf "  ${BOLD}1) Anthropic API key${NC}  ${RED}(обязательно)${NC}\n"
    printf "     ${DIM}Основной мозг + кодер Claude. Ключ: https://console.anthropic.com/keys${NC}\n"
    printf "     ${BOLD}ANTHROPIC_API_KEY:${NC} "
    read -r ANTHROPIC_KEY < "$TTY"
    [ -z "$ANTHROPIC_KEY" ] && error "Без Anthropic API key Тройка не запустится."

    # --- Groq (голос) ---
    printf "\n  ${BOLD}2) Groq API key${NC}  ${YELLOW}(для голоса)${NC}\n"
    printf "     ${DIM}Распознавание речи, бесплатно: https://console.groq.com/keys${NC}\n"
    printf "     ${DIM}Пропустишь — будет работать текстовый чат, голос нет.${NC}\n"
    printf "     ${BOLD}GROQ_API_KEY${NC} ${DIM}(Enter — пропустить):${NC} "
    read -r GROQ_KEY < "$TTY"

    # --- OpenRouter (опц.) ---
    printf "\n  ${BOLD}3) OpenRouter API key${NC}  ${DIM}(опционально)${NC}\n"
    printf "     ${DIM}Резервные модели (GPT, Gemini…): https://openrouter.ai/keys${NC}\n"
    printf "     ${BOLD}OPENROUTER_API_KEY${NC} ${DIM}(Enter — пропустить):${NC} "
    read -r OPENROUTER_KEY < "$TTY"

    # --- API-ключ для приложения (по умолчанию hermes-2024) ---
    printf "\n  ${BOLD}4) Пароль доступа${NC}  ${DIM}(для приложения и API)${NC}\n"
    printf "     ${DIM}Этот же ключ вводишь в приложении. Enter — оставить hermes-2024.${NC}\n"
    printf "     ${BOLD}API_SERVER_KEY${NC} ${DIM}(Enter — hermes-2024):${NC} "
    read -r SERVER_KEY < "$TTY"
    [ -z "$SERVER_KEY" ] && SERVER_KEY="hermes-2024"

    # --- Пишем .env ---
    set_kv() {  # set_kv KEY VALUE
        local k="$1" v="$2"
        if grep -qE "^#?\s*${k}=" .env 2>/dev/null; then
            sed -i "s|^#\?\s*${k}=.*|${k}=${v}|" .env
        else
            printf '%s=%s\n' "$k" "$v" >> .env
        fi
    }

    cp .env.example .env
    set_kv ANTHROPIC_API_KEY "$ANTHROPIC_KEY"
    [ -n "$GROQ_KEY" ]       && set_kv GROQ_API_KEY       "$GROQ_KEY"
    [ -n "$OPENROUTER_KEY" ] && set_kv OPENROUTER_API_KEY "$OPENROUTER_KEY"
    set_kv API_SERVER_KEY "$SERVER_KEY"
    set_kv STT_BACKEND "groq"

    chmod 600 .env
    printf "\n"
    success ".env записан ${DIM}(права 600)${NC}"
fi

# ════════════════════════════════════════════════════════
# Шаг 4 — Запуск
# ════════════════════════════════════════════════════════
step 4 "Запуск Тройки"

spin "Тяну образ troika69/troika ${DIM}(первый раз — пара минут)${NC}" \
    $COMPOSE_CMD -f docker-compose.troika.yml pull
spin "Поднимаю контейнер" \
    $COMPOSE_CMD -f docker-compose.troika.yml up -d

# --- Ждём /health красивым прогресс-баром ---
printf "\n  ${BOLD}Жду готовности gateway${NC} ${DIM}(до 90с)${NC}\n  "
WAIT=0; MAXW=90; READY=0
while [ "$WAIT" -lt "$MAXW" ]; do
    if curl -sf http://localhost:8642/health &>/dev/null; then READY=1; break; fi
    # прогресс-бар
    FILLED=$(( WAIT * 30 / MAXW ))
    BAR=""
    for _ in $(seq 1 "$FILLED");          do BAR="${BAR}█"; done
    for _ in $(seq 1 $((30 - FILLED)));   do BAR="${BAR}░"; done
    printf "\r  ${CYAN}%s${NC} %ss " "$BAR" "$WAIT"
    sleep 3; WAIT=$((WAIT+3))
done
printf "\n"

if [ "$READY" -eq 1 ]; then
    success "Gateway отвечает — Тройка живая!"
else
    warn "Gateway пока молчит. Проверь логи и повтори через минуту:"
    warn "  ${CYAN}$COMPOSE_CMD -f docker-compose.troika.yml logs -f${NC}"
fi

# ════════════════════════════════════════════════════════
# Финал
# ════════════════════════════════════════════════════════
SERVER_IP="$(curl -sf --max-time 5 https://api.ipify.org 2>/dev/null \
            || hostname -I 2>/dev/null | awk '{print $1}' \
            || echo '<IP-сервера>')"
ADDR="http://${SERVER_IP}:8642"

printf "\n"
rule
printf "${BOLD}${GREEN}  ✓ Тройка установлена и запущена${NC}\n"
rule
printf "\n"
printf "  ${BOLD}Адрес для приложения${NC}\n"
printf "  ${GREEN}${BOLD}%s${NC}\n" "$ADDR"
printf "  ${DIM}Вбей этот адрес в приложении Тройка → Настройки → URL сервера${NC}\n\n"

# QR-код адреса — если в контейнере есть qrencode/python-qrcode, рисуем
if command -v qrencode &>/dev/null; then
    printf "  ${DIM}Или отсканируй QR:${NC}\n"
    qrencode -t ANSIUTF8 "$ADDR" | sed 's/^/  /'
    printf "\n"
fi

printf "  ${BOLD}${YELLOW}Важно — открой порты на firewall VPS:${NC}\n"
printf "    ${CYAN}8642${NC} ${DIM}— gateway (чат, голос, управление телефоном)${NC}\n"
printf "    ${CYAN}8643${NC} ${DIM}— распознавание речи (телефон шлёт сюда аудио)${NC}\n"
printf "  ${DIM}ufw: ${NC}${CYAN}sudo ufw allow 8642 && sudo ufw allow 8643${NC}\n\n"

printf "  ${BOLD}Вход кодеров по подписке${NC} ${DIM}(один раз, интерактивно):${NC}\n"
printf "    ${CYAN}docker exec -it troika claude${NC}  ${DIM}→ /login  (подписка Claude)${NC}\n"
printf "    ${CYAN}docker exec -it troika gemini${NC}  ${DIM}→ войти в Google${NC}\n\n"

printf "  ${BOLD}Управление${NC}\n"
printf "    ${DIM}логи:${NC}     ${CYAN}cd %s && %s -f docker-compose.troika.yml logs -f${NC}\n" "$TROIKA_DIR" "$COMPOSE_CMD"
printf "    ${DIM}стоп:${NC}     ${CYAN}%s -f docker-compose.troika.yml down${NC}\n" "$COMPOSE_CMD"
printf "    ${DIM}обновить:${NC} ${CYAN}%s -f docker-compose.troika.yml pull && %s -f docker-compose.troika.yml up -d${NC}\n" "$COMPOSE_CMD" "$COMPOSE_CMD"
printf "\n"
rule
printf "${DIM}  Файлы: %s${NC}\n\n" "$TROIKA_DIR"
