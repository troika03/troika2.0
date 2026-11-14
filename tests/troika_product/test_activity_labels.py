"""The run status line names the kind of action, never its content."""

import asyncio
import json

import pytest

from troika_product.activity_labels import DEFAULT_LABEL, activity_label


@pytest.mark.parametrize("tool, expected", [
    ("web_search", "Ищу в интернете"),
    ("web_extract", "Читаю страницу"),
    ("phone_create_beautiful_pptx", "Готовлю презентацию"),
    ("phone_create_docx", "Готовлю документ"),
    ("troika_assistant", "Обновляю дела и заметки"),
    ("troika_tool_search", "Подбираю инструмент"),
    ("android_calendar_list_events", "Проверяю календарь"),
    ("code_review", "Проверяю результат"),
    ("unknown_private_tool", DEFAULT_LABEL),
    (None, DEFAULT_LABEL),
])
def test_known_tools_get_fixed_phrases(tool, expected):
    assert activity_label(tool) == expected


def test_routed_product_tool_is_unwrapped_without_echoing_arguments():
    from troika_product.capabilities import CALL_TOOL, TOOL_CAPABILITY

    routed = "web_search" if "web_search" in TOOL_CAPABILITY else next(iter(TOOL_CAPABILITY))
    label = activity_label(CALL_TOOL, {"tool": routed, "arguments": {"query": "секретный запрос"}})
    assert label == activity_label(routed)
    assert "секретный" not in label


@pytest.mark.asyncio
async def test_product_run_event_carries_label_but_hides_tool_and_args():
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    adapter._run_streams["label-test"] = asyncio.Queue()
    callback = adapter._make_run_event_callback("label-test", asyncio.get_running_loop(), product_mode=True)
    callback("tool.started", "web_search", preview="личный запрос", args={"query": "личный запрос"})
    await asyncio.sleep(0)
    event = await adapter._run_streams["label-test"].get()
    assert event["tool"] == "action"
    assert event["label"] == "Ищу в интернете"
    assert "личный" not in json.dumps(event, ensure_ascii=False)
