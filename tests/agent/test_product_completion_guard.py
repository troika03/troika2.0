"""Exercise the actual conversation loop with fabricated model completions."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gateway.session_context import clear_session_override, set_session_override
from run_agent import AIAgent


def response(text="", calls=None):
    message = SimpleNamespace(
        content=text, tool_calls=calls, reasoning=None, reasoning_content=None,
        reasoning_details=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if calls else "stop")],
        model="test/model", usage=None,
    )


def call(action="task_add", title="Проверить релиз"):
    return SimpleNamespace(
        id="call_1", type="function",
        function=SimpleNamespace(
            name="troika_assistant", arguments=json.dumps({"action": action, "title": title}),
        ),
    )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    definitions = [{"type": "function", "function": {
        "name": "troika_assistant", "description": "Private tasks",
        "parameters": {"type": "object", "properties": {}},
    }}]
    set_session_override("TROIKA_PRODUCT_MODE", "1")
    try:
        with (
            patch("run_agent.get_tool_definitions", return_value=definitions),
            patch("run_agent.check_toolset_requirements", return_value={}),
            patch("run_agent.OpenAI"),
        ):
            result = AIAgent(
                api_key="test", provider="openrouter", base_url="https://openrouter.ai/api/v1",
                model="test/model", quiet_mode=True, skip_memory=True, skip_context_files=True,
                max_iterations=6,
            )
        result.client = MagicMock()
        result._cached_system_prompt = "Test system prompt"
        result._use_prompt_caching = False
        result.compression_enabled = False
        result.tool_delay = 0
        with (
            patch.object(result, "_persist_session") as persist,
            patch.object(result, "_save_trajectory"),
            patch.object(result, "_cleanup_task_resources"),
        ):
            yield result, persist
    finally:
        clear_session_override("TROIKA_PRODUCT_MODE")


def test_false_done_gets_one_retry_and_is_never_persisted(agent):
    instance, persist = agent
    instance.client.chat.completions.create.side_effect = [response("Готово!"), response("Готово!")]
    result = instance.run_conversation("Создай задачу")
    assert result["api_calls"] == 2
    assert "Не удалось подтвердить" in result["final_response"]
    assert all(m.get("content") != "Готово!" for m in result["messages"])
    persisted = persist.call_args.args[0]
    assert persisted[-1]["content"] == result["final_response"]
    assert sum(m.get("role") == "user" for m in persisted) == 1


def test_retry_can_execute_missing_action_and_return_true_result(agent):
    instance, _ = agent
    instance.client.chat.completions.create.side_effect = [
        response("Задача создана."), response(calls=[call()]), response("Готово, задача создана."),
    ]
    with patch("run_agent.handle_function_call", return_value=json.dumps({
        "ok": True, "action": "task_add", "result": {"id": "task_1", "title": "Проверить релиз"},
    })) as tool:
        result = instance.run_conversation("Создай задачу проверить релиз")
    assert result["final_response"] == "Готово, задача создана."
    tool.assert_called_once()


def test_failed_tool_cannot_be_summarized_as_done(agent):
    instance, _ = agent
    instance.client.chat.completions.create.side_effect = [
        response(calls=[call()]), response("Готово, задача создана."), response("Задача создана."),
    ]
    with patch("run_agent.handle_function_call", return_value='{"ok":false,"error":"permission_denied"}'):
        result = instance.run_conversation("Создай задачу")
    assert "Не удалось подтвердить" in result["final_response"]
    assert result["messages"][-1]["content"] == result["final_response"]


def test_previous_turn_receipts_cannot_validate_current_claim(agent):
    instance, _ = agent
    instance.client.chat.completions.create.side_effect = [response("Задача создана."), response("Задача создана.")]
    history = [
        {"role": "user", "content": "Создай первую задачу"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "old", "type": "function", "function": {
                "name": "troika_assistant", "arguments": '{"action":"task_add"}',
            },
        }]},
        {"role": "tool", "tool_call_id": "old", "content": json.dumps({
            "ok": True, "action": "task_add", "result": {"id": "old_task"},
        })},
        {"role": "assistant", "content": "Первая задача создана."},
    ]
    result = instance.run_conversation("Создай вторую задачу", conversation_history=history)
    assert "Не удалось подтвердить" in result["final_response"]


def test_normal_conversation_is_not_retried(agent):
    instance, _ = agent
    instance.client.chat.completions.create.return_value = response("Привет! Как день?")
    assert instance.run_conversation("Привет")["final_response"] == "Привет! Как день?"
    instance.client.chat.completions.create.assert_called_once()
