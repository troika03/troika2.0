"""Reviewed MCP servers for the hosted product.

Public servers (``cloud: true`` in ``mcp_directory.yaml``) are reached without
credentials and expose only their reviewed read-only tools. Account services
(``connect: oauth|token``) use the owner's own stored connection; their tools
that are not annotated read-only require an approval per call (enforced by the
capability gateway). Each call opens a short HTTPS session to the fixed URL and
caps the result size. Results are external data: the gateway wraps them as
untrusted.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from typing import Any

TOOL_PREFIX = "mcp:"
CALL_TIMEOUT = 45.0
LIST_TTL = 600.0
MAX_RESULT_CHARS = 48 * 1024
MAX_ARGUMENT_BYTES = 16 * 1024

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


class MCPUnavailable(Exception):
    """The server could not be reached or answered incorrectly."""


class MCPAuthRequired(MCPUnavailable):
    """The owner's connection is missing or no longer accepted."""


def routed_name(server: str, tool: str) -> str:
    return f"{TOOL_PREFIX}{server}/{tool}"


def split_name(name: Any) -> tuple[str, str] | None:
    if not isinstance(name, str) or not name.startswith(TOOL_PREFIX):
        return None
    server, separator, tool = name[len(TOOL_PREFIX):].partition("/")
    return (server, tool) if separator and server and tool else None


def is_account_service(entry: dict) -> bool:
    return entry.get("connect") in {"oauth", "token"}


def _run(factory, timeout: float):
    """Run a coroutine on a private loop so no caller loop is disturbed."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(lambda: asyncio.run(asyncio.wait_for(factory(), timeout)))
        return future.result(timeout=timeout + 5)
    except (concurrent.futures.TimeoutError, asyncio.TimeoutError) as error:
        raise MCPUnavailable("timeout") from error
    finally:
        pool.shutdown(wait=False)


async def _session(url: str, action, auth=None, headers=None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url, headers=headers or None, auth=auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def _auth_required(error: BaseException) -> bool:
    from troika_product.service_connections import ServiceAuthRequired
    seen, pending = set(), [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ServiceAuthRequired):
            return True
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) in {401, 403}:
            return True
        pending.extend(getattr(current, "exceptions", ()) or ())
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return False


def _call(entry: dict, user_id: str | None, action):
    async def run():
        auth, headers = None, None
        if is_account_service(entry):
            from troika_product.service_connections import auth_for
            auth, headers = auth_for(entry, user_id or "")
        return await _session(entry["url"], action, auth, headers)
    try:
        return _run(run, CALL_TIMEOUT)
    except MCPUnavailable:
        raise
    except Exception as error:  # network, protocol, auth and TaskGroup errors
        if _auth_required(error):
            raise MCPAuthRequired("sign-in required") from error
        raise MCPUnavailable(type(error).__name__) from error


def _schemas(entry: dict, tools) -> list[dict]:
    allowed = set(entry.get("tools") or ())
    schemas = []
    for tool in tools:
        if allowed and tool.name not in allowed:
            continue
        annotations = getattr(tool, "annotations", None)
        # Public servers are reviewed as read-only as a whole.
        read_only = not is_account_service(entry) or bool(annotations and annotations.readOnlyHint)
        schemas.append({
            "name": routed_name(entry["id"], tool.name),
            "description": " ".join(str(tool.description or "").split())[:1200],
            "parameters": tool.inputSchema if isinstance(tool.inputSchema, dict) else {"type": "object"},
            "read_only": read_only,
        })
    return schemas


def list_tools(entry: dict, user_id: str | None = None) -> list[dict]:
    """Tool schemas of one server for one owner, cached briefly."""
    key = (user_id or "" if is_account_service(entry) else "", entry["id"])
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < LIST_TTL:
            return cached[1]

    async def action(session):
        return (await session.list_tools()).tools
    schemas = _schemas(entry, _call(entry, user_id, action))
    with _cache_lock:
        _cache[key] = (time.monotonic(), schemas)
    return schemas


def forget(user_id: str, server_id: str) -> None:
    with _cache_lock:
        _cache.pop((user_id, server_id), None)


async def probe_async(entry: dict, auth=None, headers=None) -> list:
    """Authenticated list_tools on the caller's loop (used during sign-in)."""
    async def action(session):
        return (await session.list_tools()).tools
    return await _session(entry["url"], action, auth, headers)


def call_tool(entry: dict, tool: str, arguments: dict, user_id: str | None = None) -> dict:
    allowed = entry.get("tools")
    if allowed and tool not in allowed:
        raise PermissionError("tool is not reviewed")
    if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ValueError("arguments too large")

    async def action(session):
        return await session.call_tool(tool, arguments)
    result = _call(entry, user_id, action)
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            # Images, audio and embedded resources are not forwarded.
            parts.append(f"[{getattr(block, 'type', 'content')} omitted]")
    text = "\n\n".join(parts)
    return {
        "server": entry["id"],
        "tool": tool,
        "is_error": bool(getattr(result, "isError", False)),
        "content": text[:MAX_RESULT_CHARS],
        "truncated": len(text) > MAX_RESULT_CHARS,
    }
