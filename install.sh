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

# sudo-обёртка: если не root и sudo есть — используем его
if [ "$(id -u)" -eq 0 ]; then SUDO=""; elif command -v sudo &>/dev/null; then SUDO="sudo"; else SUDO=""; fi

if ! command -v curl &>/dev/null; then
    error "curl не найден. Поставь: ${CYAN}apt install curl${NC}"
fi

# --- Docker: если нет — ставим сам ---
if ! command -v docker &>/dev/null; then
    warn "Docker не найден — ставлю автоматически"
    spin "Устанавливаю Docker (curl get.docker.com)" sh -c "curl -fsSL https://get.docker.com | $SUDO sh"
    # Запускаем демон (на systemd-системах)
    $SUDO systemctl enable --now docker &>/dev/null || $SUDO service docker start &>/dev/null || true
fi

# --- Демон запущен? ---
if ! docker info &>/dev/null 2>&1; then
    $SUDO systemctl start docker &>/dev/null || $SUDO service docker start &>/dev/null || true
    sleep 2
fi
if ! docker info &>/dev/null 2>&1; then
    # Возможно не хватает прав — пробуем через sudo на весь дальнейший docker
    if [ -n "$SUDO" ] && $SUDO docker info &>/dev/null 2>&1; then
        DOCKER="$SUDO docker"
    else
        error "Docker установлен, но демон не отвечает.\n    Запусти: ${CYAN}${SUDO} systemctl start docker${NC} и повтори установку"
    fi
else
    DOCKER="docker"
fi

# --- Compose (plugin или legacy) ---
if $DOCKER compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="$DOCKER compose"
elif command -v docker-compose &>/dev/null 2>&1; then
    COMPOSE_CMD="${SUDO} docker-compose"
else
    # get.docker.com уже ставит compose-plugin; если вдруг нет — доставим
    warn "Docker Compose не найден — доставляю plugin"
    spin "Ставлю docker-compose-plugin" sh -c "$SUDO apt-get update -qq && $SUDO apt-get install -y -qq docker-compose-plugin" || true
    if $DOCKER compose version &>/dev/null 2>&1; then
        COMPOSE_CMD="$DOCKER compose"
    else
        error "Не удалось поставить Docker Compose.\n    Поставь вручную: https://docs.docker.com/compose/install/"
    fi
fi

success "Docker      ${DIM}$($DOCKER --version | sed 's/,.*//')${NC}"
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

    # --- Anthropic (основной мозг + кодер Claude) ---
    printf "  ${BOLD}1) Anthropic API key${NC}  ${GREEN}(рекомендуется)${NC}\n"
    printf "     ${DIM}Основной мозг + кодер Claude. Ключ: https://console.anthropic.com/keys${NC}\n"
    printf "     ${DIM}Можно пропустить, если задашь другого провайдера ниже.${NC}\n"
    printf "     ${BOLD}ANTHROPIC_API_KEY${NC} ${DIM}(Enter — пропустить):${NC} "
    read -r ANTHROPIC_KEY < "$TTY"

    # --- Groq (голос) ---
    printf "\n  ${BOLD}2) Groq API key${NC}  ${YELLOW}(для голоса)${NC}\n"
    printf "     ${DIM}Распознавание речи, бесплатно: https://console.groq.com/keys${NC}\n"
    printf "     ${DIM}Пропустишь — будет работать текстовый чат, голос нет.${NC}\n"
    printf "     ${BOLD}GROQ_API_KEY${NC} ${DIM}(Enter — пропустить):${NC} "
    read -r GROQ_KEY < "$TTY"

    # --- Доп. провайдеры «мозга» (по желанию) ---
    # Имя_переменной | Подпись | Где взять ключ
    PROVIDERS="
OPENROUTER_API_KEY|OpenRouter (один ключ — сотни моделей)|https://openrouter.ai/keys
OPENAI_API_KEY|OpenAI (GPT-4o, o1, o3)|https://platform.openai.com/api-keys
GEMINI_API_KEY|Google Gemini (2.5/3 Pro, Flash)|https://aistudio.google.com/app/apikey
XAI_API_KEY|xAI Grok|https://console.x.ai
DEEPSEEK_API_KEY|DeepSeek (дёшево, силён в коде)|https://platform.deepseek.com/api_keys
MISTRAL_API_KEY|Mistral|https://console.mistral.ai/api-keys
"
    printf "\n  ${BOLD}3) Другие провайдеры мозга${NC} ${DIM}(по желанию — Enter пропускает каждый)${NC}\n"
    printf "     ${DIM}Любой можно добавить/поменять и потом в %s/.env${NC}\n" "$TROIKA_DIR"
    rm -f /tmp/troika_extra_keys   # чистим от прошлого запуска
    printf '%s\n' "$PROVIDERS" | while IFS='|' read -r VAR LABEL URL; do
        [ -z "$VAR" ] && continue
        printf "     ${BOLD}%s${NC} ${DIM}— %s${NC}\n" "$LABEL" "$URL"
        printf "       ${BOLD}%s${NC} ${DIM}(Enter — пропустить):${NC} " "$VAR"
        read -r VAL < "$TTY"
        [ -n "$VAL" ] && printf '%s=%s\n' "$VAR" "$VAL" >> /tmp/troika_extra_keys
    done

    # --- API-ключ для приложения (unique per installation) ---
    printf "\n  ${BOLD}4) Пароль доступа${NC}  ${DIM}(для приложения и API)${NC}\n"
    printf "     ${DIM}Этот же ключ вводишь в приложении. Enter — создать случайный ключ.${NC}\n"
    printf "     ${BOLD}API_SERVER_KEY${NC} ${DIM}(Enter — сгенерировать):${NC} "
    read -r SERVER_KEY < "$TTY"
    if [ -z "$SERVER_KEY" ]; then
        if command -v openssl >/dev/null 2>&1; then
            SERVER_KEY="$(openssl rand -hex 32)"
        else
            SERVER_KEY="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
        fi
        printf "     ${GREEN}Создан уникальный ключ. Сохрани его: он понадобится приложению.${NC}\n"
    fi
    case "${SERVER_KEY}" in
        hermes-2024|your_api_key|your_api_key_here|changeme|placeholder)
            error "API_SERVER_KEY содержит опубликованный шаблон. Укажи свой ключ или нажми Enter для генерации."
            ;;
    esac

    # --- Проверка: хоть один мозг должен быть ---
    if [ -z "$ANTHROPIC_KEY" ] && [ ! -s /tmp/troika_extra_keys ]; then
        rm -f /tmp/troika_extra_keys
        error "Не задан ни один провайдер мозга.\n    Нужен хотя бы Anthropic ИЛИ один из доп. провайдеров (шаг 3)."
    fi

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
    [ -n "$ANTHROPIC_KEY" ]   && set_kv ANTHROPIC_API_KEY "$ANTHROPIC_KEY"
    [ -n "$GROQ_KEY" ]        && set_kv GROQ_API_KEY      "$GROQ_KEY"
    # доп. провайдеры из временного файла
    if [ -s /tmp/troika_extra_keys ]; then
        while IFS='=' read -r VAR VAL; do
            [ -n "$VAR" ] && set_kv "$VAR" "$VAL"
        done < /tmp/troika_extra_keys
    fi
    rm -f /tmp/troika_extra_keys
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

# --- Автооткрытие портов на локальном firewall ---
# Телефон стучится на 8642 (gateway) и 8643 (STT). Без открытых портов
# приложение не подключится. Открываем сами, тихо и идемпотентно.
open_ports() {
    # ufw (Ubuntu/Debian)
    if command -v ufw &>/dev/null && $SUDO ufw status 2>/dev/null | grep -qi "Status: active"; then
        $SUDO ufw allow 8642/tcp &>/dev/null || true
        $SUDO ufw allow 8643/tcp &>/dev/null || true
        return 0
    fi
    # firewalld (CentOS/RHEL/Fedora)
    if command -v firewall-cmd &>/dev/null && $SUDO firewall-cmd --state &>/dev/null 2>&1; then
        $SUDO firewall-cmd --permanent --add-port=8642/tcp &>/dev/null || true
        $SUDO firewall-cmd --permanent --add-port=8643/tcp &>/dev/null || true
        $SUDO firewall-cmd --reload &>/dev/null || true
        return 0
    fi
    return 1
}
if open_ports; then
    success "Порты 8642/8643 открыты на firewall"
    FW_OK=1
else
    FW_OK=0   # активного firewall нет — порты и так доступны
fi

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
# Вход кодеров по подписке (интерактивно, сразу)
# ════════════════════════════════════════════════════════
# Кодер (claude/gemini CLI) работает по ПОДПИСКЕ — нужен один интерактивный
# логин внутри контейнера. Предлагаем сделать прямо сейчас, пока есть TTY.
if [ "$READY" -eq 1 ] && [ -e /dev/tty ]; then
    printf "\n  ${BOLD}Вход кодеров по подписке${NC} ${DIM}(чтобы Тройка могла писать код)${NC}\n"
    printf "  ${DIM}claude/gemini CLI просят войти один раз. Можно сейчас или потом.${NC}\n"
    printf "  ${BOLD}Залогинить кодеры сейчас? [Y/n]:${NC} "
    read -r DO_LOGIN < "$TTY"
    case "${DO_LOGIN:-y}" in
        [Nn]*)
            warn "Пропущено. Потом: ${CYAN}$DOCKER exec -it troika claude${NC} → /login"
            ;;
        *)
            printf "\n  ${CYAN}→ Claude${NC} ${DIM}(в открывшемся CLI набери /login и следуй ссылке)${NC}\n"
            $DOCKER exec -it troika claude < /dev/tty || \
                warn "claude-login прерван — повторишь позже: ${CYAN}$DOCKER exec -it troika claude${NC}"
            printf "\n  ${CYAN}→ Gemini${NC} ${DIM}(войди в Google-аккаунт по ссылке)${NC}\n"
            $DOCKER exec -it troika gemini < /dev/tty || \
                warn "gemini-login прерван — повторишь позже: ${CYAN}$DOCKER exec -it troika gemini${NC}"
            ;;
    esac
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

if [ "${FW_OK:-0}" = "1" ]; then
    printf "  ${GREEN}✓${NC} Порты 8642/8643 открыты автоматически\n"
else
    printf "  ${DIM}Локального firewall нет — порты 8642/8643 уже доступны.${NC}\n"
fi
printf "  ${DIM}Если у провайдера есть ВНЕШНИЙ firewall (панель VPS) —${NC}\n"
printf "  ${DIM}разреши там TCP 8642 и 8643.${NC}\n\n"

printf "  ${BOLD}Управление${NC}\n"
printf "    ${DIM}логи:${NC}     ${CYAN}cd %s && %s -f docker-compose.troika.yml logs -f${NC}\n" "$TROIKA_DIR" "$COMPOSE_CMD"
printf "    ${DIM}стоп:${NC}     ${CYAN}%s -f docker-compose.troika.yml down${NC}\n" "$COMPOSE_CMD"
printf "    ${DIM}обновить:${NC} ${CYAN}%s -f docker-compose.troika.yml pull && %s -f docker-compose.troika.yml up -d${NC}\n" "$COMPOSE_CMD" "$COMPOSE_CMD"
printf "\n"
rule
printf "${DIM}  Файлы: %s${NC}\n\n" "$TROIKA_DIR"
