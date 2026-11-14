"""Account history: owner-scoped listing, rename/delete and compression lineage."""

import asyncio
import json
import time

import pytest

from hermes_state import SessionDB
from troika_product.access import AccessRegistry
from troika_product.conversation_sessions import ConversationSessions
from troika_product.memory import MemoryStore


def _principal(registry, email, platform="android"):
    user = registry.create_user(email)
    device = registry.create_device(user, name=platform, platform=platform)
    token = registry.issue_device_token(device)
    return registry.authenticate(token), token


@pytest.fixture
def world(tmp_path):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    registry = AccessRegistry(tmp_path / "accounts.db")
    owner, owner_token = _principal(registry, "owner@example.com")
    foreign, foreign_token = _principal(registry, "foreign@example.com")
    db = SessionDB(tmp_path / "state.db")
    home = registry.account_home_session_id(owner)
    assert registry.claim_session(owner, home)
    db.create_session(home, "api_server")
    db.append_message(home, "user", "Запомни проект REF-1")
    db.append_message(home, "assistant", "Готово")
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(registry.database_path),
    }))
    adapter._session_db = db
    adapter._product_sessions_dir = tmp_path / "sessions"
    yield adapter, registry, db, owner, owner_token, foreign, foreign_token, home
    db.close()


def _call(adapter, handler, token, *, method="GET", session_id=None, body=None, query=None):
    class Request(dict):
        headers = {"Authorization": "Bearer " + token}
        match_info = {"session_id": session_id} if session_id else {}
        remote, transport = "127.0.0.1", None
        path_qs = "/v1/sessions" + (f"/{session_id}" if session_id else "")

        async def json(self):
            return body

    request = Request()
    request.method = method
    request.query = query or {}
    assert adapter._check_auth(request) is None
    response = asyncio.run(handler(request))
    return response.status, json.loads(response.body)


def _listing(adapter, token):
    status, payload = _call(adapter, adapter._handle_list_sessions, token)
    assert status == 200
    return payload["sessions"]


def test_listing_is_filtered_by_owner_before_paging(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    # Many newer conversations of another account used to fill the global
    # top-200 page and hide this owner's history entirely.
    for index in range(230):
        sid = f"foreign-{index}"
        assert registry.claim_session(foreign, sid)
        db.create_session(sid, "api_server")
        db.append_message(sid, "user", f"чужое {index}")
    items = _listing(adapter, owner_token)
    assert [item["id"] for item in items] == [home]
    assert all(not item["id"].startswith("foreign") for item in items)
    assert len(_listing(adapter, foreign_token)) == 50  # default page size


def test_rotated_segments_are_one_conversation_and_survive_restart(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    sessions = ConversationSessions(registry, db)
    segment, _, reason = sessions.resolve(owner, home, "Привет!")
    assert segment != home and reason == "conversation"
    db.create_session(segment, "api_server")
    db.append_message(segment, "user", "Привет!")
    db.append_message(segment, "assistant", "Здравствуйте")

    items = _listing(adapter, owner_token)
    assert len(items) == 1 and items[0]["id"] == home
    assert items[0]["message_count"] == 4
    assert items[0]["preview"].startswith("Запомни проект")

    # Opening either id returns the whole account timeline.
    status, payload = _call(adapter, adapter._handle_get_session_messages, owner_token, session_id=home)
    assert status == 200
    assert [m["content"] for m in payload["messages"]] == [
        "Запомни проект REF-1", "Готово", "Привет!", "Здравствуйте"]

    # A fresh store/adapter over the same databases sees the same history.
    restarted = ConversationSessions(registry, db)
    assert restarted.history(owner) == items
    assert restarted.tip(owner, home) == segment


def test_rename_is_owner_scoped_and_reversible(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    status, payload = _call(adapter, adapter._handle_session_item, owner_token,
                            method="PATCH", session_id=home, body={"title": "  Мой   проект "})
    assert status == 200 and payload == {"id": home, "title": "Мой проект"}
    assert _listing(adapter, owner_token)[0]["title"] == "Мой проект"

    status, _ = _call(adapter, adapter._handle_session_item, foreign_token,
                      method="PATCH", session_id=home, body={"title": "Взлом"})
    assert status == 404
    assert _listing(adapter, owner_token)[0]["title"] == "Мой проект"

    for bad in ({"title": "x" * 101}, {"title": 5}, {"name": "x"}, ["x"]):
        status, _ = _call(adapter, adapter._handle_session_item, owner_token,
                          method="PATCH", session_id=home, body=bad)
        assert status == 400

    status, payload = _call(adapter, adapter._handle_session_item, owner_token,
                            method="PATCH", session_id=home, body={"title": " "})
    assert status == 200 and payload["title"] is None
    assert _listing(adapter, owner_token)[0]["title"] is None
    export = registry.export_account_rows(owner)
    assert export["conversation_titles"] == []


def test_delete_removes_all_segments_but_keeps_memory_and_alias(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    memory = MemoryStore(registry.database_path)
    memory.create_memory(owner, title="Проект", content="REF-1 важен")
    sessions = ConversationSessions(registry, db)
    segment, _, _ = sessions.resolve(owner, home, "Привет!")
    db.create_session(segment, "api_server")
    db.append_message(segment, "user", "Привет!")
    other = "desktop-other"
    assert registry.claim_session(owner, other)
    db.create_session(other, "api_server")
    db.append_message(other, "user", "Другой разговор")

    status, _ = _call(adapter, adapter._handle_session_item, foreign_token,
                      method="DELETE", session_id=home)
    assert status == 404 and db.get_messages(home)

    status, payload = _call(adapter, adapter._handle_session_item, owner_token,
                            method="DELETE", session_id=segment)
    assert status == 200 and payload == {"id": home, "deleted": True}
    assert db.get_session(home) is None and db.get_session(segment) is None
    assert [item["id"] for item in _listing(adapter, owner_token)] == [other]
    # Memory is a separate account store and is not part of a conversation.
    assert "REF-1 важен" in memory.assistant_context(owner)
    # The stable alias still belongs to the owner and starts an empty chat.
    assert registry.session_belongs_to(owner, home)
    assert not registry.claim_session(foreign, home)
    effective, history, reason = sessions.resolve(owner, home, "Новый вопрос")
    assert effective == home and history == [] and reason is None


def _compress(db, parent, child, messages):
    db.end_session(parent, "compression")
    time.sleep(0.01)
    db.create_session(child, "api_server", parent_session_id=parent)
    for role, content in messages:
        db.append_message(child, role, content)


def test_compression_continuation_is_owned_listed_and_continued(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    child = "20261114_120000_abcdef"
    _compress(db, home, child, [("user", "[summary] REF-1"), ("user", "После сжатия"),
                                ("assistant", "Продолжаем")])

    # Before the fix another account could claim the unowned child id and
    # load its transcript as history for a new run.
    assert adapter._authorize_product_session(_Req(foreign_token, adapter), child, claim=True).status == 403

    items = _listing(adapter, owner_token)
    assert len(items) == 1 and items[0]["id"] == home
    assert registry.session_belongs_to(owner, child)
    status, payload = _call(adapter, adapter._handle_get_session_messages, owner_token, session_id=home)
    assert [m["content"] for m in payload["messages"]][-2:] == ["После сжатия", "Продолжаем"]

    # The next turn continues in the live continuation, not the ended parent.
    request = _Req(owner_token, adapter)
    effective, history = adapter._prepare_product_conversation(
        request, home, "Что дальше?", db.get_messages_as_conversation(home))
    assert effective == child
    assert [m["content"] for m in history][-1] == "Продолжаем"

    # Account deletion manifest includes the continuation.
    assert child in registry.prepare_account_deletion(owner).session_ids


def test_unowned_existing_transcript_cannot_be_claimed(world):
    adapter, registry, db, owner, owner_token, foreign, foreign_token, home = world
    db.create_session("telegram-private", "telegram")
    db.append_message("telegram-private", "user", "личное")
    response = adapter._authorize_product_session(_Req(owner_token, adapter), "telegram-private", claim=True)
    assert response.status == 403
    assert adapter._authorize_product_session(_Req(owner_token, adapter), "desktop-new", claim=True) is None


def _Req(token, adapter):
    class Request(dict):
        headers = {"Authorization": "Bearer " + token}
        match_info = {}
        remote, transport, method, path_qs = "127.0.0.1", None, "POST", "/v1/runs"
    request = Request()
    assert adapter._check_auth(request) is None
    return request
