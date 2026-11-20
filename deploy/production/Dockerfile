FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie@sha256:b3c543b6c4f23a5f2df22866bd7857e5d304b67a564f4feab6ac22044dde719b

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HERMES_HOME=/opt/troika \
    HOME=/opt/troika \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN touch README.md \
    && uv sync --frozen --no-install-project --extra messaging --extra edge-tts --extra product-voice --extra mcp

COPY . .
RUN uv pip install --no-cache-dir --no-deps -e .

EXPOSE 8765
CMD ["hermes", "gateway", "run"]
