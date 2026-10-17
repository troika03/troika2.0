import asyncio
import json
import threading
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.streaming import GuardedTextStream


@pytest.mark.parametrize('message,social,configured,expected', [
    ('Привет!', True, {'effort': 'medium'}, {'enabled': False}),
    ('Привет, создай сайт', False, {'effort': 'medium'}, {'effort': 'medium'}),
    ('Объясни устройство велосипеда', False, None, {'effort': 'low'}),
])
def test_social_turns_skip_reasoning_and_explicit_work_settings_are_preserved(tmp_path, monkeypatch, message, social, configured, expected):
    from gateway import run as runtime
    from hermes_cli import tools_config
    import run_agent

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        'product_auth_enabled': True, 'product_auth_db': str(tmp_path/'access.db'),
    }))
    captured = {}
    monkeypatch.setattr(runtime, '_resolve_runtime_agent_kwargs', lambda: {})
    monkeypatch.setattr(runtime, '_resolve_gateway_model', lambda: 'openrouter/free')
    monkeypatch.setattr(runtime, '_load_gateway_config', lambda: {})
    monkeypatch.setattr(runtime.GatewayRunner, '_load_reasoning_config', lambda: configured)
    monkeypatch.setattr(runtime.GatewayRunner, '_load_fallback_model', lambda: None)
    monkeypatch.setattr(tools_config, '_get_platform_tools', lambda *args: [])
    monkeypatch.setattr(adapter, '_ensure_session_db', lambda: None)

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(run_agent, 'AIAgent', create)
    adapter._create_agent(current_user_message=message)
    assert captured['reasoning_config'] == expected
    assert bool(captured['enabled_toolsets']) is (not social)


def test_first_phrase_arrives_before_checked_final_and_is_not_repeated():
    heard = []
    stream = GuardedTextStream(heard.append, 'Поговорим')
    stream.feed('[emo:joy] Привет! ')
    assert heard == ['[emo:joy] Привет!']
    stream.feed('Как ты?')
    stream.finish_result({'final_response': '[emo:joy] Привет! Как ты?', 'completed': True})
    assert ''.join(heard) == '[emo:joy] Привет! Как ты?'


@pytest.mark.parametrize('draft', [
    'Готово!', 'Документ создан. ', 'Файл сохранён на телефоне. ',
    'Напоминание установлено. ', 'Сообщение отправлено. ',
    'Я проверила сайт. ', 'All files created. ',
])
def test_action_claims_wait_for_the_existing_final_guard(draft):
    heard = []
    stream = GuardedTextStream(heard.append, 'Сделай просьбу')
    for char in draft:
        stream.feed(char)
    assert heard == []
    stream.finish_result({'final_response': 'Не удалось подтвердить действие.'})
    assert heard == ['Не удалось подтвердить действие.']


def test_split_claim_and_failed_result_never_escape():
    heard = []
    stream = GuardedTextStream(heard.append, 'Создай файл')
    stream.feed('Привет! Файл со')
    stream.feed('хранён. Следующая фраза!')
    assert heard == ['Привет!']
    stream.finish_result({'final_response': 'Файл сохранён.', 'failed': True})
    stream.feed('Ещё текст!')
    assert heard == ['Привет!']


def test_buffered_provider_and_canonical_correction_are_delivered_once():
    heard = []
    stream = GuardedTextStream(heard.append, 'Разговор')
    stream.feed('Привет! Файл создан. ')
    stream.finish_result({'final_response': 'Не удалось подтвердить просьбу.'})
    stream.finish_result({'final_response': 'Не удалось подтвердить просьбу.'})
    assert ''.join(heard) == 'Привет!\nНе удалось подтвердить просьбу.'
    heard.clear()
    stream = GuardedTextStream(heard.append, 'Разговор')
    stream.finish_result({'final_response': 'Ответ без дельт.'})
    assert heard == ['Ответ без дельт.']


def test_decimal_and_bounded_unfinished_text():
    heard = []
    stream = GuardedTextStream(heard.append, 'Объясни')
    stream.feed('Число 3.')
    assert heard == []
    stream.feed('14. Следующая часть')
    assert heard == ['Число 3.14.']
    stream.feed('x' * 5000)
    assert stream.pending == '' and stream.blocked
    stream.finish_result({'final_response': 'Число 3.14. Короткий итог.'})
    assert ''.join(heard) == 'Число 3.14. Короткий итог.'


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['chat', 'runs'])
async def test_authenticated_http_stream_delivers_phrase_while_agent_is_blocked(tmp_path, monkeypatch, endpoint):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        'product_auth_enabled': True, 'product_auth_db': str(tmp_path/'access.db'),
        'product_artifact_root': str(tmp_path/'artifacts'),
        'product_workspace_root': str(tmp_path/'workspaces'),
        'product_quotas_enabled': False,
    }))
    registry = adapter._access_registry
    user = registry.create_user('stream@example.com')
    token = registry.issue_device_token(registry.create_device(user, name='Phone', platform='android'))
    release = threading.Event()

    def create(**options):
        callback = options['stream_delta_callback']
        assert callback is not None

        def run(**kwargs):
            callback('Привет! ')
            assert release.wait(5), 'HTTP consumer did not receive early text'
            callback('Файл сохранён. ')
            return {'final_response': 'Привет! Не удалось подтвердить действие.', 'completed': True}

        return SimpleNamespace(run_conversation=run)

    monkeypatch.setattr(adapter, '_create_agent', create)
    app = web.Application()
    app.router.add_post('/v1/chat/completions', adapter._handle_chat_completions)
    app.router.add_post('/v1/runs', adapter._handle_runs)
    app.router.add_get('/v1/runs/{run_id}/events', adapter._handle_run_events)
    headers = {'Authorization': 'Bearer '+token}
    received = []

    async def next_text(response):
        while True:
            line = await response.content.readline()
            if not line: return None
            if not line.startswith(b'data:'): continue
            data = line[5:].strip()
            if data == b'[DONE]': return None
            payload = json.loads(data)
            if endpoint == 'chat':
                text = (payload.get('choices') or [{}])[0].get('delta', {}).get('content')
            else:
                if payload.get('event') in {'run.completed', 'run.failed'}: return None
                text = payload.get('delta') if payload.get('event') == 'message.delta' else None
            if text: return text

    async with TestClient(TestServer(app)) as client:
        try:
            if endpoint == 'chat':
                response = await client.post('/v1/chat/completions', headers=headers, json={
                    'messages': [{'role': 'user', 'content': 'Привет!'}], 'stream': True,
                })
            else:
                started = await client.post('/v1/runs', headers=headers, json={'input': 'Привет!'})
                assert started.status == 202
                run_id = (await started.json())['run_id']
                response = await client.get('/v1/runs/'+run_id+'/events', headers=headers)
            assert response.status == 200
            first = await asyncio.wait_for(next_text(response), 2)
            assert first == 'Привет!'
            assert not release.is_set()
            received.append(first)
            release.set()
            while text := await asyncio.wait_for(next_text(response), 3):
                received.append(text)
            assert ''.join(received) == 'Привет! Не удалось подтвердить действие.'
            assert 'Файл сохранён' not in ''.join(received)
        finally:
            release.set()
