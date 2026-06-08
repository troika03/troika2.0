"""Тесты финального build-gate автопилота (B1): «проект реально собирается»
перед деплоем/итогом. Красный flutter analyze → fix-pass на pro → перепроверка.

Контекст: в тестах 2-5 июня автопилот рапортовал «готово» поверх несобираемого
кода. _final_build_gate один раз гоняет _static_check по типу проекта и честно
отдаёт статус сборки. См. autopilot-flash-invalid-stream / troika-autopilot-robustness.
"""
import asyncio

import pytest

from tools import project_tool as p


def _patch_static_check(monkeypatch, results):
    """Подменяет _static_check последовательностью результатов (по вызовам)."""
    seq = iter(results)

    async def fake_static_check(product_dir, timeout=240):
        return dict(next(seq))

    monkeypatch.setattr(p, "_static_check", fake_static_check)


def _patch_resilient(monkeypatch, recorder):
    async def fake_resilient(workspace, task, timeout, **kw):
        recorder.append(kw.get("escalate_model") or "default")
        return {"ok": True}

    monkeypatch.setattr(p, "_run_gemini_resilient", fake_resilient, raising=False)
    # _final_build_gate импортирует _run_gemini_resilient локально из модуля gemini_code_tool
    from tools import gemini_code_tool as g
    monkeypatch.setattr(g, "_run_gemini_resilient", fake_resilient)


def test_no_local_check_does_not_block(monkeypatch, tmp_path):
    """Тип проекта без локальной проверки (напр. чистый web) → checked=False, не врём."""
    _patch_static_check(monkeypatch, [{"ran": False, "ok": True, "kind": "none"}])
    recorder = []
    _patch_resilient(monkeypatch, recorder)

    res = asyncio.run(p._final_build_gate(tmp_path, 300))
    assert res["checked"] is False
    assert res["ok"] is True
    assert recorder == []  # fix-pass не запускался


def test_green_first_pass_no_fix(monkeypatch, tmp_path):
    """Анализ зелёный сразу → ok, без fix-pass."""
    _patch_static_check(monkeypatch, [
        {"ran": True, "ok": True, "kind": "flutter", "errors": ""},
    ])
    recorder = []
    _patch_resilient(monkeypatch, recorder)

    res = asyncio.run(p._final_build_gate(tmp_path, 300))
    assert res == {"checked": True, "ok": True, "kind": "flutter",
                   "fixed": False, "errors_tail": ""}
    assert recorder == []


def test_red_then_fixed_green(monkeypatch, tmp_path):
    """Красный → fix-pass на pro → перепроверка зелёная → ok+fixed."""
    _patch_static_check(monkeypatch, [
        {"ran": True, "ok": False, "kind": "flutter", "errors": "error: undefined name 'foo'"},
        {"ran": True, "ok": True, "kind": "flutter", "errors": ""},  # recheck
    ])
    recorder = []
    _patch_resilient(monkeypatch, recorder)

    res = asyncio.run(p._final_build_gate(tmp_path, 300))
    assert res["checked"] is True
    assert res["ok"] is True
    assert res["fixed"] is True
    assert recorder == ["gemini-2.5-pro"]  # fix-pass эскалирован на pro


def test_red_then_still_red(monkeypatch, tmp_path):
    """Красный → fix-pass → всё ещё красный → ok=False + хвост ошибок для доработки."""
    _patch_static_check(monkeypatch, [
        {"ran": True, "ok": False, "kind": "flutter", "errors": "error: A"},
        {"ran": True, "ok": False, "kind": "flutter", "errors": "error: B still broken"},
    ])
    recorder = []
    _patch_resilient(monkeypatch, recorder)

    res = asyncio.run(p._final_build_gate(tmp_path, 300))
    assert res["checked"] is True
    assert res["ok"] is False
    assert res["fixed"] is True
    assert "still broken" in res["errors_tail"]
