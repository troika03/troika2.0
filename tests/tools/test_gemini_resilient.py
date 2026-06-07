"""Тесты resilient-обёртки кодер-движка: ретрай на malformed-флапах
gemini-2.5-flash и эскалация на gemini-2.5-pro.

Контекст: gemini-2.5-flash под нагрузкой реальных кодинг-задач регулярно
обрывается на «[ERROR] Invalid stream: ... malformed tool call», не дописывая
код → автопилот делал 0/N задач. Обёртка _run_gemini_resilient ретраит такие
фейлы и на последней попытке эскалирует на pro. См. autopilot-flash-invalid-stream.
"""
import asyncio

import pytest

from tools import gemini_code_tool as g


def test_malformed_regex_matches_invalid_stream():
    msg = "[ERROR] Invalid stream: The model returned an empty response or malformed tool call."
    assert g._MALFORMED_RE.search(msg)
    assert g._MALFORMED_RE.search("got a malformed tool call here")
    assert not g._MALFORMED_RE.search("ECONNRESET: socket hang up")


def _patch_run_gemini(monkeypatch, results, recorder):
    """Подменяет _run_gemini последовательностью результатов; пишет model в recorder.
    Не трогает файловую систему — _list_files мокаем пустым (нет прогресса),
    чтобы тестировать именно ветку ретраев."""
    seq = iter(results)

    async def fake_run_gemini(workspace, task, timeout, *, model=None, **kw):
        recorder.append(model or "default")
        return dict(next(seq))

    monkeypatch.setattr(g, "_run_gemini", fake_run_gemini)
    monkeypatch.setattr(g, "_list_files", lambda ws: [])  # нет файлового прогресса


def test_retries_then_escalates_to_pro(monkeypatch, tmp_path):
    """malformed без прогресса дважды → 3-я попытка на pro."""
    recorder = []
    _patch_run_gemini(monkeypatch, [
        {"ok": True, "malformed": True},   # attempt 1: flash флапнул
        {"ok": True, "malformed": True},   # attempt 2: flash снова флапнул
        {"ok": True, "malformed": False},  # attempt 3: pro отработал чисто
    ], recorder)

    res = asyncio.run(g._run_gemini_resilient(tmp_path, "task", 60))
    # последняя попытка должна была пойти на pro
    assert recorder == ["default", "default", g._ESCALATE_MODEL]
    assert res["attempts"] == 3
    assert res["model_used"] == g._ESCALATE_MODEL


def test_network_failure_not_retried(monkeypatch, tmp_path):
    """Сетевой стопор НЕ ретраим и НЕ эскалируем — отдаём наверх для автопилота."""
    recorder = []
    _patch_run_gemini(monkeypatch, [
        {"ok": False, "stalled": True, "stderr_tail": "ECONNRESET"},
    ], recorder)

    res = asyncio.run(g._run_gemini_resilient(tmp_path, "task", 60))
    assert recorder == ["default"]          # ровно одна попытка
    assert res["attempts"] == 1
    assert res.get("stalled") is True


def test_progress_accepts_even_with_malformed_tail(monkeypatch, tmp_path):
    """rc==0 + НОВЫЕ файлы + malformed в хвосте = успех (flash успел до обрыва)."""
    recorder = []

    async def fake_run_gemini(workspace, task, timeout, *, model=None, **kw):
        recorder.append(model or "default")
        # имитируем запись файла во время вызова
        snapshot["files"] = ["lib/main.dart"]
        return {"ok": True, "malformed": True}

    snapshot = {"files": []}
    monkeypatch.setattr(g, "_run_gemini", fake_run_gemini)
    # before=[] (до вызова), after=["lib/main.dart"] (после) → new_files=True
    monkeypatch.setattr(g, "_list_files", lambda ws: list(snapshot["files"]))

    res = asyncio.run(g._run_gemini_resilient(tmp_path, "task", 60))
    assert recorder == ["default"]          # не ретраим — новые файлы есть
    assert res["ok"] is True


def test_malformed_no_files_exhausts_then_returns_last(monkeypatch, tmp_path):
    """malformed без файлов на всех попытках (включая pro) → отдаём последний res."""
    recorder = []
    _patch_run_gemini(monkeypatch, [
        {"ok": True, "malformed": True},
        {"ok": True, "malformed": True},
        {"ok": True, "malformed": True},   # даже pro флапнул
    ], recorder)

    res = asyncio.run(g._run_gemini_resilient(tmp_path, "task", 60))
    assert recorder == ["default", "default", g._ESCALATE_MODEL]
    assert res["attempts"] == 3
    assert res["malformed"] is True
