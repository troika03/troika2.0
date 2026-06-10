"""Юнит-тесты слоя проверки самоулучшения (tools/self_improve_verify.py).

Без gateway/песочницы — только чистые функции: классификатор риска, frozen-core
гарантия, вывод pytest-k и модулей из изменённых файлов. Живой green-прогон —
отдельный integration-тест (по умолчанию исключён `-m 'not integration'`).
"""

import pytest

from tools.self_improve_verify import (
    classify_risk,
    _touched_tool_modules,
    _pytest_k_from_files,
    _count_changed_lines,
)
from tools.self_improve_tool import _FORBIDDEN_RE


# ── B. Классификатор риска ──────────────────────────────────────────────────

_NEW_TOOL_DIFF = (
    "diff --git a/tools/hello_tool.py b/tools/hello_tool.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n+++ b/tools/hello_tool.py\n"
    "+def hello():\n+    return 'hi'\n"
)


def test_new_tool_is_safe():
    r = classify_risk(["tools/hello_tool.py"], _NEW_TOOL_DIFF)
    assert r["risk"] == "safe"


def test_skill_is_safe():
    r = classify_risk(["skills/my-skill/SKILL.md"], "diff\n+text")
    assert r["risk"] == "safe"


def test_doc_is_safe():
    r = classify_risk(["README.md"], "diff\n+text")
    assert r["risk"] == "safe"


@pytest.mark.parametrize("path", [
    "tools/memory_search_tool.py",   # память
    "tools/some_auth_tool.py",       # auth
    "tools/http_client_tool.py",     # сеть
    "tools/billing_tool.py",         # деньги
    "tools/session_tool.py",         # сессии
])
def test_sensitive_paths_are_risky(path):
    r = classify_risk([path], "diff\n+x")
    assert r["risk"] == "risky", r


def test_outside_safe_dirs_is_risky():
    r = classify_risk(["agent/core.py"], "diff\n+x")
    assert r["risk"] == "risky"


def test_large_edit_of_existing_file_is_risky():
    # Существующий файл (нет 'new file mode'), много строк → risky.
    big = "diff --git a/tools/foo_tool.py b/tools/foo_tool.py\n"
    big += "--- a/tools/foo_tool.py\n+++ b/tools/foo_tool.py\n"
    big += "\n".join(f"+line{i}" for i in range(80))
    r = classify_risk(["tools/foo_tool.py"], big)
    assert r["risk"] == "risky"


def test_large_new_file_still_safe():
    # Новый файл может быть большим — это не правка существующего поведения.
    big = "diff --git a/tools/foo_tool.py b/tools/foo_tool.py\nnew file mode 100644\n"
    big += "--- /dev/null\n+++ b/tools/foo_tool.py\n"
    big += "\n".join(f"+line{i}" for i in range(80))
    r = classify_risk(["tools/foo_tool.py"], big)
    assert r["risk"] == "safe", r


def test_empty_files_is_risky():
    assert classify_risk([], "")["risk"] == "risky"


def test_mixed_one_risky_makes_all_risky():
    r = classify_risk(["tools/hello_tool.py", "tools/auth_tool.py"], _NEW_TOOL_DIFF)
    assert r["risk"] == "risky"


# ── D. Frozen-core: движок не правит сам себя ───────────────────────────────

@pytest.mark.parametrize("path", [
    "tools/self_improve_verify.py",
    "tools/self_improve_watcher.py",
    "tools/self_improve_tool.py",
    "tools/registry.py",
    "tools/job_runner.py",
    "gateway/run.py",
    "cli.py",
    ".env",
])
def test_engine_and_core_paths_are_forbidden(path):
    assert _FORBIDDEN_RE.match(path), f"should be forbidden: {path}"


def test_ordinary_tool_not_forbidden():
    assert not _FORBIDDEN_RE.match("tools/hello_tool.py")


# ── Хелперы вывода тестов/модулей ───────────────────────────────────────────

def test_touched_tool_modules():
    mods = _touched_tool_modules(["tools/foo_tool.py", "skills/x.md", "tools/bar.py"])
    assert mods == ["tools.foo_tool", "tools.bar"]


def test_pytest_k_from_files():
    assert _pytest_k_from_files(["tools/foo_tool.py"]) == "foo"
    assert _pytest_k_from_files(["tools/bar.py"]) == "bar"
    # без tools-файлов → None
    assert _pytest_k_from_files(["README.md"]) is None


def test_count_changed_lines():
    diff = "+++ b/x\n+added\n-removed\n--- a/x\n unchanged\n"
    # +added и -removed считаются; +++/--- нет
    assert _count_changed_lines(diff) == 2
