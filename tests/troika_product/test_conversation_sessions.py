"""Conversation boundaries preserve originals without reauthorizing old work."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.provider_metering import provider_metering_scope
from hermes_state import SessionDB
from troika_product.access import AccessRegistry
from troika_product.conversation_sessions import ConversationSessions, conversation_only
from troika_product.working_context import WorkingContext


@pytest.fixture
def conversation(tmp_path):
    registry = AccessRegistry(tmp_path / "accounts.db")
    user = registry.create_user("conversation@example.com")
    device = registry.create_device(user, name="Phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    session_id = registry.account_home_session_id(principal)
    assert registry.claim_session(principal, session_id)
    db = SessionDB(tmp_path / "state.db")
    db.create_session(session_id, "api_server")
    db.append_message(session_id, "user", "Create the old project with reference REF-287.")
    db.append_message(session_id, "assistant", "The old project was delivered.")
    sessions = ConversationSessions(registry, db)
    yield registry, principal, db, sessions, session_id
    db.close()


@pytest.mark.parametrize("text", ["Привет!", "Тройка, привет", "Как дела?", "Спасибо", "hello"])
def test_complete_social_utterance_is_conversation_only(text):
    assert conversation_only(text)


@pytest.mark.parametrize("text", ["Привет, создай сайт", "продолжи", "Спасибо, продолжай писать код", "hello, create a file", [{"type": "text", "text": "Привет"}]])
def test_action_is_never_misclassified_as_social(text):
    assert not conversation_only(text)


def test_greeting_rotates_and_client_replay_cannot_revive_old_request(conversation):
    registry, principal, db, sessions, home = conversation
    original = db.get_messages(home)
    effective, history, reason = sessions.resolve(
        principal, home, "Привет!", db.get_messages_as_conversation(home)
    )
    assert effective != home and history == [] and reason == "conversation"
    assert registry.session_belongs_to(principal, effective)
    assert db.get_messages(home) == original
    db.create_session(effective, "api_server")
    db.append_message(effective, "user", "Привет!")
    db.append_message(effective, "assistant", "Привет.")
    # The old phone and another device can keep using the stable home alias.
    second, history, reason = sessions.resolve(principal, home, "Какой сегодня день?")
    assert second != effective and reason == "new_request"
    assert history == []
    assert [m["content"] for m in sessions.timeline(principal, home)] == [
        m["content"] for m in original
    ] + ["Привет!", "Привет."]
    assert sessions.timeline(principal, effective) == sessions.timeline(principal, home)


def test_idle_and_size_boundaries_are_durable(conversation):
    registry, principal, db, sessions, home = conversation
    now = max(m["timestamp"] for m in db.get_messages(home))
    effective, history, reason = sessions.resolve(principal, home, "Новый вопрос", now=now + 1801)
    assert effective != home and not history and reason == "idle"
    # Resolving through an old alias after a server restart still reaches the tip.
    restarted = ConversationSessions(registry, db)
    tip, _, _ = restarted.resolve(principal, home, "Второй вопрос", now=now + 1802)
    assert tip == effective
    restarted.max_turns = 2
    next_tip, history, reason = restarted.resolve(principal, home, "Третий вопрос", now=now + 1803)
    assert next_tip != tip and not history and reason == "context_limit"


def test_concurrent_devices_share_one_active_segment(conversation):
    registry, principal, db, sessions, home = conversation
    first, _, _ = sessions.resolve(principal, home, "Привет")
    device = registry.create_device(principal.user_id, name="PC", platform="windows")
    pc = registry.authenticate(registry.issue_device_token(device))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda p: sessions.resolve(p, home, "Новый вопрос"), [principal, pc]))
    assert {r[0] for r in results} == {first}


def test_archive_is_retrievable_but_not_in_new_prompt(conversation):
    registry, principal, db, sessions, home = conversation
    effective, _, _ = sessions.resolve(principal, home, "Привет")
    guard = SimpleNamespace(principal=principal, stopped=False, ledger=SimpleNamespace(registry=registry))
    context = WorkingContext(guard, enabled=True)
    context.archive_messages = sessions.archive(principal, effective)
    payload = {"messages": [{"role": "user", "content": "Что было в прошлом проекте?"}], "tools": [
        {"function": {"name": "troika_tool_search"}}, {"function": {"name": "troika_tool_call"}}]}
    with provider_metering_scope(guard):
        prepared = context.prepare(payload, client=SimpleNamespace())
        assert "REF-287" not in str(prepared)
        match = context.retrieve({"action": "history_search", "query": "REF-287"})["matches"][0]
        assert "REF-287" in context.retrieve({"action": "history_read", "index": match["index"]})["text"]
        assert len(context.retrieve({"action": "history_recent"})["matches"]) == 3
        registry.revoke_device(principal, principal.device_id)
        with pytest.raises(PermissionError):
            context.retrieve({"action": "history_read", "index": 1})


def test_foreign_account_cannot_resolve_or_read_channel(conversation):
    registry, principal, db, sessions, home = conversation
    user = registry.create_user("foreign@example.com")
    device = registry.create_device(user, name="Foreign", platform="android")
    foreign = registry.authenticate(registry.issue_device_token(device))
    for read in [lambda: sessions.resolve(foreign, home, "Привет"),
                 lambda: sessions.archive(foreign, home), lambda: sessions.timeline(foreign, home)]:
        with pytest.raises(PermissionError):
            read()


def test_account_deletion_removes_segment_metadata(conversation):
    registry, principal, db, sessions, home = conversation
    effective, _, _ = sessions.resolve(principal, home, "Привет")
    manifest = registry.prepare_account_deletion(principal)
    assert effective in manifest.session_ids and home in manifest.session_ids
    registry.finalize_account_deletion(principal.user_id)
    with registry._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM troika_conversation_segments").fetchone()[0] == 0


def test_product_gateway_routes_old_alias_and_returns_complete_timeline(conversation):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    registry, principal, db, sessions, home = conversation
    token = registry.issue_device_token(principal.device_id)
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(registry.database_path),
        "product_resource_enabled": True, "product_compact_context_enabled": True,
    }))
    adapter._session_db = db
    class Request(dict):
        headers = {"Authorization": "Bearer " + token}
        match_info = {"session_id": home}
        remote, transport, method, path_qs = "127.0.0.1", None, "GET", "/v1/sessions/" + home + "/messages"
    request = Request()
    assert adapter._check_auth(request) is None
    effective, history = adapter._prepare_product_conversation(
        request, home, "Привет", db.get_messages_as_conversation(home)
    )
    assert effective != home and not history
    db.create_session(effective, "api_server")
    db.append_message(effective, "user", "Привет")
    db.append_message(effective, "assistant", "Привет.")
    response = asyncio.run(adapter._handle_get_session_messages(request))
    assert response.status == 200
    assert [m["content"] for m in json.loads(response.body)["messages"]] == [
        "Create the old project with reference REF-287.", "The old project was delivered.", "Привет", "Привет."
    ]


def test_real_product_agent_has_no_tools_on_greeting(conversation):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from model_tools import get_tool_definitions

    registry, principal, db, sessions, home = conversation
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(registry.database_path),
    }))
    adapter._session_db = db
    with patch("gateway.run._resolve_runtime_agent_kwargs", return_value={"api_key": "fixture"}), \
         patch("gateway.run._resolve_gateway_model", return_value="fixture/model"), \
         patch("gateway.run._load_gateway_config", return_value={}), \
         patch("run_agent.AIAgent", return_value=MagicMock()) as create:
        adapter._create_agent(session_id=home, current_user_message="Привет")
        assert create.call_args.kwargs["enabled_toolsets"] == []
        assert get_tool_definitions(enabled_toolsets=[], quiet_mode=True) == []
        adapter._create_agent(session_id=home, current_user_message="Привет, создай сайт")
        assert create.call_args.kwargs["enabled_toolsets"]
