"""Pro admission, independent background sessions and ownership on Run transport."""

import asyncio
from contextlib import nullcontext
import threading
import time
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from troika_product.access import AccessRegistry
from troika_product.development_runtime import register_autopilot_routes, start_development_run


@pytest.mark.asyncio
async def test_background_run_leaves_conversation_available_and_stop_is_project_scoped(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    tokens = {}
    for plan in ("free", "plus", "pro"):
        user = registry.create_user(plan + "@example.com", plan=plan)
        device = registry.create_device(user, name="phone", platform="android")
        tokens[plan] = registry.issue_device_token(device)
    def auth(request):
        principal = registry.authenticate(request.headers.get("Authorization", "").removeprefix("Bearer "))
        if principal is None:
            return web.json_response({}, status=401)
        request["principal"] = principal
    adapter = SimpleNamespace(_access_registry=registry, _check_auth=auth,
        _product_principal=lambda r: r.get("principal"), _run_statuses={}, _run_owners={},
        _run_streams={}, _run_streams_created={}, _active_run_agents={}, _active_run_tasks={},
        _background_tasks=set(), _MAX_CONCURRENT_RUNS=10,
        _consume_product_request_quota=lambda r: None,
        _authorize_product_session=lambda *a, **kw: None,
        _resource_call_scope=lambda *a: nullcontext())
    def status(run, state, **fields):
        value = adapter._run_statuses.setdefault(run, {"run_id": run, "created_at": 1})
        value.update(status=state, **fields)
    adapter._set_run_status = status
    entered = threading.Event()
    class Team:
        def __init__(self, cancelled, progress, max_workers):
            self.cancelled, self.progress = cancelled, progress
        def run(self, task, initial):
            self.progress(stage="planning", role="planner", worker_id="planner",
                          worker_state="running", message="Planning", report="", calls=1)
            entered.set()
            while not self.cancelled():
                time.sleep(.01)
            raise InterruptedError()
    async def start(request):
        denied = auth(request)
        if denied is not None:
            return denied
        return await start_development_run(adapter, request, await request.json(), team_factory=Team)
    async def conversation(request):
        return web.json_response({"answer": "Conversation is available"})
    app = web.Application()
    register_autopilot_routes(app, adapter)
    app.router.add_post("/v1/runs", start)
    app.router.add_post("/conversation", conversation)
    client = TestClient(TestServer(app))
    await client.start_server()
    headers = lambda plan: {"Authorization": "Bearer " + tokens[plan]}
    body = {"workflow": "development", "input": "Build a site", "idempotency_key": "unique-project", "free_only": True}
    try:
        for plan in ("free", "plus"):
            response = await client.post("/v1/runs", headers=headers(plan), json=body)
            assert response.status == 403
        assert adapter._active_run_tasks == {}
        first = await client.post("/v1/runs", headers=headers("pro"), json=body)
        assert first.status == 202
        data = await first.json()
        assert data["session_id"].startswith("development-")
        assert (await client.post("/conversation")).status == 200
        replay = await client.post("/v1/runs", headers=headers("pro"), json=body)
        assert (await replay.json())["run_id"] == data["run_id"]
        assert len(adapter._active_run_tasks) == 1
        other = await (await client.get("/v1/development/projects", headers=headers("plus"))).json()
        assert other["projects"] == []
        adapter._active_run_agents[data["run_id"]].interrupt()
        await asyncio.wait_for(asyncio.gather(*list(adapter._background_tasks)), 2)
        assert adapter._run_statuses[data["run_id"]]["status"] == "cancelled"
        assert not adapter._active_run_tasks
    finally:
        for handle in adapter._active_run_agents.values():
            handle.interrupt()
        await asyncio.gather(*list(adapter._background_tasks), return_exceptions=True)
        await client.close()
from contextlib import asynccontextmanager

@asynccontextmanager
async def runtime_client(tmp_path, team_factory):
    registry = AccessRegistry(tmp_path / 'runtime.db')
    user = registry.create_user('autopilot@example.com', plan='pro')
    device = registry.create_device(user, name='phone', platform='android')
    token = registry.issue_device_token(device)
    def auth(request):
        request['principal'] = registry.authenticate(request.headers.get('Authorization', '').removeprefix('Bearer '))
        if request['principal'] is None:
            return web.json_response({}, status=401)
    adapter = SimpleNamespace(_access_registry=registry, _check_auth=auth,
        _product_principal=lambda r: r.get('principal'), _run_statuses={}, _run_owners={},
        _run_streams={}, _run_streams_created={}, _active_run_agents={}, _active_run_tasks={},
        _background_tasks=set(), _MAX_CONCURRENT_RUNS=10,
        _consume_product_request_quota=lambda r: None,
        _authorize_product_session=lambda *a, **kw: None,
        _resource_call_scope=lambda *a: nullcontext())
    def status(run, state, **fields):
        adapter._run_statuses.setdefault(run, {'run_id': run, 'created_at': 1}).update(status=state, **fields)
    adapter._set_run_status = status
    async def start(request):
        denied = auth(request)
        if denied is not None: return denied
        return await start_development_run(adapter, request, await request.json(), team_factory=team_factory)
    app = web.Application()
    register_autopilot_routes(app, adapter)
    app.router.add_post('/v1/runs', start)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client, adapter, {'Authorization': 'Bearer ' + token}, registry, user, device
    finally:
        for handle in list(adapter._active_run_agents.values()): handle.interrupt()
        await asyncio.gather(*list(adapter._background_tasks), return_exceptions=True)
        await client.close()
        from troika_product.device_delivery import device_deliveries
        device_deliveries.purge_owner(user)

class HoldingTeam:
    def __init__(self, cancelled, **kwargs): self.cancelled = cancelled
    def run(self, *args):
        while not self.cancelled(): time.sleep(.01)
        raise InterruptedError()

def request_body(key='example-project'):
    return {'input': 'Build a site', 'idempotency_key': key, 'free_only': True}

@pytest.mark.asyncio
async def test_four_background_projects_leave_the_fifth_slot_for_chat(tmp_path):
    async with runtime_client(tmp_path, HoldingTeam) as (client, adapter, headers, _, user, device):
        for i in range(4):
            assert (await client.post('/v1/runs', headers=headers, json=request_body('project-key-' + str(i)))).status == 202
        response = await client.post('/v1/runs', headers=headers, json=request_body('project-key-5'))
        assert response.status == 429 and len(adapter._active_run_tasks) == 4
        assert (await response.json())['error']['code'] == 'development_capacity'
        first = next(iter(adapter._active_run_tasks))
        adapter._active_run_agents[first].interrupt()
        await adapter._active_run_tasks[first]
        assert len(adapter._active_run_tasks) == 3
        assert all(v['status'] == 'queued' for k, v in adapter._run_statuses.items() if k != first)

@pytest.mark.asyncio
async def test_owner_limit_includes_normal_runs_and_secrets_never_reach_model(tmp_path):
    async with runtime_client(tmp_path, HoldingTeam) as (client, adapter, headers, _, user, device):
        body = request_body()
        body['input'] = 'Use sk-' + 'a' * 30
        denied = await client.post('/v1/runs', headers=headers, json=body)
        assert denied.status == 400 and not adapter._active_run_tasks
        for i in range(5):
            adapter._run_statuses[str(i)] = {'status': 'running'}
            adapter._run_owners[str(i)] = (user, device)
        denied = await client.post('/v1/runs', headers=headers, json=request_body())
        assert denied.status == 429 and not adapter._active_run_tasks

@pytest.mark.asyncio
async def test_changed_retry_is_rejected_and_revoked_account_stops_work(tmp_path):
    async with runtime_client(tmp_path, HoldingTeam) as (client, adapter, headers, registry, user, device):
        first = await client.post('/v1/runs', headers=headers, json=request_body())
        run = (await first.json())['run_id']
        changed = {**request_body(), 'input': 'A different project'}
        assert (await client.post('/v1/runs', headers=headers, json=changed)).status == 409
        principal = registry.authenticate(headers['Authorization'].removeprefix('Bearer '))
        registry.revoke_device(principal, device)
        await asyncio.wait_for(asyncio.gather(*list(adapter._background_tasks)), 2)
        assert adapter._run_statuses[run]['status'] == 'cancelled'
        assert 'artifact' not in adapter._run_statuses[run]
        assert adapter._run_statuses[run]['reports'][-1]['stage'] == 'cancelled'

@pytest.mark.asyncio
async def test_complete_document_emits_report_and_delivers_only_to_owner_device(tmp_path):
    class DocumentTeam:
        def __init__(self, progress, **kwargs): self.progress = progress
        def run(self, *args):
            self.progress(stage='designing', role='designer', worker_id='designer', worker_state='running',
                          message='', report='Design chosen', calls=2)
            return {'document': {'kind': 'docx', 'args': {'title': 'Public example', 'sections': [
                {'heading': 'Result', 'body': 'A complete paragraph.', 'bullets': []}]}},
                'files': [{'path': 'content.json', 'content': '{}'}],
                'review': {'status': 'passed', 'visual_review': 'not_checked'}}
    async with runtime_client(tmp_path, DocumentTeam) as (client, adapter, headers, _, user, device):
        created = await client.post('/v1/runs', headers=headers, json=request_body())
        run = (await created.json())['run_id']
        await asyncio.gather(*list(adapter._background_tasks))
        snapshot = adapter._run_statuses[run]
        assert snapshot['status'] == 'completed' and snapshot['execution'] == 'not_run'
        assert snapshot['reports'][-1]['stage'] == 'completed'
        assert snapshot['workers'][0]['status'] == 'completed'
        events = []
        while not adapter._run_streams[run].empty():
            events.append(adapter._run_streams[run].get_nowait())
        assert events[-2]['event'] == 'run.completed' and events[-1] is None
        from troika_product.device_delivery import device_deliveries
        delivery = device_deliveries.get(snapshot['artifact']['id'], user, device)
        assert delivery is not None and delivery.data.startswith(b'PK')
        assert device_deliveries.get(snapshot['artifact']['id'], user, 'another-device') is None
@pytest.mark.asyncio
async def test_foreground_can_use_fifth_slot_but_not_a_sixth(tmp_path):
    from troika_product.development_runtime import check_foreground_capacity
    async with runtime_client(tmp_path, HoldingTeam) as (client, adapter, headers, registry, user, device):
        principal = registry.authenticate(headers['Authorization'].removeprefix('Bearer '))
        request = {'principal': principal}
        for i in range(4):
            adapter._run_statuses[str(i)] = {'status': 'running', 'workflow': 'development'}
            adapter._run_owners[str(i)] = (user, device)
        assert check_foreground_capacity(adapter, request) is None
        adapter._run_statuses['chat'] = {'status': 'running'}
        adapter._run_owners['chat'] = (user, device)
        assert check_foreground_capacity(adapter, request).status == 429
        adapter._run_statuses['chat']['status'] = 'completed'
        assert check_foreground_capacity(adapter, request) is None

@pytest.mark.asyncio
async def test_private_provider_failure_preserves_safe_code_without_leaking_exception(tmp_path):
    from agent.provider_metering import ProviderCallBlocked
    class FailedTeam:
        def __init__(self, **kwargs): pass
        def run(self, *args):
            raise ProviderCallBlocked('resource_byok_request_failed', 'secret-provider-key-must-not-leak')
    async with runtime_client(tmp_path, FailedTeam) as (client, adapter, headers, *_):
        reply = await client.post('/v1/runs', headers=headers, json=request_body())
        run = (await reply.json())['run_id']
        await asyncio.gather(*list(adapter._background_tasks))
        snapshot = adapter._run_statuses[run]
        assert snapshot['status'] == 'failed'
        assert snapshot['error']['code'] == 'resource_byok_request_failed'
        assert 'secret-provider-key' not in str(snapshot)
        assert snapshot['reports'][-1]['stage'] == 'failed'
        assert snapshot.get('artifact') is None
