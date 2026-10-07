"""Bounded source metadata for the authenticated run event stream."""

import ipaddress
import json
from urllib.parse import urlsplit


def _source(url, title="", status="found"):
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return None
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        url = parsed._replace(fragment="").geturl()
    except ValueError:
        return None
    return {"url": url, "title": title[:240] if isinstance(title, str) else "", "status": status}


def web_source_activity(tool_name, *, args=None, result=None, started=False, is_error=False):
    """Describe found/opening/read sources without forwarding page contents."""
    if tool_name not in {"web_search", "web_extract", "web_research"}:
        return None
    if started:
        sources = []
        if tool_name == "web_extract" and isinstance(args, dict):
            urls = args.get("urls", [])
            if isinstance(urls, list):
                sources = [s for url in urls[:20] if (s := _source(url, status="opening"))]
        return {"phase": "reading" if tool_name == "web_extract" else "searching", "sources": sources}
    try:
        if isinstance(result, str):
            prefix = f'<untrusted_tool_result source="{tool_name}">\n'
            if result.startswith(prefix) and result.rstrip().endswith('</untrusted_tool_result>'):
                # The runtime stores external results inside a fixed data envelope.
                # Parse its JSON payload; never forward the envelope or page text.
                result = result.partition('\n\n')[2].rstrip().removesuffix('</untrusted_tool_result>').strip()
        payload = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        payload = None
    if is_error or not isinstance(payload, dict) or payload.get("success") is False or payload.get("ok") is False or payload.get("error"):
        failed = web_source_activity(tool_name, args=args, started=True)["sources"]
        for source in failed:
            source["status"] = "failed"
        return {"phase": "failed", "sources": failed}
    if tool_name == "web_search":
        data = payload.get("data")
        rows = data.get("web", []) if isinstance(data, dict) else []
        phase = "found"
    elif tool_name == "web_extract":
        rows = payload.get("results", [])
        phase = "read"
    else:
        rows = payload.get("source_details", [])
        phase = "found"
    sources, seen = [], set()
    for row in rows[:20] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        status = "found"
        if tool_name == "web_extract":
            status = "read" if not row.get("error") and (row.get("content") or row.get("raw_content")) else "failed"
        elif tool_name == "web_research" and row.get("status") == "read":
            status = "read"
        source = _source(row.get("url"), row.get("title"), status)
        if source and source["url"] not in seen:
            seen.add(source["url"])
            sources.append(source)
    if tool_name == "web_extract" and not any(s["status"] == "read" for s in sources):
        phase = "failed"
    return {"phase": phase, "sources": sources}


def session_source_metadata(rows):
    """Rebuild per-reply sources from existing owner-authorized tool history."""
    metadata, sources, calls = {}, {}, {}
    for index, row in enumerate(rows):
        role = row.get("role")
        if role == "user":
            sources, calls = {}, {}
        if role == "assistant":
            tool_calls = row.get("tool_calls") or []
            if isinstance(tool_calls, str):
                try:
                    tool_calls = json.loads(tool_calls)
                except ValueError:
                    tool_calls = []
            for call in tool_calls if isinstance(tool_calls, list) else []:
                if isinstance(call, dict) and isinstance(call.get("function"), dict) and isinstance(call.get("id"), str):
                    function = call["function"]
                    args = function.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = None
                    calls[call["id"]] = (function.get("name"), args)
            if not tool_calls and sources:
                metadata[index] = {"phase": "found", "sources": list(sources.values())}
        elif role == "tool":
            call_id = row.get("tool_call_id")
            name, args = calls.get(call_id, (None, None)) if isinstance(call_id, str) else (None, None)
            name = row.get("tool_name") or name
            activity = web_source_activity(name, args=args, result=row.get("content"))
            if activity is None:
                continue
            for source in activity["sources"]:
                url = source["url"]
                previous = sources.get(url)
                if previous and previous["status"] == "read" and source["status"] == "found":
                    continue
                if len(sources) < 20 or previous:
                    sources[url] = source
    return metadata
