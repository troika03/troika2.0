"""
Speaker ID — отличить Мишу от других голосов.

Использует Resemblyzer (256-dim voice embedding, ~30MB модель, torch-based).
Зависимость ставится по требованию: `pip install resemblyzer`.

Workflow:
  1. enroll: Миша один раз произносит 5-10 коротких фраз, мы усредняем
     embedding'и и сохраняем как эталон.
  2. verify: на каждом запросе телефон шлёт wav, сервер делает embedding и
     сравнивает cosine с эталоном. Если score < threshold → not_misha.

Хранилище: ~/.troika/speaker_profiles/<name>.npy + meta.json
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from tools.registry import registry

logger = logging.getLogger(__name__)


_DEFAULT_THRESHOLD = 0.72
_DEFAULT_NAME = "misha"


def _profiles_dir() -> Path:
    p = get_hermes_home() / "speaker_profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _meta_path() -> Path:
    return _profiles_dir() / "meta.json"


def _read_meta() -> Dict[str, Any]:
    p = _meta_path()
    if not p.exists():
        return {"profiles": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}}


def _write_meta(meta: Dict[str, Any]) -> None:
    _meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _try_import_resemblyzer():
    try:
        import numpy as np  # noqa: F401
        from resemblyzer import VoiceEncoder, preprocess_wav  # type: ignore
        return VoiceEncoder, preprocess_wav
    except ImportError as e:
        return None, str(e)


def _decode_audio(args: Dict[str, Any]):
    """Берёт либо wav_path, либо wav_base64. Возвращает numpy array через preprocess."""
    _, preprocess_wav = _try_import_resemblyzer()
    if preprocess_wav is None or isinstance(preprocess_wav, str):
        return None, "resemblyzer_not_installed"

    wav_path = args.get("wav_path")
    wav_b64 = args.get("wav_base64")
    if wav_path:
        p = Path(wav_path).expanduser()
        if not p.exists():
            return None, f"wav_not_found: {p}"
        try:
            return preprocess_wav(p), None
        except Exception as e:
            return None, f"preprocess_failed: {e}"
    if wav_b64:
        try:
            raw = base64.b64decode(wav_b64)
        except Exception as e:
            return None, f"bad_base64: {e}"
        try:
            import soundfile as sf  # type: ignore
            import numpy as np
            data, sr = sf.read(io.BytesIO(raw))
            if data.ndim > 1:
                data = data.mean(axis=1)
            data = data.astype("float32")
            if sr != 16000:
                # resample через librosa
                import librosa  # type: ignore
                data = librosa.resample(data, orig_sr=sr, target_sr=16000)
            return preprocess_wav(data), None
        except ImportError as e:
            return None, f"audio_libs_missing: {e}"
        except Exception as e:
            return None, f"decode_failed: {e}"
    return None, "missing_wav_path_or_wav_base64"


def _enroll(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or _DEFAULT_NAME).strip().lower()
    samples = args.get("samples")
    if not isinstance(samples, list) or not samples:
        # Альтернатива: один длинный wav через wav_path/wav_base64
        if not (args.get("wav_path") or args.get("wav_base64")):
            return {
                "ok": False,
                "error": "need_samples_or_wav",
                "hint": "Передай samples=[{wav_path/wav_base64}, …] (5-10 фраз) или один длинный wav.",
            }
        samples = [{"wav_path": args.get("wav_path"), "wav_base64": args.get("wav_base64")}]

    VoiceEncoder, _ = _try_import_resemblyzer()
    if VoiceEncoder is None:
        return {
            "ok": False,
            "error": "resemblyzer_not_installed",
            "hint": "pip install resemblyzer soundfile librosa",
        }

    encoder = VoiceEncoder(verbose=False)
    import numpy as np

    embeddings: List[Any] = []
    errors: List[str] = []
    for i, s in enumerate(samples):
        wav, err = _decode_audio(s)
        if err:
            errors.append(f"sample[{i}]: {err}")
            continue
        try:
            emb = encoder.embed_utterance(wav)
            embeddings.append(emb)
        except Exception as e:
            errors.append(f"sample[{i}]: embed_failed: {e}")

    if not embeddings:
        return {"ok": False, "error": "no_valid_samples", "errors": errors}

    centroid = np.mean(np.stack(embeddings), axis=0)
    centroid_path = _profiles_dir() / f"{name}.npy"
    np.save(centroid_path, centroid)

    meta = _read_meta()
    meta["profiles"][name] = {
        "samples_used": len(embeddings),
        "sample_errors": errors,
        "centroid_path": str(centroid_path),
        "updated_at": time.time(),
    }
    _write_meta(meta)
    return {
        "ok": True,
        "name": name,
        "samples_used": len(embeddings),
        "sample_errors": errors or None,
    }


def _verify(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or _DEFAULT_NAME).strip().lower()
    threshold = float(args.get("threshold", _DEFAULT_THRESHOLD))

    meta = _read_meta()
    prof = meta.get("profiles", {}).get(name)
    if not prof:
        return {"ok": False, "error": "no_profile", "hint": f"Сначала enroll для '{name}'."}

    VoiceEncoder, _ = _try_import_resemblyzer()
    if VoiceEncoder is None:
        return {
            "ok": False,
            "error": "resemblyzer_not_installed",
            "hint": "pip install resemblyzer soundfile librosa",
        }

    wav, err = _decode_audio(args)
    if err:
        return {"ok": False, "error": err}

    import numpy as np

    encoder = VoiceEncoder(verbose=False)
    try:
        emb = encoder.embed_utterance(wav)
    except Exception as e:
        return {"ok": False, "error": f"embed_failed: {e}"}

    centroid = np.load(prof["centroid_path"])
    cos = float(np.dot(emb, centroid) / (np.linalg.norm(emb) * np.linalg.norm(centroid) + 1e-9))
    is_match = cos >= threshold
    return {
        "ok": True,
        "name": name,
        "is_match": is_match,
        "score": round(cos, 3),
        "threshold": threshold,
    }


def _list_profiles() -> Dict[str, Any]:
    meta = _read_meta()
    profs = meta.get("profiles", {})
    return {
        "ok": True,
        "count": len(profs),
        "profiles": [
            {"name": n, "samples_used": v.get("samples_used"), "updated_at": v.get("updated_at")}
            for n, v in profs.items()
        ],
    }


def _forget(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip().lower()
    if not name:
        return {"ok": False, "error": "missing 'name'"}
    meta = _read_meta()
    prof = meta.get("profiles", {}).pop(name, None)
    if prof:
        try:
            Path(prof.get("centroid_path", "")).unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
    _write_meta(meta)
    return {"ok": True, "deleted": bool(prof), "name": name}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    op = (args.get("operation") or "verify").strip().lower()
    if op == "enroll":
        res = _enroll(args)
    elif op == "verify":
        res = _verify(args)
    elif op == "list":
        res = _list_profiles()
    elif op == "forget":
        res = _forget(args)
    else:
        res = {"ok": False, "error": f"unknown operation '{op}'", "allowed": ["enroll", "verify", "list", "forget"]}
    return json.dumps(res, ensure_ascii=False)


SPEAKER_ID_SCHEMA = {
    "name": "speaker_id",
    "description": (
        "Отличить голос Миши от других через Resemblyzer (voice embedding + "
        "cosine similarity). operations: enroll (запомнить голос — нужно 5-10 "
        "коротких wav-фраз), verify (этот голос — Миша? score 0..1), list, forget. "
        "Требует pip install resemblyzer soundfile librosa. Модель ~30MB качается "
        "при первом VoiceEncoder()."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["enroll", "verify", "list", "forget"],
                "description": "По умолчанию verify.",
            },
            "name": {
                "type": "string",
                "description": "Имя профиля (default 'misha').",
            },
            "wav_path": {
                "type": "string",
                "description": "Путь к wav-файлу для verify или одного-файла enroll.",
            },
            "wav_base64": {
                "type": "string",
                "description": "Альтернатива wav_path: содержимое wav в base64.",
            },
            "samples": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "Для enroll: список объектов {wav_path|wav_base64}. "
                    "Рекомендуется 5-10 фраз по 2-5 секунд."
                ),
            },
            "threshold": {
                "type": "number",
                "description": f"Порог cosine similarity для verify (default {_DEFAULT_THRESHOLD}).",
            },
        },
        "required": [],
    },
}


registry.register(
    name="speaker_id",
    toolset="speaker_id",
    schema=SPEAKER_ID_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="🎙",
)
