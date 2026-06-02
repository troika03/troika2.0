"""
notes — RAG-поиск по Obsidian-vault'у через локальные embeddings.

Vault: тот же что и у obsidian_note (``d:\\troikahermes-vault``).
Hermes делает разовое ``operation=index`` (по необходимости — инкрементально),
после чего ``operation=search`` отдаёт top-k чанков, релевантных запросу.

Архитектура (минимум зависимостей):

- Embeddings: sentence-transformers + модель BGE-M3 (default) или
  multilingual-e5-base, ~600MB. Lazy-import — tool регистрируется без
  пакета, при первом вызове просит ``pip install sentence-transformers``.
- Vector store: ``sqlite-vec`` (расширение SQLite) если установлен; иначе
  fallback — хранить embeddings как np.float32 blob и считать cosine
  через numpy. Для vault'а в несколько сотен заметок это нормально.
- Чанкинг: по абзацам, склеиваем до ~800 символов, overlap=120.

State: ``~/.troika/notes_index.db`` — ``files(path, mtime, size, hash)``,
``chunks(id, path, ord, text, embedding BLOB)``.

operations:
  - ``index`` — пройти по vault, переиндексировать изменённые/новые файлы.
    args: ``folder`` (optional, default = вся vault), ``rebuild`` (bool,
    дропнуть и пересобрать всё).
  - ``search`` — top-k по запросу. args: ``query`` (req), ``k`` (default 5),
    ``folder`` (optional filter).
  - ``stats`` — сколько файлов/чанков проиндексировано.

Триггеры (голос):
  - «найди в obsidian / в моих заметках / что я писал про X» → search
  - «переиндексируй заметки» / «обнови vault» → index
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------

_VAULT_CANDIDATES = [
    Path(r"d:\troikahermes-vault"),
    Path(r"D:\troikahermes-vault"),
    Path.home() / ".claude" / "projects" / "d--troikahermes" / "memory",
]

_TROIKA_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_INDEX_DB = _TROIKA_HOME / "notes_index.db"

_DEFAULT_MODEL = os.environ.get("TROIKA_NOTES_MODEL", "BAAI/bge-m3")
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120

# Lazy-loaded
_MODEL = None
_MODEL_LOCK = threading.Lock()
_VEC_DIM: Optional[int] = None


def _vault_root() -> Optional[Path]:
    env = os.environ.get("TROIKA_VAULT_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for cand in _VAULT_CANDIDATES:
        if cand.exists():
            return cand
    return None


# ---------------------------------------------------------------------------
# Embedding model (lazy)
# ---------------------------------------------------------------------------


def _try_load_model() -> Tuple[Optional[Any], Optional[str]]:
    """Loads sentence-transformers model lazily. Returns (model, error_hint)."""
    global _MODEL, _VEC_DIM
    if _MODEL is not None:
        return _MODEL, None
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL, None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            return None, (
                "sentence-transformers не установлен. "
                "Поставь: pip install sentence-transformers"
            )
        try:
            logger.info("Loading embedding model %s...", _DEFAULT_MODEL)
            _MODEL = SentenceTransformer(_DEFAULT_MODEL)
            # Прогон одного предложения чтобы узнать размерность
            test = _MODEL.encode(["test"], convert_to_numpy=True)
            _VEC_DIM = int(test.shape[1])
            logger.info("Embedding model loaded: dim=%s", _VEC_DIM)
            return _MODEL, None
        except Exception as e:
            return None, f"Не удалось загрузить модель {_DEFAULT_MODEL}: {e}"


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    _TROIKA_HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_INDEX_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            hash TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            ord INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        """
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Чанкинг
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _chunk(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    """Простой чанкер: режем по абзацам, склеиваем до ~chunk_size, overlap по символам."""
    text = _strip_frontmatter(text).strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + len(p) + 2 <= chunk_size:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf)
            # overlap: хвост предыдущего чанка
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = (tail + "\n\n" + p).strip() if tail else p
    if buf:
        chunks.append(buf)
    # Если параграф огромный — порежем жёстко
    out: List[str] = []
    for c in chunks:
        if len(c) <= chunk_size * 2:
            out.append(c)
        else:
            for i in range(0, len(c), chunk_size - overlap):
                out.append(c[i : i + chunk_size])
    return out


# ---------------------------------------------------------------------------
# Embeddings → blob
# ---------------------------------------------------------------------------


def _encode_texts(model: Any, texts: List[str]):
    import numpy as np  # noqa: F401  (для type-clarity, sentence-transformers тащит numpy)

    embs = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embs.astype("float32")


def _embedding_to_blob(vec) -> bytes:
    return vec.tobytes()


def _blob_to_embedding(blob: bytes):
    import numpy as np

    return np.frombuffer(blob, dtype="float32")


def _cosine_search(query_vec, all_vecs, k: int):
    """Cosine top-k. all_vecs уже нормализованы (см. normalize_embeddings=True)."""
    import numpy as np

    # query_vec L2-нормализован моделью, так что dot == cosine
    scores = all_vecs @ query_vec
    idx = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in idx]


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _file_hash(p: Path) -> str:
    try:
        data = p.read_bytes()
        return hashlib.sha1(data).hexdigest()
    except Exception:
        return ""


def _op_index(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _vault_root()
    if root is None:
        return {"ok": False, "error": "vault_not_found"}

    model, err = _try_load_model()
    if err:
        return {"ok": False, "error": err, "hint": "pip install sentence-transformers"}

    folder = (args.get("folder") or "").strip("/\\")
    base = (root / folder) if folder else root
    if not base.exists():
        return {"ok": False, "error": f"folder_not_found: {folder}"}

    rebuild = bool(args.get("rebuild", False))

    conn = _connect()
    try:
        if rebuild:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM files")
            conn.commit()

        # Найти все .md
        files = list(base.rglob("*.md"))
        # Пропускаем системные/служебные
        files = [f for f in files if not any(part.startswith(".") for part in f.parts)]

        cur = conn.cursor()
        existing = {
            row[0]: (row[1], row[2], row[3])
            for row in cur.execute("SELECT path, mtime, size, hash FROM files")
        }

        to_index: List[Tuple[Path, str]] = []
        skipped = 0
        for f in files:
            try:
                rel = str(f.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            stat = f.stat()
            mtime, size = stat.st_mtime, stat.st_size
            old = existing.get(rel)
            if old and abs(old[0] - mtime) < 1.0 and old[1] == size:
                skipped += 1
                continue
            to_index.append((f, rel))

        # Удалить из индекса те файлы которые исчезли с диска
        on_disk = {str(f.relative_to(root)).replace("\\", "/") for f in files}
        gone = [p for p in existing.keys() if p not in on_disk]
        for p in gone:
            cur.execute("DELETE FROM chunks WHERE path = ?", (p,))
            cur.execute("DELETE FROM files WHERE path = ?", (p,))

        new_files = 0
        new_chunks = 0
        for f, rel in to_index:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("read fail %s: %s", rel, e)
                continue
            chunks = _chunk(text)
            if not chunks:
                # Файл пустой — всё равно отметим как индексированный, чтобы не возвращаться
                pass

            # Удалить старые чанки
            cur.execute("DELETE FROM chunks WHERE path = ?", (rel,))

            if chunks:
                embs = _encode_texts(model, chunks)
                rows = [
                    (rel, i, c, _embedding_to_blob(embs[i]))
                    for i, c in enumerate(chunks)
                ]
                cur.executemany(
                    "INSERT INTO chunks(path, ord, text, embedding) VALUES (?,?,?,?)",
                    rows,
                )
                new_chunks += len(chunks)

            stat = f.stat()
            cur.execute(
                "INSERT OR REPLACE INTO files(path, mtime, size, hash, indexed_at) "
                "VALUES (?,?,?,?,?)",
                (
                    rel,
                    stat.st_mtime,
                    stat.st_size,
                    _file_hash(f),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            new_files += 1

        conn.commit()
        return {
            "ok": True,
            "vault": str(root),
            "total_files_on_disk": len(files),
            "indexed_now": new_files,
            "new_chunks": new_chunks,
            "skipped_unchanged": skipped,
            "removed_from_index": len(gone),
            "model": _DEFAULT_MODEL,
            "vec_dim": _VEC_DIM,
        }
    finally:
        conn.close()


def _op_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return {"ok": False, "error": "missing 'query'"}
    k = int(args.get("k") or 5)
    k = max(1, min(k, 20))
    folder = (args.get("folder") or "").strip("/\\")

    model, err = _try_load_model()
    if err:
        return {"ok": False, "error": err, "hint": "pip install sentence-transformers"}

    if not _INDEX_DB.exists():
        return {
            "ok": False,
            "error": "index_not_built",
            "hint": "Сначала вызови notes(operation='index') чтобы построить индекс.",
        }

    conn = _connect()
    try:
        cur = conn.cursor()
        if folder:
            rows = cur.execute(
                "SELECT id, path, ord, text, embedding FROM chunks WHERE path LIKE ?",
                (folder.rstrip("/") + "/%",),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT id, path, ord, text, embedding FROM chunks"
            ).fetchall()

        if not rows:
            return {"ok": True, "query": query, "count": 0, "hits": [],
                    "hint": "Индекс пуст. Запусти notes(operation='index')."}

        import numpy as np

        all_vecs = np.stack([_blob_to_embedding(r[4]) for r in rows]).astype("float32")
        q_vec = _encode_texts(model, [query])[0]
        top = _cosine_search(q_vec, all_vecs, k)

        hits = []
        for idx, score in top:
            r = rows[idx]
            text = r[3]
            snippet = text[:400].replace("\n", " ")
            hits.append(
                {
                    "path": r[1],
                    "chunk_ord": int(r[2]),
                    "score": round(score, 4),
                    "snippet": snippet,
                }
            )
        return {"ok": True, "query": query, "count": len(hits), "hits": hits,
                "model": _DEFAULT_MODEL}
    finally:
        conn.close()


def _op_stats(_: Dict[str, Any]) -> Dict[str, Any]:
    if not _INDEX_DB.exists():
        return {"ok": True, "indexed": False, "db": str(_INDEX_DB)}
    conn = _connect()
    try:
        files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        size_bytes = _INDEX_DB.stat().st_size if _INDEX_DB.exists() else 0
        last = conn.execute(
            "SELECT path, indexed_at FROM files ORDER BY indexed_at DESC LIMIT 1"
        ).fetchone()
        return {
            "ok": True,
            "indexed": True,
            "files": int(files_n),
            "chunks": int(chunks_n),
            "db_size_mb": round(size_bytes / 1024 / 1024, 2),
            "model": _DEFAULT_MODEL,
            "vec_dim": _VEC_DIM,
            "last_indexed_path": last[0] if last else None,
            "last_indexed_at": last[1] if last else None,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Handler + schema
# ---------------------------------------------------------------------------


async def _handle(args: Dict[str, Any], **_kw) -> str:
    op = (args.get("operation") or args.get("op") or "").strip().lower()
    if not op:
        return json.dumps({"ok": False, "error": "missing 'operation'"}, ensure_ascii=False)
    try:
        if op == "index":
            res = _op_index(args)
        elif op == "search":
            res = _op_search(args)
        elif op == "stats":
            res = _op_stats(args)
        else:
            res = {"ok": False, "error": f"unknown_operation: {op}",
                   "allowed": ["index", "search", "stats"]}
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        logger.exception("notes tool failure")
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


NOTES_SCHEMA = {
    "name": "notes",
    "description": (
        "RAG по Obsidian-vault'у (d:\\troikahermes-vault). operation=search "
        "ищет top-k чанков по семантическому смыслу (BGE-M3, multilingual). "
        "Использовать когда Миша говорит «найди в obsidian», «что я писал про X», "
        "«поищи в заметках». operation=index переиндексирует изменённые "
        "файлы (быстро — пропускает неизменённые). operation=stats — статус "
        "индекса. Если индекс пуст — сначала зови index, потом search."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["index", "search", "stats"],
                "description": "search — найти по смыслу; index — обновить индекс; stats — статистика.",
            },
            "query": {
                "type": "string",
                "description": "Поисковый запрос (для operation=search). На русском или английском.",
            },
            "k": {
                "type": "integer",
                "description": "Сколько top-результатов вернуть (1..20, default 5).",
            },
            "folder": {
                "type": "string",
                "description": "Ограничить scope конкретной папкой vault'а (например 'project').",
            },
            "rebuild": {
                "type": "boolean",
                "description": "Для operation=index: дропнуть и пересобрать индекс с нуля.",
            },
        },
        "required": ["operation"],
    },
}


registry.register(
    name="notes",
    toolset="notes",
    schema=NOTES_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="📚",
)
