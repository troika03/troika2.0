"""Owner isolation and lifecycle checks for Troika account memory."""

import pytest

from troika_product import memory as memory_module
from troika_product.access import AccessRegistry
from troika_product.memory import MemoryStore


def _identity(registry: AccessRegistry, email: str):
    user_id = registry.create_user(email)
    device_id = registry.create_device(user_id, name="Phone", platform="android")
    token = registry.issue_device_token(device_id)
    principal = registry.authenticate(token)
    assert principal is not None
    return token, principal


def test_memory_crud_and_prompt_context_are_owner_scoped(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    _, first = _identity(registry, "one@example.com")
    _, second = _identity(registry, "two@example.com")
    store = MemoryStore(registry.database_path)

    first_memory = store.create_memory(
        first,
        kind="preference",
        title="Формат ответов",
        content="Предпочитаю короткие ответы на русском языке.",
        idempotency_key="memory-format-v1",
    )
    repeated = store.create_memory(
        first,
        kind="fact",
        title="Другой заголовок",
        content="Другой текст",
        idempotency_key="memory-format-v1",
    )
    second_memory = store.create_memory(
        second,
        title="SECOND USER PRIVATE MEMORY",
        content="SECOND USER SECRET CONTEXT",
    )

    assert repeated.id == first_memory.id
    assert [item.id for item in store.list_memories(first)] == [first_memory.id]
    assert [item.id for item in store.list_memories(second)] == [second_memory.id]

    with pytest.raises(LookupError):
        store.update_memory(second, first_memory.id, title="Чужая правка")
    with pytest.raises(LookupError):
        store.delete_memory(second, first_memory.id)

    updated = store.update_memory(
        first,
        first_memory.id,
        kind="instruction",
        title="Стиль общения",
        content="Отвечай кратко и по-русски.",
    )
    context = store.assistant_context(first)
    assert updated.kind == "instruction"
    assert "Стиль общения" in context
    assert "SECOND USER PRIVATE MEMORY" not in context
    assert "SECOND USER SECRET CONTEXT" not in context

    deleted = store.delete_memory(first, first_memory.id)
    assert deleted.id == first_memory.id
    assert store.list_memories(first) == []
    assert store.assistant_context(first) == ""


def test_revoked_token_cannot_read_memory(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    token, principal = _identity(registry, "owner@example.com")
    store = MemoryStore(registry.database_path)
    store.create_memory(principal, title="Город", content="Живу в Казани.")

    assert registry.revoke_token(token) is True
    with pytest.raises(PermissionError):
        store.list_memories(principal)


def test_memory_count_is_bounded_per_owner(tmp_path, monkeypatch) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    _, principal = _identity(registry, "owner@example.com")
    store = MemoryStore(registry.database_path)
    monkeypatch.setattr(memory_module, "MAX_MEMORIES_PER_USER", 1)

    store.create_memory(principal, title="Первая", content="Первая запись")
    with pytest.raises(ValueError, match="memory limit reached"):
        store.create_memory(principal, title="Вторая", content="Вторая запись")
