"""
memory_semantic — семантический слой над Obsidian-vault'ом Тройки.

Назначение: дополнить лексический memory_search «поиском по смыслу». Запрос
«как починить зависший gemini» должен находить заметку про taskkill, даже если
дословного пересечения слов нет.

Дизайн (важно — это усиление, а НЕ замена fuzzy):
  • локальные эмбеддинги через sentence-transformers (RU+EN multilingual);
  • модель грузится ЛЕНИВО при первом запросе (~1-2с), потом висит в памяти;
  • эмбеддинги документов кэшируются на диск (<vault>/.semantic_cache.npz),
    инвалидация по mtime — пересчитываем только изменившиеся файлы;
  • если sentence-transformers нет / модель не грузится — все функции тихо
    отдают «семантика недоступна», и memory_search работает как раньше.

Никаких сетевых вызовов в рантайме после первой загрузки модели: всё локально,
не жжёт OAuth-квоту и работает офлайн.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_VAULT = Path("C:/Users/kiqu/.claude/projects/d--troikahermes/memory")
_VAULT = Path(os.environ.get("HERMES_MEMORY_VAULT") or _DEFAULT_VAULT)

# Multilingual MiniLM: ~470MB, ровно работает на русском И английском. Переопределяемо.
_MODEL_NAME = os.environ.get(
    "HERMES_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)
_CACHE_FILE = _VAULT / ".semantic_cache.npz"

# Ленивые синглтоны — грузим модель один раз на процесс.
_model = None              # SentenceTransformer | False (False = недоступна)
_np = None                 # numpy module | None


def _lazy_numpy():
    global _np
    if _np is None:
        try:
            import numpy as np
            _np = np
        except Exception as e:  # pragma: no cover
            logger.warning("numpy unavailable, semantic search off: %s", e)
            _np = False
    return _np if _np is not False else None


# Скачивать модель в рантайме поиска НЕЛЬЗЯ: на нестабильной сети (DNS отдаёт
# IPv6 без маршрута) обращение к HF hub виснет и повесило бы первый memory_search.
# Поэтому грузим СТРОГО из локального кэша (local_files_only) — без единого
# сетевого запроса. Если модели нет локально → семантика просто off (fallback на
# fuzzy). Скачивание — отдельной явной операцией prefetch_model() на стабильной сети.
def _model_in_cache() -> bool:
    """Есть ли модель в локальном HF-кэше — дешёвая проверка ФС ДО импорта torch.

    Импорт sentence_transformers тянет весь torch-стек (~30с холодного старта).
    Если модели и так нет локально, нет смысла платить за импорт на каждом
    первом memory_search — сразу говорим «нет» по файловой системе.
    """
    from pathlib import Path as _P
    safe = _MODEL_NAME.replace("/", "--")
    candidates = [
        _P.home() / ".cache" / "huggingface" / "hub" / f"models--sentence-transformers--{safe}",
        _P.home() / ".cache" / "huggingface" / "hub" / f"models--{safe}",
        _P.home() / ".cache" / "torch" / "sentence_transformers" / safe,
    ]
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        candidates.append(_P(hf_home) / "hub" / f"models--sentence-transformers--{safe}")
    for c in candidates:
        # модель «есть», если в папке лежит снапшот с весами (не пустой каталог)
        if c.exists() and any(c.rglob("*.safetensors")) or (c.exists() and any(c.rglob("pytorch_model.bin"))):
            return True
    return False


def _lazy_model():
    """Грузит SentenceTransformer из ЛОКАЛЬНОГО кэша (без сети). None если нет."""
    global _model
    if _model is None and not _model_in_cache():
        # модели нет локально → не импортируем torch вообще, сразу off
        _model = False
        return None
    if _model is None:
        # HF_HUB_OFFLINE=1 жёстко отрубает ЛЮБЫЕ сетевые обращения huggingface на
        # время загрузки — даже скрытые проверки ревизий, которые иначе виснут на
        # битом IPv6. Возвращаем прежнее значение env после.
        prev = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("loading embedding model %s from local cache…", _MODEL_NAME)
            _model = SentenceTransformer(_MODEL_NAME, local_files_only=True)
            logger.info("embedding model ready")
        except Exception as e:
            logger.info("embedding model not in local cache — semantic search off "
                        "(run prefetch_model() on stable network): %s", e)
            _model = False
        finally:
            if prev is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prev
    return _model if _model is not False else None


def prefetch_model() -> bool:
    """Явно скачать embedding-модель (РАЗРЕШЕН сетевой доступ). Зови на стабильной
    сети — НЕ в рантайме поиска. Возвращает True если модель готова локально.

    На сети с битым IPv6-маршрутом форсим IPv4, иначе HF hub виснет.
    """
    global _model
    import socket
    _orig = socket.getaddrinfo

    def _ipv4_only(host, *a, **k):
        res = _orig(host, *a, **k)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        return v4 or res
    socket.getaddrinfo = _ipv4_only
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("prefetching embedding model %s (network allowed)…", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)  # сеть разрешена
        logger.info("embedding model prefetched")
        return True
    except Exception as e:
        logger.warning("prefetch_model failed: %s", e)
        _model = None  # сбрасываем, чтобы _lazy_model попробовал локально позже
        return False
    finally:
        socket.getaddrinfo = _orig


def is_available() -> bool:
    """Можно ли вообще делать семантику (есть numpy + грузится модель)."""
    return _lazy_numpy() is not None and _lazy_model() is not None


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip()
    return text


def _doc_text_for_embed(text: str) -> str:
    """Текст файла → компактная строка для эмбеддинга (description + начало тела).

    Эмбеддим не весь файл (шумно и медленно), а смысловое ядро: description из
    frontmatter + первые ~1500 символов тела. Этого хватает для recall фактов.
    """
    desc = ""
    m = re.search(r'^description:\s*"?(.+?)"?\s*$', text, re.IGNORECASE | re.MULTILINE)
    if m:
        desc = m.group(1).strip()
    body = _strip_frontmatter(text)
    body = re.sub(r"\s+", " ", body).strip()
    core = (desc + ". " + body) if desc else body
    return core[:1500]


def _iter_docs() -> List[Tuple[str, float, str]]:
    """Список (rel_path, mtime, embed_text) по всем .md vault'а (кроме MEMORY.md)."""
    out: List[Tuple[str, float, str]] = []
    if not _VAULT.exists():
        return out
    for md in _VAULT.rglob("*.md"):
        if md.name == "MEMORY.md":
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
            mtime = md.stat().st_mtime
        except Exception:
            continue
        rel = md.relative_to(_VAULT).as_posix()
        out.append((rel, mtime, _doc_text_for_embed(text)))
    return out


def _load_cache():
    """Читает кэш эмбеддингов. Возвращает (paths, mtimes, vectors) или None."""
    np = _lazy_numpy()
    if np is None or not _CACHE_FILE.exists():
        return None
    try:
        data = np.load(_CACHE_FILE, allow_pickle=True)
        return (list(data["paths"]), list(data["mtimes"]), data["vectors"])
    except Exception as e:
        logger.debug("semantic cache unreadable (%s) — rebuilding", e)
        return None


def _save_cache(paths: List[str], mtimes: List[float], vectors) -> None:
    np = _lazy_numpy()
    if np is None:
        return
    try:
        np.savez(_CACHE_FILE, paths=np.array(paths, dtype=object),
                 mtimes=np.array(mtimes, dtype="float64"), vectors=vectors)
    except Exception as e:
        logger.debug("semantic cache save failed: %s", e)


def _build_or_update_index() -> Optional[Dict[str, object]]:
    """Возвращает {paths, vectors(np 2D, L2-normalized)} или None если семантика недоступна.

    Инкрементально: эмбеддит только новые/изменённые файлы (по mtime), остальное
    берёт из кэша. Удалённые файлы выпадают из индекса.
    """
    np = _lazy_numpy()
    model = _lazy_model()
    if np is None or model is None:
        return None

    docs = _iter_docs()
    if not docs:
        return None

    cache = _load_cache()
    cached: Dict[str, Tuple[float, object]] = {}
    if cache is not None:
        c_paths, c_mtimes, c_vecs = cache
        for i, p in enumerate(c_paths):
            try:
                cached[p] = (float(c_mtimes[i]), c_vecs[i])
            except Exception:
                continue

    paths: List[str] = []
    mtimes: List[float] = []
    vecs: List[object] = []
    to_embed: List[Tuple[int, str]] = []  # (index in paths, text)

    for rel, mtime, text in docs:
        paths.append(rel)
        mtimes.append(mtime)
        hit = cached.get(rel)
        if hit is not None and abs(hit[0] - mtime) < 1e-6:
            vecs.append(hit[1])           # переиспользуем кэшированный вектор
        else:
            vecs.append(None)             # заполним после батч-энкодинга
            to_embed.append((len(paths) - 1, text))

    if to_embed:
        logger.info("embedding %d new/changed memory docs", len(to_embed))
        new_vecs = model.encode([t for _, t in to_embed],
                                normalize_embeddings=True,
                                show_progress_bar=False)
        for (idx, _), v in zip(to_embed, new_vecs):
            vecs[idx] = np.asarray(v, dtype="float32")

    matrix = np.vstack([np.asarray(v, dtype="float32") for v in vecs])
    # Кэш сохраняем, только если что-то пересчитывали (или кэша не было).
    if to_embed or cache is None:
        _save_cache(paths, mtimes, matrix)
    return {"paths": paths, "vectors": matrix}


def semantic_scores(query: str) -> Dict[str, float]:
    """rel_path → косинусная близость [0..1] запроса ко всем докам vault'а.

    Пустой dict, если семантика недоступна (модель/numpy нет) — вызывающий код
    тогда просто работает без семантического вклада. Косинус = dot, т.к. векторы
    L2-нормированы.
    """
    np = _lazy_numpy()
    model = _lazy_model()
    if np is None or model is None or not query.strip():
        return {}
    try:
        index = _build_or_update_index()
        if not index:
            return {}
        q = model.encode([query], normalize_embeddings=True, show_progress_bar=False)
        q = np.asarray(q, dtype="float32")[0]
        sims = index["vectors"] @ q          # (N,) косинусные близости
        return {p: float(s) for p, s in zip(index["paths"], sims)}
    except Exception as e:
        logger.warning("semantic scoring failed, falling back to fuzzy only: %s", e)
        return {}
