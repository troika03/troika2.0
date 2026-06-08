"""Тесты B3 — web_research (голосовой «разберись и ответь коротко»).

Сеть и LLM НЕ трогаем: мокаем web_search_tool / web_extract_tool / синтез и
check_web_api_key. Проверяем оркестрацию (search→extract→синтез), деградации
(нет ключа, пустая выдача, extract упал, нет LLM) и форму ответа для голоса.

Важно: tool импортирует функции в свой namespace (from tools.web_tools import ...),
поэтому патчим их на tools.web_research_tool, а не на tools.web_tools.
"""
import asyncio
import json

import pytest

from tools import web_research_tool as wr


def _run(args):
    return json.loads(asyncio.run(wr._handle(args)))


def _search_json(items):
    return json.dumps({"success": True, "data": {"web": items}})


def _extract_json(results):
    return json.dumps({"results": results})


def test_missing_question():
    res = _run({})
    assert res["ok"] is False
    assert "say_to_user" in res


def test_no_api_key(monkeypatch):
    monkeypatch.setattr(wr, "check_web_api_key", lambda: False)
    res = _run({"question": "что с курсом биткоина"})
    assert res["ok"] is False
    assert res["error"] == "web_api_not_configured"
    assert "не настроен" in res["say_to_user"].lower()


def test_empty_search_results(monkeypatch):
    monkeypatch.setattr(wr, "check_web_api_key", lambda: True)
    monkeypatch.setattr(wr, "web_search_tool", lambda q, limit=5: _search_json([]))
    res = _run({"question": "абракадабра несуществующее"})
    assert res["ok"] is True
    assert res["sources"] == []
    assert "ничего не нашёл" in res["say_to_user"].lower()


def test_search_provider_not_configured(monkeypatch):
    """success:false от провайдера → ok=False с честной ошибкой, НЕ «ничего не нашёл»."""
    monkeypatch.setattr(wr, "check_web_api_key", lambda: True)
    monkeypatch.setattr(wr, "web_search_tool", lambda q, limit=5: json.dumps(
        {"success": False, "error": "No web search provider configured. Run `hermes tools`."}))
    res = _run({"question": "что угодно"})
    assert res["ok"] is False
    assert "provider" in res["error"].lower()
    assert "не настроен" in res["say_to_user"].lower()


def test_happy_path_synthesizes_spoken_answer(monkeypatch):
    monkeypatch.setattr(wr, "check_web_api_key", lambda: True)
    monkeypatch.setattr(wr, "web_search_tool", lambda q, limit=5: _search_json([
        {"title": "CoinDesk BTC", "url": "https://www.coindesk.com/btc", "description": "Bitcoin price today"},
        {"title": "Binance", "url": "https://binance.com/price", "description": "BTC/USDT"},
    ]))

    async def fake_extract(urls, fmt):
        return _extract_json([
            {"url": "https://www.coindesk.com/btc", "title": "CoinDesk BTC",
             "content": "Bitcoin торгуется около 68 тысяч долларов на сегодня."},
        ])
    monkeypatch.setattr(wr, "web_extract_tool", fake_extract)

    async def fake_synth(question, pages, snippets):
        # проверим, что в синтез реально пришёл контент страницы
        assert pages and "68" in pages[0]["content"]
        return "Биткоин сейчас торгуется примерно по шестьдесят восемь тысяч долларов."
    monkeypatch.setattr(wr, "_synthesize", fake_synth)

    res = _run({"question": "какой сейчас курс биткоина"})
    assert res["ok"] is True
    assert res["synthesized"] is True
    assert res["pages_read"] == 1
    assert "шестьдесят восемь" in res["say_to_user"]
    assert "coindesk.com" in res["sources"]


def test_extract_fails_falls_back_to_snippets(monkeypatch):
    monkeypatch.setattr(wr, "check_web_api_key", lambda: True)
    monkeypatch.setattr(wr, "web_search_tool", lambda q, limit=5: _search_json([
        {"title": "Источник", "url": "https://example.com/a", "description": "Краткий ответ из сниппета."},
    ]))

    async def boom(urls, fmt):
        raise RuntimeError("extract backend down")
    monkeypatch.setattr(wr, "web_extract_tool", boom)

    async def fake_synth(question, pages, snippets):
        # extract упал → pages пуст, синтез идёт из сниппетов
        assert pages == []
        assert snippets and snippets[0]["description"]
        return "Короткий ответ по сниппетам."
    monkeypatch.setattr(wr, "_synthesize", fake_synth)

    res = _run({"question": "вопрос"})
    assert res["ok"] is True
    assert res["pages_read"] == 0
    assert res["say_to_user"] == "Короткий ответ по сниппетам."
    assert res["sources"] == ["example.com"]


def test_no_llm_uses_snippet_fallback(monkeypatch):
    """Синтез вернул None (нет auxiliary-модели) → ответ из сниппетов, ok=True."""
    monkeypatch.setattr(wr, "check_web_api_key", lambda: True)
    monkeypatch.setattr(wr, "web_search_tool", lambda q, limit=5: _search_json([
        {"title": "T1", "url": "https://a.com/x", "description": "Первый факт по теме."},
        {"title": "T2", "url": "https://b.com/y", "description": "Второй факт по теме."},
    ]))

    async def fake_extract(urls, fmt):
        return _extract_json([])  # пусто
    monkeypatch.setattr(wr, "web_extract_tool", fake_extract)

    async def no_synth(question, pages, snippets):
        return None
    monkeypatch.setattr(wr, "_synthesize", no_synth)

    res = _run({"question": "тема"})
    assert res["ok"] is True
    assert res["synthesized"] is False
    assert "факт по теме" in res["say_to_user"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
