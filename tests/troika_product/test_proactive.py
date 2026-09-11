"""Tenant isolation and useful-proactivity rules."""

from datetime import datetime, timezone, timedelta

import pytest

from troika_product.access import AccessRegistry
from troika_product.notifications import NotificationPreferences
from troika_product.proactive import ProactiveStore


def _identity(registry, email):
    user_id = registry.create_user(email)
    device_id = registry.create_device(user_id, name="Phone", platform="android")
    token = registry.issue_device_token(device_id)
    return registry.authenticate(token)


def _setup(tmp_path):
    access = AccessRegistry(tmp_path / "access.db")
    first = _identity(access, "one@example.com")
    second = _identity(access, "two@example.com")
    assert first is not None and second is not None
    store = ProactiveStore(access.database_path)
    return access, store, first, second


def test_projects_notes_tasks_and_context_are_private(tmp_path):
    access, store, first, second = _setup(tmp_path)
    project = store.create_project(first, name="Мобильный запуск", summary="Версия beta")
    note = store.add_note(first, project_id=project.id, kind="decision", content="Оставить push выключенным")
    task = store.create_task(first, project_id=project.id, title="Проверить onboarding", details="Проверить новый экран разрешений", due_at="2026-09-12T10:00:00+03:00", idempotency_key="task-onboarding-v1")
    assert store.list_projects(second) == []
    with pytest.raises(LookupError):
        store.list_tasks(second, project_id=project.id)
    assert store.list_notes(first, project_id=project.id)[0]["id"] == note["id"]
    assert task.project_id == project.id
    context = store.assistant_context(first)
    assert "Мобильный запуск" in context
    assert "Проверить onboarding" in context
    assert "Оставить push выключенным" in context
    assert store.assistant_context(second) == ""


def test_task_and_message_writes_are_idempotent(tmp_path):
    _, store, first, _ = _setup(tmp_path)
    project = store.create_project(first, name="Research")
    first_task = store.create_task(first, project_id=project.id, title="Собрать источники", idempotency_key="same-task")
    second_task = store.create_task(first, project_id=project.id, title="Другое имя", idempotency_key="same-task")
    assert second_task.id == first_task.id
    message_id = store.enqueue_message(first, kind="reminder", category="reminder", title="Проверить источники", body="Вернись к задаче и проверь источники.", reason="Явное напоминание по проекту.", project_id=project.id, idempotency_key="same-message")
    assert store.enqueue_message(first, kind="reminder", category="reminder", title="Другой текст", body="Другой текст напоминания.", reason="Повтор той же операции.", project_id=project.id, idempotency_key="same-message") == message_id


def test_reminder_waits_for_opt_in_and_quiet_hours(tmp_path):
    access, store, first, _ = _setup(tmp_path)
    project = store.create_project(first, name="План")
    available_at = datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc)
    store.enqueue_message(first, kind="reminder", category="reminder", title="Проверить план", body="Проверь план проекта и выбери следующий шаг.", reason="Срок проверки плана.", project_id=project.id, available_at=available_at.isoformat(), idempotency_key="plan-reminder")
    assert store.list_inbox(first, now=available_at) == []
    access.set_notification_preferences(first, NotificationPreferences(reminders_enabled=True, quiet_hours_enabled=True, timezone="Europe/Moscow", quiet_start="21:00", quiet_end="08:00"))
    assert store.list_inbox(first, now=available_at) == []
    delivered = store.list_inbox(first, now=available_at + timedelta(hours=11))
    assert len(delivered) == 1
    assert delivered[0].reason == "Срок проверки плана."


def test_proactive_requires_concrete_context_and_caps_delivery(tmp_path):
    access, store, first, _ = _setup(tmp_path)
    project = store.create_project(first, name="Развитие")
    access.set_notification_preferences(first, NotificationPreferences(proactive_enabled=True))
    with pytest.raises(ValueError):
        store.enqueue_message(first, kind="proactive", category="progress_review", title="Привет", body="Как дела", reason="Проверка", idempotency_key="empty-social")
    with pytest.raises(ValueError):
        store.enqueue_message(first, kind="proactive", category="progress_review", title="Привет!", body="Как дела?", reason="Проверка проекта.", project_id=project.id, idempotency_key="punctuated-social")
    with pytest.raises(ValueError):
        store.enqueue_message(first, kind="proactive", category="progress_review", title="Проверить проект", body="Есть конкретный прогресс проекта.", reason="Проверка проекта.", project_id=project.id, requires_approval="false", idempotency_key="invalid-approval")
    now = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    for number in range(4):
        store.enqueue_message(first, kind="proactive", category="progress_review", title=f"Разбор проекта {number}", body=f"Проверь измеримый результат проекта {number}.", reason="Плановый обзор прогресса проекта.", project_id=project.id, available_at=now.isoformat(), idempotency_key=f"review-{number}")
    delivered = store.list_inbox(first, now=now)
    assert len(delivered) == 3
