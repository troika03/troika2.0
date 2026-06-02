"""
Obsidian vault tool — read/write/search notes in d:\\troikahermes-vault.

The vault is also Claude's memory store (a junction to
``~/.claude/projects/d--troikahermes/memory/``), so writes are visible to
both Hermes and Claude immediately.

All paths are resolved relative to the vault root and clamped inside it —
absolute paths or "../" escapes return an error.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)


VAULT_ROOT_CANDIDATES = [
    Path(r"d:\troikahermes-vault"),
    Path(r"D:\troikahermes-vault"),
    Path.home() / ".claude" / "projects" / "d--troikahermes" / "memory",
]


def _vault_root() -> Path | None:
    env = os.environ.get("TROIKA_VAULT_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for cand in VAULT_ROOT_CANDIDATES:
        if cand.exists():
            return cand
    return None


def _resolve_inside(root: Path, rel: str) -> Path | None:
    rel = (rel or "").strip().lstrip("/\\")
    if not rel:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> Dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _slugify(name: str) -> str:
    name = re.sub(r"[\s/\\]+", "-", name.strip().lower())
    name = re.sub(r"[^a-z0-9а-яё\-_]", "", name)
    return name or f"note-{int(datetime.now().timestamp())}"


async def _handle(args: Dict[str, Any], **_kw) -> str:
    root = _vault_root()
    if root is None:
        return json.dumps(
            {"ok": False, "error": "vault_not_found", "tried": [str(p) for p in VAULT_ROOT_CANDIDATES]},
            ensure_ascii=False,
        )

    op = (args.get("operation") or args.get("op") or "").strip().lower()
    if not op:
        return json.dumps({"ok": False, "error": "missing 'operation'"}, ensure_ascii=False)

    if op == "list":
        folder = args.get("folder", "")
        base = _resolve_inside(root, folder) if folder else root
        if base is None or not base.exists():
            return json.dumps({"ok": False, "error": f"folder_not_found: {folder}"}, ensure_ascii=False)
        items: List[Dict[str, Any]] = []
        for p in sorted(base.rglob("*.md")):
            try:
                rel = str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            items.append({"path": rel, "size": p.stat().st_size})
            if len(items) >= 300:
                break
        return json.dumps({"ok": True, "vault": str(root), "count": len(items), "notes": items}, ensure_ascii=False)

    if op == "read":
        path = args.get("path") or args.get("name")
        if not path:
            return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
        if not path.endswith(".md"):
            path = path + ".md"
        target = _resolve_inside(root, path)
        if target is None or not target.exists():
            return json.dumps({"ok": False, "error": f"note_not_found: {path}"}, ensure_ascii=False)
        text = target.read_text(encoding="utf-8", errors="replace")
        max_chars = int(args.get("max_chars") or 20000)
        truncated = len(text) > max_chars
        return json.dumps({
            "ok": True,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "frontmatter": _parse_frontmatter(text),
            "content": text[:max_chars],
            "truncated": truncated,
            "size": len(text),
        }, ensure_ascii=False)

    if op in ("write", "create", "append"):
        path = args.get("path") or args.get("name")
        content = args.get("content")
        if not path or content is None:
            return json.dumps({"ok": False, "error": "need 'path' and 'content'"}, ensure_ascii=False)
        if not path.endswith(".md"):
            path = path + ".md"
        target = _resolve_inside(root, path)
        if target is None:
            return json.dumps({"ok": False, "error": f"invalid_path: {path}"}, ensure_ascii=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        if op == "append" and target.exists():
            existing = target.read_text(encoding="utf-8", errors="replace")
            sep = "" if existing.endswith("\n") else "\n"
            target.write_text(existing + sep + content, encoding="utf-8")
            action = "appended"
        else:
            target.write_text(content, encoding="utf-8")
            action = "created" if not target.exists() or op == "create" else "overwritten"
        return json.dumps({
            "ok": True,
            "action": action,
            "path": str(target.relative_to(root)).replace("\\", "/"),
            "size": target.stat().st_size,
        }, ensure_ascii=False)

    if op == "search":
        q = (args.get("query") or args.get("q") or "").strip()
        if not q:
            return json.dumps({"ok": False, "error": "missing 'query'"}, ensure_ascii=False)
        q_low = q.lower()
        hits: List[Dict[str, Any]] = []
        for p in root.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lowered = text.lower()
            if q_low not in lowered and q_low not in p.name.lower():
                continue
            idx = lowered.find(q_low)
            snippet_start = max(0, idx - 80) if idx >= 0 else 0
            snippet_end = (idx + 200) if idx >= 0 else 200
            snippet = text[snippet_start:snippet_end].replace("\n", " ")
            try:
                rel = str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            hits.append({"path": rel, "snippet": snippet})
            if len(hits) >= 25:
                break
        return json.dumps({"ok": True, "query": q, "count": len(hits), "hits": hits}, ensure_ascii=False)

    if op == "quick":
        text = (args.get("content") or args.get("text") or "").strip()
        if not text:
            return json.dumps({"ok": False, "error": "missing 'content'"}, ensure_ascii=False)
        title = (args.get("title") or text.split("\n", 1)[0][:60]).strip()
        slug = _slugify(title)
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d_%H%M")
        folder = (args.get("folder") or "inbox").strip("/\\")
        path = f"{folder}/{stamp}-{slug}.md"
        target = _resolve_inside(root, path)
        if target is None:
            return json.dumps({"ok": False, "error": f"invalid_path: {path}"}, ensure_ascii=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "---\n"
            f"name: {slug}\n"
            f"description: {title[:140]}\n"
            f"created: {datetime.now().isoformat(timespec='seconds')}\n"
            "metadata:\n"
            "  type: quick-note\n"
            "  source: voice\n"
            "---\n\n"
            f"# {title}\n\n"
            f"{text}\n"
        )
        target.write_text(body, encoding="utf-8")
        return json.dumps({
            "ok": True,
            "action": "quick",
            "path": str(target.relative_to(root)).replace("\\", "/"),
        }, ensure_ascii=False)

    if op == "delete":
        path = args.get("path") or args.get("name")
        if not path:
            return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
        if not path.endswith(".md"):
            path = path + ".md"
        target = _resolve_inside(root, path)
        if target is None or not target.exists():
            return json.dumps({"ok": False, "error": f"note_not_found: {path}"}, ensure_ascii=False)
        target.unlink()
        return json.dumps({"ok": True, "action": "deleted", "path": path}, ensure_ascii=False)

    return json.dumps({"ok": False, "error": f"unknown_operation: {op}"}, ensure_ascii=False)


OBSIDIAN_SCHEMA = {
    "name": "obsidian_note",
    "description": (
        "Obsidian vault notes — read, write, search, list, quick-capture, delete. "
        "Vault lives at d:\\troikahermes-vault (also linked to Claude memory). "
        "Use this when Misha says 'запиши в obsidian / в заметку', 'найди в "
        "заметках', 'что я писал про X', 'напомни себе', 'сохрани идею'. "
        "For tiny voice captures use operation='quick' — it auto-files into "
        "inbox/ with timestamp + slug. For structured updates of an existing "
        "memory file use operation='write' (or 'append')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list", "read", "write", "create", "append", "search", "quick", "delete"],
                "description": "What to do with the vault.",
            },
            "path": {
                "type": "string",
                "description": "Relative path inside vault, e.g. 'project/foo.md' or 'inbox/idea'. .md extension auto-added.",
            },
            "folder": {
                "type": "string",
                "description": "Folder to list (for 'list') or to file into (for 'quick'). Default for quick: 'inbox'.",
            },
            "content": {
                "type": "string",
                "description": "Note body. Required for write/create/append/quick.",
            },
            "title": {
                "type": "string",
                "description": "Human title for quick-capture. Defaults to first line of content.",
            },
            "query": {
                "type": "string",
                "description": "Search string (case-insensitive, matches body + filename).",
            },
            "max_chars": {
                "type": "integer",
                "description": "Cap returned content for 'read' (default 20000).",
            },
        },
        "required": ["operation"],
    },
}


registry.register(
    name="obsidian_note",
    toolset="obsidian",
    schema=OBSIDIAN_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="🟪",
)
