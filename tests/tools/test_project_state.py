"""Тесты B2 — авто-саммари проекта в .STATE.md и его выжимка для инжекта."""
from pathlib import Path

from tools import project_tool as p


def test_write_and_read_state(tmp_path, monkeypatch):
    # минимальный .project.json чтобы _read_meta дал name/phase
    (tmp_path / ".project.json").write_text(
        '{"name": "Калькулятор чаевых", "phase": "build"}', encoding="utf-8")

    p._write_project_state(
        tmp_path,
        done=["T1.1 ввод суммы", "T1.2 расчёт"],
        failed=["T3.4 экспорт"],
        remaining=5,
        build={"checked": True, "ok": True, "fixed": True},
        deploy_url=None,
        paused_network=False,
    )

    state = (tmp_path / ".STATE.md").read_text(encoding="utf-8")
    assert "Калькулятор чаевых" in state
    assert "сделано задач за последний прогон: 2" in state
    assert "осталось задач: 5" in state
    assert "не вышли: 1" in state
    assert "сборка: ОК" in state

    brief = p._read_project_state_brief(tmp_path)
    assert "осталось задач: 5" in brief
    assert brief.startswith("фаза")  # служебные строки (# / _обновлено_) отброшены


def test_state_build_failed_message(tmp_path):
    (tmp_path / ".project.json").write_text('{"name": "X", "phase": "build"}',
                                            encoding="utf-8")
    p._write_project_state(
        tmp_path, done=["A"], failed=[], remaining=0,
        build={"checked": True, "ok": False, "fixed": True},
    )
    state = (tmp_path / ".STATE.md").read_text(encoding="utf-8")
    assert "ЕСТЬ ОШИБКИ" in state


def test_read_brief_missing_file(tmp_path):
    assert p._read_project_state_brief(tmp_path) == ""
