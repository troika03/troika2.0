import hashlib
import io
import json
import time
import zipfile

import pytest

from troika_product.development import build_project
from troika_product.device_delivery import DeviceDeliveryStore


def test_handoff_is_owner_device_bound_and_removed_after_ack():
    store = DeviceDeliveryStore()
    metadata = store.create("one", "phone", "Отчёт", "pdf", "application/pdf", b"%PDF-content")
    assert metadata["sha256"] == hashlib.sha256(b"%PDF-content").hexdigest()
    assert store.get(metadata["id"], "two", "phone") is None
    assert store.get(metadata["id"], "one", "pc") is None
    assert not store.acknowledge(metadata["id"], "two", "phone")
    assert store.list_pending("one", "phone") == [metadata]
    assert store.get(metadata["id"], "one", "phone").data == b"%PDF-content"
    assert store.acknowledge(metadata["id"], "one", "phone")
    assert store.list_pending("one", "phone") == []


def test_expiry_actually_frees_ram_without_another_request():
    store = DeviceDeliveryStore(ttl=0.02)
    item = store.create("one", "phone", "x", "pdf", "application/pdf", b"%PDF-x")
    deadline = time.monotonic() + 2
    while item["id"] in store._items and time.monotonic() < deadline:
        time.sleep(0.01)
    assert item["id"] not in store._items


def test_capacity_is_bounded():
    store = DeviceDeliveryStore(max_bytes=8)
    item = store.create("one", "phone", "x", "pdf", "application/pdf", b"%PDF-x")
    with pytest.raises(ValueError, match="capacity"):
        store.create("one", "phone", "y", "pdf", "application/pdf", b"%PDF-y")
    store.acknowledge(item["id"], "one", "phone")


def test_revoke_and_account_purge_free_only_matching_files():
    store = DeviceDeliveryStore()
    ids = [store.create(user, device, "x", "pdf", "application/pdf", b"%PDF-x")["id"]
           for user, device in [("one", "phone"), ("one", "pc"), ("two", "phone")]]
    store.purge_owner("one", "phone")
    assert store.get(ids[0], "one", "phone") is None
    assert store.get(ids[1], "one", "pc")
    store.purge_owner("one")
    assert store.get(ids[1], "one", "pc") is None
    assert store.get(ids[2], "two", "phone")
    store.purge_owner("two")


@pytest.mark.parametrize("path", ["../x.py", "/x", "C:/x", "CON.py", "a./b", ".ENV", ".Git/x", "TROIKA-PROJECT.JSON"])
def test_project_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        build_project({"files": [{"path": path, "content": "x"}]})


@pytest.mark.parametrize("paths", [["a", "a/b.py"], ["a/b.py", "A"], ["a.py", "A.py"]])
def test_project_rejects_file_directory_conflicts(paths):
    with pytest.raises(ValueError):
        build_project({"files": [{"path": path, "content": "x"} for path in paths]})


def test_project_checks_syntax_but_never_executes_source(tmp_path):
    marker = tmp_path / "executed"
    data, checks = build_project({"files": [
        {"path": "main.py", "content": f"open({str(marker)!r}, 'w').write('bad')"},
        {"path": "test_bad.py", "content": "def broken(:"},
        {"path": "data.json", "content": "{"},
    ]})
    assert not marker.exists()
    assert [(c["scope"], c["status"]) for c in checks] == [
        ("python_syntax", "passed"), ("python_syntax", "failed"), ("json_syntax", "failed")]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("troika-project.json"))
        assert manifest["execution"] == "not_run"
        assert manifest["files"] == ["main.py", "test_bad.py", "data.json"]
