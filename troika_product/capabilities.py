"""Account-owned capability catalogue and stable, deferred tool gateway.

The complete reviewed product allowlist stays on the server. Models receive
only discovery/call schemas; detailed schemas arrive as append-only tool
results. No provider-specific tool loading or change to past history is needed.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any

from gateway.session_context import (
    clear_session_override, get_session_env, get_session_overrides,
    set_session_override,
)
from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.development import DEVELOPMENT_GUIDANCE
from troika_product.feature_policy import FORBIDDEN_PRODUCT_TOOLS, product_toolsets


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    tools: tuple[str, ...]
    skill: str


CAPABILITIES = (
    Capability("assistant", "Дела и память", "Задачи, заметки, проекты и напоминания.",
               ("troika_assistant", "troika_reminder", "troika_context"),
               "Сохранять дела и напоминания, помнить подтверждённые предпочтения."),
    Capability("web", "Поиск в интернете", "Находить информацию и источники.",
               ("web_search", "web_extract", "web_research"),
               "Искать информацию, сопоставлять источники и приводить ссылки."),
    Capability("documents", "Документы и презентации", "Создавать Word, PDF и PowerPoint.",
               ("troika_create_docx", "troika_create_pdf", "troika_create_pptx"),
               "Готовить документы и презентации по задаче пользователя."),
    Capability("development", "Разработка", "Создавать проекты с кодом, README и тестами.",
               ("troika_create_project",),
               DEVELOPMENT_GUIDANCE),
    Capability("files", "Файлы", "Искать, читать и изменять личные файлы.",
               ("troika_files", "troika_file_search", "troika_terminal"),
               "Работать с файлами владельца через ограниченные файловые операции."),
    Capability("phone", "Телефон", "Управлять подключённым телефоном с его разрешения.",
               ("android_status", "android_battery", "android_network",
                "android_open_app", "android_web_search", "android_set_alarm",
                "android_set_timer", "android_navigate", "android_volume",
                "android_brightness", "android_torch", "android_camera_photo"),
               "Выполнять доступные действия на подключённом телефоне с подтверждением."),
    Capability("images", "Создание изображений", "Создавать изображения через настроенный сервис.",
               ("image_generate", "image_pollinations_url"),
               "Создавать изображение по описанию пользователя."),
    Capability("vision", "Анализ изображений", "Разбирать изображения через настроенный сервис.",
               ("vision_analyze",), "Анализировать переданное пользователем изображение."),
    Capability("screen", "Просмотр экрана", "Одноразовый снимок экрана в закрытой бете.",
               ("troika_screen_snapshot",), "Анализировать разрешённый одноразовый снимок экрана."),
)
BY_ID = {item.id: item for item in CAPABILITIES}
TOOL_CAPABILITY = {tool: item.id for item in CAPABILITIES for tool in item.tools}
TOOL_TITLES = {
    "troika_assistant": "Задачи, проекты, заметки и память",
    "troika_reminder": "Напоминания",
    "troika_context": "Исходная история и инструкции",
    "web_search": "Поиск страниц", "web_extract": "Чтение страниц",
    "web_research": "Исследование с источниками",
    "troika_create_docx": "Документ Word", "troika_create_pdf": "Документ PDF",
    "troika_create_pptx": "Презентация PowerPoint", "troika_create_project": "Проект с кодом",
    "troika_files": "Личные файлы", "troika_file_search": "Поиск по файлам",
    "troika_terminal": "Ограниченные файловые команды",
    "android_status": "Состояние телефона", "android_battery": "Заряд батареи",
    "android_network": "Состояние сети", "android_open_app": "Открытие приложения",
    "android_web_search": "Поиск в браузере телефона",
    "android_set_alarm": "Будильник", "android_set_timer": "Таймер",
    "android_navigate": "Навигация", "android_volume": "Громкость",
    "android_brightness": "Яркость", "android_torch": "Фонарик",
    "android_camera_photo": "Фото с подтверждением",
    "image_generate": "Генерация изображения", "vision_analyze": "Анализ изображения",
    "image_pollinations_url": "Ссылка на созданное изображение",
    "troika_screen_snapshot": "Одноразовый снимок экрана",
}
ROUTER_TOOLSET = "troika-capabilities"
SEARCH_TOOL = "troika_tool_search"
CALL_TOOL = "troika_tool_call"

SEARCH_SCHEMA = {
    "name": SEARCH_TOOL,
    "description": (
        "Load full tool schemas and a skill for a needed capability: assistant "
        "(tasks/memory/reminders), web, documents, development, files, phone, "
        "images, vision, screen; skills/mcp list the owner's connected skills "
        "and MCP servers, tool=<id> loads one. Use catalog for enabled/configured status only. "
        "Optional tool selects one exact tool. "
        "No discovery needed for ordinary conversation. Disabled/unconfigured tools are excluded."
    ),
    "parameters": {"type": "object", "properties": {
        "capability": {"type": "string", "enum": ["catalog", "skills", "mcp", *BY_ID]},
        "tool": {"type": "string", "description": "Optional exact tool name."},
    }, "required": ["capability"], "additionalProperties": False},
}
CALL_SCHEMA = {
    "name": CALL_TOOL,
    "description": (
        "Execute a product tool using its previously discovered schema. "
        "Pass the exact tool name and its parameters as arguments. "
        "Use this gateway, not a direct call to a discovered tool. "
        "Existing ownership, device consent and approval checks still apply."
    ),
    "parameters": {"type": "object", "properties": {
        "tool": {"type": "string"},
        "arguments": {"type": "object", "description": "Parameters from the discovered schema."},
    }, "required": ["tool", "arguments"], "additionalProperties": False},
}

ROUTING_GUIDANCE = """
Возможности подключаются автоматически по необходимости. Подробные описания
доступных инструментов получай через troika_tool_search; выполняй их через
troika_tool_call с точным именем и arguments из полученной схемы. Имена
инструментов в личности Тройки относятся к этому каталогу, а не к прямым
вызовам. Обычный разговор не требует поиска инструментов. Для сложной задачи
можно последовательно использовать несколько возможностей. Не угадывай
параметры; описание из истории можно использовать повторно. Отключённую или
недоступную возможность не обходи другим инструментом. Поиск схемы не
означает выполнение действия. Не называй отсутствие полной схемы в первом
запросе отсутствием функции: сначала проверь соответствующую возможность.
Задачи во внешних сервисах (GitHub, Notion, Jira, Stripe и др.) и поиск по
документации библиотек выполняй через capability mcp: без tool — список
подключённых владельцем серверов, tool=<id сервера> — их схемы; вызывай через
troika_tool_call с именем mcp:<сервер>/<инструмент>. Действие с
read_only=false сервер подтвердит у владельца. Неподключённый сервис предложи
подключить в «Возможности → MCP». Подключённые навыки — capability skills.
"""


class CapabilityStore:
    """Merge small per-capability patches, never accepting another owner ID."""

    def __init__(self, registry: AccessRegistry):
        self.registry = registry

    def preferences(self, principal: AccessPrincipal) -> dict[str, bool]:
        with self.registry._connect() as connection:
            self.registry._require_active_principal(connection, principal)
            row = connection.execute(
                "SELECT preferences_json FROM troika_capability_preferences WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
        overrides = json.loads(row["preferences_json"]) if row else {}
        return {key: overrides.get(key, True) for key in BY_ID}

    def update(self, principal: AccessPrincipal, patch: Any) -> dict[str, bool]:
        if not isinstance(patch, dict) or not patch or any(
            key not in BY_ID or type(value) is not bool for key, value in patch.items()
        ):
            raise ValueError("expected known capability IDs and boolean values")
        with self.registry._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(connection, principal)
            row = connection.execute(
                "SELECT preferences_json FROM troika_capability_preferences WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            current = json.loads(row["preferences_json"]) if row else {}
            current.update(patch)
            connection.execute(
                "INSERT INTO troika_capability_preferences (user_id, preferences_json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "preferences_json = excluded.preferences_json, updated_at = excluded.updated_at",
                (principal.user_id, json.dumps(current, separators=(",", ":")), time.time()),
            )
        return {key: current.get(key, True) for key in BY_ID}


def session_identity() -> tuple[AccessRegistry, AccessPrincipal]:
    if get_session_env("TROIKA_PRODUCT_MODE", "") != "1":
        raise PermissionError("product identity required")
    values = [get_session_env(key, "") for key in (
        "TROIKA_PRODUCT_ACCESS_DB", "TROIKA_PRODUCT_USER_ID",
        "TROIKA_PRODUCT_DEVICE_ID", "TROIKA_PRODUCT_TOKEN_ID",
    )]
    if not all(values):
        raise PermissionError("product identity required")
    return AccessRegistry(Path(values[0])), AccessPrincipal(*values[1:])


def available_schemas() -> dict[str, dict]:
    """Reuse reviewed toolset resolution, including both screen feature gates."""
    from model_tools import get_tool_definitions
    from troika_product.working_context import compact_enabled
    toolsets = product_toolsets(
            screen_snapshot_enabled=get_session_env("TROIKA_PRODUCT_SCREEN_SNAPSHOT_ENABLED", "") == "1",
            external_vision_enabled=get_session_env("TROIKA_PRODUCT_SCREEN_EXTERNAL_VISION_ENABLED", "") == "1",
        )
    previous = get_session_overrides()
    if compact_enabled():
        toolsets.append(ROUTER_TOOLSET)
        set_session_override("TROIKA_CONTEXT_DISCOVERY", "1")
    try:
        schemas = get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
    finally:
        if compact_enabled():
            if "TROIKA_CONTEXT_DISCOVERY" in previous:
                set_session_override("TROIKA_CONTEXT_DISCOVERY", previous["TROIKA_CONTEXT_DISCOVERY"])
            else:
                clear_session_override("TROIKA_CONTEXT_DISCOVERY")
    result = {schema["function"]["name"]: schema["function"] for schema in schemas
              if schema["function"]["name"] in TOOL_CAPABILITY
              and schema["function"]["name"] not in FORBIDDEN_PRODUCT_TOOLS}
    # The upstream web tool shares one requirement check for search/extract.
    # A configured search-only provider must not advertise page reading.
    if "web_extract" in result:
        from agent.web_search_registry import get_active_extract_provider
        if get_active_extract_provider() is None:
            result.pop("web_extract")
    return result


@contextmanager
def catalogue_context(adapter, principal):
    """Probe product tool configuration without process-global identity."""
    previous = get_session_overrides()
    overrides = {
        "TROIKA_PRODUCT_MODE": "1",
        "TROIKA_PRODUCT_ACCESS_DB": str(adapter._product_artifact_db),
        "TROIKA_PRODUCT_USER_ID": principal.user_id,
        "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
        "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE": "1" if adapter._artifact_store else "0",
        "TROIKA_PRODUCT_WORKSPACE_AVAILABLE": "1" if adapter._workspace_store else "0",
        "TROIKA_PRODUCT_SCREEN_SNAPSHOT_ENABLED": "1" if adapter._product_screen_snapshot_enabled else "0",
        "TROIKA_PRODUCT_SCREEN_EXTERNAL_VISION_ENABLED": "1" if adapter._product_screen_external_vision_enabled else "0",
    }
    try:
        for key, value in overrides.items():
            set_session_override(key, value)
        yield
    finally:
        for key in overrides:
            if key in previous:
                set_session_override(key, previous[key])
            else:
                clear_session_override(key)


def catalogue(preferences: dict[str, bool], schemas: dict[str, dict]) -> dict:
    return {"object": "troika.capabilities", "loading": "on_demand", "capabilities": [
        {"id": item.id, "title": item.title, "description": item.description,
         "enabled": preferences[item.id], "available": any(tool in schemas for tool in item.tools),
         "source": "builtin",
         "skills": [{"id": item.id, "description": item.skill}],
         "tools": [{"id": tool, "title": TOOL_TITLES[tool], "available": tool in schemas}
                   for tool in item.tools]}
        for item in CAPABILITIES
    ]}


def discover(args: dict, **_: Any) -> str:
    try:
        registry, principal = session_identity()
        from agent.provider_metering import current_provider_guard
        if getattr(getattr(current_provider_guard(), "context", None), "conversation_only", False):
            return _error("no_action_requested")
        preferences = CapabilityStore(registry).preferences(principal)
        capability = args.get("capability")
        if capability == "skills":
            from troika_product.extensions import discover_skills
            return discover_skills(registry, principal, args.get("tool"))
        if capability == "mcp":
            from troika_product.extensions import discover_mcp
            return discover_mcp(registry, principal, args.get("tool"))
        if capability == "catalog":
            from troika_product.extensions import ExtensionStore
            schemas = available_schemas()
            return json.dumps({"ok": True, "capabilities": [
                {"id": item.id, "title": item.title, "enabled": preferences[item.id],
                 "configured": any(tool in schemas for tool in item.tools)}
                for item in CAPABILITIES
            ], "connected_skills": sorted(ExtensionStore(registry).connected(principal)),
                "connected_mcp": sorted(ExtensionStore(registry, "mcp").connected(principal))},
                ensure_ascii=False)
        item = BY_ID.get(capability) if isinstance(capability, str) else None
        if item is None:
            raise ValueError("unknown capability")
        if not preferences[item.id]:
            return _error("capability_disabled")
        schemas = available_schemas()
        tool = args.get("tool")
        if tool is not None and (not isinstance(tool, str) or tool not in item.tools):
            raise ValueError("tool does not belong to capability")
        selected = [schemas[name] for name in item.tools if name in schemas and (not tool or name == tool)]
        if not selected:
            return _error("capability_unavailable")
        from troika_product.context_guidance import capability_guidance
        guidance = capability_guidance(item.id, device=get_session_env("TROIKA_PRODUCT_DELIVERY_MODE", "server") == "device")
        return json.dumps({"ok": True, "capability": item.id, "skill": item.skill,
                           "guidance": guidance,
                           "tools": selected, "call_via": CALL_TOOL}, ensure_ascii=False)
    except PermissionError:
        return _error("product_identity_required")
    except (ValueError, TypeError):
        return _error("invalid_discovery_arguments")


def _error(code: str) -> str:
    return json.dumps({"ok": False, "error": code})


def execute(args: dict, **kwargs: Any) -> str:
    try:
        registry, principal = session_identity()
        from agent.provider_metering import current_provider_guard
        if getattr(getattr(current_provider_guard(), "context", None), "conversation_only", False):
            return _error("no_action_requested")
        preferences = CapabilityStore(registry).preferences(principal)
        tool, arguments = args.get("tool"), args.get("arguments")
        if isinstance(tool, str) and tool.startswith("mcp:"):
            if isinstance(arguments, str):
                try:
                    if len(arguments.encode("utf-8")) > 1024 * 1024:
                        return _error("invalid_tool_arguments")
                    arguments = json.loads(arguments)
                except (UnicodeError, ValueError, TypeError, RecursionError):
                    return _error("invalid_tool_arguments")
            if not isinstance(arguments, dict):
                return _error("invalid_tool_arguments")
            from troika_product.extensions import execute_mcp, wrap_external
            envelope, _ = execute_mcp(registry, principal, tool, arguments)
            return wrap_external(envelope)
        if not isinstance(tool, str) or tool not in TOOL_CAPABILITY or tool in FORBIDDEN_PRODUCT_TOOLS:
            return _error("tool_not_allowed")
        if not isinstance(arguments, dict):
            return _error("invalid_tool_arguments")
        if not preferences[TOOL_CAPABILITY[tool]]:
            return _error("capability_disabled")
        schemas = available_schemas()
        if tool not in schemas:
            return _error("tool_unavailable")
        # Validate required parameters/types before reaching a mutating handler.
        # jsonschema is declared directly because dispatch relies on it.
        from jsonschema import Draft7Validator
        if not Draft7Validator(schemas[tool].get("parameters", {})).is_valid(arguments):
            return _error("invalid_tool_arguments")
        from model_tools import handle_function_call
        from agent.provider_metering import current_provider_guard
        guard = current_provider_guard()
        hold = guard.begin_tool(tool, arguments) if hasattr(guard, "begin_tool") else None
        try:
            result = handle_function_call(tool, arguments, task_id=kwargs.get("task_id"),
                                          enabled_tools=list(schemas))
        except BaseException:
            if hold is not None:
                guard.finish_tool(hold, successful=False)
            raise
        try:
            payload = json.loads(result)
        except (ValueError, TypeError):
            payload = result
        failed = isinstance(payload, dict) and (
            payload.get("error") or payload.get("ok") is False or payload.get("success") is False
        )
        if hold is not None:
            guard.finish_tool(hold, successful=not bool(failed))
        envelope = json.dumps({"ok": not bool(failed), "routed_tool": tool, "result": payload},
                              ensure_ascii=False)
        # Retain the existing external-data boundary even though dispatch now
        # uses one fixed tool name. Internal receipts remain plain JSON.
        if tool in {"web_search", "web_extract", "web_research"}:
            from agent.tool_dispatch_helpers import _maybe_wrap_untrusted
            envelope = _maybe_wrap_untrusted("web_search", envelope)
        return envelope
    except PermissionError:
        return _error("product_identity_required")
    except (ValueError, TypeError):
        return _error("invalid_tool_arguments")


def routed_call(name: str, args: Any) -> tuple[str, dict]:
    """Resolve display metadata only; this never authorizes execution."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    args = args if isinstance(args, dict) else {}
    if (name == CALL_TOOL and isinstance(args.get("tool"), str)
            and args["tool"] in TOOL_CAPABILITY and isinstance(args.get("arguments"), dict)):
        return args["tool"], args["arguments"]
    return name, args


def routed_result(name: str, args: Any, result: Any) -> tuple[str, dict, Any]:
    """Unwrap only a gateway receipt matching a known product tool."""
    if name != CALL_TOOL:
        return name, args, result
    payload = result
    if isinstance(payload, str):
        if payload.startswith('<untrusted_tool_result source="web_search">\n'):
            payload = payload.partition("\n\n")[2].rstrip().removesuffix("</untrusted_tool_result>").strip()
        try:
            payload = json.loads(payload)
        except ValueError:
            return name, args, result
    if (not isinstance(payload, dict) or not isinstance(payload.get("routed_tool"), str)
            or payload["routed_tool"] not in TOOL_CAPABILITY):
        return name, args, result
    tool, inner_args = routed_call(name, args)
    if args is not None and tool != payload["routed_tool"]:
        return name, args, result
    if payload.get("ok") is not True:
        return payload["routed_tool"], inner_args, {"ok": False, "error": "routed_tool_failed"}
    return payload["routed_tool"], inner_args, payload.get("result")


def wrap_progress(callback):
    if callback is None:
        return None
    def wrapped(event, name=None, preview=None, args=None, **kwargs):
        if event == "tool.started":
            name, args = routed_call(name, args)
        else:
            name, args, result = routed_result(name, args, kwargs.get("result"))
            if "result" in kwargs:
                kwargs["result"] = result
        return callback(event, name, preview, args, **kwargs)
    return wrapped
