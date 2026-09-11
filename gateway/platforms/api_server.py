"""
OpenAI-compatible API server platform adapter.

Exposes an HTTP server with endpoints:
- POST /v1/chat/completions        — OpenAI Chat Completions format (stateless; opt-in session continuity via X-Hermes-Session-Id header; opt-in long-term memory scoping via X-Hermes-Session-Key header)
- POST /v1/responses               — OpenAI Responses API format (stateful via previous_response_id; X-Hermes-Session-Key supported)
- GET  /v1/responses/{response_id} — Retrieve a stored response
- DELETE /v1/responses/{response_id} — Delete a stored response
- GET  /v1/models                  — lists hermes-agent as an available model
- GET  /v1/capabilities            — machine-readable API capabilities for external UIs
- POST /v1/runs                    — start a run, returns run_id immediately (202)
- GET  /v1/runs/{run_id}           — retrieve current run status
- GET  /v1/runs/{run_id}/events    — SSE stream of structured lifecycle events
- POST /v1/runs/{run_id}/approval — resolve a pending run approval
- POST /v1/runs/{run_id}/stop       — interrupt a running agent
- GET  /health                     — health check
- GET  /health/detailed            — rich status for cross-container dashboard probing

Any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat,
AnythingLLM, NextChat, ChatBox, etc.) can connect to hermes-agent
through this adapter by pointing at http://localhost:8642/v1.

Requires:
- aiohttp (already available in the gateway)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket as _socket
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    SendResult,
    is_network_accessible,
)

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
MAX_STORED_RESPONSES = 100
MAX_REQUEST_BYTES = 10_000_000  # 10 MB — accommodates long agent conversations with tool calls
CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS = 30.0
MAX_NORMALIZED_TEXT_LENGTH = 65_536  # 64 KB cap for normalized content parts
MAX_CONTENT_LIST_SIZE = 1_000  # Max items when content is an array


def _coerce_port(value: Any, default: int = DEFAULT_PORT) -> int:
    """Parse a listen port without letting malformed env/config values crash startup."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_TRUE_REQUEST_BOOL_STRINGS = frozenset({"1", "true", "yes", "on"})
_FALSE_REQUEST_BOOL_STRINGS = frozenset({"0", "false", "no", "off"})


def _coerce_request_bool(value: Any, default: bool = False) -> bool:
    """Normalize boolean-like API payload values.

    External clients should send real JSON booleans, but some OpenAI-compatible
    frontends and middleware serialize flags like ``stream`` as strings.  Using
    Python truthiness on those values misroutes requests because ``"false"`` is
    still truthy.  Treat only explicit bool-ish scalars as booleans; everything
    else falls back to the caller's default.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_REQUEST_BOOL_STRINGS:
            return True
        if normalized in _FALSE_REQUEST_BOOL_STRINGS:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_config_bool(value: Any, default: bool = False) -> bool:
    """Interpret config/env booleans without treating ``'false'`` as true."""
    return _coerce_request_bool(value, default=default)


def _normalize_chat_content(
    content: Any, *, _max_depth: int = 10, _depth: int = 0,
) -> str:
    """Normalize OpenAI chat message content into a plain text string.

    Some clients (Open WebUI, LobeChat, etc.) send content as an array of
    typed parts instead of a plain string::

        [{"type": "text", "text": "hello"}, {"type": "input_text", "text": "..."}]

    This function flattens those into a single string so the agent pipeline
    (which expects strings) doesn't choke.

    Defensive limits prevent abuse: recursion depth, list size, and output
    length are all bounded.
    """
    if _depth > _max_depth:
        return ""
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:MAX_NORMALIZED_TEXT_LENGTH] if len(content) > MAX_NORMALIZED_TEXT_LENGTH else content

    if isinstance(content, list):
        parts: List[str] = []
        items = content[:MAX_CONTENT_LIST_SIZE] if len(content) > MAX_CONTENT_LIST_SIZE else content
        for item in items:
            if isinstance(item, str):
                if item:
                    parts.append(item[:MAX_NORMALIZED_TEXT_LENGTH])
            elif isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type in {"text", "input_text", "output_text"}:
                    text = item.get("text", "")
                    if text:
                        try:
                            parts.append(str(text)[:MAX_NORMALIZED_TEXT_LENGTH])
                        except Exception:
                            pass
                # Silently skip image_url / other non-text parts
            elif isinstance(item, list):
                nested = _normalize_chat_content(item, _max_depth=_max_depth, _depth=_depth + 1)
                if nested:
                    parts.append(nested)
            # Check accumulated size
            if sum(len(p) for p in parts) >= MAX_NORMALIZED_TEXT_LENGTH:
                break
        result = "\n".join(parts)
        return result[:MAX_NORMALIZED_TEXT_LENGTH] if len(result) > MAX_NORMALIZED_TEXT_LENGTH else result

    # Fallback for unexpected types (int, float, bool, etc.)
    try:
        result = str(content)
        return result[:MAX_NORMALIZED_TEXT_LENGTH] if len(result) > MAX_NORMALIZED_TEXT_LENGTH else result
    except Exception:
        return ""


# Content part type aliases used by the OpenAI Chat Completions and Responses
# APIs.  We accept both spellings on input and emit a single canonical internal
# shape (``{"type": "text", ...}`` / ``{"type": "image_url", ...}``) that the
# rest of the agent pipeline already understands.
_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
_IMAGE_PART_TYPES = frozenset({"image_url", "input_image"})
_FILE_PART_TYPES = frozenset({"file", "input_file"})


def _normalize_multimodal_content(content: Any) -> Any:
    """Validate and normalize multimodal content for the API server.

    Returns a plain string when the content is text-only, or a list of
    ``{"type": "text"|"image_url", ...}`` parts when images are present.
    The output shape is the native OpenAI Chat Completions vision format,
    which the agent pipeline accepts verbatim (OpenAI-wire providers) or
    converts (``_preprocess_anthropic_content`` for Anthropic).

    Raises ``ValueError`` with an OpenAI-style code on invalid input:
      * ``unsupported_content_type`` — file/input_file/file_id parts, or
        non-image ``data:`` URLs.
      * ``invalid_image_url`` — missing URL or unsupported scheme.
      * ``invalid_content_part`` — malformed text/image objects.

    Callers translate the ValueError into a 400 response.
    """
    # Scalar passthrough mirrors ``_normalize_chat_content``.
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:MAX_NORMALIZED_TEXT_LENGTH] if len(content) > MAX_NORMALIZED_TEXT_LENGTH else content
    if not isinstance(content, list):
        # Mirror the legacy text-normalizer's fallback so callers that
        # pre-existed image support still get a string back.
        return _normalize_chat_content(content)

    items = content[:MAX_CONTENT_LIST_SIZE] if len(content) > MAX_CONTENT_LIST_SIZE else content
    normalized_parts: List[Dict[str, Any]] = []
    text_accum_len = 0

    for part in items:
        if isinstance(part, str):
            if part:
                trimmed = part[:MAX_NORMALIZED_TEXT_LENGTH]
                normalized_parts.append({"type": "text", "text": trimmed})
                text_accum_len += len(trimmed)
            continue

        if not isinstance(part, dict):
            # Ignore unknown scalars for forward compatibility with future
            # Responses API additions (e.g. ``refusal``).  The same policy
            # the text normalizer applies.
            continue

        raw_type = part.get("type")
        part_type = str(raw_type or "").strip().lower()

        if part_type in _TEXT_PART_TYPES:
            text = part.get("text")
            if text is None:
                continue
            if not isinstance(text, str):
                text = str(text)
            if text:
                trimmed = text[:MAX_NORMALIZED_TEXT_LENGTH]
                normalized_parts.append({"type": "text", "text": trimmed})
                text_accum_len += len(trimmed)
            continue

        if part_type in _IMAGE_PART_TYPES:
            detail = part.get("detail")
            image_ref = part.get("image_url")
            # OpenAI Responses sends ``input_image`` with a top-level
            # ``image_url`` string; Chat Completions sends ``image_url`` as
            # ``{"url": "...", "detail": "..."}``.  Support both.
            if isinstance(image_ref, dict):
                url_value = image_ref.get("url")
                detail = image_ref.get("detail", detail)
            else:
                url_value = image_ref
            if not isinstance(url_value, str) or not url_value.strip():
                raise ValueError("invalid_image_url:Image parts must include a non-empty image URL.")
            url_value = url_value.strip()
            lowered = url_value.lower()
            if lowered.startswith("data:"):
                if not lowered.startswith("data:image/") or "," not in url_value:
                    raise ValueError(
                        "unsupported_content_type:Only image data URLs are supported. "
                        "Non-image data payloads are not supported."
                    )
            elif not (lowered.startswith("http://") or lowered.startswith("https://")):
                raise ValueError(
                    "invalid_image_url:Image inputs must use http(s) URLs or data:image/... URLs."
                )
            image_part: Dict[str, Any] = {"type": "image_url", "image_url": {"url": url_value}}
            if detail is not None:
                if not isinstance(detail, str) or not detail.strip():
                    raise ValueError("invalid_content_part:Image detail must be a non-empty string when provided.")
                image_part["image_url"]["detail"] = detail.strip()
            normalized_parts.append(image_part)
            continue

        if part_type in _FILE_PART_TYPES:
            raise ValueError(
                "unsupported_content_type:Inline image inputs are supported, "
                "but uploaded files and document inputs are not supported on this endpoint."
            )

        # Unknown part type — reject explicitly so clients get a clear error
        # instead of a silently dropped turn.
        raise ValueError(
            f"unsupported_content_type:Unsupported content part type {raw_type!r}. "
            "Only text and image_url/input_image parts are supported."
        )

    if not normalized_parts:
        return ""

    # Text-only: collapse to a plain string so downstream logging/trajectory
    # code sees the native shape and prompt caching on text-only turns is
    # unaffected.
    if all(p.get("type") == "text" for p in normalized_parts):
        return "\n".join(p["text"] for p in normalized_parts if p.get("text"))

    return normalized_parts


def _content_has_visible_payload(content: Any) -> bool:
    """True when content has any text or image attachment.  Used to reject empty turns."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type") or "").strip().lower()
                if ptype in _TEXT_PART_TYPES and str(part.get("text") or "").strip():
                    return True
                if ptype in _IMAGE_PART_TYPES:
                    return True
    return False


def _multimodal_validation_error(exc: ValueError, *, param: str) -> "web.Response":
    """Translate a ``_normalize_multimodal_content`` ValueError into a 400 response."""
    raw = str(exc)
    code, _, message = raw.partition(":")
    if not message:
        code, message = "invalid_content_part", raw
    return web.json_response(
        _openai_error(message, code=code, param=param),
        status=400,
    )


def check_api_server_requirements() -> bool:
    """Check if API server dependencies are available."""
    return AIOHTTP_AVAILABLE


class ResponseStore:
    """
    SQLite-backed LRU store for Responses API state.

    Each stored response includes the full internal conversation history
    (with tool calls and results) so it can be reconstructed on subsequent
    requests via previous_response_id.

    Persists across gateway restarts.  Falls back to in-memory SQLite
    if the on-disk path is unavailable.
    """

    def __init__(self, max_size: int = MAX_STORED_RESPONSES, db_path: str = None):
        self._max_size = max_size
        if db_path is None:
            try:
                from hermes_cli.config import get_hermes_home
                db_path = str(get_hermes_home() / "response_store.db")
            except Exception:
                db_path = ":memory:"
        self._db_path: Optional[str] = db_path if db_path != ":memory:" else None
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
        except Exception:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._db_path = None
        # Use shared WAL-fallback helper so response_store.db degrades
        # gracefully on NFS/SMB/FUSE-mounted HERMES_HOME (same filesystem
        # issue addressed for state.db/kanban.db — see
        # hermes_state._WAL_INCOMPAT_MARKERS).
        from hermes_state import apply_wal_with_fallback
        apply_wal_with_fallback(self._conn, db_label="response_store.db")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS responses (
                response_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                accessed_at REAL NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                name TEXT PRIMARY KEY,
                response_id TEXT NOT NULL
            )"""
        )
        self._conn.commit()
        # response_store.db contains conversation history (tool payloads,
        # prompts, results). Tighten to owner-only after creation so other
        # local users on a shared box can't read it. Run once at __init__
        # rather than after every commit — chmod-on-every-write is wasted
        # syscalls on a hot path.
        self._tighten_file_permissions()

    def _tighten_file_permissions(self) -> None:
        """Force owner-only permissions on the DB and SQLite sidecars."""
        if not self._db_path:
            return
        for candidate in (
            Path(self._db_path),
            Path(f"{self._db_path}-wal"),
            Path(f"{self._db_path}-shm"),
        ):
            try:
                if candidate.exists():
                    candidate.chmod(0o600)
            except OSError:
                logger.debug(
                    "Failed to restrict response store permissions for %s",
                    candidate,
                    exc_info=True,
                )

    def get(self, response_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored response by ID (updates access time for LRU)."""
        row = self._conn.execute(
            "SELECT data FROM responses WHERE response_id = ?", (response_id,)
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE responses SET accessed_at = ? WHERE response_id = ?",
            (time.time(), response_id),
        )
        self._conn.commit()
        return json.loads(row[0])

    def put(self, response_id: str, data: Dict[str, Any]) -> None:
        """Store a response, evicting the oldest if at capacity."""
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (response_id, data, accessed_at) VALUES (?, ?, ?)",
            (response_id, json.dumps(data, default=str), time.time()),
        )
        # Evict oldest entries beyond max_size
        count = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        if count > self._max_size:
            # Collect IDs that will be evicted
            evict_ids = [
                row[0]
                for row in self._conn.execute(
                    "SELECT response_id FROM responses ORDER BY accessed_at ASC LIMIT ?",
                    (count - self._max_size,),
                ).fetchall()
            ]
            if evict_ids:
                placeholders = ",".join("?" for _ in evict_ids)
                # Clear conversation mappings pointing to evicted responses
                self._conn.execute(
                    f"DELETE FROM conversations WHERE response_id IN ({placeholders})",
                    evict_ids,
                )
                # Delete evicted responses
                self._conn.execute(
                    f"DELETE FROM responses WHERE response_id IN ({placeholders})",
                    evict_ids,
                )
        self._conn.commit()

    def delete(self, response_id: str) -> bool:
        """Remove a response from the store. Returns True if found and deleted."""
        # Clear conversation mappings pointing to this response
        self._conn.execute(
            "DELETE FROM conversations WHERE response_id = ?", (response_id,)
        )
        cursor = self._conn.execute(
            "DELETE FROM responses WHERE response_id = ?", (response_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_conversation(self, name: str) -> Optional[str]:
        """Get the latest response_id for a conversation name."""
        row = self._conn.execute(
            "SELECT response_id FROM conversations WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def set_conversation(self, name: str, response_id: str) -> None:
        """Map a conversation name to its latest response_id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO conversations (name, response_id) VALUES (?, ?)",
            (name, response_id),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def __len__(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Idempotency-Key",
}


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def cors_middleware(request, handler):
        """Add CORS headers for explicitly allowed origins; handle OPTIONS preflight."""
        adapter = request.app.get("api_server_adapter")
        origin = request.headers.get("Origin", "")
        cors_headers = None
        if adapter is not None:
            if not adapter._origin_allowed(origin):
                return web.Response(status=403)
            cors_headers = adapter._cors_headers_for_origin(origin)

        if request.method == "OPTIONS":
            if cors_headers is None:
                return web.Response(status=403)
            return web.Response(status=200, headers=cors_headers)

        response = await handler(request)
        if cors_headers is not None:
            response.headers.update(cors_headers)
        return response
else:
    cors_middleware = None  # type: ignore[assignment]


def _openai_error(message: str, err_type: str = "invalid_request_error", param: str = None, code: str = None) -> Dict[str, Any]:
    """OpenAI-style error envelope."""
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        }
    }


_TTS_MD_STRIP = re.compile(r"(\*\*|__|`+|^#{1,6}\s+)", re.MULTILINE)
_TTS_MULTISPACE = re.compile(r"[ \t]{2,}")
_TTS_ELLIPSIS = re.compile(r"\.{3,}")
_TTS_DASH_SPACES = re.compile(r"\s*[—–-]\s+")
_TTS_COMMA_BEFORE_CONJ = re.compile(r",\s+(но|однако|зато|а)\b", re.IGNORECASE)
_TTS_PARENS = re.compile(r"\s*\(([^)]{1,80})\)\s*")
_TTS_URL = re.compile(r"https?://\S+")
_TTS_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_TTS_INLINE_CODE = re.compile(r"`([^`]+)`")
_TTS_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_TTS_NUM_LIST = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_TTS_LONG_SENTENCE_COMMA = re.compile(r"([а-яё]{4,}),\s+(что|чтобы|который|которая|которое|которые|если|потому)\b", re.IGNORECASE)


def _naturalize_tts_text(text: str) -> str:
    """Нормализовать текст перед Edge TTS для более живой просодии.

    Edge экранирует <>, поэтому SSML недоступен — управляем интонацией
    через пунктуацию: длинные паузы на точках, мягкие — на тире, очистка
    markdown-артефактов, единообразие троеточий.
    """
    if not text:
        return text
    # Код-блоки и inline-код проговаривать бессмысленно — выкидываем
    t = _TTS_CODE_BLOCK.sub(" … ", text)
    t = _TTS_INLINE_CODE.sub(r"\1", t)
    # URL → «ссылка» (произнесение URL по буквам всё ломает)
    t = _TTS_URL.sub("ссылка", t)
    # Markdown-артефакты
    t = _TTS_MD_STRIP.sub("", t)
    t = _TTS_BULLET.sub("", t)
    t = _TTS_NUM_LIST.sub("", t)
    # Скобки → запятые (Edge произносит круглые скобки буквально иногда)
    t = _TTS_PARENS.sub(r", \1, ", t)
    t = _TTS_ELLIPSIS.sub("…", t)
    t = _TTS_DASH_SPACES.sub(" — ", t)
    # ВАЖНО: НЕ добавляем искусственных пауз. Раньше тут запятые перед «но/а»
    # превращались в точки, а внутри длинных фраз вставлялись тире — это делало
    # речь рубленой, «дикторской». Миша просил плавную речь без больших пауз,
    # поэтому естественную пунктуацию автора оставляем как есть.
    t = _TTS_MULTISPACE.sub(" ", t)
    return t.strip()


# Тоны Тройки: смещения rate/pitch/volume относительно базы. Привязаны к
# IRIS-профилям (см. agent/iris_persona.py), плюс набор чисто-эмоциональных
# тонов, которые мозг помечает тегом [emo:...] в начале ответа.
#
# Раньше сдвиги были крошечными (±2-5 Hz, ±6% скорости) — на слух почти не
# отличить «радость» от «поддержки», голос звучал ровно. Теперь разброс по
# питчу до ±10 Hz, по скорости ±12%, плюс громкость — этого достаточно, чтобы
# эмоция была реально слышна, но без «мультяшности» (Edge всё равно держит
# Светлану в рамках естественности).
#
# Кортеж: (Δrate-множитель, Δpitch-Hz, Δvolume-%).
_TTS_TONES = {
    # — IRIS-профили (общее настроение) —
    "spark":   (1.09,  7,  4),   # бодрый/утро — быстрее, выше, звонче
    "playful": (1.08,  9,  3),   # игривый — живо, заметно выше
    "focus":   (1.04,  0,  0),   # рабочий — собранно, ровно
    "steady":  (1.00,  0,  0),   # нейтральный
    "calm":    (0.92, -4, -3),   # спокойный/вечер — медленнее, мягче, тише
    "support": (0.88, -6, -6),   # поддержка/усталость — тихо, тепло, низко
    # — чисто-эмоциональные тона (мозг помечает [emo:...]) —
    "joy":     (1.10, 10,  6),   # радость/успех — быстро, высоко, громко
    "excited": (1.12, 11,  7),   # восторг — на пике энергии
    "warm":    (0.95,  2, -1),   # нежность/тепло — мягко, чуть выше, неспешно
    "sad":     (0.86, -8, -7),   # грусть/сожаление — медленно, низко, тихо
    "worried": (0.96, -3, -2),   # тревога/беспокойство — собранно, чуть ниже
    "tender":  (0.93,  3, -3),   # ласково/успокаивающе — мягко и тихо
    "proud":   (1.06,  6,  3),   # гордость за результат — уверенно, чуть выше
}

# Алиасы: русские/синонимичные метки, которые может выдать мозг → канон.
_TTS_TONE_ALIASES = {
    "радость": "joy", "рад": "joy", "happy": "joy", "восторг": "excited",
    "грусть": "sad", "грустно": "sad", "жаль": "sad", "sorry": "sad",
    "тепло": "warm", "нежно": "warm", "ласково": "tender",
    "тревога": "worried", "беспокойство": "worried", "worry": "worried",
    "гордость": "proud", "горжусь": "proud",
    "игриво": "playful", "бодро": "spark", "спокойно": "calm",
    "поддержка": "support", "сочувствие": "support",
}

# Тег эмоции от мозга: [emo:joy] / [emo: грусть] в начале ответа. Сервер его
# читает (приоритетнее времени суток) и ВЫРЕЗАЕТ из произносимого текста.
import re as _re_emo
_EMO_TAG_RE = _re_emo.compile(r"\[emo:\s*([a-zа-яё_]+)\s*\]", _re_emo.IGNORECASE)


def _extract_emo_tag(text: str):
    """Вернуть (canon_tone | None, text_без_тега). Тег ищется в любом месте."""
    if not text:
        return None, text
    m = _EMO_TAG_RE.search(text)
    if not m:
        return None, text
    raw = m.group(1).strip().lower()
    canon = raw if raw in _TTS_TONES else _TTS_TONE_ALIASES.get(raw)
    cleaned = _EMO_TAG_RE.sub("", text).strip()
    return canon, cleaned


def _infer_tone_from_text(text: str) -> str:
    """Грубый тон по самой фразе, когда нет явного tone и тега [emo:...]."""
    s = (text or "").strip()
    if not s:
        return "steady"
    low = s.lower()
    # Эмоциональные слова-маркеры — дают живую интонацию даже без тега мозга.
    if any(w in low for w in ("ура", "получилось", "готово!", "отлично", "супер", "класс")):
        return "joy"
    if any(w in low for w in ("жаль", "к сожалению", "увы", "не вышло", "не получилось")):
        return "sad"
    if "!" in s:
        return "spark"          # восклицание — энергичнее
    if s.endswith("?"):
        return "focus"          # вопрос — собранный, интонация вверх делается отдельно
    return "steady"


def _tts_prosody(text: str, tone: Optional[str], base_rate_mult: float,
                 base_pitch_hz: int, base_volume: int = 0):
    """Вернуть (rate_mult, pitch_hz, volume_pct) с учётом тона и типа фразы.

    Реальный человек не говорит всё одним тоном: радость — быстрее, выше и
    громче; грусть — медленно, низко и тихо; вопрос — интонация вверх. Здесь
    это и эмулируется сдвигами rate/pitch/volume поверх базовых параметров.
    """
    t = (tone or "").strip().lower()
    if t not in _TTS_TONES:
        t = _TTS_TONE_ALIASES.get(t) or _infer_tone_from_text(text)
    dr, dp, dv = _TTS_TONES.get(t, (1.0, 0, 0))
    rate_mult = base_rate_mult * dr
    pitch_hz = base_pitch_hz + dp
    volume_pct = base_volume + dv
    # Вопрос — приподнимаем тон в конце (интонация вверх). Edge не даёт SSML,
    # поэтому имитируем общим лёгким подъёмом pitch на вопросительных фразах.
    if (text or "").strip().endswith("?"):
        pitch_hz += 3
    # Клампы в допустимые Edge-диапазоны.
    rate_mult = max(0.5, min(rate_mult, 1.6))
    pitch_hz = max(-30, min(pitch_hz, 30))
    volume_pct = max(-50, min(volume_pct, 30))
    return rate_mult, pitch_hz, volume_pct


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def body_limit_middleware(request, handler):
        """Reject overly large request bodies early based on Content-Length."""
        if request.method in {"POST", "PUT", "PATCH"}:
            cl = request.headers.get("Content-Length")
            if cl is not None:
                try:
                    if int(cl) > MAX_REQUEST_BYTES:
                        return web.json_response(_openai_error("Request body too large.", code="body_too_large"), status=413)
                except ValueError:
                    return web.json_response(_openai_error("Invalid Content-Length header.", code="invalid_content_length"), status=400)
        return await handler(request)
else:
    body_limit_middleware = None  # type: ignore[assignment]

_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
}


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def security_headers_middleware(request, handler):
        """Add security headers to all responses (including errors)."""
        response = await handler(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
else:
    security_headers_middleware = None  # type: ignore[assignment]


class _IdempotencyCache:
    """In-memory idempotency cache with TTL and basic LRU semantics."""
    def __init__(self, max_items: int = 1000, ttl_seconds: int = 300):
        from collections import OrderedDict
        self._store = OrderedDict()
        self._inflight: Dict[tuple[str, str], "asyncio.Task[Any]"] = {}
        self._ttl = ttl_seconds
        self._max = max_items

    def _purge(self):
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v["ts"] > self._ttl]
        for k in expired:
            self._store.pop(k, None)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    async def get_or_set(self, key: str, fingerprint: str, compute_coro):
        self._purge()
        item = self._store.get(key)
        if item and item["fp"] == fingerprint:
            return item["resp"]

        inflight_key = (key, fingerprint)
        task = self._inflight.get(inflight_key)
        if task is None:
            async def _compute_and_store():
                resp = await compute_coro()
                import time as _t
                self._store[key] = {"resp": resp, "fp": fingerprint, "ts": _t.time()}
                self._purge()
                return resp

            task = asyncio.create_task(_compute_and_store())
            self._inflight[inflight_key] = task

            def _clear_inflight(done_task: "asyncio.Task[Any]") -> None:
                if self._inflight.get(inflight_key) is done_task:
                    self._inflight.pop(inflight_key, None)

            task.add_done_callback(_clear_inflight)

        return await asyncio.shield(task)


_idem_cache = _IdempotencyCache()


def _make_request_fingerprint(body: Dict[str, Any], keys: List[str]) -> str:
    from hashlib import sha256
    subset = {k: body.get(k) for k in keys}
    return sha256(repr(subset).encode("utf-8")).hexdigest()


def _derive_chat_session_id(
    system_prompt: Optional[str],
    first_user_message: str,
) -> str:
    """Derive a stable session ID from the conversation's first user message.

    OpenAI-compatible frontends (Open WebUI, LibreChat, etc.) send the full
    conversation history with every request.  The system prompt and first user
    message are constant across all turns of the same conversation, so hashing
    them produces a deterministic session ID that lets the API server reuse
    the same Hermes session (and therefore the same Docker container sandbox
    directory) across turns.
    """
    seed = f"{system_prompt or ''}\n{first_user_message}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"api-{digest}"


_CRON_AVAILABLE = False
try:
    from cron.jobs import (
        list_jobs as _cron_list,
        get_job as _cron_get,
        create_job as _cron_create,
        update_job as _cron_update,
        remove_job as _cron_remove,
        pause_job as _cron_pause,
        resume_job as _cron_resume,
        trigger_job as _cron_trigger,
    )
    _CRON_AVAILABLE = True
except ImportError:
    _cron_list = None
    _cron_get = None
    _cron_create = None
    _cron_update = None
    _cron_remove = None
    _cron_pause = None
    _cron_resume = None
    _cron_trigger = None


class APIServerAdapter(BasePlatformAdapter):
    """
    OpenAI-compatible HTTP API server adapter.

    Runs an aiohttp web server that accepts OpenAI-format requests
    and routes them through hermes-agent's AIAgent.
    """

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.API_SERVER)
        extra = config.extra or {}
        self._host: str = extra.get("host", os.getenv("API_SERVER_HOST", DEFAULT_HOST))
        raw_port = extra.get("port")
        if raw_port is None:
            raw_port = os.getenv("API_SERVER_PORT", str(DEFAULT_PORT))
        self._port: int = _coerce_port(raw_port, DEFAULT_PORT)
        self._api_key: str = extra.get("key", os.getenv("API_SERVER_KEY", ""))
        self._product_auth_enabled = _coerce_config_bool(
            extra.get(
                "product_auth_enabled",
                os.getenv("TROIKA_PRODUCT_AUTH_ENABLED", "false"),
            )
        )
        # Cost metering remains implemented, but early product development is
        # intentionally unmetered.  Operators can re-enable quota enforcement
        # without a schema migration when paid plans are introduced.
        self._product_quotas_enabled = _coerce_config_bool(
            extra.get(
                "product_quotas_enabled",
                os.getenv("TROIKA_PRODUCT_QUOTAS_ENABLED", "false"),
            )
        )
        self._product_voice_enabled = _coerce_config_bool(
            extra.get(
                "product_voice_enabled",
                os.getenv("TROIKA_PRODUCT_VOICE_ENABLED", "true"),
            )
        )
        self._product_stt_url = str(
            extra.get(
                "product_stt_url",
                os.getenv("TROIKA_PRODUCT_STT_URL", "http://127.0.0.1:8766"),
            )
        ).rstrip("/")
        self._access_registry = None
        self._artifact_store = None
        self._product_auth_error: Optional[str] = None
        self._product_artifact_error: Optional[str] = None
        self._product_artifact_db: Optional[Path] = None
        self._product_artifact_root: Optional[Path] = None
        if self._product_auth_enabled:
            try:
                from troika_product.access import AccessRegistry

                raw_database = extra.get(
                    "product_auth_db", os.getenv("TROIKA_PRODUCT_AUTH_DB", "")
                )
                database_path = Path(str(raw_database)) if raw_database else None
                self._access_registry = AccessRegistry(database_path)
                self._product_artifact_db = self._access_registry.database_path.resolve()
                raw_artifact_root = extra.get(
                    "product_artifact_root",
                    os.getenv("TROIKA_PRODUCT_ARTIFACT_ROOT", ""),
                )
                self._product_artifact_root = (
                    Path(str(raw_artifact_root)).resolve()
                    if raw_artifact_root
                    else None
                )
                try:
                    from troika_product.artifacts import ArtifactStore

                    self._artifact_store = ArtifactStore(
                        database_path=self._product_artifact_db,
                        storage_root=self._product_artifact_root,
                    )
                    self._product_artifact_root = self._artifact_store.storage_root
                except Exception as exc:
                    # Chat stays available if the optional file subsystem is
                    # unhealthy, while every artifact endpoint/tool fails closed.
                    self._product_artifact_error = str(exc)
            except Exception as exc:
                # Product auth must fail closed at connect time; never silently
                # fall back to the legacy shared-key mode.
                self._product_auth_error = str(exc)
        self._cors_origins: tuple[str, ...] = self._parse_cors_origins(
            extra.get("cors_origins", os.getenv("API_SERVER_CORS_ORIGINS", "")),
        )
        self._model_name: str = self._resolve_model_name(
            extra.get("model_name", os.getenv("API_SERVER_MODEL_NAME", "")),
        )
        self._app: Optional["web.Application"] = None
        self._runner: Optional["web.AppRunner"] = None
        self._site: Optional["web.TCPSite"] = None
        self._response_store = ResponseStore()
        # Active run streams: run_id -> asyncio.Queue of SSE event dicts
        self._run_streams: Dict[str, "asyncio.Queue[Optional[Dict]]"] = {}
        # Creation timestamps for orphaned-run TTL sweep
        self._run_streams_created: Dict[str, float] = {}
        # Active run agent/task references for stop support
        self._active_run_agents: Dict[str, Any] = {}
        self._active_run_tasks: Dict[str, "asyncio.Task"] = {}
        # Pollable run status for dashboards and external control-plane UIs.
        self._run_statuses: Dict[str, Dict[str, Any]] = {}
        # Product-mode run ownership.  Runs are transient server objects, so
        # retain their owner only for the same lifetime as _run_statuses.
        self._run_owners: Dict[str, tuple[str, str]] = {}
        # Active approval session key for each run_id.  The approval core
        # resolves requests by session key, while API clients address the
        # in-flight run by run_id.
        self._run_approval_sessions: Dict[str, str] = {}
        self._session_db: Optional[Any] = None  # Lazy-init SessionDB for session continuity

    @staticmethod
    def _parse_cors_origins(value: Any) -> tuple[str, ...]:
        """Normalize configured CORS origins into a stable tuple."""
        if not value:
            return ()

        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = [str(value)]

        return tuple(str(item).strip() for item in items if str(item).strip())

    @staticmethod
    def _resolve_model_name(explicit: str) -> str:
        """Derive the advertised model name for /v1/models.

        Priority:
        1. Explicit override (config extra or API_SERVER_MODEL_NAME env var)
        2. Active profile name (so each profile advertises a distinct model)
        3. Fallback: "hermes-agent"
        """
        if explicit and explicit.strip():
            return explicit.strip()
        try:
            from hermes_cli.profiles import get_active_profile_name
            profile = get_active_profile_name()
            if profile and profile not in {"default", "custom"}:
                return profile
        except Exception:
            pass
        return "hermes-agent"

    def _cors_headers_for_origin(self, origin: str) -> Optional[Dict[str, str]]:
        """Return CORS headers for an allowed browser origin."""
        if not origin or not self._cors_origins:
            return None

        if "*" in self._cors_origins:
            headers = dict(_CORS_HEADERS)
            headers["Access-Control-Allow-Origin"] = "*"
            headers["Access-Control-Max-Age"] = "600"
            return headers

        if origin not in self._cors_origins:
            return None

        headers = dict(_CORS_HEADERS)
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
        headers["Access-Control-Max-Age"] = "600"
        return headers

    def _origin_allowed(self, origin: str) -> bool:
        """Allow non-browser clients and explicitly configured browser origins."""
        if not origin:
            return True

        if not self._cors_origins:
            return False

        return "*" in self._cors_origins or origin in self._cors_origins

    @staticmethod
    def _clean_log_value(value: Any, *, max_len: int = 200) -> str:
        """Sanitize request metadata before it reaches security logs."""
        if value is None:
            return ""
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        return text[:max_len]

    def _request_audit_context(self, request: "web.Request") -> Dict[str, str]:
        """Return non-secret source metadata for security/audit warnings."""
        peer_ip = ""
        try:
            peer = request.transport.get_extra_info("peername") if request.transport else None
            if isinstance(peer, (tuple, list)) and peer:
                peer_ip = str(peer[0])
        except Exception:
            peer_ip = ""

        return {
            "remote": self._clean_log_value(getattr(request, "remote", "") or peer_ip),
            "peer_ip": self._clean_log_value(peer_ip),
            "forwarded_for": self._clean_log_value(request.headers.get("X-Forwarded-For", "")),
            "real_ip": self._clean_log_value(request.headers.get("X-Real-IP", "")),
            "method": self._clean_log_value(request.method, max_len=16),
            "path": self._clean_log_value(request.path_qs, max_len=500),
            "user_agent": self._clean_log_value(request.headers.get("User-Agent", ""), max_len=300),
        }

    def _request_audit_log_suffix(self, request: "web.Request") -> str:
        ctx = self._request_audit_context(request)
        fields = [f"{key}={value!r}" for key, value in ctx.items() if value]
        return " ".join(fields) if fields else "source='unknown'"

    def _cron_origin_from_request(self, request: "web.Request") -> Dict[str, str]:
        """Persist safe API source metadata on cron jobs created over HTTP."""
        ctx = self._request_audit_context(request)
        origin = {
            "platform": "api_server",
            "chat_id": "api",
        }
        if ctx.get("remote"):
            origin["source_ip"] = ctx["remote"]
        if ctx.get("peer_ip"):
            origin["peer_ip"] = ctx["peer_ip"]
        if ctx.get("forwarded_for"):
            origin["forwarded_for"] = ctx["forwarded_for"]
        if ctx.get("real_ip"):
            origin["real_ip"] = ctx["real_ip"]
        if ctx.get("user_agent"):
            origin["user_agent"] = ctx["user_agent"]
        return origin

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _product_principal(self, request: "web.Request") -> Optional[Any]:
        """Return the request's authenticated product principal, if enabled."""
        if self._access_registry is None:
            return None
        return request.get("troika_product_principal")

    def _product_device_context_allowed(self, request: "web.Request") -> bool:
        """Require explicit app consent before product device context is accepted."""
        if self._access_registry is None:
            return True
        return request.headers.get("X-Troika-Device-Context-Consent", "").lower() == "granted"

    def _record_product_audit(
        self,
        request: "web.Request",
        event_type: str,
        *,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record product security events without retaining request content."""
        if self._access_registry is None:
            return
        principal = self._product_principal(request)
        if principal is None:
            return
        try:
            self._access_registry.record_audit_event(
                event_type,
                principal=principal,
                session_id=session_id,
                run_id=run_id,
                details=details,
            )
        except Exception:
            # The agent flow is still available if an optional beta audit write
            # fails, but operators get a high-severity signal to investigate.
            logger.exception(
                "Product audit write failed: %s",
                self._request_audit_log_suffix(request),
            )

    def _authorize_product_session(
        self, request: "web.Request", session_id: str, *, claim: bool
    ) -> Optional["web.Response"]:
        """Bind or validate session ownership when product auth is enabled."""
        if self._access_registry is None:
            return None
        principal = self._product_principal(request)
        if principal is None:
            return web.json_response(_openai_error("Product authentication is required"), status=401)
        permitted = (
            self._access_registry.claim_session(principal, session_id)
            if claim
            else self._access_registry.session_belongs_to(principal, session_id)
        )
        if permitted:
            if claim:
                self._record_product_audit(
                    request, "session.claimed", session_id=session_id
                )
            return None
        self._record_product_audit(request, "session.denied", session_id=session_id)
        logger.warning(
            "Product session access rejected: %s",
            self._request_audit_log_suffix(request),
        )
        return web.json_response(
            _openai_error("This session belongs to another user"), status=403
        )

    def _consume_product_request_quota(
        self, request: "web.Request"
    ) -> Optional["web.Response"]:
        """Reserve one paid/beta request before starting agent work."""
        if self._access_registry is None or not self._product_quotas_enabled:
            return None
        principal = self._product_principal(request)
        if principal is None:
            return web.json_response(
                _openai_error("Product authentication is required"), status=401
            )
        try:
            decision = self._access_registry.consume_chat_request(principal)
        except Exception:
            logger.exception(
                "Product quota lookup failed: %s",
                self._request_audit_log_suffix(request),
            )
            # Product billing/access failures must not fall through to an
            # unmetered agent run.
            return web.json_response(
                _openai_error("Usage service is temporarily unavailable"), status=503
            )
        request["troika_usage"] = decision
        if decision.allowed:
            return None
        self._record_product_audit(
            request,
            "request.quota_exhausted",
            details={"limit": decision.limit, "used": decision.used},
        )
        logger.info(
            "Product daily quota exhausted: %s",
            self._request_audit_log_suffix(request),
        )
        return web.json_response(
            _openai_error(
                "Daily request limit reached. Try again after the next UTC day.",
                code="daily_request_limit_exceeded",
            ),
            status=429,
            headers={
                "X-Troika-Daily-Request-Limit": str(decision.limit),
                "X-Troika-Requests-Remaining": "0",
            },
        )

    def _product_quota_headers(self, request: "web.Request") -> Dict[str, str]:
        """Expose non-sensitive quota state to the authenticated client."""
        decision = request.get("troika_usage")
        if decision is None:
            return {}
        return {
            "X-Troika-Daily-Request-Limit": str(decision.limit),
            "X-Troika-Requests-Remaining": str(decision.remaining),
        }

    def _authorize_product_run(
        self, request: "web.Request", run_id: str
    ) -> Optional["web.Response"]:
        """Restrict run status, SSE, approval, and stop to its owner."""
        if self._access_registry is None:
            return None
        principal = self._product_principal(request)
        owner = self._run_owners.get(run_id)
        if (
            principal is not None
            and owner is not None
            and owner == (principal.user_id, principal.device_id)
        ):
            return None
        self._record_product_audit(request, "run.access_denied", run_id=run_id)
        # Return 404 rather than revealing that another user's run exists.
        logger.warning(
            "Product run access rejected: %s",
            self._request_audit_log_suffix(request),
        )
        return web.json_response(
            _openai_error(f"Run not found: {run_id}", code="run_not_found"), status=404
        )

    def _check_auth(self, request: "web.Request") -> Optional["web.Response"]:
        """
        Validate Bearer token from Authorization header.

        Returns None if auth is OK, or a 401 web.Response on failure.
        If no API key is configured, all requests are allowed (only when API
        server is local).
        """
        auth_header = request.headers.get("Authorization", "")
        if self._access_registry is not None:
            token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
            principal = self._access_registry.authenticate(token)
            if principal is not None:
                request["troika_product_principal"] = principal
                return None
        elif not self._api_key:
            return None  # No key configured — allow all (local-only use)
        elif auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if hmac.compare_digest(token, self._api_key):
                return None  # Auth OK

        logger.warning(
            "API server rejected invalid API key: %s",
            self._request_audit_log_suffix(request),
        )
        return web.json_response(
            {"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}},
            status=401,
        )

    # ------------------------------------------------------------------
    # Session header helpers
    # ------------------------------------------------------------------

    # Soft length cap for session identifiers.  Headers are bounded in
    # aggregate by aiohttp (``client_max_size`` / default 8 KiB per
    # header), but we impose a tighter limit on the session headers so a
    # caller can't burn memory by passing a multi-kilobyte "session key".
    # 256 chars is well above any realistic stable channel identifier
    # (e.g. ``agent:main:webui:dm:user-42``) while staying small enough
    # that the sanitized form is safe to pass into Honcho / state.db.
    _MAX_SESSION_HEADER_LEN = 256

    def _parse_session_key_header(
        self, request: "web.Request"
    ) -> tuple[Optional[str], Optional["web.Response"]]:
        """Extract and validate the ``X-Hermes-Session-Key`` header.

        The session key is a stable per-channel identifier that scopes
        long-term memory (e.g. Honcho sessions) across transcripts.  It
        is independent of ``X-Hermes-Session-Id``: callers may send
        either, both, or neither.

        Returns ``(session_key, None)`` on success (with an empty/absent
        header yielding ``None`` for the key), or ``(None, error_response)``
        on validation failure.

        Security: like session continuation, accepting a caller-supplied
        memory scope requires API-key authentication so that an
        unauthenticated client on a local-only server can't inject itself
        into another user's long-term memory scope by guessing a key.
        """
        principal = self._product_principal(request)
        if principal is not None:
            # The device token is the identity boundary.  Ignore a header that
            # might be forged by a client and use a server-derived scope.
            return principal.memory_scope, None

        raw = request.headers.get("X-Hermes-Session-Key", "").strip()
        if not raw:
            return None, None

        if not self._api_key and self._access_registry is None:
            logger.warning(
                "X-Hermes-Session-Key rejected: no API key configured. "
                "Set API_SERVER_KEY to enable long-term memory scoping."
            )
            return None, web.json_response(
                _openai_error(
                    "X-Hermes-Session-Key requires API key authentication. "
                    "Configure API_SERVER_KEY to enable this feature."
                ),
                status=403,
            )

        # Reject control characters that could enable header injection on
        # the echo path.
        if re.search(r'[\r\n\x00]', raw):
            return None, web.json_response(
                {"error": {"message": "Invalid session key", "type": "invalid_request_error"}},
                status=400,
            )

        if len(raw) > self._MAX_SESSION_HEADER_LEN:
            return None, web.json_response(
                {"error": {"message": "Session key too long", "type": "invalid_request_error"}},
                status=400,
            )

        return raw, None

    # ------------------------------------------------------------------
    # Session DB helper
    # ------------------------------------------------------------------

    def _ensure_session_db(self):
        """Lazily initialise and return the shared SessionDB instance.

        Sessions are persisted to ``state.db`` so that ``hermes sessions list``
        shows API-server conversations alongside CLI and gateway ones.
        """
        if self._session_db is None:
            try:
                from hermes_state import SessionDB
                self._session_db = SessionDB()
            except Exception as e:
                logger.debug("SessionDB unavailable for API server: %s", e)
        return self._session_db

    # ------------------------------------------------------------------
    # Agent creation helper
    # ------------------------------------------------------------------

    def _create_agent(
        self,
        ephemeral_system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        stream_delta_callback=None,
        tool_progress_callback=None,
        tool_start_callback=None,
        tool_complete_callback=None,
        gateway_session_key: Optional[str] = None,
    ) -> Any:
        """
        Create an AIAgent instance using the gateway's runtime config.

        Uses _resolve_runtime_agent_kwargs() to pick up model, api_key,
        base_url, etc. from config.yaml / env vars.  Toolsets are resolved
        from config.yaml platform_toolsets.api_server (same as all other
        gateway platforms), falling back to the hermes-api-server default.

        ``gateway_session_key`` is a stable per-channel identifier supplied
        by the client (via ``X-Hermes-Session-Key``).  Unlike ``session_id``
        which scopes the short-term transcript and rotates on /new, this
        key is meant to persist across transcripts so long-term memory
        providers (e.g. Honcho) can scope their per-chat state correctly
        — matching the semantics of the native gateway's ``session_key``.
        """
        from run_agent import AIAgent
        from gateway.run import _resolve_runtime_agent_kwargs, _resolve_gateway_model, _load_gateway_config, GatewayRunner
        from hermes_cli.tools_config import _get_platform_tools

        runtime_kwargs = _resolve_runtime_agent_kwargs()
        reasoning_config = GatewayRunner._load_reasoning_config()
        model = _resolve_gateway_model()

        user_config = _load_gateway_config()
        enabled_toolsets = sorted(_get_platform_tools(user_config, "api_server"))
        if self._access_registry is not None:
            # Product API must never inherit a local operator's broad toolset.
            # Device/PC/server actions need a separately paired companion and
            # explicit product approval model before product exposure.
            enabled_toolsets = ["troika-product"]

        max_iterations = int(os.getenv("HERMES_MAX_ITERATIONS", "90"))

        # Load fallback provider chain so the API server platform has the
        # same fallback behaviour as Telegram/Discord/Slack (fixes #4954).
        fallback_model = GatewayRunner._load_fallback_model()

        agent = AIAgent(
            model=model,
            **runtime_kwargs,
            max_iterations=max_iterations,
            quiet_mode=True,
            verbose_logging=False,
            ephemeral_system_prompt=ephemeral_system_prompt or None,
            enabled_toolsets=enabled_toolsets,
            session_id=session_id,
            platform="api_server",
            stream_delta_callback=stream_delta_callback,
            tool_progress_callback=tool_progress_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            session_db=self._ensure_session_db(),
            fallback_model=fallback_model,
            reasoning_config=reasoning_config,
            gateway_session_key=gateway_session_key,
        )
        # Product conversations can contain voice transcripts and private
        # document text. Keep raw user content out of the operator logs.
        agent._redact_content_logs = self._access_registry is not None
        return agent

    # ------------------------------------------------------------------
    # HTTP Handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, request: "web.Request") -> "web.Response":
        """GET /health — simple health check."""
        return web.json_response({"status": "ok", "platform": "hermes-agent"})

    async def _handle_health_detailed(self, request: "web.Request") -> "web.Response":
        """GET /health/detailed — rich status for cross-container dashboard probing.

        Returns gateway state, connected platforms, PID, and uptime so the
        dashboard can display full status without needing a shared PID file or
        /proc access.  No authentication required.
        """
        from gateway.status import read_runtime_status

        runtime = read_runtime_status() or {}
        return web.json_response({
            "status": "ok",
            "platform": "hermes-agent",
            "gateway_state": runtime.get("gateway_state"),
            "platforms": runtime.get("platforms", {}),
            "active_agents": runtime.get("active_agents", 0),
            "exit_reason": runtime.get("exit_reason"),
            "updated_at": runtime.get("updated_at"),
            "pid": os.getpid(),
        })

    async def _handle_models(self, request: "web.Request") -> "web.Response":
        """GET /v1/models — return hermes-agent as an available model."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        return web.json_response({
            "object": "list",
            "data": [
                {
                    "id": self._model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "hermes",
                    "permission": [],
                    "root": self._model_name,
                    "parent": None,
                }
            ],
        })

    async def _handle_capabilities(self, request: "web.Request") -> "web.Response":
        """GET /v1/capabilities — advertise the stable API surface.

        External UIs and orchestrators use this endpoint to discover the API
        server's plugin-safe contract without scraping docs or assuming that
        every Hermes version exposes the same endpoints.
        """
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        responses_enabled = self._access_registry is None

        return web.json_response({
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "model": self._model_name,
            "auth": {
                "type": "bearer",
                "required": bool(self._api_key or self._access_registry),
                "mode": "product" if self._access_registry is not None else "legacy",
            },
            "runtime": {
                "mode": "server_agent",
                "tool_execution": "server",
                "split_runtime": False,
                "description": (
                    "The API server creates a server-side Hermes AIAgent; "
                    "tools execute on the API-server host unless a future "
                    "explicit split-runtime mode is enabled."
                ),
            },
            "features": {
                "chat_completions": True,
                "chat_completions_streaming": True,
                # The legacy Responses store has global response IDs and has
                # not yet been migrated to tenant-owned storage. Do not
                # advertise it to product tokens where it could cross users.
                "responses_api": responses_enabled,
                "responses_streaming": responses_enabled,
                "run_submission": True,
                "run_status": True,
                "run_events_sse": True,
                "run_stop": True,
                "run_approval_response": True,
                "tool_progress_events": True,
                "approval_events": True,
                "private_artifacts": self._artifact_store is not None,
                "notification_preferences": self._access_registry is not None,
                "product_quota_enforcement": self._product_quotas_enabled,
                "session_continuity_header": "X-Hermes-Session-Id",
                "session_key_header": "X-Hermes-Session-Key",
                "cors": bool(self._cors_origins),
            },
            "endpoints": {
                "health": {"method": "GET", "path": "/health"},
                "health_detailed": {"method": "GET", "path": "/health/detailed"},
                "models": {"method": "GET", "path": "/v1/models"},
                "chat_completions": {"method": "POST", "path": "/v1/chat/completions"},
                **(
                    {"responses": {"method": "POST", "path": "/v1/responses"}}
                    if responses_enabled
                    else {}
                ),
                "runs": {"method": "POST", "path": "/v1/runs"},
                "run_status": {"method": "GET", "path": "/v1/runs/{run_id}"},
                "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"},
                "run_approval": {"method": "POST", "path": "/v1/runs/{run_id}/approval"},
                "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
                **(
                    {
                        "notification_preferences": {
                            "method": "GET", "path": "/v1/notification-preferences",
                        },
                        "notification_preferences_update": {
                            "method": "PUT", "path": "/v1/notification-preferences",
                        },
                    }
                    if self._access_registry is not None
                    else {}
                ),
                **(
                    {
                        "artifacts": {"method": "GET", "path": "/v1/artifacts"},
                        "artifact_download": {
                            "method": "GET",
                            "path": "/v1/artifacts/{artifact_id}/download",
                        },
                        "artifact_delete": {
                            "method": "DELETE",
                            "path": "/v1/artifacts/{artifact_id}",
                        },
                    }
                    if self._artifact_store is not None
                    else {}
                ),
            },
        })

    async def _handle_notification_preferences(self, request: "web.Request") -> "web.Response":
        """Read or replace the authenticated account's notification preferences."""
        auth_err = self._check_auth(request)
        if auth_err is not None:
            return auth_err
        principal = self._product_principal(request)
        if principal is None:
            return web.json_response(
                _openai_error("Notification preferences are unavailable"),
                status=503 if self._product_auth_enabled else 404,
            )
        if request.method == "PUT":
            from troika_product.notifications import NotificationPreferences

            try:
                preferences = NotificationPreferences.from_dict(await request.json())
            except (ValueError, TypeError, UnicodeError):
                return web.json_response(
                    _openai_error("Invalid notification preferences", code="invalid_preferences"),
                    status=400,
                )
        try:
            if request.method == "PUT":
                result = self._access_registry.set_notification_preferences(principal, preferences)
            else:
                result = self._access_registry.notification_preferences(principal)
        except PermissionError:
            return web.json_response(_openai_error("Product authentication is required"), status=401)
        except Exception:
            logger.exception("Product notification preferences unavailable")
            return web.json_response(
                _openai_error("Notification preferences are temporarily unavailable"), status=503,
            )
        return web.json_response(result.to_dict(), headers={"Cache-Control": "no-store"})

    async def _handle_phone_ws(self, request: "web.Request") -> "web.Response":
        """GET /v1/phone/commands — WebSocket-канал для Android-телефона."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            principal = self._product_principal(request)
            if principal is None:
                return web.json_response(
                    _openai_error("Product authentication is required"), status=401
                )
            from gateway.platforms.phone_bridge import product_bridge

            def _record_lifecycle(state: str) -> None:
                self._record_product_audit(request, f"phone.{state}")

            return await product_bridge.handle_connection(
                request,
                principal.device_id,
                lifecycle_callback=_record_lifecycle,
            )
        from gateway.platforms.phone_bridge import bridge
        logger.info("Phone WS handshake from %s, bridge id=%s", request.remote, id(bridge))
        return await bridge.handle_connection(request)

    async def _handle_phone_status(self, request: "web.Request") -> "web.Response":
        """GET /v1/phone/status — диагностика (то же что bridge.is_connected())."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            principal = self._product_principal(request)
            if principal is None:
                return web.json_response(
                    _openai_error("Product authentication is required"), status=401
                )
            from gateway.platforms.phone_bridge import product_bridge

            return web.json_response(
                {"connected": product_bridge.is_connected(principal.device_id)}
            )
        from gateway.platforms.phone_bridge import bridge
        return web.json_response({"connected": bridge.is_connected(), "bridge_id": id(bridge)})

    def _require_artifact_principal(self, request: "web.Request") -> Any:
        """Authenticate one artifact request and return its private store/owner."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        principal = self._product_principal(request)
        if principal is None or self._artifact_store is None:
            return web.json_response(
                _openai_error(
                    "Private files are unavailable",
                    code="artifact_storage_unavailable",
                ),
                status=503 if self._product_auth_enabled else 404,
            )
        return self._artifact_store, principal

    async def _handle_list_artifacts(self, request: "web.Request") -> "web.Response":
        """GET /v1/artifacts — list only the authenticated user's files."""
        resolved = self._require_artifact_principal(request)
        if isinstance(resolved, web.Response):
            return resolved
        store, principal = resolved
        try:
            items = [item.to_dict() for item in store.list_for_user(principal.user_id)]
        except Exception:
            logger.exception("Product artifact listing failed")
            return web.json_response(
                _openai_error("Private files are temporarily unavailable"), status=503
            )
        return web.json_response({"object": "list", "data": items})

    async def _handle_download_artifact(self, request: "web.Request") -> "web.Response":
        """GET /v1/artifacts/{id}/download — owner-scoped verified download."""
        resolved = self._require_artifact_principal(request)
        if isinstance(resolved, web.Response):
            return resolved
        store, principal = resolved
        artifact_id = request.match_info.get("artifact_id", "")
        try:
            stored = store.read_for_user(principal.user_id, artifact_id)
        except Exception:
            logger.exception("Product artifact integrity/read failure")
            return web.json_response(
                _openai_error("This file is temporarily unavailable"), status=503
            )
        if stored is None:
            return web.json_response(
                _openai_error("File not found", code="artifact_not_found"), status=404
            )
        artifact, data = stored
        ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", artifact.filename).strip("._")
        if not ascii_name:
            ascii_name = f"document.{artifact.kind}"
        disposition = (
            f'attachment; filename="{ascii_name[:120]}"; '
            f"filename*=UTF-8''{quote(artifact.filename, safe='')}"
        )
        self._record_product_audit(
            request,
            "artifact.downloaded",
            details={
                "artifact_digest": hashlib.sha256(artifact.id.encode("utf-8")).hexdigest()[:32],
                "kind": artifact.kind,
                "size": artifact.size,
            },
        )
        return web.Response(
            body=data,
            content_type=artifact.mime_type,
            headers={
                "Content-Disposition": disposition,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    async def _handle_delete_artifact(self, request: "web.Request") -> "web.Response":
        """DELETE /v1/artifacts/{id} — direct, authenticated user action."""
        resolved = self._require_artifact_principal(request)
        if isinstance(resolved, web.Response):
            return resolved
        store, principal = resolved
        artifact_id = request.match_info.get("artifact_id", "")
        try:
            artifact = store.delete_for_user(principal.user_id, artifact_id)
        except Exception:
            logger.exception("Product artifact deletion failed")
            return web.json_response(
                _openai_error("File deletion is temporarily unavailable"), status=503
            )
        if artifact is None:
            return web.json_response(
                _openai_error("File not found", code="artifact_not_found"), status=404
            )
        self._record_product_audit(
            request,
            "artifact.deleted",
            details={
                "artifact_digest": hashlib.sha256(artifact.id.encode("utf-8")).hexdigest()[:32],
                "kind": artifact.kind,
                "size": artifact.size,
            },
        )
        return web.json_response({"ok": True, "id": artifact.id})

    async def _handle_list_sessions(self, request: "web.Request") -> "web.Response":
        """GET /v1/sessions — список сессий для UI истории.

        Query params:
          - source (optional): фильтр по платформе (api_server, phone, и т.д.)
          - limit (default 50, max 200)
          - offset (default 0)
        """
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        db = self._ensure_session_db()
        if db is None:
            return web.json_response({"error": "session_db_unavailable"}, status=503)

        try:
            limit = min(int(request.query.get("limit", "50")), 200)
            offset = max(int(request.query.get("offset", "0")), 0)
        except ValueError:
            return web.json_response({"error": "bad_limit_or_offset"}, status=400)

        source = request.query.get("source") or None
        try:
            fetch_limit = 200 if self._access_registry is not None else limit
            fetch_offset = 0 if self._access_registry is not None else offset
            sessions = db.list_sessions_rich(
                source=source,
                limit=fetch_limit,
                offset=fetch_offset,
                order_by_last_active=True,
            )
        except Exception as e:
            logger.error("list_sessions failed: %s", e, exc_info=True)
            return web.json_response({"error": f"list_failed: {e}"}, status=500)

        allowed_session_ids = None
        principal = self._product_principal(request)
        if principal is not None:
            allowed_session_ids = self._access_registry.user_session_ids(principal)
        items: List[Dict[str, Any]] = []
        for s in sessions or []:
            if allowed_session_ids is not None and s.get("id") not in allowed_session_ids:
                continue
            items.append({
                "id": s.get("id"),
                "source": s.get("source"),
                "title": s.get("title"),
                "preview": s.get("preview"),
                "message_count": s.get("message_count"),
                "started_at": s.get("started_at"),
                "last_active": s.get("last_active"),
            })
        if allowed_session_ids is not None:
            items = items[offset:offset + limit]
        return web.json_response({"sessions": items, "count": len(items)})

    async def _handle_get_session_messages(self, request: "web.Request") -> "web.Response":
        """GET /v1/sessions/{session_id}/messages — транскрипт одной сессии."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        session_id = request.match_info.get("session_id", "").strip()
        if not session_id or re.search(r"[\r\n\x00]", session_id):
            return web.json_response({"error": "bad_session_id"}, status=400)
        session_auth_err = self._authorize_product_session(
            request, session_id, claim=False
        )
        if session_auth_err:
            return session_auth_err

        db = self._ensure_session_db()
        if db is None:
            return web.json_response({"error": "session_db_unavailable"}, status=503)

        try:
            rows = db.get_messages(session_id)
        except Exception as e:
            logger.error("get_messages failed for %s: %s", session_id, e, exc_info=True)
            return web.json_response({"error": f"load_failed: {e}"}, status=500)

        items: List[Dict[str, Any]] = []
        for row in rows or []:
            role = row.get("role")
            if role not in ("user", "assistant"):
                continue
            content = row.get("content")
            if isinstance(content, list):
                # Multimodal — выжимаем только текст для UI истории
                parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = "\n".join(p for p in parts if p)
            if not isinstance(content, str) or not content.strip():
                continue
            items.append({
                "role": role,
                "content": content,
                "timestamp": row.get("timestamp"),
            })
        return web.json_response({
            "session_id": session_id,
            "messages": items,
            "count": len(items),
        })

    async def _handle_phone_notify(self, request: "web.Request") -> "web.Response":
        """POST /v1/phone/notify — сервер шлёт push-уведомление на телефон.

        Body: {"text": "...", "speak": true, "title": "Тройка"}
        - speak=true → телефон озвучит через EdgeTTS
        - speak=false → только notification в шторке
        """
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            return web.json_response(_openai_error("Phone control is unavailable in product mode"), status=403)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)

        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "missing 'text'"}, status=400)
        if len(text) > 2000:
            text = text[:2000]

        from gateway.platforms.phone_bridge import bridge
        if not bridge.is_connected():
            return web.json_response({"ok": False, "error": "phone_not_connected"}, status=503)

        result = await bridge.send_command(
            "notify_user",
            {
                "text": text,
                "speak": bool(body.get("speak", True)),
                "title": (body.get("title") or "Тройка").strip()[:80],
            },
            timeout=10.0,
        )
        return web.json_response({"ok": bool(result.get("ok", True)), "result": result})

    async def _handle_audio_transcriptions(self, request: "web.Request") -> "web.Response":
        """Expose private STT on the authenticated API origin used by Android."""
        auth_err = self._check_auth(request)
        if auth_err is not None:
            return auth_err
        if (
            not self._product_auth_enabled
            or self._access_registry is None
            or not self._product_voice_enabled
        ):
            return web.json_response({"error": "Product voice is unavailable"}, status=503)
        session_id = request.headers.get("X-Hermes-Session-Id", "")
        if not session_id:
            return web.json_response({"error": "Voice session is required"}, status=400)
        session_err = self._authorize_product_session(request, session_id, claim=True)
        if session_err is not None:
            return session_err
        import aiohttp
        from troika_product.voice import guarded_voice, read_audio_upload

        async def operation():
            audio, language = await read_audio_upload(request)
            form = aiohttp.FormData()
            form.add_field("file", audio, filename="voice.wav", content_type="application/octet-stream")
            form.add_field("language", language)
            # Operator-owned destination, never accepted from the client.
            headers = {
                "Authorization": request.headers["Authorization"],
                "X-Hermes-Session-Id": session_id,
            }
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=85)) as client:
                    async with client.post(
                        self._product_stt_url + "/v1/audio/transcriptions", data=form,
                        headers=headers, allow_redirects=False,
                    ) as response:
                        if response.status != 200:
                            status = response.status if response.status in {400, 401, 403, 413, 503, 504} else 502
                            return web.json_response({"error": "Speech recognition unavailable"}, status=status)
                        body = bytearray()
                        async for chunk in response.content.iter_chunked(8192):
                            body.extend(chunk)
                            if len(body) > 1024 * 1024:
                                raise web.HTTPBadGateway(text="Invalid speech response")
                        data = json.loads(body)
                        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
                            raise ValueError("Invalid speech response")
                        return web.json_response({"text": data["text"]})
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return web.json_response({"error": "Speech recognition unavailable"}, status=503)

        token = request.headers["Authorization"].removeprefix("Bearer ").strip()
        return await guarded_voice(
            operation,
            registry=self._access_registry,
            token=token,
            request=request,
            enabled=lambda: self._product_voice_enabled,
        )

    async def _handle_audio_speech(self, request: "web.Request") -> "web.Response":
        auth_err = self._check_auth(request)
        if auth_err is not None:
            return auth_err
        if self._product_auth_enabled:
            if not self._product_voice_enabled:
                return web.json_response({"error": "Product voice is unavailable"}, status=503)
            from troika_product.voice import guarded_voice

            token = request.headers["Authorization"].removeprefix("Bearer ").strip()
            return await guarded_voice(
                lambda: self._synthesize_audio_speech(request),
                registry=self._access_registry,
                token=token,
                request=request,
                enabled=lambda: self._product_voice_enabled,
            )
        return await self._synthesize_audio_speech(request)

    async def _synthesize_audio_speech(self, request: "web.Request") -> "web.Response":
        """POST /v1/audio/speech — Edge TTS (OpenAI-compatible body, MP3 response).

        Body: {"input": "текст", "voice": "ru-RU-SvetlanaNeural", "speed": 1.0}
        Default voice: ru-RU-SvetlanaNeural (мягкий женский, нейросетевой).
        """
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)

        text = (body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "missing 'input'"}, status=400)
        if len(text) > 5000:
            text = text[:5000]
        # Для русского у Edge только два голоса: Svetlana (жен) и Dmitry (муж).
        # Светлана + pitch+8Hz/rate+4% звучит заметно живее «дикторского» базы.
        voice = body.get("voice") or "ru-RU-SvetlanaNeural"

        # Параметры голоса (SSML формат Edge TTS):
        # rate: -50%..+200% (скорость)
        # pitch: -50Hz..+50Hz (тон, для "женственности" поднять)
        # volume: -100%..+100%
        def _fmt_rate(v):
            try:
                pct = int(round((float(v) - 1.0) * 100))
                return f"{pct:+d}%"
            except (TypeError, ValueError):
                return "+0%"

        def _fmt_pitch(v):
            try:
                hz = int(round(float(v)))
                return f"{hz:+d}Hz"
            except (TypeError, ValueError):
                return "+0Hz"

        def _fmt_volume(v):
            try:
                pct = int(round(float(v)))
                return f"{pct:+d}%"
            except (TypeError, ValueError):
                return "+0%"

        # speed (legacy 1.0=normal) или rate (новый, прямой множитель)
        # Дефолт rate=1.04 (+4%) — чуть быстрее, меньше «диктора», звучит разговорнее.
        base_rate_mult = body.get("speed") if body.get("speed") is not None else body.get("rate", 1.04)
        try:
            base_rate_mult = float(base_rate_mult)
        except (TypeError, ValueError):
            base_rate_mult = 1.04
        # pitch=+8Hz по умолчанию — добавляет лёгкости и теплоты.
        # Edge экранирует <>, inline SSML не работает: тюнинг идёт через
        # параметры Communicate + предварительную нормализацию текста.
        try:
            base_pitch_hz = int(round(float(body.get("pitch", 8))))
        except (TypeError, ValueError):
            base_pitch_hz = 8

        # Эмоция ответа: мозг помечает фразу тегом [emo:joy]/[emo:грусть] в
        # начале (см. SOUL.md). Тег вырезаем из произносимого текста и используем
        # как самый приоритетный источник тона — он точнее, чем время суток.
        emo_tone, text = _extract_emo_tag(text)

        # Авто-тон: приоритет (1) тег [emo:...] от мозга → (2) явный "tone" в теле
        # → (3) текущий профиль IRIS (настроение Миши) → (4) тип самой фразы. Так
        # голос звучит живо: радостный ответ — звонко, поддержка — мягко.
        tone = emo_tone or body.get("tone")
        if not tone and not self._product_auth_enabled:
            try:
                from agent.iris_persona import _choose_profile
                tone = _choose_profile()
            except Exception:
                tone = None
        try:
            base_volume = int(round(float(body.get("volume", 0))))
        except (TypeError, ValueError):
            base_volume = 0
        rate_mult, pitch_hz, volume_pct = _tts_prosody(
            text, tone, base_rate_mult, base_pitch_hz, base_volume
        )
        rate = _fmt_rate(rate_mult)
        pitch = _fmt_pitch(pitch_hz)
        volume = _fmt_volume(volume_pct)

        import re as _re_tts
        original_text = text
        naturalized = _naturalize_tts_text(text)
        # Edge TTS бросает NoAudioReceived, если в тексте нет произносимых
        # символов (например, ответ был одним код-блоком → стал «…»).
        # В таком случае откатываемся к оригиналу, а если и он «немой» —
        # подставляем безопасную заглушку, чтобы не падать 500-кой.
        if not _re_tts.search(r"\w", naturalized):
            naturalized = original_text if _re_tts.search(r"\w", original_text) else "Готово."
        text = naturalized

        import os as _os_tts
        backend = (_os_tts.getenv("TTS_BACKEND") or "edge").strip().lower()
        fish_key = _os_tts.getenv("FISH_API_KEY", "").strip()
        fish_voice = (body.get("fish_voice_id") or _os_tts.getenv("FISH_VOICE_ID", "")).strip()

        if backend == "fish" and fish_key and fish_voice:
            try:
                import aiohttp
                payload = {
                    "text": text,
                    "reference_id": fish_voice,
                    "format": "mp3",
                    "normalize": True,
                }
                headers = {
                    "Authorization": f"Bearer {fish_key}",
                    "Content-Type": "application/json",
                }
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    async with sess.post(
                        "https://api.fish.audio/v1/tts",
                        json=payload, headers=headers,
                    ) as resp:
                        if resp.status == 200:
                            audio = await resp.read()
                            if len(audio) > 10 * 1024 * 1024:
                                raise ValueError("Speech output too large")
                            return web.Response(body=audio, content_type="audio/mpeg")
                        logger.warning(
                            "Fish TTS %s — fallback to Edge", resp.status
                        )
            except Exception as e:
                logger.warning("Fish TTS error (%s) — fallback to Edge", type(e).__name__)

        try:
            import edge_tts
            communicate = edge_tts.Communicate(
                text, voice=voice, rate=rate, pitch=pitch, volume=volume
            )
            audio = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                    if len(audio) > 10 * 1024 * 1024:
                        raise ValueError("Speech output too large")
            return web.Response(body=bytes(audio), content_type="audio/mpeg")
        except Exception as e:
            logger.error("Edge TTS error (%s)", type(e).__name__)
            return web.json_response({"error": "Speech synthesis unavailable"}, status=503)

    async def _handle_chat_completions(self, request: "web.Request") -> "web.Response":
        """POST /v1/chat/completions — OpenAI Chat Completions format."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        product_principal = self._product_principal(request)

        # Parse request body
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(_openai_error("Invalid JSON in request body"), status=400)

        messages = body.get("messages")
        if not messages or not isinstance(messages, list):
            return web.json_response(
                {"error": {"message": "Missing or invalid 'messages' field", "type": "invalid_request_error"}},
                status=400,
            )

        stream = _coerce_request_bool(body.get("stream"), default=False)

        # Extract system message (becomes ephemeral system prompt layered ON TOP of core)
        system_prompt = None
        conversation_messages: List[Dict[str, str]] = []

        for idx, msg in enumerate(messages):
            role = msg.get("role", "")
            raw_content = msg.get("content", "")
            if role == "system":
                # System messages don't support images (Anthropic rejects, OpenAI
                # text-model systems don't render them).  Flatten to text.
                content = _normalize_chat_content(raw_content)
                if system_prompt is None:
                    system_prompt = content
                else:
                    system_prompt = system_prompt + "\n" + content
            elif role in {"user", "assistant"}:
                try:
                    content = _normalize_multimodal_content(raw_content)
                except ValueError as exc:
                    return _multimodal_validation_error(exc, param=f"messages[{idx}].content")
                conversation_messages.append({"role": role, "content": content})

        # Extract the last user message as the primary input
        user_message: Any = ""
        history = []
        if conversation_messages:
            user_message = conversation_messages[-1].get("content", "")
            history = conversation_messages[:-1]

        if not _content_has_visible_payload(user_message):
            return web.json_response(
                {"error": {"message": "No user message found in messages", "type": "invalid_request_error"}},
                status=400,
            )

        # Allow caller to scope long-term memory (e.g. Honcho) with a
        # stable per-channel identifier via X-Hermes-Session-Key.  This
        # is independent of X-Hermes-Session-Id: the key persists across
        # transcripts while the id rotates when the caller starts a new
        # transcript (i.e. /new semantics).  See _parse_session_key_header.
        gateway_session_key, key_err = self._parse_session_key_header(request)
        if key_err is not None:
            return key_err

        if (
            self._access_registry is not None
            and request.headers.get("X-Troika-Device-Context-Consent", "").lower()
            == "revoked"
            and gateway_session_key
        ):
            from tools.location_tool import clear_device_context

            clear_device_context(gateway_session_key)
            self._record_product_audit(
                request,
                "device_context.revoked",
                session_id=gateway_session_key,
            )

        # X-Hermes-Device-Context: JSON {bssid, ssid, network_type,
        # bluetooth: [...], device_name}. Кладём в кэш location_tool по
        # session_key и подмешиваем подсказку про место (дом/работа/машина)
        # в system prompt.
        raw_ctx = request.headers.get("X-Hermes-Device-Context", "").strip()
        if raw_ctx and self._product_device_context_allowed(request):
            try:
                if re.search(r"[\r\n\x00]", raw_ctx):
                    raise ValueError("control chars in header")
                if len(raw_ctx) > 4096:
                    raise ValueError("header too long")
                parsed_ctx = json.loads(raw_ctx)
                if isinstance(parsed_ctx, dict):
                    from tools.location_tool import (
                        remember_device_context,
                        system_prompt_amendment as _loc_amend,
                    )
                    # Device context is sensitive and belongs only to an
                    # authenticated, explicitly scoped session.  Never put
                    # it in a shared fallback bucket.
                    if gateway_session_key:
                        remember_device_context(gateway_session_key, parsed_ctx)
                        amendment = _loc_amend(gateway_session_key)
                        if amendment:
                            system_prompt = (system_prompt or "") + amendment
                    else:
                        logger.debug(
                            "device_context header ignored: no session key was provided"
                        )
            except Exception as e:
                logger.debug("device_context header ignored: %s", e)
        elif raw_ctx:
            logger.info(
                "device_context header ignored: explicit product consent missing: %s",
                self._request_audit_log_suffix(request),
            )

        # Active local project context is a legacy single-user feature.  It can
        # contain an operator project name and server path, so it must never be
        # injected into a hosted product user's conversation.
        if self._access_registry is None:
            try:
                from tools.project_tool import get_active_project_summary as _active_proj

                _proj_summary = _active_proj()
                if _proj_summary:
                    system_prompt = (system_prompt or "") + "\n\n" + _proj_summary
            except Exception as _e:
                logger.debug("active_project injection skipped: %s", _e)

        # Allow caller to continue an existing session by passing X-Hermes-Session-Id.
        # When provided, history is loaded from state.db instead of from the request body.
        #
        # Security: session continuation exposes conversation history, so it is
        # only allowed when the API key is configured and the request is
        # authenticated.  Without this gate, any unauthenticated client could
        # read arbitrary session history by guessing/enumerating session IDs.
        provided_session_id = request.headers.get("X-Hermes-Session-Id", "").strip()
        if provided_session_id:
            if not self._api_key and self._access_registry is None:
                logger.warning(
                    "Session continuation via X-Hermes-Session-Id rejected: "
                    "no API key configured.  Set API_SERVER_KEY to enable "
                    "session continuity."
                )
                return web.json_response(
                    _openai_error(
                        "Session continuation requires API key authentication. "
                        "Configure API_SERVER_KEY to enable this feature."
                    ),
                    status=403,
                )
            # Sanitize: reject control characters that could enable header injection.
            if re.search(r'[\r\n\x00]', provided_session_id):
                return web.json_response(
                    {"error": {"message": "Invalid session ID", "type": "invalid_request_error"}},
                    status=400,
                )
            session_id = provided_session_id
            try:
                db = self._ensure_session_db()
                if db is not None:
                    history = db.get_messages_as_conversation(session_id)
                    # Troika voice: ограничиваем историю до последних N сообщений
                    # чтобы голосовая Тройка не тащила месяцы диалога в каждый
                    # запрос. Lim читается из env TROIKA_HISTORY_LIMIT (default 20).
                    # Sliced с конца — самые свежие реплики. 0 или отрицательное
                    # отключает лимит.
                    try:
                        _hlim = int(os.environ.get("TROIKA_HISTORY_LIMIT", "20"))
                    except (TypeError, ValueError):
                        _hlim = 20
                    if _hlim > 0 and len(history) > _hlim:
                        # Стрипаем висящие tool-сообщения в начале — у LLM это
                        # ломает контекст (tool_call_id без предыдущего
                        # assistant с tool_calls). Берём более широкий хвост и
                        # двигаемся вперёд пока не найдём user/system.
                        cut = max(0, len(history) - _hlim)
                        while cut < len(history) and history[cut].get("role") in {"tool", "assistant"}:
                            cut += 1
                        if cut < len(history):
                            history = history[cut:]
                            logger.info(
                                "Troika voice: trimmed history for %s to %d msgs (limit=%d)",
                                session_id, len(history), _hlim,
                            )
            except Exception as e:
                logger.warning("Failed to load session history for %s: %s", session_id, e)
                history = []
        else:
            # Derive a stable session ID from the conversation fingerprint so
            # that consecutive messages from the same Open WebUI (or similar)
            # conversation map to the same Hermes session.  The first user
            # message + system prompt are constant across all turns.
            first_user = ""
            for cm in conversation_messages:
                if cm.get("role") == "user":
                    first_user = cm.get("content", "")
                    break
            session_id = _derive_chat_session_id(system_prompt, first_user)
            # history already set from request body above

        session_auth_err = self._authorize_product_session(
            request, session_id, claim=True
        )
        if session_auth_err:
            return session_auth_err

        quota_err = self._consume_product_request_quota(request)
        if quota_err:
            return quota_err
        usage = request.get("troika_usage")
        if product_principal is not None:
            audit_details: Dict[str, Any] = {"endpoint": "chat_completions"}
            if usage is not None:
                audit_details.update(
                    {"limit": usage.limit, "remaining": usage.remaining}
                )
            self._record_product_audit(
                request,
                "request.accepted",
                session_id=session_id,
                details=audit_details,
            )

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        model_name = body.get("model", self._model_name)
        created = int(time.time())

        if stream:
            import queue as _q
            _stream_q: _q.Queue = _q.Queue()

            def _on_delta(delta):
                # Filter out None — the agent fires stream_delta_callback(None)
                # to signal the CLI display to close its response box before
                # tool execution, but the SSE writer uses None as end-of-stream
                # sentinel.  Forwarding it would prematurely close the HTTP
                # response, causing Open WebUI (and similar frontends) to miss
                # the final answer after tool calls.  The SSE loop detects
                # completion via agent_task.done() instead.
                if delta is not None:
                    _stream_q.put(delta)

            # Track which tool_call_ids we've emitted a "running" lifecycle
            # event for, so a "completed" event without a matching "running"
            # (e.g. internal/filtered tools) is silently dropped instead of
            # producing an orphaned event clients can't correlate.
            _started_tool_call_ids: set[str] = set()

            def _on_tool_start(tool_call_id, function_name, function_args):
                """Emit ``hermes.tool.progress`` with ``status: running``.

                Replaces the old ``tool_progress_callback("tool.started",
                ...)`` emit so SSE consumers receive a single event per
                tool start, carrying both the legacy ``tool``/``emoji``/
                ``label`` payload (for #6972 frontends) and the new
                ``toolCallId``/``status`` correlation fields (#16588).

                Skips tools whose names start with ``_`` so internal
                events (``_thinking``, …) stay off the wire — matching
                the prior ``_on_tool_progress`` filter exactly.
                """
                if not tool_call_id or function_name.startswith("_"):
                    return
                _started_tool_call_ids.add(tool_call_id)
                from agent.display import build_tool_preview, get_tool_emoji
                label = build_tool_preview(function_name, function_args) or function_name
                _stream_q.put(("__tool_progress__", {
                    "tool": function_name,
                    "emoji": get_tool_emoji(function_name),
                    "label": label,
                    "toolCallId": tool_call_id,
                    "status": "running",
                }))

            def _on_tool_complete(tool_call_id, function_name, function_args, function_result):
                """Emit the matching ``status: completed`` event.

                Dropped if the start was filtered (internal tool, missing
                id, or never seen) so clients never get an orphaned
                ``completed`` they can't correlate to a prior ``running``.
                """
                if not tool_call_id or tool_call_id not in _started_tool_call_ids:
                    return
                _started_tool_call_ids.discard(tool_call_id)
                _stream_q.put(("__tool_progress__", {
                    "tool": function_name,
                    "toolCallId": tool_call_id,
                    "status": "completed",
                }))

            # Start agent in background.  agent_ref is a mutable container
            # so the SSE writer can interrupt the agent on client disconnect.
            #
            # ``tool_progress_callback`` is intentionally not wired here:
            # it would duplicate every emit because ``run_agent`` fires it
            # side-by-side with ``tool_start_callback``/``tool_complete_callback``.
            # The structured callbacks are strictly richer (they carry the
            # tool_call id), so they own the chat-completions SSE channel.
            agent_ref = [None]
            agent_task = asyncio.ensure_future(self._run_agent(
                user_message=user_message,
                conversation_history=history,
                ephemeral_system_prompt=system_prompt,
                session_id=session_id,
                stream_delta_callback=_on_delta,
                tool_start_callback=_on_tool_start,
                tool_complete_callback=_on_tool_complete,
                agent_ref=agent_ref,
                gateway_session_key=gateway_session_key,
                product_principal=product_principal,
            ))
            # Ensure SSE drain loops can terminate without relying on polling
            # agent_task.done(), which can race with queue timeout checks.
            agent_task.add_done_callback(lambda _fut: _stream_q.put(None))

            return await self._write_sse_chat_completion(
                request, completion_id, model_name, created, _stream_q,
                agent_task, agent_ref, session_id=session_id,
                gateway_session_key=gateway_session_key,
            )

        # Non-streaming: run the agent (with optional Idempotency-Key)
        async def _compute_completion():
            return await self._run_agent(
                user_message=user_message,
                conversation_history=history,
                ephemeral_system_prompt=system_prompt,
                session_id=session_id,
                gateway_session_key=gateway_session_key,
                product_principal=product_principal,
            )

        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            fp = _make_request_fingerprint(body, keys=["model", "messages", "tools", "tool_choice", "stream"])
            try:
                result, usage = await _idem_cache.get_or_set(idempotency_key, fp, _compute_completion)
            except Exception as e:
                logger.error("Error running agent for chat completions: %s", e, exc_info=True)
                return web.json_response(
                    _openai_error(f"Internal server error: {e}", err_type="server_error"),
                    status=500,
                )
        else:
            try:
                result, usage = await _compute_completion()
            except Exception as e:
                logger.error("Error running agent for chat completions: %s", e, exc_info=True)
                return web.json_response(
                    _openai_error(f"Internal server error: {e}", err_type="server_error"),
                    status=500,
                )

        final_response = result.get("final_response") or ""
        is_partial = bool(result.get("partial"))
        is_failed = bool(result.get("failed"))
        completed = bool(result.get("completed", True))
        err_msg = result.get("error")

        # Decide finish_reason. OpenAI uses "length" for truncation, "stop"
        # for normal completion, and downstream SDKs accept "error" / custom
        # codes. See issue #22496.
        if is_partial and err_msg and "truncat" in err_msg.lower():
            finish_reason = "length"
        elif is_failed or (not completed and err_msg):
            finish_reason = "error"
        else:
            finish_reason = "stop"

        response_headers = {
            "X-Hermes-Session-Id": result.get("session_id", session_id),
        }
        if gateway_session_key:
            response_headers["X-Hermes-Session-Key"] = gateway_session_key

        # Hard-fail path: no usable assistant text AND a real failure → 5xx
        # with OpenAI-style error envelope so SDK clients raise instead of
        # silently rendering the internal failure string as message.content.
        if not final_response and (is_failed or is_partial):
            err_body = _openai_error(
                err_msg or "Agent run did not produce a response.",
                err_type="server_error",
                code="agent_incomplete",
            )
            err_body["error"]["hermes"] = {
                "completed": completed,
                "partial": is_partial,
                "failed": is_failed,
            }
            response_headers["X-Hermes-Completed"] = "false"
            response_headers["X-Hermes-Partial"] = "true" if is_partial else "false"
            return web.json_response(err_body, status=502, headers=response_headers)

        # Soft-partial path: we have *some* text but the run did not complete
        # (e.g. truncation with partial buffered output). Still 200 but signal
        # truncation via finish_reason="length" + Hermes-specific extras.
        response_data = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": final_response,
                    },
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }
        if is_partial or is_failed or not completed:
            response_data["hermes"] = {
                "completed": completed,
                "partial": is_partial,
                "failed": is_failed,
                "error": err_msg,
                "error_code": "output_truncated" if finish_reason == "length" else "agent_error",
            }
            response_headers["X-Hermes-Completed"] = "false"
            response_headers["X-Hermes-Partial"] = "true" if is_partial else "false"
            if err_msg:
                response_headers["X-Hermes-Error"] = err_msg[:200]

        return web.json_response(response_data, headers=response_headers)

    async def _write_sse_chat_completion(
        self, request: "web.Request", completion_id: str, model: str,
        created: int, stream_q, agent_task, agent_ref=None, session_id: str = None,
        gateway_session_key: str = None,
    ) -> "web.StreamResponse":
        """Write real streaming SSE from agent's stream_delta_callback queue.

        If the client disconnects mid-stream (network drop, browser tab close),
        the agent is interrupted via ``agent.interrupt()`` so it stops making
        LLM API calls, and the asyncio task wrapper is cancelled.
        """
        import queue as _q

        sse_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        # CORS middleware can't inject headers into StreamResponse after
        # prepare() flushes them, so resolve CORS headers up front.
        origin = request.headers.get("Origin", "")
        cors = self._cors_headers_for_origin(origin) if origin else None
        if cors:
            sse_headers.update(cors)
        if session_id:
            sse_headers["X-Hermes-Session-Id"] = session_id
        if gateway_session_key:
            sse_headers["X-Hermes-Session-Key"] = gateway_session_key
        response = web.StreamResponse(status=200, headers=sse_headers)
        await response.prepare(request)

        try:
            last_activity = time.monotonic()

            # Role chunk
            role_chunk = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            await response.write(f"data: {json.dumps(role_chunk)}\n\n".encode())
            last_activity = time.monotonic()

            # Helper — route a queue item to the correct SSE event.
            async def _emit(item):
                """Write a single queue item to the SSE stream.

                Plain strings are sent as normal ``delta.content`` chunks.
                Tagged tuples ``("__tool_progress__", payload)`` are sent
                as a custom ``event: hermes.tool.progress`` SSE event so
                frontends can display them without storing the markers in
                conversation history.  See #6972 for the original event,
                #16588 for the ``toolCallId``/``status`` lifecycle fields.
                """
                if isinstance(item, tuple) and len(item) == 2 and item[0] == "__tool_progress__":
                    event_data = json.dumps(item[1])
                    await response.write(
                        f"event: hermes.tool.progress\ndata: {event_data}\n\n".encode()
                    )
                else:
                    content_chunk = {
                        "id": completion_id, "object": "chat.completion.chunk",
                        "created": created, "model": model,
                        "choices": [{"index": 0, "delta": {"content": item}, "finish_reason": None}],
                    }
                    await response.write(f"data: {json.dumps(content_chunk)}\n\n".encode())
                return time.monotonic()

            # Stream content chunks as they arrive from the agent
            loop = asyncio.get_running_loop()
            while True:
                try:
                    delta = await loop.run_in_executor(None, lambda: stream_q.get(timeout=0.5))
                except _q.Empty:
                    if agent_task.done():
                        # Drain any remaining items
                        while True:
                            try:
                                delta = stream_q.get_nowait()
                                if delta is None:
                                    break
                                last_activity = await _emit(delta)
                            except _q.Empty:
                                break
                        break
                    if time.monotonic() - last_activity >= CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS:
                        await response.write(b": keepalive\n\n")
                        last_activity = time.monotonic()
                    continue

                if delta is None:  # End of stream sentinel
                    break

                last_activity = await _emit(delta)

            # Get usage from completed agent
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            try:
                result, agent_usage = await agent_task
                usage = agent_usage or usage
            except Exception as exc:
                logger.warning("Agent task %s failed, usage data lost: %s", completion_id, exc)

            # Finish chunk
            finish_chunk = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
            await response.write(f"data: {json.dumps(finish_chunk)}\n\n".encode())
            await response.write(b"data: [DONE]\n\n")
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            # Client disconnected mid-stream.  Interrupt the agent so it
            # stops making LLM API calls at the next loop iteration, then
            # cancel the asyncio task wrapper.
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE client disconnected")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            logger.info("SSE client disconnected; interrupted agent task %s", completion_id)
        except Exception as _exc:
            # Agent crashed mid-stream.  Try to emit an error chunk
            # so the client gets a proper response instead of a
            # TransferEncodingError from incomplete chunked encoding.
            import traceback as _tb
            logger.error("Agent crashed mid-stream for %s: %s", completion_id, _tb.format_exc()[:300])
            try:
                error_chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                }
                await response.write(f"data: {json.dumps(error_chunk)}\n\n".encode())
                await response.write(b"data: [DONE]\n\n")
            except Exception:
                pass

        return response

    async def _write_sse_responses(
        self,
        request: "web.Request",
        response_id: str,
        model: str,
        created_at: int,
        stream_q,
        agent_task,
        agent_ref,
        conversation_history: List[Dict[str, str]],
        user_message: str,
        instructions: Optional[str],
        conversation: Optional[str],
        store: bool,
        session_id: str,
        gateway_session_key: Optional[str] = None,
    ) -> "web.StreamResponse":
        """Write an SSE stream for POST /v1/responses (OpenAI Responses API).

        Emits spec-compliant event types as the agent runs:

        - ``response.created`` — initial envelope (status=in_progress)
        - ``response.output_text.delta`` / ``response.output_text.done`` —
          streamed assistant text
        - ``response.output_item.added`` / ``response.output_item.done``
          with ``item.type == "function_call"`` — when the agent invokes a
          tool (both events fire; the ``done`` event carries the finalized
          ``arguments`` string)
        - ``response.output_item.added`` with
          ``item.type == "function_call_output"`` — tool result with
          ``{call_id, output, status}``
        - ``response.completed`` — terminal event carrying the full
          response object with all output items + usage (same payload
          shape as the non-streaming path for parity)
        - ``response.failed`` — terminal event on agent error

        If the client disconnects mid-stream, ``agent.interrupt()`` is
        called so the agent stops issuing upstream LLM calls, then the
        asyncio task is cancelled.  When ``store=True`` an initial
        ``in_progress`` snapshot is persisted immediately after
        ``response.created`` and disconnects update it to an
        ``incomplete`` snapshot so GET /v1/responses/{id} and
        ``previous_response_id`` chaining still have something to
        recover from.
        """
        import queue as _q

        sse_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        origin = request.headers.get("Origin", "")
        cors = self._cors_headers_for_origin(origin) if origin else None
        if cors:
            sse_headers.update(cors)
        if session_id:
            sse_headers["X-Hermes-Session-Id"] = session_id
        if gateway_session_key:
            sse_headers["X-Hermes-Session-Key"] = gateway_session_key
        response = web.StreamResponse(status=200, headers=sse_headers)
        await response.prepare(request)

        # State accumulated during the stream
        final_text_parts: List[str] = []
        # Track open function_call items by name so we can emit a matching
        # ``done`` event when the tool completes.  Order preserved.
        pending_tool_calls: List[Dict[str, Any]] = []
        # Output items we've emitted so far (used to build the terminal
        # response.completed payload).  Kept in the order they appeared.
        emitted_items: List[Dict[str, Any]] = []
        # Monotonic counter for output_index (spec requires it).
        output_index = 0
        # Monotonic counter for call_id generation if the agent doesn't
        # provide one (it doesn't, from tool_progress_callback).
        call_counter = 0
        # Canonical Responses SSE events include a monotonically increasing
        # sequence_number. Add it server-side for every emitted event so
        # clients that validate the OpenAI event schema can parse our stream.
        sequence_number = 0
        # Track the assistant message item id + content index for text
        # delta events — the spec ties deltas to a specific item.
        message_item_id = f"msg_{uuid.uuid4().hex[:24]}"
        message_output_index: Optional[int] = None
        message_opened = False

        async def _write_event(event_type: str, data: Dict[str, Any]) -> None:
            nonlocal sequence_number
            if "sequence_number" not in data:
                data["sequence_number"] = sequence_number
            sequence_number += 1
            payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            await response.write(payload.encode())

        def _envelope(status: str) -> Dict[str, Any]:
            env: Dict[str, Any] = {
                "id": response_id,
                "object": "response",
                "status": status,
                "created_at": created_at,
                "model": model,
            }
            return env

        final_response_text = ""
        agent_error: Optional[str] = None
        usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        terminal_snapshot_persisted = False

        def _persist_response_snapshot(
            response_env: Dict[str, Any],
            *,
            conversation_history_snapshot: Optional[List[Dict[str, Any]]] = None,
        ) -> None:
            if not store:
                return
            if conversation_history_snapshot is None:
                conversation_history_snapshot = list(conversation_history)
                conversation_history_snapshot.append({"role": "user", "content": user_message})
            self._response_store.put(response_id, {
                "response": response_env,
                "conversation_history": conversation_history_snapshot,
                "instructions": instructions,
                "session_id": session_id,
            })
            if conversation:
                self._response_store.set_conversation(conversation, response_id)

        def _persist_incomplete_if_needed() -> None:
            """Persist an ``incomplete`` snapshot if no terminal one was written.

            Called from both the client-disconnect (``ConnectionResetError``)
            and server-cancellation (``asyncio.CancelledError``) paths so
            GET /v1/responses/{id} and ``previous_response_id`` chaining keep
            working after abrupt stream termination.
            """
            if not store or terminal_snapshot_persisted:
                return
            incomplete_text = "".join(final_text_parts) or final_response_text
            incomplete_items: List[Dict[str, Any]] = list(emitted_items)
            if incomplete_text:
                incomplete_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": incomplete_text}],
                })
            incomplete_env = _envelope("incomplete")
            incomplete_env["output"] = incomplete_items
            incomplete_env["usage"] = {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
            incomplete_history = list(conversation_history)
            incomplete_history.append({"role": "user", "content": user_message})
            if incomplete_text:
                incomplete_history.append({"role": "assistant", "content": incomplete_text})
            _persist_response_snapshot(
                incomplete_env,
                conversation_history_snapshot=incomplete_history,
            )

        try:
            # response.created — initial envelope, status=in_progress
            created_env = _envelope("in_progress")
            created_env["output"] = []
            await _write_event("response.created", {
                "type": "response.created",
                "response": created_env,
            })
            _persist_response_snapshot(created_env)
            last_activity = time.monotonic()

            async def _open_message_item() -> None:
                """Emit response.output_item.added for the assistant message
                the first time any text delta arrives."""
                nonlocal message_opened, message_output_index, output_index
                if message_opened:
                    return
                message_opened = True
                message_output_index = output_index
                output_index += 1
                item = {
                    "id": message_item_id,
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                }
                await _write_event("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": message_output_index,
                    "item": item,
                })

            async def _emit_text_delta(delta_text: str) -> None:
                await _open_message_item()
                final_text_parts.append(delta_text)
                await _write_event("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "item_id": message_item_id,
                    "output_index": message_output_index,
                    "content_index": 0,
                    "delta": delta_text,
                    "logprobs": [],
                })

            async def _emit_tool_started(payload: Dict[str, Any]) -> str:
                """Emit response.output_item.added for a function_call.

                Returns the call_id so the matching completion event can
                reference it.  Prefer the real ``tool_call_id`` from the
                agent when available; fall back to a generated call id for
                safety in tests or older code paths.
                """
                nonlocal output_index, call_counter
                call_counter += 1
                call_id = payload.get("tool_call_id") or f"call_{response_id[5:]}_{call_counter}"
                args = payload.get("arguments", {})
                if isinstance(args, dict):
                    arguments_str = json.dumps(args)
                else:
                    arguments_str = str(args)
                item = {
                    "id": f"fc_{uuid.uuid4().hex[:24]}",
                    "type": "function_call",
                    "status": "in_progress",
                    "name": payload.get("name", ""),
                    "call_id": call_id,
                    "arguments": arguments_str,
                }
                idx = output_index
                output_index += 1
                pending_tool_calls.append({
                    "call_id": call_id,
                    "name": payload.get("name", ""),
                    "arguments": arguments_str,
                    "item_id": item["id"],
                    "output_index": idx,
                })
                emitted_items.append({
                    "type": "function_call",
                    "name": payload.get("name", ""),
                    "arguments": arguments_str,
                    "call_id": call_id,
                })
                await _write_event("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": idx,
                    "item": item,
                })
                return call_id

            async def _emit_tool_completed(payload: Dict[str, Any]) -> None:
                """Emit response.output_item.done (function_call) followed
                by response.output_item.added (function_call_output)."""
                nonlocal output_index
                call_id = payload.get("tool_call_id")
                result = payload.get("result", "")
                pending = None
                if call_id:
                    for i, p in enumerate(pending_tool_calls):
                        if p["call_id"] == call_id:
                            pending = pending_tool_calls.pop(i)
                            break
                if pending is None:
                    # Completion without a matching start — skip to avoid
                    # emitting orphaned done events.
                    return

                # function_call done
                done_item = {
                    "id": pending["item_id"],
                    "type": "function_call",
                    "status": "completed",
                    "name": pending["name"],
                    "call_id": pending["call_id"],
                    "arguments": pending["arguments"],
                }
                await _write_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": pending["output_index"],
                    "item": done_item,
                })

                # function_call_output added (result)
                result_str = result if isinstance(result, str) else json.dumps(result)
                output_parts = [{"type": "input_text", "text": result_str}]
                output_item = {
                    "id": f"fco_{uuid.uuid4().hex[:24]}",
                    "type": "function_call_output",
                    "call_id": pending["call_id"],
                    "output": output_parts,
                    "status": "completed",
                }
                idx = output_index
                output_index += 1
                emitted_items.append({
                    "type": "function_call_output",
                    "call_id": pending["call_id"],
                    "output": output_parts,
                })
                await _write_event("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": idx,
                    "item": output_item,
                })
                await _write_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": idx,
                    "item": output_item,
                })

            # Main drain loop — thread-safe queue fed by agent callbacks.
            async def _dispatch(it) -> None:
                """Route a queue item to the correct SSE emitter.

                Plain strings are text deltas — they are batched (50ms)
                to reduce Open WebUI re-render storms.  Tagged tuples
                with ``__tool_started__`` / ``__tool_completed__``
                prefixes are tool lifecycle events and flush the buffer
                before emitting.
                """
                nonlocal _batch_timer
                if isinstance(it, tuple) and len(it) == 2 and isinstance(it[0], str):
                    tag, payload = it
                    # Flush batched text before tool events
                    if _batch_buf:
                        await _flush_batch()
                    if tag == "__tool_started__":
                        await _emit_tool_started(payload)
                    elif tag == "__tool_completed__":
                        await _emit_tool_completed(payload)
                elif isinstance(it, str):
                    # Batch text deltas — append to buffer, flush on timer
                    _batch_buf.append(it)
                    if _batch_timer is None:
                        _batch_timer = asyncio.create_task(_batch_flush_after(0.05))
                # Other types are silently dropped.

            # ── Batching state ──
            _batch_buf: List[str] = []
            _batch_timer: Optional[asyncio.Task] = None
            _batch_lock = asyncio.Lock()

            async def _batch_flush_after(delay: float) -> None:
                """Wait delay seconds, then flush accumulated text deltas."""
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                # Clear timer reference BEFORE flush so new deltas
                # can start a fresh timer while we emit
                nonlocal _batch_buf, _batch_timer
                _batch_timer = None
                await _flush_batch()

            async def _flush_batch() -> None:
                """Emit a single SSE delta for all accumulated text."""
                nonlocal _batch_buf
                async with _batch_lock:
                    if _batch_buf:
                        combined = "".join(_batch_buf)
                        _batch_buf = []
                        await _emit_text_delta(combined)

            loop = asyncio.get_running_loop()
            while True:
                try:
                    item = await loop.run_in_executor(None, lambda: stream_q.get(timeout=0.5))
                except _q.Empty:
                    if agent_task.done():
                        # Drain remaining
                        while True:
                            try:
                                item = stream_q.get_nowait()
                                if item is None:
                                    break
                                await _dispatch(item)
                                last_activity = time.monotonic()
                            except _q.Empty:
                                break
                        break
                    if time.monotonic() - last_activity >= CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS:
                        await response.write(b": keepalive\n\n")
                        last_activity = time.monotonic()
                    continue

                if item is None:  # EOS sentinel
                    # Cancel pending timer and flush remaining batched text
                    if _batch_timer and not _batch_timer.done():
                        _batch_timer.cancel()
                        _batch_timer = None
                    if _batch_buf:
                        await _flush_batch()
                    break

                await _dispatch(item)
                last_activity = time.monotonic()

            # Flush any final batched text before processing result
            if _batch_buf:
                await _flush_batch()

            # Pick up agent result + usage from the completed task
            try:
                result, agent_usage = await agent_task
                usage = agent_usage or usage
                # If the agent produced a final_response but no text
                # deltas were streamed (e.g. some providers only emit
                # the full response at the end), emit a single fallback
                # delta so Responses clients still receive a live text part.
                agent_final = result.get("final_response", "") if isinstance(result, dict) else ""
                if agent_final and not final_text_parts:
                    await _emit_text_delta(agent_final)
                if agent_final and not final_response_text:
                    final_response_text = agent_final
                if isinstance(result, dict) and result.get("error") and not final_response_text:
                    agent_error = result["error"]
            except Exception as e:  # noqa: BLE001
                logger.error("Error running agent for streaming responses: %s", e, exc_info=True)
                agent_error = str(e)

            # Close the message item if it was opened
            final_response_text = "".join(final_text_parts) or final_response_text
            if message_opened:
                await _write_event("response.output_text.done", {
                    "type": "response.output_text.done",
                    "item_id": message_item_id,
                    "output_index": message_output_index,
                    "content_index": 0,
                    "text": final_response_text,
                    "logprobs": [],
                })
                msg_done_item = {
                    "id": message_item_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": final_response_text}
                    ],
                }
                await _write_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": message_output_index,
                    "item": msg_done_item,
                })

            # Always append a final message item in the completed
            # response envelope so clients that only parse the terminal
            # payload still see the assistant text.  This mirrors the
            # shape produced by _extract_output_items in the batch path.
            final_items: List[Dict[str, Any]] = list(emitted_items)

            # Trim large content from tool call arguments to keep the
            # response.completed event under ~100KB.  Clients already
            # received full details via incremental events.
            for _item in final_items:
                if _item.get("type") == "function_call":
                    try:
                        _args = json.loads(_item.get("arguments", "{}")) if isinstance(_item.get("arguments"), str) else _item.get("arguments", {})
                        if isinstance(_args, dict):
                            for _k in ("content", "query", "pattern", "old_string", "new_string"):
                                if isinstance(_args.get(_k), str) and len(_args[_k]) > 500:
                                    _args[_k] = "[" + str(len(_args[_k])) + " chars — truncated for response.completed]"
                            _item["arguments"] = json.dumps(_args)
                    except Exception:
                        pass
                elif _item.get("type") == "function_call_output":
                    _output = _item.get("output", [])
                    if isinstance(_output, list) and _output:
                        _first = _output[0]
                        if isinstance(_first, dict) and _first.get("type") == "input_text":
                            _text = _first.get("text", "")
                            if len(_text) > 1000:
                                _first["text"] = _text[:500] + "...[" + str(len(_text) - 500) + " more chars]"
                                _item["output"] = [_first]

            final_items.append({
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": final_response_text or (agent_error or "")}
                ],
            })

            if agent_error:
                failed_env = _envelope("failed")
                failed_env["output"] = final_items
                failed_env["error"] = {"message": agent_error, "type": "server_error"}
                failed_env["usage"] = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }
                _failed_history = list(conversation_history)
                _failed_history.append({"role": "user", "content": user_message})
                if final_response_text or agent_error:
                    _failed_history.append({
                        "role": "assistant",
                        "content": final_response_text or agent_error,
                    })
                _persist_response_snapshot(
                    failed_env,
                    conversation_history_snapshot=_failed_history,
                )
                terminal_snapshot_persisted = True
                await _write_event("response.failed", {
                    "type": "response.failed",
                    "response": failed_env,
                })
            else:
                completed_env = _envelope("completed")
                completed_env["output"] = final_items
                completed_env["usage"] = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }
                full_history = self._build_response_conversation_history(
                    conversation_history,
                    user_message,
                    result,
                    final_response_text,
                )
                _persist_response_snapshot(
                    completed_env,
                    conversation_history_snapshot=full_history,
                )
                terminal_snapshot_persisted = True
                await _write_event("response.completed", {
                    "type": "response.completed",
                    "response": completed_env,
                })

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            _persist_incomplete_if_needed()
            # Client disconnected — interrupt the agent so it stops
            # making upstream LLM calls, then cancel the task.
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE client disconnected")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            logger.info("SSE client disconnected; interrupted agent task %s", response_id)
        except asyncio.CancelledError:
            # Server-side cancellation (e.g. shutdown, request timeout) —
            # persist an incomplete snapshot so GET /v1/responses/{id} and
            # previous_response_id chaining still work, then re-raise so the
            # runtime's cancellation semantics are respected.
            _persist_incomplete_if_needed()
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE task cancelled")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
            logger.info("SSE task cancelled; persisted incomplete snapshot for %s", response_id)
            raise
        except Exception as _exc:
            # Agent crashed with an unhandled error (e.g. model API error like
            # BadRequestError, AuthenticationError).  Emit a response.failed
            # event and properly terminate the SSE stream so the client doesn't
            # get a TransferEncodingError from incomplete chunked encoding.
            import traceback as _tb
            _persist_incomplete_if_needed()
            agent_error = _tb.format_exc()
            try:
                failed_env = _envelope("failed")
                failed_env["output"] = list(emitted_items)
                failed_env["error"] = {"message": str(_exc)[:500], "type": "server_error"}
                failed_env["usage"] = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }
                await _write_event("response.failed", {
                    "type": "response.failed",
                    "response": failed_env,
                })
            except Exception:
                pass
            logger.error("Agent crashed mid-stream for %s: %s", response_id, str(agent_error)[:300])

        return response

    async def _handle_responses(self, request: "web.Request") -> "web.Response":
        """POST /v1/responses — OpenAI Responses API format."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            return web.json_response(
                _openai_error(
                    "Responses API is unavailable in product mode until its "
                    "stored-response ownership is tenant-scoped",
                    code="endpoint_unavailable",
                ),
                status=404,
            )

        # Long-term memory scope header (see chat_completions for details).
        gateway_session_key, key_err = self._parse_session_key_header(request)
        if key_err is not None:
            return key_err

        # Parse request body
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(
                {"error": {"message": "Invalid JSON in request body", "type": "invalid_request_error"}},
                status=400,
            )

        raw_input = body.get("input")
        if raw_input is None:
            return web.json_response(_openai_error("Missing 'input' field"), status=400)

        instructions = body.get("instructions")
        previous_response_id = body.get("previous_response_id")
        conversation = body.get("conversation")
        store = _coerce_request_bool(body.get("store"), default=True)

        # conversation and previous_response_id are mutually exclusive
        if conversation and previous_response_id:
            return web.json_response(_openai_error("Cannot use both 'conversation' and 'previous_response_id'"), status=400)

        # Resolve conversation name to latest response_id
        if conversation:
            previous_response_id = self._response_store.get_conversation(conversation)
            # No error if conversation doesn't exist yet — it's a new conversation

        # Normalize input to message list
        input_messages: List[Dict[str, Any]] = []
        if isinstance(raw_input, str):
            input_messages = [{"role": "user", "content": raw_input}]
        elif isinstance(raw_input, list):
            for idx, item in enumerate(raw_input):
                if isinstance(item, str):
                    input_messages.append({"role": "user", "content": item})
                elif isinstance(item, dict):
                    role = item.get("role", "user")
                    try:
                        content = _normalize_multimodal_content(item.get("content", ""))
                    except ValueError as exc:
                        return _multimodal_validation_error(exc, param=f"input[{idx}].content")
                    input_messages.append({"role": role, "content": content})
        else:
            return web.json_response(_openai_error("'input' must be a string or array"), status=400)

        # Accept explicit conversation_history from the request body.
        # This lets stateless clients supply their own history instead of
        # relying on server-side response chaining via previous_response_id.
        # Precedence: explicit conversation_history > previous_response_id.
        conversation_history: List[Dict[str, Any]] = []
        raw_history = body.get("conversation_history")
        if raw_history:
            if not isinstance(raw_history, list):
                return web.json_response(
                    _openai_error("'conversation_history' must be an array of message objects"),
                    status=400,
                )
            for i, entry in enumerate(raw_history):
                if not isinstance(entry, dict) or "role" not in entry or "content" not in entry:
                    return web.json_response(
                        _openai_error(f"conversation_history[{i}] must have 'role' and 'content' fields"),
                        status=400,
                    )
                try:
                    entry_content = _normalize_multimodal_content(entry["content"])
                except ValueError as exc:
                    return _multimodal_validation_error(exc, param=f"conversation_history[{i}].content")
                conversation_history.append({"role": str(entry["role"]), "content": entry_content})
            if previous_response_id:
                logger.debug("Both conversation_history and previous_response_id provided; using conversation_history")

        stored_session_id = None
        if not conversation_history and previous_response_id:
            stored = self._response_store.get(previous_response_id)
            if stored is None:
                return web.json_response(_openai_error(f"Previous response not found: {previous_response_id}"), status=404)
            conversation_history = list(stored.get("conversation_history", []))
            stored_session_id = stored.get("session_id")
            # If no instructions provided, carry forward from previous
            if instructions is None:
                instructions = stored.get("instructions")

        # Append new input messages to history (all but the last become history)
        for msg in input_messages[:-1]:
            conversation_history.append(msg)

        # Last input message is the user_message
        user_message: Any = input_messages[-1].get("content", "") if input_messages else ""
        if not _content_has_visible_payload(user_message):
            return web.json_response(_openai_error("No user message found in input"), status=400)

        # Truncation support
        if body.get("truncation") == "auto" and len(conversation_history) > 100:
            conversation_history = conversation_history[-100:]

        # Reuse session from previous_response_id chain so the dashboard
        # groups the entire conversation under one session entry.
        session_id = stored_session_id or str(uuid.uuid4())

        stream = _coerce_request_bool(body.get("stream"), default=False)
        if stream:
            # Streaming branch — emit OpenAI Responses SSE events as the
            # agent runs so frontends can render text deltas and tool
            # calls in real time.  See _write_sse_responses for details.
            import queue as _q
            _stream_q: _q.Queue = _q.Queue()

            def _on_delta(delta):
                # None from the agent is a CLI box-close signal, not EOS.
                # Forwarding would kill the SSE stream prematurely; the
                # SSE writer detects completion via agent_task.done().
                if delta is not None:
                    _stream_q.put(delta)

            def _on_tool_progress(event_type, name, preview, args, **kwargs):
                """Queue non-start tool progress events if needed in future.

                The structured Responses stream uses ``tool_start_callback``
                and ``tool_complete_callback`` for exact call-id correlation,
                so progress events are currently ignored here.
                """
                return

            def _on_tool_start(tool_call_id, function_name, function_args):
                """Queue a started tool for live function_call streaming."""
                _stream_q.put(("__tool_started__", {
                    "tool_call_id": tool_call_id,
                    "name": function_name,
                    "arguments": function_args or {},
                }))

            def _on_tool_complete(tool_call_id, function_name, function_args, function_result):
                """Queue a completed tool result for live function_call_output streaming."""
                _stream_q.put(("__tool_completed__", {
                    "tool_call_id": tool_call_id,
                    "name": function_name,
                    "arguments": function_args or {},
                    "result": function_result,
                }))

            agent_ref = [None]
            agent_task = asyncio.ensure_future(self._run_agent(
                user_message=user_message,
                conversation_history=conversation_history,
                ephemeral_system_prompt=instructions,
                session_id=session_id,
                stream_delta_callback=_on_delta,
                tool_progress_callback=_on_tool_progress,
                tool_start_callback=_on_tool_start,
                tool_complete_callback=_on_tool_complete,
                agent_ref=agent_ref,
                gateway_session_key=gateway_session_key,
            ))
            # Ensure SSE drain loops can terminate without relying on polling
            # agent_task.done(), which can race with queue timeout checks.
            agent_task.add_done_callback(lambda _fut: _stream_q.put(None))

            response_id = f"resp_{uuid.uuid4().hex[:28]}"
            model_name = body.get("model", self._model_name)
            created_at = int(time.time())

            return await self._write_sse_responses(
                request=request,
                response_id=response_id,
                model=model_name,
                created_at=created_at,
                stream_q=_stream_q,
                agent_task=agent_task,
                agent_ref=agent_ref,
                conversation_history=conversation_history,
                user_message=user_message,
                instructions=instructions,
                conversation=conversation,
                store=store,
                session_id=session_id,
                gateway_session_key=gateway_session_key,
            )

        async def _compute_response():
            return await self._run_agent(
                user_message=user_message,
                conversation_history=conversation_history,
                ephemeral_system_prompt=instructions,
                session_id=session_id,
                gateway_session_key=gateway_session_key,
            )

        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            fp = _make_request_fingerprint(
                body,
                keys=["input", "instructions", "previous_response_id", "conversation", "model", "tools"],
            )
            try:
                result, usage = await _idem_cache.get_or_set(idempotency_key, fp, _compute_response)
            except Exception as e:
                logger.error("Error running agent for responses: %s", e, exc_info=True)
                return web.json_response(
                    _openai_error(f"Internal server error: {e}", err_type="server_error"),
                    status=500,
                )
        else:
            try:
                result, usage = await _compute_response()
            except Exception as e:
                logger.error("Error running agent for responses: %s", e, exc_info=True)
                return web.json_response(
                    _openai_error(f"Internal server error: {e}", err_type="server_error"),
                    status=500,
                )

        final_response = result.get("final_response", "")
        if not final_response:
            final_response = result.get("error", "(No response generated)")

        response_id = f"resp_{uuid.uuid4().hex[:28]}"
        created_at = int(time.time())

        # Build the full conversation history for storage
        # (includes tool calls from the agent run)
        full_history = self._build_response_conversation_history(
            conversation_history,
            user_message,
            result,
            final_response,
        )

        # Build output items from the current turn only.  AIAgent returns a
        # full transcript in result["messages"], while older/mocked paths may
        # return only the current turn suffix.
        output_start_index = self._response_messages_turn_start_index(
            conversation_history,
            user_message,
            result,
        )
        output_items = self._extract_output_items(result, start_index=output_start_index)

        response_data = {
            "id": response_id,
            "object": "response",
            "status": "completed",
            "created_at": created_at,
            "model": body.get("model", self._model_name),
            "output": output_items,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

        # Store the complete response object for future chaining / GET retrieval
        if store:
            self._response_store.put(response_id, {
                "response": response_data,
                "conversation_history": full_history,
                "instructions": instructions,
                "session_id": session_id,
            })
            # Update conversation mapping so the next request with the same
            # conversation name automatically chains to this response
            if conversation:
                self._response_store.set_conversation(conversation, response_id)

        response_headers = {"X-Hermes-Session-Id": session_id}
        if gateway_session_key:
            response_headers["X-Hermes-Session-Key"] = gateway_session_key
        return web.json_response(response_data, headers=response_headers)

    # ------------------------------------------------------------------
    # GET / DELETE response endpoints
    # ------------------------------------------------------------------

    async def _handle_get_response(self, request: "web.Request") -> "web.Response":
        """GET /v1/responses/{response_id} — retrieve a stored response."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            return web.json_response(
                _openai_error("Response not found", code="response_not_found"), status=404
            )

        response_id = request.match_info["response_id"]
        stored = self._response_store.get(response_id)
        if stored is None:
            return web.json_response(_openai_error(f"Response not found: {response_id}"), status=404)

        return web.json_response(stored["response"])

    async def _handle_delete_response(self, request: "web.Request") -> "web.Response":
        """DELETE /v1/responses/{response_id} — delete a stored response."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        if self._access_registry is not None:
            return web.json_response(
                _openai_error("Response not found", code="response_not_found"), status=404
            )

        response_id = request.match_info["response_id"]
        deleted = self._response_store.delete(response_id)
        if not deleted:
            return web.json_response(_openai_error(f"Response not found: {response_id}"), status=404)

        return web.json_response({
            "id": response_id,
            "object": "response",
            "deleted": True,
        })

    # ------------------------------------------------------------------
    # Cron jobs API
    # ------------------------------------------------------------------

    _JOB_ID_RE = __import__("re").compile(r"[a-f0-9]{12}")
    # Allowed fields for update — prevents clients injecting arbitrary keys
    _UPDATE_ALLOWED_FIELDS = {"name", "schedule", "prompt", "deliver", "skills", "skill", "repeat", "enabled"}
    _MAX_NAME_LENGTH = 200
    _MAX_PROMPT_LENGTH = 5000

    @staticmethod
    def _check_jobs_available() -> Optional["web.Response"]:
        """Return error response if cron module isn't available."""
        if not _CRON_AVAILABLE:
            return web.json_response(
                {"error": "Cron module not available"}, status=501,
            )
        return None

    def _check_job_id(self, request: "web.Request") -> tuple:
        """Validate and extract job_id. Returns (job_id, error_response)."""
        job_id = request.match_info["job_id"]
        if not self._JOB_ID_RE.fullmatch(job_id):
            logger.warning(
                "Cron jobs API rejected invalid job_id %r: %s",
                job_id,
                self._request_audit_log_suffix(request),
            )
            return job_id, web.json_response(
                {"error": "Invalid job ID format"}, status=400,
            )
        return job_id, None

    async def _handle_list_jobs(self, request: "web.Request") -> "web.Response":
        """GET /api/jobs — list all cron jobs."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        try:
            include_disabled = request.query.get("include_disabled", "").lower() in {"true", "1"}
            jobs = _cron_list(include_disabled=include_disabled)
            return web.json_response({"jobs": jobs})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_create_job(self, request: "web.Request") -> "web.Response":
        """POST /api/jobs — create a new cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        try:
            body = await request.json()
            name = (body.get("name") or "").strip()
            schedule = (body.get("schedule") or "").strip()
            prompt = body.get("prompt", "")
            deliver = body.get("deliver", "local")
            skills = body.get("skills")
            repeat = body.get("repeat")

            if not name:
                return web.json_response({"error": "Name is required"}, status=400)
            if len(name) > self._MAX_NAME_LENGTH:
                return web.json_response(
                    {"error": f"Name must be ≤ {self._MAX_NAME_LENGTH} characters"}, status=400,
                )
            if not schedule:
                return web.json_response({"error": "Schedule is required"}, status=400)
            if len(prompt) > self._MAX_PROMPT_LENGTH:
                return web.json_response(
                    {"error": f"Prompt must be ≤ {self._MAX_PROMPT_LENGTH} characters"}, status=400,
                )
            if repeat is not None and (not isinstance(repeat, int) or repeat < 1):
                return web.json_response({"error": "Repeat must be a positive integer"}, status=400)

            kwargs = {
                "prompt": prompt,
                "schedule": schedule,
                "name": name,
                "deliver": deliver,
                "origin": self._cron_origin_from_request(request),
            }
            if skills:
                kwargs["skills"] = skills
            if repeat is not None:
                kwargs["repeat"] = repeat

            job = _cron_create(**kwargs)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_get_job(self, request: "web.Request") -> "web.Response":
        """GET /api/jobs/{job_id} — get a single cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            job = _cron_get(job_id)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_update_job(self, request: "web.Request") -> "web.Response":
        """PATCH /api/jobs/{job_id} — update a cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            body = await request.json()
            # Whitelist allowed fields to prevent arbitrary key injection
            sanitized = {k: v for k, v in body.items() if k in self._UPDATE_ALLOWED_FIELDS}
            if not sanitized:
                return web.json_response({"error": "No valid fields to update"}, status=400)
            # Validate lengths if present
            if "name" in sanitized and len(sanitized["name"]) > self._MAX_NAME_LENGTH:
                return web.json_response(
                    {"error": f"Name must be ≤ {self._MAX_NAME_LENGTH} characters"}, status=400,
                )
            if "prompt" in sanitized and len(sanitized["prompt"]) > self._MAX_PROMPT_LENGTH:
                return web.json_response(
                    {"error": f"Prompt must be ≤ {self._MAX_PROMPT_LENGTH} characters"}, status=400,
                )
            job = _cron_update(job_id, sanitized)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_delete_job(self, request: "web.Request") -> "web.Response":
        """DELETE /api/jobs/{job_id} — delete a cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            success = _cron_remove(job_id)
            if not success:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_pause_job(self, request: "web.Request") -> "web.Response":
        """POST /api/jobs/{job_id}/pause — pause a cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            job = _cron_pause(job_id)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_resume_job(self, request: "web.Request") -> "web.Response":
        """POST /api/jobs/{job_id}/resume — resume a paused cron job."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            job = _cron_resume(job_id)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_run_job(self, request: "web.Request") -> "web.Response":
        """POST /api/jobs/{job_id}/run — trigger immediate execution."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        cron_err = self._check_jobs_available()
        if cron_err:
            return cron_err
        job_id, id_err = self._check_job_id(request)
        if id_err:
            return id_err
        try:
            job = _cron_trigger(job_id)
            if not job:
                return web.json_response({"error": "Job not found"}, status=404)
            return web.json_response({"job": job})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # ------------------------------------------------------------------
    # Output extraction helper
    # ------------------------------------------------------------------

    @staticmethod
    def _build_response_conversation_history(
        conversation_history: List[Dict[str, Any]],
        user_message: Any,
        result: Dict[str, Any],
        final_response: Any,
    ) -> List[Dict[str, Any]]:
        """Build the stored Responses transcript without duplicating history."""
        prior = list(conversation_history)
        current_user = {"role": "user", "content": user_message}
        agent_messages = result.get("messages") if isinstance(result, dict) else None

        if isinstance(agent_messages, list) and agent_messages:
            turn_start = APIServerAdapter._response_messages_turn_start_index(
                conversation_history,
                user_message,
                result,
            )
            if turn_start:
                return list(agent_messages)

            full_history = prior
            full_history.append(current_user)
            full_history.extend(agent_messages)
            return full_history

        full_history = prior
        full_history.append(current_user)
        full_history.append({"role": "assistant", "content": final_response})
        return full_history

    @staticmethod
    def _response_messages_turn_start_index(
        conversation_history: List[Dict[str, Any]],
        user_message: Any,
        result: Dict[str, Any],
    ) -> int:
        """Detect transcript-shaped result["messages"] and return turn start."""
        agent_messages = result.get("messages") if isinstance(result, dict) else None
        if not isinstance(agent_messages, list) or not agent_messages:
            return 0

        prior = list(conversation_history)
        current_user = {"role": "user", "content": user_message}
        expected_prefix = prior + [current_user]
        if agent_messages[:len(expected_prefix)] == expected_prefix:
            return len(expected_prefix)
        if prior and agent_messages[:len(prior)] == prior:
            return len(prior)
        return 0

    @staticmethod
    def _extract_output_items(result: Dict[str, Any], start_index: int = 0) -> List[Dict[str, Any]]:
        """
        Build the output item array from the agent's messages.

        Walks *result["messages"]* starting at *start_index* and emits:
        - ``function_call`` items for each tool_call on assistant messages
        - ``function_call_output`` items for each tool-role message
        - a final ``message`` item with the assistant's text reply
        """
        items: List[Dict[str, Any]] = []
        messages = result.get("messages", [])
        if start_index > 0:
            messages = messages[start_index:]

        for msg in messages:
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    items.append({
                        "type": "function_call",
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", ""),
                        "call_id": tc.get("id", ""),
                    })
            elif role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": msg.get("content", ""),
                })

        # Final assistant message
        final = result.get("final_response", "")
        if not final:
            final = result.get("error", "(No response generated)")

        items.append({
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": final,
                }
            ],
        })
        return items

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    async def _run_agent(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        ephemeral_system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        stream_delta_callback=None,
        tool_progress_callback=None,
        tool_start_callback=None,
        tool_complete_callback=None,
        agent_ref: Optional[list] = None,
        gateway_session_key: Optional[str] = None,
        product_principal: Optional[Any] = None,
    ) -> tuple:
        """
        Create an agent and run a conversation in a thread executor.

        Returns ``(result_dict, usage_dict)`` where *usage_dict* contains
        ``input_tokens``, ``output_tokens`` and ``total_tokens``.

        If *agent_ref* is a one-element list, the AIAgent instance is stored
        at ``agent_ref[0]`` before ``run_conversation`` begins.  This allows
        callers (e.g. the SSE writer) to call ``agent.interrupt()`` from
        another thread to stop in-progress LLM calls.
        """
        loop = asyncio.get_running_loop()

        def _run():
            from gateway.session_context import (
                clear_session_override,
                set_session_override,
            )

            product_override_names: list[str] = []
            if product_principal is not None:
                # Product identity is derived from the accepted bearer token,
                # never from model arguments or caller-controlled headers.
                # ContextVars propagate into parallel tool workers.
                set_session_override("TROIKA_PRODUCT_MODE", "1")
                set_session_override(
                    "TROIKA_PRODUCT_USER_ID", product_principal.user_id
                )
                set_session_override(
                    "TROIKA_PRODUCT_DEVICE_ID", product_principal.device_id
                )
                set_session_override(
                    "TROIKA_PRODUCT_TOKEN_ID", product_principal.token_id
                )
                set_session_override(
                    "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE",
                    "1" if self._artifact_store is not None else "0",
                )
                product_override_names.extend(
                    [
                        "TROIKA_PRODUCT_MODE",
                        "TROIKA_PRODUCT_USER_ID",
                        "TROIKA_PRODUCT_DEVICE_ID",
                        "TROIKA_PRODUCT_TOKEN_ID",
                        "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE",
                    ]
                )
                if self._product_artifact_db is not None:
                    set_session_override(
                        "TROIKA_PRODUCT_ARTIFACT_DB", str(self._product_artifact_db)
                    )
                    product_override_names.append("TROIKA_PRODUCT_ARTIFACT_DB")
                if self._product_artifact_root is not None:
                    set_session_override(
                        "TROIKA_PRODUCT_ARTIFACT_ROOT",
                        str(self._product_artifact_root),
                    )
                    product_override_names.append("TROIKA_PRODUCT_ARTIFACT_ROOT")
            try:
                agent = self._create_agent(
                    ephemeral_system_prompt=ephemeral_system_prompt,
                    session_id=session_id,
                    stream_delta_callback=stream_delta_callback,
                    tool_progress_callback=tool_progress_callback,
                    tool_start_callback=tool_start_callback,
                    tool_complete_callback=tool_complete_callback,
                    gateway_session_key=gateway_session_key,
                )
                if agent_ref is not None:
                    agent_ref[0] = agent
                effective_task_id = session_id or str(uuid.uuid4())
                result = agent.run_conversation(
                    user_message=user_message,
                    conversation_history=conversation_history,
                    task_id=effective_task_id,
                )
                usage = {
                    "input_tokens": getattr(agent, "session_prompt_tokens", 0) or 0,
                    "output_tokens": getattr(agent, "session_completion_tokens", 0) or 0,
                    "total_tokens": getattr(agent, "session_total_tokens", 0) or 0,
                }
                # Include the effective session ID in the result so callers
                # (e.g. X-Hermes-Session-Id header) can track compression-
                # triggered session rotations. (#16938)
                _eff_sid = getattr(agent, "session_id", session_id)
                if isinstance(_eff_sid, str) and _eff_sid:
                    result["session_id"] = _eff_sid
                return result, usage
            finally:
                for override_name in reversed(product_override_names):
                    clear_session_override(override_name)

        return await loop.run_in_executor(None, _run)

    # ------------------------------------------------------------------
    # /v1/runs — structured event streaming
    # ------------------------------------------------------------------

    _MAX_CONCURRENT_RUNS = 10  # Prevent unbounded resource allocation
    _RUN_STREAM_TTL = 300  # seconds before orphaned runs are swept
    _RUN_STATUS_TTL = 3600  # seconds to retain terminal run status for polling

    def _set_run_status(self, run_id: str, status: str, **fields: Any) -> Dict[str, Any]:
        """Update pollable run status without exposing private agent objects."""
        now = time.time()
        current = self._run_statuses.get(run_id, {})
        current.update({
            "object": "hermes.run",
            "run_id": run_id,
            "status": status,
            "updated_at": now,
        })
        current.setdefault("created_at", fields.pop("created_at", now))
        current.update(fields)
        self._run_statuses[run_id] = current
        return current

    def _make_run_event_callback(self, run_id: str, loop: "asyncio.AbstractEventLoop"):
        """Return a tool_progress_callback that pushes structured events to the run's SSE queue."""
        def _push(event: Dict[str, Any]) -> None:
            self._set_run_status(
                run_id,
                self._run_statuses.get(run_id, {}).get("status", "running"),
                last_event=event.get("event"),
            )
            q = self._run_streams.get(run_id)
            if q is None:
                return
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

        def _callback(event_type: str, tool_name: str = None, preview: str = None, args=None, **kwargs):
            ts = time.time()
            if event_type == "tool.started":
                _push({
                    "event": "tool.started",
                    "run_id": run_id,
                    "timestamp": ts,
                    "tool": tool_name,
                    "preview": preview,
                })
            elif event_type == "tool.completed":
                _push({
                    "event": "tool.completed",
                    "run_id": run_id,
                    "timestamp": ts,
                    "tool": tool_name,
                    "duration": round(kwargs.get("duration", 0), 3),
                    "error": kwargs.get("is_error", False),
                })
            elif event_type == "reasoning.available":
                _push({
                    "event": "reasoning.available",
                    "run_id": run_id,
                    "timestamp": ts,
                    "text": preview or "",
                })
            # _thinking and subagent_progress are intentionally not forwarded

        return _callback

    async def _handle_runs(self, request: "web.Request") -> "web.Response":
        """POST /v1/runs — start an agent run, return run_id immediately."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        # Long-term memory scope header (see chat_completions for details).
        gateway_session_key, key_err = self._parse_session_key_header(request)
        if key_err is not None:
            return key_err

        # Enforce concurrency limit
        if len(self._run_streams) >= self._MAX_CONCURRENT_RUNS:
            return web.json_response(
                _openai_error(f"Too many concurrent runs (max {self._MAX_CONCURRENT_RUNS})", code="rate_limit_exceeded"),
                status=429,
            )

        try:
            body = await request.json()
        except Exception:
            return web.json_response(_openai_error("Invalid JSON"), status=400)

        raw_input = body.get("input")
        if not raw_input:
            return web.json_response(_openai_error("Missing 'input' field"), status=400)

        user_message = raw_input if isinstance(raw_input, str) else (raw_input[-1].get("content", "") if isinstance(raw_input, list) else "")
        if not user_message:
            return web.json_response(_openai_error("No user message found in input"), status=400)

        instructions = body.get("instructions")
        previous_response_id = body.get("previous_response_id")

        # Accept explicit conversation_history from the request body.
        # Precedence: explicit conversation_history > previous_response_id.
        conversation_history: List[Dict[str, str]] = []
        raw_history = body.get("conversation_history")
        if raw_history:
            if not isinstance(raw_history, list):
                return web.json_response(
                    _openai_error("'conversation_history' must be an array of message objects"),
                    status=400,
                )
            for i, entry in enumerate(raw_history):
                if not isinstance(entry, dict) or "role" not in entry or "content" not in entry:
                    return web.json_response(
                        _openai_error(f"conversation_history[{i}] must have 'role' and 'content' fields"),
                        status=400,
                    )
                conversation_history.append({"role": str(entry["role"]), "content": str(entry["content"])})
            if previous_response_id:
                logger.debug("Both conversation_history and previous_response_id provided; using conversation_history")

        stored_session_id = None
        if not conversation_history and previous_response_id:
            stored = self._response_store.get(previous_response_id)
            if stored:
                conversation_history = list(stored.get("conversation_history", []))
                stored_session_id = stored.get("session_id")
                if instructions is None:
                    instructions = stored.get("instructions")

        # When input is a multi-message array, extract all but the last
        # message as conversation history (the last becomes user_message).
        # Only fires when no explicit history was provided.
        if not conversation_history and isinstance(raw_input, list) and len(raw_input) > 1:
            for msg in raw_input[:-1]:
                if isinstance(msg, dict) and msg.get("role") and msg.get("content"):
                    content = msg["content"]
                    if isinstance(content, list):
                        # Flatten multi-part content blocks to text
                        content = " ".join(
                            part.get("text", "") for part in content
                            if isinstance(part, dict) and part.get("type") == "text"
                        )
                    conversation_history.append({"role": msg["role"], "content": str(content)})

        run_id = f"run_{uuid.uuid4().hex}"
        session_id = body.get("session_id") or stored_session_id or run_id
        session_auth_err = self._authorize_product_session(
            request, str(session_id), claim=True
        )
        if session_auth_err:
            return session_auth_err

        quota_err = self._consume_product_request_quota(request)
        if quota_err:
            return quota_err

        usage = request.get("troika_usage")
        if self._product_principal(request) is not None:
            audit_details: Dict[str, Any] = {"endpoint": "runs"}
            if usage is not None:
                audit_details.update(
                    {"limit": usage.limit, "remaining": usage.remaining}
                )
            self._record_product_audit(
                request,
                "request.accepted",
                session_id=str(session_id),
                details=audit_details,
            )

        approval_session_key = gateway_session_key or session_id or run_id
        ephemeral_system_prompt = instructions
        loop = asyncio.get_running_loop()
        q: "asyncio.Queue[Optional[Dict]]" = asyncio.Queue()
        created_at = time.time()
        self._run_streams[run_id] = q
        self._run_streams_created[run_id] = created_at
        self._run_approval_sessions[run_id] = approval_session_key
        principal = self._product_principal(request)
        if principal is not None:
            self._run_owners[run_id] = (principal.user_id, principal.device_id)
        self._record_product_audit(
            request, "run.started", session_id=str(session_id), run_id=run_id
        )

        event_cb = self._make_run_event_callback(run_id, loop)

        # Also wire stream_delta_callback so message.delta events flow through.
        def _text_cb(delta: Optional[str]) -> None:
            if delta is None:
                return
            try:
                loop.call_soon_threadsafe(q.put_nowait, {
                    "event": "message.delta",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "delta": delta,
                })
            except Exception:
                pass

        self._set_run_status(
            run_id,
            "queued",
            created_at=created_at,
            session_id=session_id,
            model=body.get("model", self._model_name),
        )

        async def _run_and_close():
            try:
                self._set_run_status(run_id, "running")

                def _approval_notify(approval_data: Dict[str, Any]) -> None:
                    event = dict(approval_data or {})
                    choices = event.get("choices")
                    if not isinstance(choices, list) or not choices:
                        choices = ["once", "session", "always", "deny"]
                    event.update({
                        "event": "approval.request",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "choices": choices,
                    })
                    self._set_run_status(
                        run_id,
                        "waiting_for_approval",
                        last_event="approval.request",
                    )
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, event)
                    except Exception:
                        pass

                def _run_sync():
                    from gateway.session_context import (
                        clear_session_override,
                        clear_session_vars,
                        set_session_override,
                        set_session_vars,
                    )
                    from tools.approval import (
                        register_gateway_notify,
                        reset_current_session_key,
                        set_current_session_key,
                        unregister_gateway_notify,
                    )

                    effective_task_id = session_id or run_id
                    approval_token = None
                    session_tokens = []
                    product_override_names: list[str] = []
                    try:
                        # Bind approval/session identity for this API run via
                        # contextvars so concurrent runs do not share process
                        # environment state.
                        approval_token = set_current_session_key(approval_session_key)
                        session_tokens = set_session_vars(
                            platform="api_server",
                            session_key=approval_session_key,
                        )
                        if principal is not None:
                            # Bind the device identity before agent creation:
                            # availability checks and all tool workers see the
                            # same server-derived device scope.
                            set_session_override("TROIKA_PRODUCT_MODE", "1")
                            set_session_override(
                                "TROIKA_PRODUCT_USER_ID", principal.user_id
                            )
                            set_session_override(
                                "TROIKA_PRODUCT_DEVICE_ID", principal.device_id
                            )
                            set_session_override(
                                "TROIKA_PRODUCT_TOKEN_ID", principal.token_id
                            )
                            set_session_override(
                                "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE",
                                "1" if self._artifact_store is not None else "0",
                            )
                            product_override_names.extend(
                                [
                                    "TROIKA_PRODUCT_MODE",
                                    "TROIKA_PRODUCT_USER_ID",
                                    "TROIKA_PRODUCT_DEVICE_ID",
                                    "TROIKA_PRODUCT_TOKEN_ID",
                                    "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE",
                                ]
                            )
                            if self._product_artifact_db is not None:
                                set_session_override(
                                    "TROIKA_PRODUCT_ARTIFACT_DB",
                                    str(self._product_artifact_db),
                                )
                                product_override_names.append(
                                    "TROIKA_PRODUCT_ARTIFACT_DB"
                                )
                            if self._product_artifact_root is not None:
                                set_session_override(
                                    "TROIKA_PRODUCT_ARTIFACT_ROOT",
                                    str(self._product_artifact_root),
                                )
                                product_override_names.append(
                                    "TROIKA_PRODUCT_ARTIFACT_ROOT"
                                )
                        agent = self._create_agent(
                            ephemeral_system_prompt=ephemeral_system_prompt,
                            session_id=session_id,
                            stream_delta_callback=_text_cb,
                            tool_progress_callback=event_cb,
                            gateway_session_key=gateway_session_key,
                        )
                        self._active_run_agents[run_id] = agent
                        register_gateway_notify(approval_session_key, _approval_notify)
                        r = agent.run_conversation(
                            user_message=user_message,
                            conversation_history=conversation_history,
                            task_id=effective_task_id,
                        )
                    finally:
                        try:
                            unregister_gateway_notify(approval_session_key)
                        finally:
                            if approval_token is not None:
                                try:
                                    reset_current_session_key(approval_token)
                                except Exception:
                                    pass
                            if session_tokens:
                                try:
                                    clear_session_vars(session_tokens)
                                except Exception:
                                    pass
                            for override_name in reversed(product_override_names):
                                clear_session_override(override_name)
                    u = {
                        "input_tokens": getattr(agent, "session_prompt_tokens", 0) or 0,
                        "output_tokens": getattr(agent, "session_completion_tokens", 0) or 0,
                        "total_tokens": getattr(agent, "session_total_tokens", 0) or 0,
                    }
                    return r, u

                result, usage = await asyncio.get_running_loop().run_in_executor(None, _run_sync)
                # Check for structured failure (non-retryable client errors like
                # 401/400 return failed=True instead of raising, so the except
                # block below never fires — issue #15561).
                if isinstance(result, dict) and result.get("failed"):
                    error_msg = result.get("error") or "agent run failed"
                    q.put_nowait({
                        "event": "run.failed",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "error": error_msg,
                    })
                    self._set_run_status(
                        run_id,
                        "failed",
                        error=error_msg,
                        last_event="run.failed",
                    )
                else:
                    final_response = result.get("final_response", "") if isinstance(result, dict) else ""
                    q.put_nowait({
                        "event": "run.completed",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "output": final_response,
                        "usage": usage,
                    })
                    self._set_run_status(
                        run_id,
                        "completed",
                        output=final_response,
                        usage=usage,
                        last_event="run.completed",
                    )
            except asyncio.CancelledError:
                self._set_run_status(
                    run_id,
                    "cancelled",
                    last_event="run.cancelled",
                )
                try:
                    q.put_nowait({
                        "event": "run.cancelled",
                        "run_id": run_id,
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
                raise
            except Exception as exc:
                logger.exception("[api_server] run %s failed", run_id)
                self._set_run_status(
                    run_id,
                    "failed",
                    error=str(exc),
                    last_event="run.failed",
                )
                try:
                    q.put_nowait({
                        "event": "run.failed",
                        "run_id": run_id,
                        "timestamp": time.time(),
                        "error": str(exc),
                    })
                except Exception:
                    pass
            finally:
                # If the asyncio wrapper is cancelled (for example via
                # /stop), the executor thread can still be blocked waiting
                # on an approval Event.  Unregistering here releases those
                # waits immediately; the in-thread unregister is harmlessly
                # idempotent on normal completion.
                try:
                    from tools.approval import unregister_gateway_notify

                    unregister_gateway_notify(approval_session_key)
                except Exception:
                    pass
                # Sentinel: signal SSE stream to close
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
                self._active_run_agents.pop(run_id, None)
                self._active_run_tasks.pop(run_id, None)
                self._run_approval_sessions.pop(run_id, None)

        task = asyncio.create_task(_run_and_close())
        self._active_run_tasks[run_id] = task
        try:
            self._background_tasks.add(task)
        except TypeError:
            pass
        if hasattr(task, "add_done_callback"):
            task.add_done_callback(self._background_tasks.discard)

        response_headers = (
            {"X-Hermes-Session-Key": gateway_session_key} if gateway_session_key else {}
        )
        response_headers.update(self._product_quota_headers(request))
        return web.json_response(
            {"run_id": run_id, "status": "started"},
            status=202,
            headers=response_headers,
        )

    async def _handle_get_run(self, request: "web.Request") -> "web.Response":
        """GET /v1/runs/{run_id} — return pollable run status for external UIs."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        run_id = request.match_info["run_id"]
        run_auth_err = self._authorize_product_run(request, run_id)
        if run_auth_err:
            return run_auth_err
        status = self._run_statuses.get(run_id)
        if status is None:
            return web.json_response(
                _openai_error(f"Run not found: {run_id}", code="run_not_found"),
                status=404,
            )
        return web.json_response(status)

    async def _handle_run_events(self, request: "web.Request") -> "web.StreamResponse":
        """GET /v1/runs/{run_id}/events — SSE stream of structured agent lifecycle events."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        run_id = request.match_info["run_id"]
        run_auth_err = self._authorize_product_run(request, run_id)
        if run_auth_err:
            return run_auth_err

        # Allow subscribing slightly before the run is registered (race condition window)
        for _ in range(20):
            if run_id in self._run_streams:
                break
            await asyncio.sleep(0.05)
        else:
            return web.json_response(_openai_error(f"Run not found: {run_id}", code="run_not_found"), status=404)

        q = self._run_streams[run_id]

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    await response.write(b": keepalive\n\n")
                    continue
                if event is None:
                    # Run finished — send final SSE comment and close
                    await response.write(b": stream closed\n\n")
                    break
                payload = f"data: {json.dumps(event)}\n\n"
                await response.write(payload.encode())
        except Exception as exc:
            logger.debug("[api_server] SSE stream error for run %s: %s", run_id, exc)
        finally:
            self._run_streams.pop(run_id, None)
            self._run_streams_created.pop(run_id, None)

        return response


    async def _handle_run_approval(self, request: "web.Request") -> "web.Response":
        """POST /v1/runs/{run_id}/approval — resolve a pending run approval."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        run_id = request.match_info["run_id"]
        run_auth_err = self._authorize_product_run(request, run_id)
        if run_auth_err:
            return run_auth_err
        status = self._run_statuses.get(run_id)
        if status is None:
            return web.json_response(
                _openai_error(f"Run not found: {run_id}", code="run_not_found"),
                status=404,
            )

        try:
            body = await request.json()
        except Exception:
            return web.json_response(_openai_error("Invalid JSON"), status=400)

        approval_session_key = self._run_approval_sessions.get(run_id)
        if not approval_session_key:
            return web.json_response(
                _openai_error(
                    f"Run has no active approval session: {run_id}",
                    code="approval_not_active",
                ),
                status=409,
            )

        raw_choice = str(body.get("choice", "")).strip().lower()
        aliases = {"approve": "once", "approved": "once", "allow": "once"}
        choice = aliases.get(raw_choice, raw_choice)
        try:
            from tools.approval import (
                get_gateway_approval_choices,
                is_product_gateway_approval,
            )

            allowed = set(get_gateway_approval_choices(approval_session_key))
            product_action = is_product_gateway_approval(approval_session_key)
        except Exception:
            logger.exception("[api_server] approval choice lookup failed for run %s", run_id)
            return web.json_response(_openai_error("Approval state unavailable"), status=503)
        if allowed and choice not in allowed:
            expected = ", ".join(sorted(allowed))
            return web.json_response(
                _openai_error(
                    f"Invalid approval choice; expected one of: {expected}",
                    code="invalid_approval_choice",
                ),
                status=400,
            )

        resolve_all = (
            _coerce_request_bool(body.get("all"), default=False)
            or _coerce_request_bool(body.get("resolve_all"), default=False)
        )
        if product_action and resolve_all:
            return web.json_response(
                _openai_error(
                    "Product actions require separate one-time confirmations",
                    code="invalid_approval_scope",
                ),
                status=400,
            )
        try:
            from tools.approval import resolve_gateway_approval

            resolved = resolve_gateway_approval(
                approval_session_key,
                choice,
                resolve_all=resolve_all,
            )
        except Exception as exc:
            logger.exception("[api_server] approval resolution failed for run %s", run_id)
            return web.json_response(_openai_error(str(exc)), status=500)

        if resolved <= 0:
            return web.json_response(
                _openai_error(
                    f"Run has no pending approval: {run_id}",
                    code="approval_not_pending",
                ),
                status=409,
            )

        self._set_run_status(run_id, "running", last_event="approval.responded")
        self._record_product_audit(
            request,
            "run.approval_responded",
            run_id=run_id,
            details={"choice": choice, "resolved": resolved},
        )
        q = self._run_streams.get(run_id)
        if q is not None:
            try:
                q.put_nowait({
                    "event": "approval.responded",
                    "run_id": run_id,
                    "timestamp": time.time(),
                    "choice": choice,
                    "resolved": resolved,
                })
            except Exception:
                pass

        return web.json_response({
            "object": "hermes.run.approval_response",
            "run_id": run_id,
            "choice": choice,
            "resolved": resolved,
        })

    async def _handle_stop_run(self, request: "web.Request") -> "web.Response":
        """POST /v1/runs/{run_id}/stop — interrupt a running agent."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err

        run_id = request.match_info["run_id"]
        run_auth_err = self._authorize_product_run(request, run_id)
        if run_auth_err:
            return run_auth_err
        agent = self._active_run_agents.get(run_id)
        task = self._active_run_tasks.get(run_id)

        if agent is None and task is None:
            return web.json_response(_openai_error(f"Run not found: {run_id}", code="run_not_found"), status=404)

        self._set_run_status(run_id, "stopping", last_event="run.stopping")
        self._record_product_audit(request, "run.stop_requested", run_id=run_id)

        if agent is not None:
            try:
                agent.interrupt("Stop requested via API")
            except Exception:
                pass

        if task is not None and not task.done():
            task.cancel()
            # Bounded wait: run_conversation() executes in the default
            # executor thread which task.cancel() cannot preempt — we rely on
            # agent.interrupt() above to break the loop. Cap the wait so a
            # slow/unresponsive interrupt can't hang this handler.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "[api_server] stop for run %s timed out after 5s; "
                    "agent may still be finishing the current step",
                    run_id,
                )
            except (asyncio.CancelledError, Exception):
                pass

        return web.json_response({"run_id": run_id, "status": "stopping"})

    async def _sweep_orphaned_runs(self) -> None:
        """Periodically clean up run streams that were never consumed."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            stale = [
                run_id
                for run_id, created_at in list(self._run_streams_created.items())
                if now - created_at > self._RUN_STREAM_TTL
            ]
            for run_id in stale:
                logger.debug("[api_server] sweeping orphaned run %s", run_id)
                try:
                    from tools.approval import unregister_gateway_notify

                    approval_session_key = self._run_approval_sessions.get(run_id)
                    if approval_session_key:
                        unregister_gateway_notify(approval_session_key)
                except Exception:
                    pass
                self._run_streams.pop(run_id, None)
                self._run_streams_created.pop(run_id, None)
                self._active_run_agents.pop(run_id, None)
                self._active_run_tasks.pop(run_id, None)
                self._run_approval_sessions.pop(run_id, None)

            stale_statuses = [
                run_id
                for run_id, status in list(self._run_statuses.items())
                if status.get("status") in {"completed", "failed", "cancelled"}
                and now - float(status.get("updated_at", 0) or 0) > self._RUN_STATUS_TTL
            ]
            for run_id in stale_statuses:
                self._run_statuses.pop(run_id, None)
                self._run_owners.pop(run_id, None)

    # ------------------------------------------------------------------
    # BasePlatformAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Start the aiohttp web server."""
        if not AIOHTTP_AVAILABLE:
            logger.warning("[%s] aiohttp not installed", self.name)
            return False

        if self._product_auth_enabled and self._access_registry is None:
            logger.error(
                "[%s] Refusing to start: Troika product auth could not initialize: %s",
                self.name,
                self._product_auth_error or "unknown error",
            )
            return False

        try:
            mws = [mw for mw in (cors_middleware, body_limit_middleware, security_headers_middleware) if mw is not None]
            self._app = web.Application(middlewares=mws, client_max_size=MAX_REQUEST_BYTES)
            self._app["api_server_adapter"] = self
            self._app.router.add_get("/health", self._handle_health)
            self._app.router.add_get("/health/detailed", self._handle_health_detailed)
            self._app.router.add_get("/v1/health", self._handle_health)
            self._app.router.add_get("/v1/models", self._handle_models)
            self._app.router.add_get("/v1/capabilities", self._handle_capabilities)
            self._app.router.add_get(
                "/v1/notification-preferences", self._handle_notification_preferences,
            )
            self._app.router.add_put(
                "/v1/notification-preferences", self._handle_notification_preferences,
            )
            self._app.router.add_post("/v1/chat/completions", self._handle_chat_completions)
            self._app.router.add_get("/v1/phone/commands", self._handle_phone_ws)
            self._app.router.add_get("/v1/phone/status", self._handle_phone_status)
            self._app.router.add_get("/v1/artifacts", self._handle_list_artifacts)
            self._app.router.add_get(
                "/v1/artifacts/{artifact_id}/download",
                self._handle_download_artifact,
            )
            self._app.router.add_delete(
                "/v1/artifacts/{artifact_id}", self._handle_delete_artifact
            )
            if self._access_registry is None:
                self._app.router.add_post("/v1/phone/notify", self._handle_phone_notify)
            self._app.router.add_get("/v1/sessions", self._handle_list_sessions)
            self._app.router.add_get("/v1/sessions/{session_id}/messages", self._handle_get_session_messages)
            self._app.router.add_post("/v1/audio/speech", self._handle_audio_speech)
            self._app.router.add_post("/v1/audio/transcriptions", self._handle_audio_transcriptions)
            self._app.router.add_post("/v1/responses", self._handle_responses)
            self._app.router.add_get("/v1/responses/{response_id}", self._handle_get_response)
            self._app.router.add_delete("/v1/responses/{response_id}", self._handle_delete_response)
            # Jobs need a user-owned scheduler and delivery channel before they
            # can be exposed to product users.  The legacy global scheduler is
            # deliberately unavailable in product mode.
            if self._access_registry is None:
                self._app.router.add_get("/api/jobs", self._handle_list_jobs)
                self._app.router.add_post("/api/jobs", self._handle_create_job)
                self._app.router.add_get("/api/jobs/{job_id}", self._handle_get_job)
                self._app.router.add_patch("/api/jobs/{job_id}", self._handle_update_job)
                self._app.router.add_delete("/api/jobs/{job_id}", self._handle_delete_job)
                self._app.router.add_post("/api/jobs/{job_id}/pause", self._handle_pause_job)
                self._app.router.add_post("/api/jobs/{job_id}/resume", self._handle_resume_job)
                self._app.router.add_post("/api/jobs/{job_id}/run", self._handle_run_job)
            # Structured event streaming
            self._app.router.add_post("/v1/runs", self._handle_runs)
            self._app.router.add_get("/v1/runs/{run_id}", self._handle_get_run)
            self._app.router.add_get("/v1/runs/{run_id}/events", self._handle_run_events)
            self._app.router.add_post("/v1/runs/{run_id}/approval", self._handle_run_approval)
            self._app.router.add_post("/v1/runs/{run_id}/stop", self._handle_stop_run)
            # Start background sweep to clean up orphaned (unconsumed) run streams
            sweep_task = asyncio.create_task(self._sweep_orphaned_runs())
            try:
                self._background_tasks.add(sweep_task)
            except TypeError:
                pass
            if hasattr(sweep_task, "add_done_callback"):
                sweep_task.add_done_callback(self._background_tasks.discard)

            # Орфаны от прошлой жизни gateway: job_runner running-задачи без worker'а.
            try:
                from tools.job_runner import cleanup_orphan_jobs, ensure_watchdog_started
                n_orph = cleanup_orphan_jobs()
                if n_orph:
                    logger.info("[%s] cleaned up %d orphan jobs", self.name, n_orph)
                ensure_watchdog_started()
            except Exception as _e:
                logger.warning("[%s] job_runner init failed: %s", self.name, _e)

            # Refuse to start network-accessible without authentication
            if (
                is_network_accessible(self._host)
                and not self._api_key
                and self._access_registry is None
            ):
                logger.error(
                    "[%s] Refusing to start: binding to %s requires API_SERVER_KEY. "
                    "Set API_SERVER_KEY or use the default 127.0.0.1.",
                    self.name, self._host,
                )
                return False

            # Refuse to start network-accessible with a placeholder key.
            # Ported from openclaw/openclaw#64586.
            if (
                is_network_accessible(self._host)
                and self._api_key
                and self._access_registry is None
            ):
                try:
                    from hermes_cli.auth import has_usable_secret
                    if not has_usable_secret(self._api_key, min_length=8):
                        logger.error(
                            "[%s] Refusing to start: API_SERVER_KEY is set to a "
                            "placeholder value. Generate a real secret "
                            "(e.g. `openssl rand -hex 32`) and set API_SERVER_KEY "
                            "before exposing the API server on %s.",
                            self.name, self._host,
                        )
                        return False
                except ImportError:
                    pass

            # Port conflict detection — fail fast if port is already in use
            try:
                with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
                    _s.settimeout(1)
                    _s.connect(('127.0.0.1', self._port))
                logger.error('[%s] Port %d already in use. Set a different port in config.yaml: platforms.api_server.port', self.name, self._port)
                return False
            except (ConnectionRefusedError, OSError):
                pass  # port is free

            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()

            self._mark_connected()
            if not self._api_key:
                logger.warning(
                    "[%s] ⚠️  No API key configured (API_SERVER_KEY / platforms.api_server.key). "
                    "All requests will be accepted without authentication. "
                    "Set an API key for production deployments to prevent "
                    "unauthorized access to sessions, responses, and cron jobs.",
                    self.name,
                )
            logger.info(
                "[%s] API server listening on http://%s:%d (model: %s)",
                self.name, self._host, self._port, self._model_name,
            )
            return True

        except Exception as e:
            logger.error("[%s] Failed to start API server: %s", self.name, e)
            return False

    async def disconnect(self) -> None:
        """Stop the aiohttp web server."""
        self._mark_disconnected()
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None
        logger.info("[%s] API server stopped", self.name)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """
        Not used — HTTP request/response cycle handles delivery directly.
        """
        return SendResult(success=False, error="API server uses HTTP request/response, not send()")

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return basic info about the API server."""
        return {
            "name": "API Server",
            "type": "api",
            "host": self._host,
            "port": self._port,
        }
