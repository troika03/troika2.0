"""Тесты B2 — гибридный (fuzzy + семантический) memory_search и graceful fallback.

Семантику (sentence-transformers) НЕ грузим в тестах: мокаем semantic_scores,
чтобы проверять именно гибридную логику скоринга и то, что без семантики поиск
работает как раньше (ноль регрессии). См. memory_semantic / troika-memory-tools.
"""
import asyncio

import pytest

from tools import memory_search_tool as ms


def _make_vault(tmp_path, files: dict):
    """files: {relpath: (description, body)} → пишет md-файлы во временный vault."""
    for rel, (desc, body) in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = f"---\nname: {p.stem}\ndescription: {desc}\ntype: project\n---\n\n{body}\n"
        p.write_text(fm, encoding="utf-8")


def test_fallback_to_fuzzy_when_no_semantics(monkeypatch, tmp_path):
    """semantic_scores пуст (модели нет) → чистый лексический поиск, как раньше."""
    _make_vault(tmp_path, {
        "project/gemini-hang.md": ("gemini зависает headless, лечится taskkill",
                                   "CREATE_NO_WINDOW вешал gemini, фикс creationflags=0"),
        "project/voice.md": ("настройка записи голоса", "гейт recordUtterance мягкий"),
    })
    monkeypatch.setattr(ms, "_VAULT", tmp_path)
    monkeypatch.setattr("tools.memory_semantic.semantic_scores", lambda q: {}, raising=False)

    res = asyncio.run(ms._handle_search({"query": "taskkill gemini", "limit": 5}))
    assert res["ok"] is True
    assert res["semantic"] is False
    names = [r["name"] for r in res["results"]]
    assert "gemini-hang" in names  # лексическое совпадение по 'gemini'/'taskkill'


def test_semantic_pulls_doc_without_lexical_overlap(monkeypatch, tmp_path):
    """Семантика вытаскивает заметку БЕЗ общих слов с запросом."""
    _make_vault(tmp_path, {
        "project/gemini-hang.md": ("процесс кодера замирает и не отвечает",
                                   "приходится принудительно снимать задачу"),
        "project/voice.md": ("настройка записи голоса", "гейт recordUtterance"),
    })
    monkeypatch.setattr(ms, "_VAULT", tmp_path)
    # Запрос 'как починить зависший gemini' лексически НЕ пересекается с заметкой,
    # но семантически близок → высокий sim вытаскивает её через ветку sim>=0.45.
    fake = {"project/gemini-hang.md": 0.62, "project/voice.md": 0.12}
    monkeypatch.setattr("tools.memory_semantic.semantic_scores",
                        lambda q: fake, raising=False)

    res = asyncio.run(ms._handle_search({"query": "как починить зависший gemini",
                                         "limit": 5}))
    assert res["semantic"] is True
    top = res["results"][0]
    assert top["name"] == "gemini-hang"
    assert top["match"] in ("semantic", "hybrid")


def test_semantic_floor_filters_noise(monkeypatch, tmp_path):
    """Слабая семантика (ниже порога) не тащит нерелевантное и не даёт баллов."""
    _make_vault(tmp_path, {
        "project/a.md": ("совсем про другое", "ничего общего"),
    })
    monkeypatch.setattr(ms, "_VAULT", tmp_path)
    monkeypatch.setattr("tools.memory_semantic.semantic_scores",
                        lambda q: {"project/a.md": 0.18}, raising=False)

    res = asyncio.run(ms._handle_search({"query": "квантовая криптография", "limit": 5}))
    # ни лексики, ни уверенной семантики → пусто
    assert res["count"] == 0


def test_hybrid_boost_reorders(monkeypatch, tmp_path):
    """При равной слабой лексике семантический буст поднимает более релевантный."""
    _make_vault(tmp_path, {
        "project/match.md": ("настройка gemini", "gemini тут упоминается один раз gemini"),
        "project/other.md": ("настройка gemini", "gemini тут упоминается один раз gemini"),
    })
    monkeypatch.setattr(ms, "_VAULT", tmp_path)
    monkeypatch.setattr("tools.memory_semantic.semantic_scores",
                        lambda q: {"project/match.md": 0.7, "project/other.md": 0.31},
                        raising=False)

    res = asyncio.run(ms._handle_search({"query": "gemini", "limit": 5}))
    assert res["results"][0]["name"] == "match"  # семантический буст вывел вперёд
