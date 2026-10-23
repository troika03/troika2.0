"""Search snippets prove reading results, not fetching an external page."""

import json

import pytest

from troika_product.completion import CompletionEvidence


URL = "https://example.com/article"
QUERY = "synthetic public article"
RESULT = {
    "title": "Synthetic public article",
    "url": URL,
    "description": "A synthetic search snippet. The page body was not fetched.",
    "position": 1,
}


def search_receipt():
    """Use the shape returned by SearXNGWebSearchProvider.search."""
    return {"success": True, "data": {"web": [dict(RESULT)]}}


def record_search(evidence, receipt=None):
    evidence.record("web_search", {"query": QUERY}, receipt or search_receipt())


@pytest.mark.parametrize("receipt", [
    search_receipt(),
    {"success": True, "data": {"web": []}},
    {"success": True, "data": {"web": [dict(RESULT), {
        "title": "Unavailable result", "url": "https://example.com/unavailable",
        "description": "", "position": 2,
    }]}},
    {"success": False, "data": {"web": [dict(RESULT)]}, "error": "synthetic_search_failed"},
])
@pytest.mark.parametrize("claim", [
    "Я прочитала страницу сайта.",
    f"Я прочитала страницу {URL}.",
    "Я прочитала страницу сайта и результаты поиска.",
])
def test_search_receipts_never_prove_an_external_page_was_read(receipt, claim):
    evidence = CompletionEvidence()
    record_search(evidence, receipt)
    assert evidence.unsupported(claim, f"Прочитай страницу {URL}")


@pytest.mark.parametrize("claim", [
    "Я прочитала результаты поиска.",
    "Я посмотрела сниппеты поисковой выдачи.",
    "По найденным сниппетам: полный текст требует отдельной проверки.",
    "Я прочитала результаты поиска сайта example.com.",
])
def test_search_receipt_allows_result_reading_and_snippet_disclosure(claim):
    evidence = CompletionEvidence()
    record_search(evidence)
    assert not evidence.unsupported(claim)


def test_empty_search_does_not_prove_reading_result_content():
    evidence = CompletionEvidence()
    record_search(evidence, {"success": True, "data": {"web": []}})
    assert evidence.unsupported("Я прочитала результаты поиска.")
    assert not evidence.unsupported("Поиск не дал результатов.")


def test_actual_extracted_page_content_proves_page_reading():
    evidence = CompletionEvidence()
    evidence.record("web_extract", {"urls": [URL]}, {
        "results": [{"url": URL, "title": "Synthetic article",
                     "content": "Synthetic extracted article body.", "error": None}],
    })
    assert not evidence.unsupported("Я прочитала страницу сайта.")


@pytest.mark.parametrize("receipt", [
    {"results": []},
    {"results": [{"url": URL, "content": "", "error": "synthetic_fetch_failed"}]},
    {"success": False, "results": [{"url": URL, "content": "Stale partial text", "error": None}]},
])
def test_unsuccessful_extract_does_not_prove_page_reading(receipt):
    evidence = CompletionEvidence()
    evidence.record("web_extract", {"urls": [URL]}, receipt)
    assert evidence.unsupported("Я прочитала страницу сайта.")


@pytest.mark.parametrize("use_search", [False, True])
@pytest.mark.parametrize("claim", [
    "Я прочитала присланную статью.",
    "Я изучила предоставленный текст.",
])
def test_provided_article_and_text_do_not_require_a_web_receipt(use_search, claim):
    evidence = CompletionEvidence()
    if use_search:
        record_search(evidence)
    assert not evidence.unsupported(claim, "Прочитай присланный текст: это синтетическая статья о поездке.")


@pytest.mark.parametrize("wrap_untrusted", [False, True])
@pytest.mark.parametrize("tool,receipt,allows_page", [
    ("web_search", search_receipt(), False),
    ("web_extract", {"results": [{"url": URL, "content": "Synthetic article body", "error": None}]}, True),
])
def test_routed_receipts_preserve_search_and_page_evidence(wrap_untrusted, tool, receipt, allows_page):
    arguments = {"query": QUERY} if tool == "web_search" else {"urls": [URL]}
    envelope = json.dumps({"ok": True, "routed_tool": tool, "result": receipt})
    if wrap_untrusted:
        from agent.tool_dispatch_helpers import _maybe_wrap_untrusted

        envelope = _maybe_wrap_untrusted("web_search", envelope)
        assert envelope.startswith('<untrusted_tool_result source="web_search">')
    evidence = CompletionEvidence()
    evidence.record("troika_tool_call", {"tool": tool, "arguments": arguments}, envelope)
    assert evidence.unsupported("Я прочитала страницу сайта.") is not allows_page


@pytest.mark.parametrize("filename,claim", [
    ("report.docx", "Документ с результатами поиска создан."),
    ("snippets.docx", "Файл snippets.docx создан."),
])
def test_file_receipt_proves_creation_when_search_terms_describe_the_file(filename, claim):
    evidence = CompletionEvidence()
    evidence.record("troika_create_docx", {"title": "Synthetic report"}, {
        "ok": True, "artifact": {"id": "synthetic-document", "filename": filename},
    })
    assert not evidence.unsupported(claim)
    assert evidence.unsupported("Я прочитала страницу сайта.")


def test_file_replace_receipt_proves_update_of_a_snippet_named_file():
    evidence = CompletionEvidence()
    evidence.record("troika_files", {"action": "replace", "path": "snippets.txt"}, {
        "ok": True, "entry": {"path": "snippets.txt"},
    })
    assert not evidence.unsupported("Файл snippets.txt обновлён.")
    assert evidence.unsupported("Я прочитала страницу сайта.")
