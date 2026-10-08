from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from troika_product.access import AccessRegistry
from troika_product.development_api import register_development_routes
from troika_product.development_checks import DevelopmentCheckStore


@pytest.mark.asyncio
async def test_authenticated_phone_pc_check_transport_and_foreign_device(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.register_account("owner@example.com", "long-test-password")
    other = registry.register_account("other@example.com", "long-test-password")
    devices = {}
    tokens = {}
    for name, user, platform in [("phone", owner, "android"), ("pc", owner, "windows"),
                                  ("foreign", other, "windows")]:
        devices[name] = registry.create_device(user, name=name, platform=platform)
        tokens[name] = registry.issue_device_token(devices[name])

    def check_auth(request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        principal = registry.authenticate(token)
        if principal is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        request["principal"] = principal
        return None

    adapter = SimpleNamespace(_check_auth=check_auth, _product_principal=lambda request: request.get("principal"),
                              _access_registry=registry)
    store = DevelopmentCheckStore()
    app = web.Application()
    register_development_routes(app, adapter, store=store)
    client = TestClient(TestServer(app))
    await client.start_server()
    headers = lambda device: {"Authorization": "Bearer " + tokens[device]}
    try:
        assert (await client.get("/v1/development/devices")).status == 401
        assert (await client.post("/v1/development/worker", headers=headers("phone"), json={"enabled": True})).status == 403
        enrolled = await client.post("/v1/development/worker", headers=headers("pc"), json={"enabled": True})
        assert enrolled.status == 200
        available = await (await client.get("/v1/development/devices", headers=headers("phone"))).json()
        assert [row["id"] for row in available["devices"]] == [devices["pc"]]
        body = {"target_device_id": devices["pc"], "mode": "python_tests", "workflow_id": "flow",
                "files": {"main.py": "print(42)"}}
        created = await client.post("/v1/development/checks", headers=headers("phone"), json=body)
        assert created.status == 202
        job_id = (await created.json())["id"]
        assert (await client.get(f"/v1/development/checks/{job_id}", headers=headers("foreign"))).status == 404
        foreign = await client.post("/v1/development/checks", headers=headers("foreign"), json=body)
        assert foreign.status == 404
        claimed = await (await client.post("/v1/development/worker", headers=headers("pc"), json={"enabled": True})).json()
        report = {"lease": claimed["job"]["lease"], "report": {"exit_code": 1, "output": "FAILED"}}
        assert (await client.post(f"/v1/development/checks/{job_id}/report", headers=headers("phone"), json=report)).status == 409
        assert (await client.post(f"/v1/development/checks/{job_id}/report", headers=headers("pc"), json=report)).status == 200
        result = await (await client.get(f"/v1/development/checks/{job_id}", headers=headers("phone"))).json()
        assert result["report"]["exit_code"] == 1
        assert "files" not in result
        assert (await client.post(f"/v1/development/checks/{job_id}/report", headers=headers("pc"), json=report)).status == 409
        registry.revoke_device(registry.authenticate(tokens["phone"]), devices["pc"])
        assert (await client.post("/v1/development/worker", headers=headers("pc"), json={"enabled": True})).status == 401
    finally:
        store.purge(owner)
        await client.close()
