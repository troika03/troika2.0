"""Troika product document tool boundary checks."""

import json

import pytest

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_documents_tool
from troika_product.access import AccessRegistry
from troika_product.artifacts import ArtifactStore
from troika_product.device_delivery import DeviceDeliveryStore


@pytest.mark.parametrize("handler,args", [
    ("_handle_docx", {"title": "Локальный", "content": "Содержимое"}),
    ("_handle_project", {"title": "Код", "files": [
        {"path": "main.py", "content": "def add(a,b): return a+b"},
        {"path": "test_add.py", "content": "from main import add\nassert add(1,2)==3"},
        {"path": "README.md", "content": "Run python test_add.py"}]}),
])
def test_device_mode_never_writes_artifact_store(tmp_path, monkeypatch, handler, args):
    store = DeviceDeliveryStore()
    monkeypatch.setattr(troika_documents_tool, "device_deliveries", store)
    monkeypatch.setattr(troika_documents_tool, "_artifact_store", lambda: pytest.fail("permanent file store accessed"))
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "one", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token", "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE": "0"}
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        payload = json.loads(getattr(troika_documents_tool, handler)(args))
    finally:
        for name in overrides:
            clear_session_override(name)
    assert payload["ok"]
    artifact = payload["artifact"]
    assert artifact["storage"] == "device"
    assert "data" not in artifact and "content" not in artifact
    assert store.get(artifact["id"], "one", "phone").data
    store.acknowledge(artifact["id"], "one", "phone")


def test_device_workspace_write_is_delivered_without_a_server_directory(monkeypatch):
    from tools import troika_workspace_tool
    store = DeviceDeliveryStore()
    monkeypatch.setattr(troika_documents_tool, "device_deliveries", store)
    monkeypatch.setattr(troika_workspace_tool, "_store", lambda: pytest.fail("server workspace accessed"))
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "one", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token"}
    try:
        for name, value in overrides.items(): set_session_override(name, value)
        payload = json.loads(troika_workspace_tool._handle_files({"action": "write", "path": "index.html", "content": "<h1>Site</h1>"}))
        assert payload["ok"] and payload["artifact"]["storage"] == "device"
        assert json.loads(troika_workspace_tool._handle_terminal({"command": "touch x.txt"}))["ok"] is False
    finally:
        for name in overrides: clear_session_override(name)
    store.acknowledge(payload["artifact"]["id"], "one", "phone")


def test_document_tool_requires_authenticated_product_context() -> None:
    payload = json.loads(
        troika_documents_tool._handle_docx({"title": "No owner", "content": "x"})
    )
    assert payload == {"ok": False, "error": "product_identity_required"}


def test_document_tool_fails_closed_when_private_storage_is_unavailable() -> None:
    try:
        set_session_override("TROIKA_PRODUCT_MODE", "1")
        set_session_override("TROIKA_PRODUCT_ARTIFACTS_AVAILABLE", "0")
        payload = json.loads(
            troika_documents_tool._handle_pdf({"title": "Unavailable"})
        )
    finally:
        clear_session_override("TROIKA_PRODUCT_ARTIFACTS_AVAILABLE")
        clear_session_override("TROIKA_PRODUCT_MODE")

    assert payload == {"ok": False, "error": "artifact_storage_unavailable"}


def test_document_tool_stores_and_audits_without_confirmation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "tools.approval.request_gateway_approval",
        lambda *args, **kwargs: pytest.fail("document creation requested approval"),
    )
    database = tmp_path / "access.db"
    root = tmp_path / "artifacts"
    access = AccessRegistry(database)
    user_id = access.create_user("one@example.com")
    token = access.issue_device_token(
        access.create_device(user_id, name="Pixel", platform="android")
    )
    principal = access.authenticate(token)
    assert principal is not None
    overrides = {
        "TROIKA_PRODUCT_MODE": "1",
        "TROIKA_PRODUCT_USER_ID": principal.user_id,
        "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
        "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE": "1",
        "TROIKA_PRODUCT_ARTIFACT_DB": str(database),
        "TROIKA_PRODUCT_ARTIFACT_ROOT": str(root),
    }
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        payload = json.loads(
            troika_documents_tool._handle_pptx(
                {
                    "title": "Презентация",
                    "slides": [
                        {"title": "Слайд", "bullets": ["Личные данные"]}
                    ],
                },
                task_id="run_private",
            )
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert payload["ok"] is True
    artifact_id = payload["artifact"]["id"]
    listed = ArtifactStore(database, root).list_for_user(principal.user_id)
    assert [item.id for item in listed] == [artifact_id]
    event = access.list_audit_events(principal.user_id)[0]
    assert event.event_type == "artifact.created"
    assert artifact_id not in json.dumps(event.details)
