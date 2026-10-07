"""Portable source projects with honest static diagnostics, without execution."""

import ast
import io
import json
from pathlib import PurePosixPath
import re
import zipfile


def build_project(args: dict) -> tuple[bytes, list[dict]]:
    files = args.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise ValueError("project requires 1 to 100 source files")
    output: dict[str, str] = {}
    diagnostics = []
    size = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("invalid project file")
        path = str(entry.get("path") or "").replace("\\", "/")
        parts = path.split("/")
        if (not path or len(path) > 240 or any(p in {"", ".", "..", ".git"} for p in parts)
                or any(re.search(r'[<>:"|?*\x00-\x1f]', p) or p.endswith((".", " ")) for p in parts)
                or any(re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p, re.I) for p in parts)
                or PurePosixPath(path).is_absolute() or path.casefold() in {p.casefold() for p in output}
                or any(p.casefold() in {".env", ".git", "id_rsa", "id_ed25519"} for p in parts)
                or path.casefold() == "troika-project.json"
                or any(path.casefold().startswith(p.casefold() + "/")
                       or p.casefold().startswith(path.casefold() + "/") for p in output)):
            raise ValueError("project path is unsafe or duplicated")
        content = entry.get("content")
        if not isinstance(content, str) or "\x00" in content:
            raise ValueError("project files must be UTF-8 text")
        size += len(content.encode("utf-8"))
        if size > 2 * 1024 * 1024:
            raise ValueError("project exceeds 2 MiB")
        output[path] = content
        check = {"path": path, "status": "not_checked", "scope": "none"}
        try:
            if path.endswith(".py"):
                check["scope"] = "python_syntax"
                ast.parse(content, filename=path)
                check.update(status="passed", scope="python_syntax")
            elif path.endswith(".json"):
                check["scope"] = "json_syntax"
                json.loads(content)
                check.update(status="passed", scope="json_syntax")
        except (SyntaxError, ValueError) as error:
            check.update(status="failed", message=str(error)[:500])
        diagnostics.append(check)
    manifest = {"version": 1, "title": str(args.get("title") or "Проект")[:200],
                "files": list(output), "checks": diagnostics,
                "execution": "not_run", "instructions": str(args.get("instructions") or "")[:8000]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in output.items():
            archive.writestr(path, content)
        archive.writestr("troika-project.json", json.dumps(manifest, ensure_ascii=False))
    return buffer.getvalue(), diagnostics
