"""Owner-scoped portable data export for the Troika product."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.artifacts import ArtifactStore


EXPORT_SCHEMA_VERSION = 1
RETENTION_POLICY_VERSION = "2026-09-14"


class DataExportUnavailableError(RuntimeError):
    """Raised when a complete owner-scoped export cannot be produced."""


def _portable_conversation(
    session_db: Any,
    session_id: str,
    owned_session_ids: set[str],
) -> dict[str, object] | None:
    exported = session_db.export_session(session_id)
    if exported is None:
        return None
    parent_session_id = exported.get("parent_session_id")
    session_fields = (
        "id",
        "source",
        "model",
        "started_at",
        "ended_at",
        "end_reason",
        "message_count",
        "tool_call_count",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "billing_provider",
        "billing_mode",
        "estimated_cost_usd",
        "actual_cost_usd",
        "cost_status",
        "title",
        "api_call_count",
    )
    message_fields = (
        "role",
        "content",
        "tool_call_id",
        "tool_calls",
        "tool_name",
        "timestamp",
        "token_count",
        "finish_reason",
        "platform_message_id",
        "observed",
    )
    portable = {field: exported.get(field) for field in session_fields}
    portable["parent_session_id"] = (
        parent_session_id if parent_session_id in owned_session_ids else None
    )
    portable["messages"] = [
        {field: message.get(field) for field in message_fields}
        for message in exported.get("messages", [])
        if isinstance(message, dict)
    ]
    return portable


class ProductDataExporter:
    """Build a ZIP containing data owned by one authenticated account."""

    def __init__(
        self,
        *,
        registry: AccessRegistry,
        artifact_store: ArtifactStore | None,
        session_db: Any | None,
    ) -> None:
        self.registry = registry
        self.artifact_store = artifact_store
        self.session_db = session_db

    def build_archive(self, principal: AccessPrincipal) -> bytes:
        """Return a complete in-memory ZIP for the authenticated owner."""
        data = self.registry.export_account_rows(principal)
        session_rows = data.get("sessions", [])
        owned_session_ids = {
            str(item["session_id"])
            for item in session_rows
            if isinstance(item, dict) and item.get("session_id")
        }
        if owned_session_ids and self.session_db is None:
            raise DataExportUnavailableError("conversation storage is unavailable")

        conversations: list[dict[str, object]] = []
        if self.session_db is not None:
            for session_id in sorted(owned_session_ids):
                conversation = _portable_conversation(
                    self.session_db, session_id, owned_session_ids
                )
                conversations.append(
                    {
                        "session_id": session_id,
                        "conversation": conversation,
                    }
                )

        from tools.location_tool import export_location_scope

        locations = []
        for device in data.get("devices", []):
            if not isinstance(device, dict) or not device.get("id"):
                continue
            device_id = str(device["id"])
            locations.append(
                {
                    "device_id": device_id,
                    **export_location_scope(
                        f"troika:{principal.user_id}:{device_id}"
                    ),
                }
            )

        artifact_rows = data.pop("artifacts", [])
        if artifact_rows and self.artifact_store is None:
            raise DataExportUnavailableError("artifact storage is unavailable")

        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        output = BytesIO()
        with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
            portable_artifacts: list[dict[str, object]] = []
            for row in artifact_rows:
                if not isinstance(row, dict):
                    continue
                artifact_id = str(row.get("id", ""))
                stored = (
                    self.artifact_store.read_for_user(principal.user_id, artifact_id)
                    if self.artifact_store is not None
                    else None
                )
                if stored is None:
                    raise DataExportUnavailableError(
                        "artifact metadata and bytes are inconsistent"
                    )
                artifact, artifact_bytes = stored
                archive_path = f"artifacts/{artifact.id}/{artifact.filename}"
                archive.writestr(archive_path, artifact_bytes)
                portable_artifacts.append({**row, "archive_path": archive_path})

            payload = {
                "export": {
                    "schema_version": EXPORT_SCHEMA_VERSION,
                    "generated_at": generated_at,
                    "scope": "authenticated_account",
                    "retention_policy_version": RETENTION_POLICY_VERSION,
                    "excluded_server_security_fields": [
                        "bearer token values and digests",
                        "vision nonce digests",
                        "artifact physical paths and storage names",
                        "model private reasoning and server system prompts",
                    ],
                },
                "data": {
                    **data,
                    "conversations": conversations,
                    "locations": locations,
                    "artifacts": portable_artifacts,
                },
            }
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
            archive.writestr("troika-data.json", serialized)
            archive.comment = (
                f"Troika account export schema {EXPORT_SCHEMA_VERSION}; "
                f"generated {generated_at}"
            ).encode("utf-8")
        return output.getvalue()

    @staticmethod
    def download_filename() -> str:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"troika-data-export-{date}.zip"
