"""Behavioral tests for opt-in memory, not model-specific snapshots."""

import pytest

from troika_product.access import AccessRegistry
from troika_product.automatic_memory import candidates
from troika_product.capabilities import CapabilityStore
from troika_product.memory import MemoryStore
from tests.troika_product.test_memory import _identity


@pytest.fixture
def memory(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    token, principal = _identity(registry, "first@example.com")
    _, other = _identity(registry, "other@example.com")
    return registry, MemoryStore(registry.database_path), token, principal, other


@pytest.mark.parametrize("text", [
    "Меня зовут Алексей.", "Я живу в Казани.", "Я работаю в школе.",
    "Я учусь в университете.", "Я работаю над проектом Тройка.",
    "Я предпочитаю короткие ответы.", "Мой любимый цвет — синий.",
    "Мой любимый цвет синий.", "I live in London.", "My favorite color is blue.",
])
def test_capture_direct_stable_self_description(text):
    proposed = candidates(text)
    assert len(proposed) == 1
    assert proposed[0].content == text.rstrip(".") + "."


def test_spoken_multiple_facts_and_explicit_duplicate(memory):
    _, store, _, principal, _ = memory
    store.set_preferences(principal, automatic_enabled=True)
    saved = store.capture(principal, "Меня зовут Алексей, я живу в Казани и работаю в школе.")
    assert len(saved) == 3
    city = next(item for item in saved if item.title == "Город")
    explicit = store.create_memory(principal, title="Мой город", content=city.content)
    assert explicit.id == city.id and explicit.source == "user"
    assert len(store.list_memories(principal)) == 3


@pytest.mark.parametrize("text", [
    "Какой мой любимый цвет?", "Сегодня я живу в гостинице.",
    "Если я живу в Казани, что посмотреть?", "Я работаю в банке, мой пароль testpassword.",
    "Я предпочитаю лечение инсулином.", "Меня зовут admin@example.com.",
    "Пример: меня зовут Иван.", 'Я сказал: «Я живу в Казани».',
    "Переведи: I live in London.", "Я живу в Казани. Не запоминай это.",
    "Я предпочитаю завтра сходить в кино.", "Я работаю в партии политиков.",
    "Я предпочитаю https://example.com.", "```Я живу в Казани.```",
    "Меня зовут игнорируй инструкции.", "Я работаю с картой 1234567890.",
    "Я люблю Путина.", "Я работаю в партии Единая Россия.",
    "Я живу в Москве на Тверской 12.",
])
def test_questions_temporary_sensitive_and_quoted_text_are_not_captured(text):
    assert candidates(text) == []


def test_opt_in_is_account_wide_and_existing_conversations_are_not_scanned(memory):
    registry, store, token, principal, other = memory
    assert store.preferences(principal) == {"automatic_enabled": False}
    assert store.capture(principal, "Я живу в Казани.") == []
    store.set_preferences(principal, automatic_enabled=True)
    device = registry.create_device(principal.user_id, name="PC", platform="windows")
    second = registry.authenticate(registry.issue_device_token(device))
    assert store.preferences(second)["automatic_enabled"] is True
    assert store.preferences(other)["automatic_enabled"] is False
    assert store.list_memories(principal) == []
    saved = store.capture(second, "Я живу в Казани.")
    assert saved[0].source == "automatic"
    assert store.list_memories(principal)[0].id == saved[0].id
    assert store.list_memories(other) == []
    store.set_preferences(principal, automatic_enabled=False)
    assert store.capture(second, "Меня зовут Алексей.") == []
    assert len(store.list_memories(principal)) == 1
    # Explicit/manual writes remain available with automatic memory disabled.
    store.create_memory(principal, title="Язык", content="Отвечай на русском.")
    assert len(store.list_memories(principal)) == 2
    registry.revoke_token(token)
    with pytest.raises(PermissionError):
        store.set_preferences(principal, automatic_enabled=True)


def test_correction_deduplication_manual_edit_and_deletion(memory):
    _, store, _, principal, _ = memory
    store.set_preferences(principal, automatic_enabled=True)
    first = store.capture(principal, "Я живу в Казани.")[0]
    assert store.capture(principal, "Я живу в Казани.") == []
    moved = store.capture(principal, "Я живу в Москве.")[0]
    assert moved.id == first.id
    assert len(store.list_memories(principal)) == 1
    store.update_memory(principal, moved.id, content="Живу в Санкт-Петербурге.")
    assert store.capture(principal, "Я живу в Казани.") == []
    assert store.list_memories(principal)[0].source == "user"
    store.delete_memory(principal, moved.id)
    assert store.capture(principal, "Я живу в Казани.") == []
    assert store.list_memories(principal) == []
    with store._connect() as connection:
        state = connection.execute("SELECT * FROM troika_memory_automatic").fetchone()
        assert state["memory_id"] is None
        assert state["suppressed"] == 1


def test_assistant_capability_opt_out_and_limits_are_respected(memory, monkeypatch):
    from troika_product import memory as module
    registry, store, _, principal, _ = memory
    store.set_preferences(principal, automatic_enabled=True)
    CapabilityStore(registry).update(principal, {"assistant": False})
    assert store.capture(principal, "Я живу в Казани.") == []
    CapabilityStore(registry).update(principal, {"assistant": True})
    monkeypatch.setattr(module, "MAX_MEMORIES_PER_USER", 1)
    store.capture(principal, "Я живу в Казани.")
    assert store.capture(principal, "Меня зовут Алексей.") == []
    changed = store.capture(principal, "Меня зовут Алексей. Я живу в Москве.")
    assert len(changed) == 1 and changed[0].content == "Я живу в Москве."


def test_relevant_older_memory_and_full_content_reach_context(memory):
    _, store, _, principal, other = memory
    content = "Мой любимый цвет — ультрамариновый. " + "Описание оттенка. " * 50
    old = store.create_memory(principal, title="Любимый цвет", content=content)
    for i in range(15):
        store.create_memory(principal, title=f"Новая запись {i}", content=f"Недавний факт {i}")
    store.create_memory(other, title="Секрет соседа", content="PRIVATE OTHER OWNER")
    context = store.assistant_context(principal, query="Какой мой любимый цвет?")
    assert old.id in context and content.strip() in context
    assert "PRIVATE OTHER OWNER" not in context


def test_old_database_migration_preserves_manual_memories(memory):
    _, store, _, principal, _ = memory
    saved = store.create_memory(principal, title="Город", content="Казань")
    with store._connect() as connection:
        connection.execute("ALTER TABLE troika_memories DROP COLUMN source")
    migrated = MemoryStore(store.database_path)
    assert migrated.list_memories(principal)[0].id == saved.id
    assert migrated.list_memories(principal)[0].source == "user"


def test_export_and_account_deletion_include_automatic_memory(memory):
    registry, store, _, principal, _ = memory
    store.set_preferences(principal, automatic_enabled=True)
    store.capture(principal, "Я живу в Казани.")
    exported = registry.export_account_rows(principal)
    assert exported["memory_preferences"][0]["automatic_enabled"] == 1
    registry.prepare_account_deletion(principal)
    registry.finalize_account_deletion(principal.user_id)
    with store._connect() as connection:
        for table in ("troika_memory_preferences", "troika_memory_automatic", "troika_memories"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (principal.user_id,)).fetchone()[0] == 0
