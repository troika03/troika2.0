"""Private artifact storage for the hosted Troika product.

The store exposes opaque artifact IDs and user-owned metadata.  Physical
paths never cross the API/tool boundary, and every read/delete is scoped by
the authenticated user ID.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata
import uuid

from hermes_constants import get_hermes_home


# This is a crash/abuse guard, not a subscription quota.  Normal generated
# documents are far smaller, while a corrupt model/tool result cannot fill the
# server disk in a single request.
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024

_KINDS = {
    "docx": (
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "pdf": (".pdf", "application/pdf"),
    "pptx": (
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
}
_OPAQUE_ID = re.compile(r"^art_[0-9a-f]{32}$")


class ArtifactIntegrityError(RuntimeError):
    """Stored bytes no longer match their immutable metadata."""


@dataclass(frozen=True)
class Artifact:
    """Safe artifact metadata returned to tools and authenticated clients."""

    id: str
    filename: str
    kind: str
    mime_type: str
    size: int
    created_at: float
    download_url: str

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


def safe_artifact_filename(value: str, kind: str) -> str:
    """Return a display filename with no path, controls, or header payload."""
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in _KINDS:
        raise ValueError("unsupported artifact kind")
    extension = _KINDS[clean_kind][0]
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = "".join(
        "_" if char in '<>:"/\\|?*' or unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    normalized = " ".join(normalized.split()).strip(" ._")
    if normalized.lower().endswith(extension):
        normalized = normalized[: -len(extension)].rstrip(" ._")
    if not normalized:
        normalized = "document"
    # Bound metadata and Content-Disposition size; this is not a usage quota.
    normalized = normalized[:160].rstrip(" ._") or "document"
    return f"{normalized}{extension}"


class ArtifactStore:
    """SQLite metadata plus opaque files, isolated by authenticated user ID."""

    def __init__(
        self,
        database_path: Path | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.database_path = database_path or get_hermes_home() / "troika_access.db"
        self.storage_root = storage_root or get_hermes_home() / "product_artifacts"
        self.database_path = Path(self.database_path).resolve()
        self.storage_root = Path(self.storage_root).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS troika_artifacts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    created_by_device_id TEXT NOT NULL REFERENCES troika_devices(id),
                    filename TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256_digest TEXT NOT NULL,
                    storage_name TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_troika_artifacts_user_time
                    ON troika_artifacts(user_id, created_at DESC);
                """
            )

    @staticmethod
    def _validate_owner(value: str, label: str) -> str:
        cleaned = str(value or "").strip()
        if not re.fullmatch(r"(?:usr|dev)_[0-9a-f]{32}", cleaned):
            raise ValueError(f"invalid {label}")
        return cleaned

    @staticmethod
    def _user_bucket(user_id: str) -> str:
        return sha256(user_id.encode("utf-8")).hexdigest()[:32]

    def _path_for(self, user_id: str, storage_name: str) -> Path:
        if not re.fullmatch(r"art_[0-9a-f]{32}\.(?:docx|pdf|pptx)", storage_name):
            raise ArtifactIntegrityError("invalid artifact storage reference")
        target = (self.storage_root / self._user_bucket(user_id) / storage_name).resolve()
        if self.storage_root not in target.parents:
            raise ArtifactIntegrityError("artifact escaped storage root")
        return target

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        artifact_id = str(row["id"])
        return Artifact(
            id=artifact_id,
            filename=str(row["filename"]),
            kind=str(row["kind"]),
            mime_type=str(row["mime_type"]),
            size=int(row["byte_size"]),
            created_at=float(row["created_at"]),
            download_url=f"/v1/artifacts/{artifact_id}/download",
        )

    def create(
        self,
        *,
        user_id: str,
        device_id: str,
        filename: str,
        kind: str,
        data: bytes,
    ) -> Artifact:
        clean_user_id = self._validate_owner(user_id, "user id")
        clean_device_id = self._validate_owner(device_id, "device id")
        clean_kind = str(kind or "").strip().lower()
        clean_filename = safe_artifact_filename(filename, clean_kind)
        if not isinstance(data, bytes) or not data:
            raise ValueError("artifact data must be non-empty bytes")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("generated artifact exceeds the technical safety size")

        with self._connect() as connection:
            owner = connection.execute(
                "SELECT devices.id FROM troika_devices AS devices "
                "JOIN troika_users AS users ON users.id = devices.user_id "
                "WHERE devices.id = ? AND devices.user_id = ? "
                "AND devices.status = 'active' AND users.status = 'active'",
                (clean_device_id, clean_user_id),
            ).fetchone()
        if owner is None:
            raise ValueError("device does not belong to an active artifact owner")

        extension, mime_type = _KINDS[clean_kind]
        artifact_id = f"art_{uuid.uuid4().hex}"
        storage_name = f"{artifact_id}{extension}"
        target = self._path_for(clean_user_id, storage_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".pending-", dir=target.parent, delete=False
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, target)
            temp_path = None
            created_at = time.time()
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO troika_artifacts "
                    "(id, user_id, created_by_device_id, filename, kind, mime_type, "
                    "byte_size, sha256_digest, storage_name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        clean_user_id,
                        clean_device_id,
                        clean_filename,
                        clean_kind,
                        mime_type,
                        len(data),
                        sha256(data).hexdigest(),
                        storage_name,
                        created_at,
                    ),
                )
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return Artifact(
            id=artifact_id,
            filename=clean_filename,
            kind=clean_kind,
            mime_type=mime_type,
            size=len(data),
            created_at=created_at,
            download_url=f"/v1/artifacts/{artifact_id}/download",
        )

    def list_for_user(self, user_id: str) -> list[Artifact]:
        clean_user_id = self._validate_owner(user_id, "user id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, filename, kind, mime_type, byte_size, created_at "
                "FROM troika_artifacts WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (clean_user_id,),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def read_for_user(self, user_id: str, artifact_id: str) -> tuple[Artifact, bytes] | None:
        clean_user_id = self._validate_owner(user_id, "user id")
        if not _OPAQUE_ID.fullmatch(str(artifact_id or "")):
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, user_id, filename, kind, mime_type, byte_size, "
                "sha256_digest, storage_name, created_at "
                "FROM troika_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, clean_user_id),
            ).fetchone()
        if row is None:
            return None
        target = self._path_for(clean_user_id, str(row["storage_name"]))
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise ArtifactIntegrityError("artifact bytes are unavailable") from exc
        if len(data) != int(row["byte_size"]) or not _constant_time_digest_equal(
            sha256(data).hexdigest(), str(row["sha256_digest"])
        ):
            raise ArtifactIntegrityError("artifact integrity check failed")
        return self._artifact_from_row(row), data

    def delete_for_user(self, user_id: str, artifact_id: str) -> Artifact | None:
        clean_user_id = self._validate_owner(user_id, "user id")
        if not _OPAQUE_ID.fullmatch(str(artifact_id or "")):
            return None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, user_id, filename, kind, mime_type, byte_size, "
                "storage_name, created_at FROM troika_artifacts "
                "WHERE id = ? AND user_id = ?",
                (artifact_id, clean_user_id),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "DELETE FROM troika_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, clean_user_id),
            )
        target = self._path_for(clean_user_id, str(row["storage_name"]))
        try:
            target.unlink(missing_ok=True)
        except OSError:
            # Metadata is already gone so access remains revoked.  Leave a
            # harmless opaque orphan for an operator cleanup job.
            pass
        return self._artifact_from_row(row)

    def purge_for_user(self, user_id: str, artifact_id: str) -> Artifact | None:
        """Delete one owner's bytes and metadata, surfacing storage failures.

        Retention uses this stricter path so a successful metric means the
        local artifact bytes are actually gone.  The public delete endpoint
        keeps its existing fail-closed behavior when an opaque orphan cannot
        be removed immediately.
        """
        clean_user_id = self._validate_owner(user_id, "user id")
        if not _OPAQUE_ID.fullmatch(str(artifact_id or "")):
            return None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, user_id, filename, kind, mime_type, byte_size, "
                "storage_name, created_at FROM troika_artifacts "
                "WHERE id = ? AND user_id = ?",
                (artifact_id, clean_user_id),
            ).fetchone()
            if row is None:
                return None
            target = self._path_for(clean_user_id, str(row["storage_name"]))
            target.unlink(missing_ok=True)
            if target.exists():
                raise OSError("artifact byte cleanup was incomplete")
            connection.execute(
                "DELETE FROM troika_artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, clean_user_id),
            )
        return self._artifact_from_row(row)

    def delete_all_files_for_user(self, user_id: str) -> None:
        """Remove one user's opaque artifact bucket before metadata deletion."""
        clean_user_id = self._validate_owner(user_id, "user id")
        bucket = (self.storage_root / self._user_bucket(clean_user_id)).resolve()
        if bucket.parent != self.storage_root:
            raise ArtifactIntegrityError("artifact bucket escaped storage root")
        if bucket.exists():
            shutil.rmtree(bucket)


def _constant_time_digest_equal(first: str, second: str) -> bool:
    import hmac

    return hmac.compare_digest(first, second)
