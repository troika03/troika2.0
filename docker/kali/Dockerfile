# Kali-стол Тройки — изолированное окружение для пентеста СВОИХ систем.
# Сборка на сервере:  docker build -t troika-kali:latest docker/kali/
#
# Образ headless (без GUI) — Тройка работает командами через терминал.
# Полный арсенал ставится через kali-linux-headless. Если образ слишком
# жирный/долго качается — замени метапакет на точечный список (см. ниже).

FROM kalilinux/kali-rolling

# Неинтерактивная установка, чтобы apt не висел на промптах.
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    # Полный headless-арсенал Kali. Жирно (~2-3 ГБ), но «всё включено».
    apt-get install -y --no-install-recommends \
        kali-linux-headless \
        # инструменты, которые иногда не входят в headless-метапакет:
        nmap masscan sqlmap nikto gobuster ffuf hydra \
        dnsutils whois netcat-traditional curl wget iproute2 iputils-ping \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Рабочая папка — сюда монтируется том /work (результаты переживают recreate).
WORKDIR /work

# Контейнер живёт фоном; Тройка исполняет команды через docker exec
# (это делает её terminal docker-backend, не нужно CMD-логики тут).
# Оставляем дефолтный shell — backend сам управляет жизненным циклом.

# --- Облегчённый вариант (если kali-linux-headless избыточен) -----------------
# Закомментируй блок выше и используй только точечный список:
#   RUN apt-get update && apt-get install -y --no-install-recommends \
#       nmap masscan sqlmap nikto gobuster ffuf hydra nuclei \
#       dnsutils whois netcat-traditional curl wget iproute2 \
#       seclists ca-certificates && \
#       apt-get clean && rm -rf /var/lib/apt/lists/*
