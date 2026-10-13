"""Portable source projects with honest static diagnostics, without execution."""

import ast
import io
import json
from pathlib import PurePosixPath
import re
import zipfile


DEVELOPMENT_GUIDANCE = """
Для разработки сначала загрузи capability development и вызови
troika_create_project с task: передай полную задачу и требования пользователя.
API-разработчик составляет план, пишет каждый файл, проверяет весь проект
моделью и делает до трёх исправлений. Не ограничивай задачу двумя файлами.
Для изменения проекта передай также текущие files. Основная проверка — ревью
моделью; выбор телефона или ПК не нужен. Запуск тестов на устройстве — отдельное
действие по запросу пользователя. Без task инструмент только упаковывает files.
Результат включает полный исходный код, README.md с запуском и тесты поведения,
проверяющие реализацию. Hello World, пустые файлы, TODO и описание вместо
кода не выполняют задачу. При отказе упаковки исправь состав проекта и
повтори вызов, а не объявляй проект готовым.
Тесты импортируют или загружают настоящие модули реализации, а не копируют
проверяемый алгоритм. Для веб-приложения с локальными JavaScript-тестами
используй модуль логики, совместимый с браузером и require: экспортируй
module.exports только при наличии module. Обработчики DOM держи отдельно.
Не подменяй работающие тесты проверкой assert(true).
Сохраняй назначение и все требования пользователя. Веб-приложение должно
иметь браузерный интерфейс, точку входа и работающую логику; не заменяй его
консольной программой. Выбранный Python/JavaScript задаёт среду проверки,
а не отменяет интерфейс, HTML/CSS или функции. Для простого веб-приложения
предпочитай HTML/CSS/JavaScript без сборки и внешних зависимостей. Логику
выделяй в модуль, доступный браузеру и локальным тестам. Проверенные тесты
логики не доказывают проверку браузерного интерфейса. Не запускай код на сервере.
"""


_SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
                    ".html", ".htm", ".css", ".java", ".kt", ".cs", ".cpp",
                    ".c", ".go", ".rs", ".swift", ".dart", ".vue", ".svelte"}


def _test_file(path: str) -> bool:
    item = PurePosixPath(path.lower())
    return (item.suffix in _SOURCE_SUFFIXES and
            (item.stem in {"test", "tests"} or item.name.startswith("test_") or ".test." in item.name or
             ".spec." in item.name or any(p in {"test", "tests", "__tests__"} for p in item.parts)))


def _hello_only(path: str, content: str) -> bool:
    """Recognise the trivial greeting stub, without judging arbitrary programs."""
    greeting = r"(?:hello[ ,]*world!?|привет[ ,]*мир!?)"
    if PurePosixPath(path).suffix.lower() == ".py":
        try:
            statements = ast.parse(content).body
            return bool(statements) and all(
                isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                and isinstance(s.value.func, ast.Name) and s.value.func.id == "print"
                and len(s.value.args) == 1 and isinstance(s.value.args[0], ast.Constant)
                and isinstance(s.value.args[0].value, str)
                and re.fullmatch(greeting, s.value.args[0].value.strip(), re.I)
                for s in statements)
        except SyntaxError:
            return False
    return bool(re.fullmatch(
        rf"\s*(?:console\.log\(\s*['\"]{greeting}['\"]\s*\)\s*;?\s*|{greeting}\s*)",
        content, re.I))


def validate_source_project(files: dict[str, str]) -> None:
    """Reject incomplete deliverables; this is not functional verification."""
    sources = {p: c for p, c in files.items()
               if PurePosixPath(p).suffix.lower() in _SOURCE_SUFFIXES and not _test_file(p)}
    missing = []
    if not any(c.strip() and not _hello_only(p, c) for p, c in sources.items()):
        missing.append("implemented source code (not an empty file or Hello World)")
    if not any(PurePosixPath(p).name.lower() == "readme.md" and c.strip() for p, c in files.items()):
        missing.append("README.md with run instructions")
    if not any(_test_file(p) and c.strip() for p, c in files.items()):
        missing.append("behavior test files for the implementation")
    if missing:
        raise ValueError("Incomplete source project: include " + "; ".join(missing) +
                         ". Write the complete requested implementation and retry; no ZIP was prepared.")


def build_project(args: dict, *, require_complete: bool = False) -> tuple[bytes, list[dict]]:
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
    if require_complete:
        validate_source_project(output)
    manifest = {"version": 1, "title": str(args.get("title") or "Проект")[:200],
                "files": list(output), "checks": diagnostics,
                "execution": "not_run", "instructions": str(args.get("instructions") or "")[:8000]}
    if args.get("review") is not None:
        manifest["review"] = args["review"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in output.items():
            archive.writestr(path, content)
        archive.writestr("troika-project.json", json.dumps(manifest, ensure_ascii=False))
    return buffer.getvalue(), diagnostics
