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


# ── Seed green .env (LLM-ключи проходят, платформенные токены — нет) ───────

def test_seed_green_env_filters_platform_and_infra_keys(tmp_path, monkeypatch):
    """seed'алка LIVE ~/.troika/.env → green .env должна пропустить LLM-ключи
    (без них gateway висит) и вырезать платформенные токены (иначе green
    попробует подключиться к боевому Telegram), API_SERVER_* (мы задаём свои),
    STT_*/TERMINAL_*/MESSAGING_*/WEBHOOK_* (не нужны/deprecated)."""
    from tools import self_improve_verify as siv

    live_home = tmp_path / "live"
    live_home.mkdir()
    (live_home / ".env").write_text(
        "# comment line\n"
        "OPENROUTER_API_KEY=or-abc\n"
        "GROQ_API_KEY=gsk-xyz\n"
        "HERMES_API_KEY=hak-123\n"
        "STITCH_API_KEY=st-1\n"
        "\n"
        "TELEGRAM_BOT_TOKEN=tg-secret\n"
        "TELEGRAM_ALLOWED_USERS=1,2,3\n"
        "DISCORD_BOT_TOKEN=dc-secret\n"
        "SLACK_BOT_TOKEN=sl-secret\n"
        "WHATSAPP_TOKEN=wa-secret\n"
        "TWILIO_ACCOUNT_SID=twx\n"
        "\n"
        "API_SERVER_ENABLED=true\n"
        "API_SERVER_HOST=0.0.0.0\n"
        "API_SERVER_KEY=live-key\n"
        "API_SERVER_PORT=8642\n"
        "\n"
        "STT_BACKEND=groq\n"
        "STT_PROXY_PORT=17999\n"
        "TERMINAL_CWD=D:\\\\some\\\\path\n"
        "MESSAGING_CWD=D:\\\\other\n"
        "WEBHOOK_SECRET=hook-secret\n",
        encoding="utf-8",
    )
    green_home = tmp_path / "green"
    green_home.mkdir()

    monkeypatch.setenv("HERMES_HOME", str(live_home))
    monkeypatch.setattr(siv, "GREEN_HERMES_HOME", green_home)

    siv._seed_green_env_file()

    dst = green_home / ".env"
    assert dst.exists()
    content = dst.read_text(encoding="utf-8")
    kept = {
        line.split("=", 1)[0]
        for line in content.splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    }

    for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "HERMES_API_KEY", "STITCH_API_KEY"):
        assert k in kept, f"{k} должен остаться (LLM-ключ)"

    for k in (
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
        "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "WHATSAPP_TOKEN",
        "TWILIO_ACCOUNT_SID",
        "API_SERVER_ENABLED", "API_SERVER_HOST", "API_SERVER_KEY", "API_SERVER_PORT",
        "STT_BACKEND", "STT_PROXY_PORT",
        "TERMINAL_CWD", "MESSAGING_CWD", "WEBHOOK_SECRET",
    ):
        assert k not in kept, f"{k} должен быть отфильтрован (платформа/инфра)"


def test_seed_green_env_no_source(tmp_path, monkeypatch):
    """Если LIVE .env отсутствует — тихо no-op, не падаем."""
    from tools import self_improve_verify as siv

    live_home = tmp_path / "live"
    live_home.mkdir()
    green_home = tmp_path / "green"
    green_home.mkdir()

    monkeypatch.setenv("HERMES_HOME", str(live_home))
    monkeypatch.setattr(siv, "GREEN_HERMES_HOME", green_home)

    siv._seed_green_env_file()
    assert not (green_home / ".env").exists()


def test_green_env_pops_terminal_and_stt(monkeypatch):
    """_green_env НЕ должен наследовать TERMINAL_CWD/MESSAGING_CWD/STT_BACKEND
    из родительского окружения — иначе green видит устаревшие пути и лишний STT."""
    from tools import self_improve_verify as siv

    monkeypatch.setenv("TERMINAL_CWD", "D:\\\\parent\\\\cwd")
    monkeypatch.setenv("MESSAGING_CWD", "D:\\\\parent\\\\msg")
    monkeypatch.setenv("STT_BACKEND", "groq")
    monkeypatch.setenv("STT_PROXY_PORT", "17999")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-secret")

    env = siv._green_env()

    assert "TERMINAL_CWD" not in env
    assert "MESSAGING_CWD" not in env
    assert "STT_BACKEND" not in env
    assert "STT_PROXY_PORT" not in env
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert env["API_SERVER_ENABLED"] == "true"
    assert env["API_SERVER_PORT"] == str(siv.GREEN_API_PORT)
