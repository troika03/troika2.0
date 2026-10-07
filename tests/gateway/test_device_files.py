import asyncio
import json

from gateway.platforms.api_server import _safe_product_action_result
from tests.gateway.test_product_auth import _adapter_with_two_users, _Request
from troika_product.device_delivery import DeviceDeliveryStore


def test_http_owner_device_download_ack(tmp_path, monkeypatch):
    adapter, first, second = _adapter_with_two_users(tmp_path)
    registry = adapter._access_registry
    principal = registry.authenticate(first)
    store = DeviceDeliveryStore()
    monkeypatch.setattr("troika_product.device_delivery.device_deliveries", store)
    artifact = store.create(principal.user_id, principal.device_id, "x", "pdf", "application/pdf", b"%PDF-test")

    def request(token, method="GET", item_id=artifact["id"]):
        req = _Request(token)
        req.method = method
        req.match_info = {"delivery_id": item_id}
        req.path_qs = "/v1/device-files/" + item_id
        return req

    assert asyncio.run(adapter._handle_device_file(request(second))).status == 404
    another = registry.issue_device_token(registry.create_device(principal.user_id, name="PC", platform="windows"))
    assert asyncio.run(adapter._handle_device_file(request(another))).status == 404
    listing = asyncio.run(adapter._handle_device_file(request(first, item_id="")))
    assert json.loads(listing.text)["data"] == [artifact]
    response = asyncio.run(adapter._handle_device_file(request(first)))
    assert response.body == b"%PDF-test" and response.headers["Cache-Control"] == "no-store"
    assert asyncio.run(adapter._handle_device_file(request(second, "POST"))).status == 404
    assert asyncio.run(adapter._handle_device_file(request(first, "POST"))).status == 200
    assert asyncio.run(adapter._handle_device_file(request(first))).status == 404


def test_result_metadata_never_forwards_content_or_internal_fields():
    result = _safe_product_action_result("troika_create_project", json.dumps({"ok": True, "artifact": {
        "id": "delivery_x", "filename": "code.zip", "storage": "device", "kind": "zip",
        "content": "private source", "user_id": "one", "data": "base64"}}))
    assert result["kind"] == "file_pending"
    assert not {"content", "data", "user_id"} & result["artifact"].keys()


def test_capabilities_advertise_the_required_delivery_protocol(tmp_path):
    adapter, token, _ = _adapter_with_two_users(tmp_path)
    response = asyncio.run(adapter._handle_capabilities(_Request(token)))
    assert response.status == 200
    assert json.loads(response.text)["features"]["device_file_delivery"] is True
