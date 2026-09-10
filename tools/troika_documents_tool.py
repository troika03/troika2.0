"""Safe document creation tools for authenticated Troika product users."""

from __future__ import annotations

from hashlib import sha256
import json
import logging
from pathlib import Path
from typing import Any, Callable

from gateway.session_context import get_session_env
from tools.registry import registry
from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.artifacts import ArtifactStore, safe_artifact_filename
from troika_product.document_generation import generate_docx, generate_pdf, generate_pptx


logger = logging.getLogger(__name__)


def _documents_available() -> bool:
    try:
        import docx  # noqa: F401
        import pptx  # noqa: F401
        import reportlab  # noqa: F401
    except Exception:
        return False
    return True


def _product_identity() -> tuple[str, str, str] | None:
    if get_session_env("TROIKA_PRODUCT_MODE", "") != "1":
        return None
    user_id = get_session_env("TROIKA_PRODUCT_USER_ID", "")
    device_id = get_session_env("TROIKA_PRODUCT_DEVICE_ID", "")
    token_id = get_session_env("TROIKA_PRODUCT_TOKEN_ID", "")
    if not user_id or not device_id or not token_id:
        return None
    return user_id, device_id, token_id


def _artifact_store() -> ArtifactStore:
    raw_database = get_session_env("TROIKA_PRODUCT_ARTIFACT_DB", "")
    raw_root = get_session_env("TROIKA_PRODUCT_ARTIFACT_ROOT", "")
    return ArtifactStore(
        database_path=Path(raw_database) if raw_database else None,
        storage_root=Path(raw_root) if raw_root else None,
    )


def _record_created(
    principal: AccessPrincipal,
    artifact_id: str,
    kind: str,
    size: int,
    task_id: str | None,
) -> None:
    raw_database = get_session_env("TROIKA_PRODUCT_ARTIFACT_DB", "")
    registry_instance = AccessRegistry(Path(raw_database) if raw_database else None)
    registry_instance.record_audit_event(
        "artifact.created",
        principal=principal,
        run_id=task_id,
        details={
            "artifact_digest": sha256(artifact_id.encode("utf-8")).hexdigest()[:32],
            "kind": kind,
            "size": size,
        },
    )


def _create_artifact(
    args: dict[str, Any],
    *,
    kind: str,
    generator: Callable[[dict[str, Any]], bytes],
    task_id: str | None,
) -> str:
    if (
        get_session_env("TROIKA_PRODUCT_MODE", "") == "1"
        and get_session_env("TROIKA_PRODUCT_ARTIFACTS_AVAILABLE", "") != "1"
    ):
        return json.dumps(
            {"ok": False, "error": "artifact_storage_unavailable"},
            ensure_ascii=False,
        )
    identity = _product_identity()
    if identity is None:
        return json.dumps(
            {"ok": False, "error": "product_identity_required"}, ensure_ascii=False
        )
    user_id, device_id, token_id = identity
    title = str(args.get("title") or "Документ")
    try:
        filename = safe_artifact_filename(str(args.get("filename") or title), kind)
        data = generator(args)
    except ValueError as exc:
        return json.dumps(
            {"ok": False, "error": "document_generation_failed", "message": str(exc)},
            ensure_ascii=False,
        )
    except Exception:
        logger.exception("Troika document generation failed")
        return json.dumps(
            {"ok": False, "error": "document_generation_failed"},
            ensure_ascii=False,
        )

    from tools.approval import request_gateway_approval

    approval = request_gateway_approval(
        "artifact.create",
        f"Сохранить файл «{filename}» в личных файлах Тройки.",
    )
    if not approval.get("approved"):
        return json.dumps(
            {"ok": False, "error": "artifact_creation_not_confirmed"},
            ensure_ascii=False,
        )

    try:
        artifact = _artifact_store().create(
            user_id=user_id,
            device_id=device_id,
            filename=filename,
            kind=kind,
            data=data,
        )
    except Exception:
        logger.exception("Troika artifact storage failed")
        return json.dumps(
            {"ok": False, "error": "artifact_storage_failed"},
            ensure_ascii=False,
        )
    principal = AccessPrincipal(user_id=user_id, device_id=device_id, token_id=token_id)
    try:
        _record_created(principal, artifact.id, kind, artifact.size, task_id)
    except Exception:
        # Audit failure must not make the agent retry and create a duplicate.
        logger.exception("Troika artifact audit write failed")
    return json.dumps({"ok": True, "artifact": artifact.to_dict()}, ensure_ascii=False)


def _handle_docx(args: dict[str, Any], **kwargs: Any) -> str:
    return _create_artifact(
        args, kind="docx", generator=generate_docx, task_id=kwargs.get("task_id")
    )


def _handle_pdf(args: dict[str, Any], **kwargs: Any) -> str:
    return _create_artifact(
        args, kind="pdf", generator=generate_pdf, task_id=kwargs.get("task_id")
    )


def _handle_pptx(args: dict[str, Any], **kwargs: Any) -> str:
    return _create_artifact(
        args, kind="pptx", generator=generate_pptx, task_id=kwargs.get("task_id")
    )


_SECTIONS = {
    "type": "array",
    "description": "Structured sections with heading and body fields.",
    "items": {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "body": {"type": "string"},
        },
    },
}

DOCX_SCHEMA = {
    "name": "troika_create_docx",
    "description": "Create a polished Word document in the user's private Troika files.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "sections": _SECTIONS,
            "filename": {"type": "string", "description": "Filename only, without a path."},
        },
        "required": ["title"],
    },
}

PDF_SCHEMA = {
    "name": "troika_create_pdf",
    "description": "Create a polished PDF in the user's private Troika files.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "sections": _SECTIONS,
            "filename": {"type": "string", "description": "Filename only, without a path."},
        },
        "required": ["title"],
    },
}

PPTX_SCHEMA = {
    "name": "troika_create_pptx",
    "description": "Create a styled PowerPoint in the user's private Troika files.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "filename": {"type": "string", "description": "Filename only, without a path."},
        },
        "required": ["title", "slides"],
    },
}

registry.register(
    name="troika_create_docx",
    toolset="troika_documents",
    schema=DOCX_SCHEMA,
    handler=_handle_docx,
    check_fn=_documents_available,
    emoji="📝",
)
registry.register(
    name="troika_create_pdf",
    toolset="troika_documents",
    schema=PDF_SCHEMA,
    handler=_handle_pdf,
    check_fn=_documents_available,
    emoji="📄",
)
registry.register(
    name="troika_create_pptx",
    toolset="troika_documents",
    schema=PPTX_SCHEMA,
    handler=_handle_pptx,
    check_fn=_documents_available,
    emoji="📊",
)
