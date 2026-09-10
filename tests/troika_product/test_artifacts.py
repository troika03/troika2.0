"""Private artifact storage and document generation checks."""

import sqlite3

import pytest

from troika_product.access import AccessRegistry
from troika_product.artifacts import (
    ArtifactIntegrityError,
    ArtifactStore,
    safe_artifact_filename,
)
from troika_product.document_generation import generate_docx, generate_pdf, generate_pptx


def _principals(tmp_path):
    database = tmp_path / "access.db"
    access = AccessRegistry(database)
    first_user = access.create_user("one@example.com")
    second_user = access.create_user("two@example.com")
    first = access.authenticate(
        access.issue_device_token(
            access.create_device(first_user, name="Pixel", platform="android")
        )
    )
    second = access.authenticate(
        access.issue_device_token(
            access.create_device(second_user, name="iPhone", platform="ios")
        )
    )
    assert first is not None and second is not None
    return database, first, second


def test_filename_is_flat_safe_and_keeps_expected_extension() -> None:
    assert safe_artifact_filename("../../Отчёт\r\n.pdf", "pdf") == "Отчёт.pdf"
    assert safe_artifact_filename("", "docx") == "document.docx"
    with pytest.raises(ValueError):
        safe_artifact_filename("archive", "zip")


def test_artifacts_are_isolated_and_never_expose_physical_paths(tmp_path) -> None:
    database, first, second = _principals(tmp_path)
    store = ArtifactStore(database, tmp_path / "artifacts")
    artifact = store.create(
        user_id=first.user_id,
        device_id=first.device_id,
        filename="private report",
        kind="pdf",
        data=b"%PDF-private",
    )

    assert [item.id for item in store.list_for_user(first.user_id)] == [artifact.id]
    assert store.list_for_user(second.user_id) == []
    assert store.read_for_user(second.user_id, artifact.id) is None
    assert store.delete_for_user(second.user_id, artifact.id) is None
    metadata = artifact.to_dict()
    assert "path" not in metadata and "storage" not in metadata
    assert metadata["download_url"].endswith(f"/{artifact.id}/download")

    stored, data = store.read_for_user(first.user_id, artifact.id)
    assert stored.filename == "private report.pdf"
    assert data == b"%PDF-private"
    assert store.delete_for_user(first.user_id, artifact.id) == artifact
    assert store.read_for_user(first.user_id, artifact.id) is None


def test_artifact_creation_rejects_a_device_owned_by_another_user(tmp_path) -> None:
    database, first, second = _principals(tmp_path)
    store = ArtifactStore(database, tmp_path / "artifacts")

    with pytest.raises(ValueError, match="does not belong"):
        store.create(
            user_id=first.user_id,
            device_id=second.device_id,
            filename="cross-tenant",
            kind="pdf",
            data=b"%PDF-private",
        )


def test_artifact_integrity_failure_is_detected(tmp_path) -> None:
    database, first, _ = _principals(tmp_path)
    root = tmp_path / "artifacts"
    store = ArtifactStore(database, root)
    artifact = store.create(
        user_id=first.user_id,
        device_id=first.device_id,
        filename="report",
        kind="pdf",
        data=b"%PDF-original",
    )
    with sqlite3.connect(database) as connection:
        storage_name = connection.execute(
            "SELECT storage_name FROM troika_artifacts WHERE id = ?", (artifact.id,)
        ).fetchone()[0]
    stored_file = next(root.rglob(storage_name))
    stored_file.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.read_for_user(first.user_id, artifact.id)


def test_document_generators_produce_real_office_and_pdf_files() -> None:
    content = {"title": "План", "content": "Первый абзац\n\nВторой абзац"}
    docx = generate_docx(content)
    pdf = generate_pdf(content)
    pptx = generate_pptx(
        {
            "title": "План",
            "slides": [{"title": "Шаги", "bullets": ["Первый", "Второй"]}],
        }
    )

    assert docx.startswith(b"PK")
    assert pdf.startswith(b"%PDF")
    assert pptx.startswith(b"PK")
    assert all(len(data) > 1_000 for data in (docx, pdf, pptx))
