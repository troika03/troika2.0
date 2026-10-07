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
from troika_product.device_delivery import device_deliveries
from troika_product.development import build_project


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
        and get_session_env("TROIKA_PRODUCT_DELIVERY_MODE", "server") != "device"
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

    try:
        if get_session_env("TROIKA_PRODUCT_DELIVERY_MODE", "server") == "device":
            mime = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "pdf": "application/pdf"}[kind]
            artifact = device_deliveries.create(user_id, device_id, filename, kind, mime, data)
            return json.dumps({"ok": True, "artifact": artifact,
                               "message": "File prepared for device download; not yet saved on device."},
                              ensure_ascii=False)
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


def _handle_project(args: dict[str, Any], **kwargs: Any) -> str:
    identity = _product_identity()
    if identity is None:
        return json.dumps({"ok": False, "error": "product_identity_required"})
    if get_session_env("TROIKA_PRODUCT_DELIVERY_MODE", "server") != "device":
        return json.dumps({"ok": False, "error": "device_delivery_client_required"})
    try:
        data, checks = build_project(args)
        name = str(args.get("title") or "project")
        artifact = device_deliveries.create(identity[0], identity[1], name, "zip", "application/zip", data)
        return json.dumps({"ok": True, "artifact": artifact, "checks": checks,
                           "execution": "not_run", "message": "Source project prepared. Only syntax checks ran; tests must run on the user's PC."}, ensure_ascii=False)
    except ValueError as error:
        return json.dumps({"ok": False, "error": "project_generation_failed", "message": str(error)})


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
    "description": "Prepare a professional Word document. Updated clients save it locally; a tool receipt alone does not prove device delivery.",
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
    "description": "Prepare a professional PDF. Updated clients save it locally; a tool receipt alone does not prove device delivery.",
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
    "description": "Prepare a professional PowerPoint. Updated clients save it locally; a tool receipt alone does not prove device delivery.",
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

registry.register(
    name="troika_create_project", toolset="troika_documents", handler=_handle_project,
    schema={"name": "troika_create_project",
            "description": "Develop a source project with code, tests and README, or provide a revised project after check output. Delivered only to the user's device as ZIP. Python/JSON syntax is checked; this does NOT execute code or prove tests passed. Include test files and clear run instructions. Never claim deployment or test success without actual local execution results.",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string"}, "instructions": {"type": "string"},
                "files": {"type": "array", "items": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Relative project path; no absolute paths or .."},
                    "content": {"type": "string"}}, "required": ["path", "content"]}}},
                "required": ["title", "files"]}},
    check_fn=_documents_available,
)
