import asyncio
import json

import pytest

from troika_product.web_sources import web_source_activity
from troika_product.web_sources import session_source_metadata


def test_source_history_survives_reload_and_does_not_cross_turns():
    rows = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "web_search"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"data": {"web": [{"url": "https://example.com/a"}]}})},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "unrelated question"},
        {"role": "assistant", "content": "unrelated answer"},
    ]
    metadata = session_source_metadata(rows)
    assert list(metadata) == [3]
    assert metadata[3]["sources"][0]["url"] == "https://example.com/a"


def test_real_runtime_envelopes_preserve_sources_and_failed_read_attempts():
    from agent.tool_dispatch_helpers import _maybe_wrap_untrusted

    search = json.dumps({'data': {'web': [{'url': 'https://example.com/a', 'title': 'Example', 'description': 'x' * 300}]}})
    error = json.dumps({'error': 'Page reading unavailable ' + 'x' * 300})
    rows = [
        {'role': 'user', 'content': 'question'},
        {'role': 'tool', 'tool_name': 'web_search', 'content': _maybe_wrap_untrusted('web_search', search)},
        {'role': 'assistant', 'tool_calls': [{'id': 'read', 'function': {'name': 'web_extract', 'arguments': json.dumps({'urls': ['https://example.com/a']})}}]},
        {'role': 'tool', 'tool_name': 'web_extract', 'tool_call_id': 'read', 'content': _maybe_wrap_untrusted('web_extract', error)},
        {'role': 'assistant', 'content': 'answer'},
    ]
    metadata = session_source_metadata(rows)
    assert metadata[4]['sources'] == [{'url': 'https://example.com/a', 'title': '', 'status': 'failed'}]
    assert 'xxx' not in json.dumps(metadata)


def test_search_sources_are_found_not_read_and_do_not_expose_content():
    event = web_source_activity("web_search", result={"success": True, "data": {"web": [
        {"url": "https://example.com/a", "title": "Example", "description": "private snippet"},
        {"url": "https://example.com/a#fragment", "title": "Duplicate"},
    ]}})
    assert event == {"phase": "found", "sources": [
        {"url": "https://example.com/a", "title": "Example", "status": "found"}
    ]}


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///private", "https://u:secret@example.com", "http://127.0.0.1/a", "http://[::1]/", "https://localhost/", "http://169.254.169.254/", "https://printer.local/"])
def test_untrusted_links_are_not_sent_to_client(url):
    event = web_source_activity("web_search", result={"data": {"web": [{"url": url}]}})
    assert event["sources"] == []


def test_extract_start_is_only_opening_and_mixed_completion_is_truthful():
    args = {"urls": ["https://example.com/a", "https://example.com/b"]}
    started = web_source_activity("web_extract", args=args, started=True)
    assert {s["status"] for s in started["sources"]} == {"opening"}
    done = web_source_activity("web_extract", result={"results": [
        {"url": args["urls"][0], "content": "private page"},
        {"url": args["urls"][1], "error": "private failure"},
    ]})
    assert [s["status"] for s in done["sources"]] == ["read", "failed"]
    assert "private" not in json.dumps(done)


def test_failed_extract_marks_attempted_sources_failed():
    event = web_source_activity("web_extract", args={"urls": ["https://example.com"]}, result="bad json")
    assert event["phase"] == "failed"
    assert event["sources"][0]["status"] == "failed"
    assert web_source_activity("terminal", result="private output") is None


def test_sources_are_bounded_and_research_keeps_read_status():
    event = web_source_activity("web_research", result={"ok": True, "source_details": [
        {"url": f"https://example.com/{i}", "title": "x" * 500, "status": "read"}
        for i in range(100)
    ]})
    assert len(event["sources"]) == 20
    assert all(s["status"] == "read" and len(s["title"]) == 240 for s in event["sources"])


@pytest.mark.asyncio
async def test_authenticated_run_event_forwards_sources_without_raw_output():
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    adapter._run_streams["source-test"] = asyncio.Queue()
    callback = adapter._make_run_event_callback("source-test", asyncio.get_running_loop(), product_mode=True)
    callback("tool.completed", "web_search", result=json.dumps({"data": {"web": [
        {"url": "https://example.com", "title": "Example", "description": "private snippet"}
    ]}}))
    await asyncio.sleep(0)
    event = await adapter._run_streams["source-test"].get()
    assert event["tool"] == "action"
    assert event["web_activity"]["sources"][0]["status"] == "found"
    assert "private snippet" not in json.dumps(event)
