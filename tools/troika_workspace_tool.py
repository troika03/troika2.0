"""Private workspace and bounded terminal tools for hosted Troika users."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shlex
from typing import Any

from gateway.session_context import get_session_env
from hermes_constants import get_hermes_home
from tools.registry import registry
from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.workspace import WorkspaceError, WorkspaceStore


def _identity() -> tuple[str, str, str] | None:
    if get_session_env("TROIKA_PRODUCT_MODE", "") != "1":
        return None
    values = (
        get_session_env("TROIKA_PRODUCT_USER_ID", "").strip(),
        get_session_env("TROIKA_PRODUCT_DEVICE_ID", "").strip(),
        get_session_env("TROIKA_PRODUCT_TOKEN_ID", "").strip(),
    )
    return values if all(values) else None


def _workspace_root() -> Path:
    configured = get_session_env("TROIKA_PRODUCT_WORKSPACE_ROOT", "").strip()
    return Path(configured) if configured else get_hermes_home() / "workspaces"


def _store() -> WorkspaceStore:
    return WorkspaceStore(_workspace_root())


def _available() -> bool:
    return (
        _identity() is not None
        and get_session_env("TROIKA_PRODUCT_WORKSPACE_AVAILABLE", "1") != "0"
    )


def _result(ok: bool, **payload: Any) -> str:
    return json.dumps({"ok": ok, **payload}, ensure_ascii=False)


def _path_digest(path: str) -> str:
    return sha256(path.encode("utf-8")).hexdigest()[:32]


def _audit(action: str, *, path: str = "", size: int = 0, task_id: str = "") -> None:
    identity = _identity()
    if identity is None:
        return
    user_id, device_id, token_id = identity
    raw_database = get_session_env("TROIKA_PRODUCT_ACCESS_DB", "").strip()
    access = AccessRegistry(Path(raw_database) if raw_database else None)
    details: dict[str, str | int] = {"action": action}
    if path:
        details["path_digest"] = _path_digest(path)
    if size:
        details["size"] = size
    access.record_audit_event(
        f"workspace.{action}",
        principal=AccessPrincipal(user_id, device_id, token_id),
        run_id=task_id or None,
        details=details,
    )


def _approve_delete(path: str, recursive: bool) -> bool:
    try:
        from tools.approval import request_gateway_approval

        description = (
            f"Удалить папку «{path}» вместе с содержимым?"
            if recursive
            else f"Удалить «{path}»?"
        )
        return bool(
            request_gateway_approval("workspace.delete", description).get("approved")
        )
    except Exception:
        return False


def _handle_files(args: dict[str, Any], **kwargs: Any) -> str:
    identity = _identity()
    if identity is None:
        return _result(False, error="product_identity_required")
    user_id = identity[0]
    action = str(args.get("action") or "").strip().lower()
    path = str(args.get("path") or "")
    store = _store()
    try:
        if action == "list":
            entries = [entry.to_dict() for entry in store.list(user_id, path)]
            return _result(True, action=action, path=path or ".", entries=entries)
        if action == "stat":
            return _result(
                True, action=action, entry=store.stat(user_id, path).to_dict()
            )
        if action == "read":
            content = store.read_text(user_id, path)
            _audit(
                "read",
                path=path,
                size=len(content.encode("utf-8")),
                task_id=kwargs.get("task_id") or "",
            )
            return _result(True, action=action, path=path, content=content)
        if action == "write":
            entry = store.write_text(
                user_id,
                path,
                str(args.get("content") or ""),
                overwrite=bool(args.get("overwrite", True)),
            )
            _audit(
                "write", path=path, size=entry.size, task_id=kwargs.get("task_id") or ""
            )
            return _result(True, action=action, entry=entry.to_dict())
        if action == "replace":
            entry = store.replace_text(
                user_id,
                path,
                str(args.get("old") or ""),
                str(args.get("new") or ""),
                replace_all=bool(args.get("replace_all", False)),
            )
            _audit(
                "replace",
                path=path,
                size=entry.size,
                task_id=kwargs.get("task_id") or "",
            )
            return _result(True, action=action, entry=entry.to_dict())
        if action == "mkdir":
            entry = store.mkdir(user_id, path)
            _audit("mkdir", path=path, task_id=kwargs.get("task_id") or "")
            return _result(True, action=action, entry=entry.to_dict())
        if action == "copy":
            destination = str(args.get("destination") or "")
            entry = store.copy(user_id, path, destination)
            _audit(
                "copy",
                path=destination,
                size=entry.size,
                task_id=kwargs.get("task_id") or "",
            )
            return _result(True, action=action, entry=entry.to_dict())
        if action == "move":
            destination = str(args.get("destination") or "")
            entry = store.move(user_id, path, destination)
            _audit("move", path=destination, task_id=kwargs.get("task_id") or "")
            return _result(True, action=action, entry=entry.to_dict())
        if action == "delete":
            recursive = bool(args.get("recursive", False))
            if not _approve_delete(path, recursive):
                return _result(False, error="approval_denied")
            store.delete(user_id, path, recursive=recursive)
            _audit("delete", path=path, task_id=kwargs.get("task_id") or "")
            return _result(True, action=action, path=path)
        return _result(False, error="unsupported_workspace_action")
    except WorkspaceError as exc:
        return _result(False, error="workspace_error", message=str(exc))
    except OSError:
        return _result(False, error="workspace_operation_failed")


def _handle_search(args: dict[str, Any], **kwargs: Any) -> str:
    identity = _identity()
    if identity is None:
        return _result(False, error="product_identity_required")
    query = str(args.get("query") or "")
    path = str(args.get("path") or "")
    try:
        matches = _store().search(identity[0], query, path=path)
        _audit("search", path=path or ".", task_id=kwargs.get("task_id") or "")
        return _result(True, query=query, path=path or ".", matches=matches)
    except WorkspaceError as exc:
        return _result(False, error="workspace_error", message=str(exc))
    except OSError:
        return _result(False, error="workspace_operation_failed")


def _terminal_tokens(command: str) -> list[str]:
    value = str(command or "").strip()
    if not value or len(value) > 1000 or "\n" in value or "\r" in value:
        raise WorkspaceError("terminal command is empty or too long")
    if any(marker in value for marker in (";", "|", "&", ">", "<", "`", "$(")):
        raise WorkspaceError("shell operators are not supported")
    try:
        return shlex.split(value, posix=True)
    except ValueError as exc:
        raise WorkspaceError("terminal command has invalid quoting") from exc


def _terminal_run(
    store: WorkspaceStore,
    user_id: str,
    tokens: list[str],
    *,
    task_id: str,
) -> str:
    command, arguments = tokens[0].lower(), tokens[1:]
    if command == "pwd" and not arguments:
        return "/workspace"
    if command == "ls" and len(arguments) <= 1:
        path = arguments[0] if arguments else ""
        entries = store.list(user_id, path)
        _audit("list", path=path or ".", task_id=task_id)
        return "\n".join(
            f"{'d' if entry.kind == 'folder' else '-'} {entry.size:>8} {entry.path}"
            for entry in entries
        )
    if command == "cat" and len(arguments) == 1:
        content = store.read_text(user_id, arguments[0])
        _audit(
            "read",
            path=arguments[0],
            size=len(content.encode("utf-8")),
            task_id=task_id,
        )
        return content
    if command in {"head", "tail"} and len(arguments) in {1, 3}:
        count = 20
        path = arguments[-1]
        if len(arguments) == 3:
            if arguments[0] != "-n" or not arguments[1].isdigit():
                raise WorkspaceError("use head/tail [-n number] file")
            count = min(200, max(1, int(arguments[1])))
        lines = store.read_text(user_id, path).splitlines()
        _audit("read", path=path, task_id=task_id)
        selected = lines[:count] if command == "head" else lines[-count:]
        return "\n".join(selected)
    if command == "wc" and len(arguments) == 1:
        content = store.read_text(user_id, arguments[0])
        _audit(
            "read",
            path=arguments[0],
            size=len(content.encode("utf-8")),
            task_id=task_id,
        )
        return f"{len(content.splitlines())} {len(content.split())} {len(content.encode('utf-8'))} {arguments[0]}"
    if command == "mkdir" and len(arguments) == 1:
        entry = store.mkdir(user_id, arguments[0])
        _audit("mkdir", path=arguments[0], task_id=task_id)
        return entry.path
    if command == "touch" and len(arguments) == 1:
        try:
            entry = store.stat(user_id, arguments[0])
            if entry.kind != "file":
                raise WorkspaceError("touch target is not a file")
        except WorkspaceError as exc:
            if str(exc) != "path does not exist":
                raise
            entry = store.write_text(user_id, arguments[0], "", overwrite=False)
        _audit("write", path=arguments[0], size=entry.size, task_id=task_id)
        return entry.path
    if command == "cp" and len(arguments) == 2:
        entry = store.copy(user_id, arguments[0], arguments[1])
        _audit("copy", path=arguments[1], size=entry.size, task_id=task_id)
        return entry.path
    if command == "mv" and len(arguments) == 2:
        entry = store.move(user_id, arguments[0], arguments[1])
        _audit("move", path=arguments[1], task_id=task_id)
        return entry.path
    if command == "rm" and len(arguments) in {1, 2}:
        recursive = len(arguments) == 2 and arguments[0] in {"-r", "-rf"}
        path = arguments[-1]
        if len(arguments) == 2 and not recursive:
            raise WorkspaceError("only rm file or rm -r folder is supported")
        if not _approve_delete(path, recursive):
            raise WorkspaceError("deletion was not approved")
        store.delete(user_id, path, recursive=recursive)
        _audit("delete", path=path, task_id=task_id)
        return path
    if command == "grep" and len(arguments) in {1, 2}:
        matches = store.search(
            user_id,
            arguments[0],
            path=arguments[1] if len(arguments) == 2 else "",
        )
        _audit(
            "search", path=arguments[1] if len(arguments) == 2 else ".", task_id=task_id
        )
        return "\n".join(
            f"{item['path']}:{item['line']}:{item['excerpt']}" for item in matches
        )
    if command == "find" and len(arguments) == 2:
        matches = store.search(user_id, arguments[1], path=arguments[0])
        _audit("search", path=arguments[0], task_id=task_id)
        return "\n".join(str(item["path"]) for item in matches)
    raise WorkspaceError(
        "supported commands: pwd, ls, cat, head, tail, wc, mkdir, touch, cp, mv, rm, grep, find"
    )


def _handle_terminal(args: dict[str, Any], **kwargs: Any) -> str:
    identity = _identity()
    if identity is None:
        return _result(False, error="product_identity_required")
    command_text = str(args.get("command") or "")
    try:
        tokens = _terminal_tokens(command_text)
        output = _terminal_run(
            _store(),
            identity[0],
            tokens,
            task_id=kwargs.get("task_id") or "",
        )
        _audit("terminal", path=tokens[0], task_id=kwargs.get("task_id") or "")
        return _result(True, command=tokens[0], output=output)
    except WorkspaceError as exc:
        return _result(False, error="workspace_terminal_error", message=str(exc))
    except OSError:
        return _result(False, error="workspace_operation_failed")


FILES_SCHEMA = {
    "name": "troika_files",
    "description": (
        "Manage files and folders in the authenticated user's private Troika workspace. "
        "Paths are relative; use list, stat, read, write, replace, mkdir, copy, move, or delete."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "stat",
                    "read",
                    "write",
                    "replace",
                    "mkdir",
                    "copy",
                    "move",
                    "delete",
                ],
            },
            "path": {"type": "string", "description": "Relative workspace path."},
            "destination": {
                "type": "string",
                "description": "Relative destination for copy or move.",
            },
            "content": {"type": "string", "description": "UTF-8 text for write."},
            "old": {"type": "string", "description": "Exact old text for replace."},
            "new": {"type": "string", "description": "Replacement text."},
            "overwrite": {"type": "boolean", "default": True},
            "replace_all": {"type": "boolean", "default": False},
            "recursive": {"type": "boolean", "default": False},
        },
        "required": ["action"],
    },
}

SEARCH_SCHEMA = {
    "name": "troika_file_search",
    "description": "Search file names and UTF-8 text inside the user's private Troika workspace.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {
                "type": "string",
                "description": "Optional relative folder or file path.",
            },
        },
        "required": ["query"],
    },
}

TERMINAL_SCHEMA = {
    "name": "troika_terminal",
    "description": (
        "Run a bounded terminal-style command only inside the user's private workspace. "
        "Supports pwd, ls, cat, head, tail, wc, mkdir, touch, cp, mv, rm, grep, and find; no shell, network, packages, or server access."
    ),
    "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}


registry.register(
    name="troika_files",
    toolset="troika_workspace",
    schema=FILES_SCHEMA,
    handler=_handle_files,
    check_fn=_available,
    emoji="📁",
)
registry.register(
    name="troika_file_search",
    toolset="troika_workspace",
    schema=SEARCH_SCHEMA,
    handler=_handle_search,
    check_fn=_available,
    emoji="🔎",
)
registry.register(
    name="troika_terminal",
    toolset="troika_workspace",
    schema=TERMINAL_SCHEMA,
    handler=_handle_terminal,
    check_fn=_available,
    emoji="⌨️",
)
