import pytest

from troika_product.completion import CompletionEvidence


def test_ram_project_cannot_claim_device_save_or_executed_tests():
    evidence = CompletionEvidence()
    evidence.record("troika_create_project", {"title": "Код"}, {
        "ok": True, "artifact": {"id": "delivery_x", "filename": "code.zip", "storage": "device"}})
    assert evidence.unsupported("Файл сохранён на устройстве.")
    assert evidence.unsupported("Тесты прошли.")
    assert not evidence.unsupported("Файл подготовлен.")
    assert not evidence.unsupported("Проект подготовлен.")
    assert not evidence.may_retry()


def test_api_review_receipt_allows_source_review_but_not_execution_claims():
    evidence = CompletionEvidence()
    evidence.record("troika_create_project", {"title": "Код", "task": "Write"}, {
        "ok": True, "artifact": {"id": "delivery_x", "filename": "code.zip", "storage": "device"},
        "review": {"method": "api_model_review", "execution": "not_run", "reviewed_files": ["main.py"],
                   "status": "passed"}})
    assert not evidence.unsupported("Модель проверила проект.")
    assert not evidence.unsupported("Модель проверила файлы.")
    assert evidence.unsupported("Тесты прошли.")
    assert evidence.unsupported("Проект сохранён на телефоне.")


@pytest.mark.parametrize("text", [
    "Готово!", "Я создала документ.", "Файл сохранён.",
    "Напоминание установлено.", "Я запомнила это в памяти.",
    "Сообщение отправлено.", "Приложение открыто.",
])
def test_no_receipt_blocks_completion(text):
    assert CompletionEvidence().unsupported(text, "Создай документ и напомни завтра")


@pytest.mark.parametrize("text", [
    "Привет!", "Не удалось создать документ.", "Файл не создан.",
    "Я не сохранила файл.", "Если файл сохранён, открой его.",
    "Я создала стихотворение: зима пришла.", "Проверила: два плюс два — четыре.",
    "Создай файл, затем скажи «готово».",
])
def test_conversation_instructions_and_negative_reports_pass(text):
    assert not CompletionEvidence().unsupported(text, "Поговорим")


def document(evidence, **extra):
    evidence.record("troika_create_docx", {"title": "Отчёт"}, {
        "ok": True, "artifact": {"id": "art_1", "filename": "report.docx"}, **extra,
    })


def test_successful_document_receipt_allows_completion():
    evidence = CompletionEvidence()
    document(evidence)
    assert not evidence.unsupported("Готово, документ создан.", "Создай документ")


@pytest.mark.parametrize("payload", [
    {"ok": False, "error": "approval_denied"},
    {"ok": True, "error": "verification_failed"},
    {"ok": True, "status": "queued"},
    {"success": "true"}, "Готово", {},
])
def test_error_pending_or_unstructured_receipt_does_not_prove_success(payload):
    evidence = CompletionEvidence()
    evidence.record("android_open_app", {"app": "browser"}, payload)
    assert evidence.unsupported("Готово, приложение открыто.", "Открой браузер")


def test_unrelated_success_cannot_cover_failed_action():
    evidence = CompletionEvidence()
    document(evidence)
    evidence.record("troika_assistant", {"action": "reminder_schedule"}, {"ok": False})
    assert evidence.unsupported("Всё готово!", "Создай документ и напоминание")
    assert evidence.unsupported("Напоминание установлено.")
    assert not evidence.unsupported("Документ создан. Напоминание не установлено.")


def test_listing_tasks_does_not_prove_task_creation():
    evidence = CompletionEvidence()
    evidence.record("troika_assistant", {"action": "task_list"}, {"ok": True, "result": []})
    assert evidence.unsupported("Задача создана.")


def test_receipt_without_persisted_identifier_is_not_proof():
    evidence = CompletionEvidence()
    evidence.record("troika_assistant", {"action": "task_add"}, {
        "ok": True, "action": "task_add", "result": {"title": "Задача"},
    })
    assert evidence.unsupported("Задача создана.")


def test_retry_supersedes_only_same_target():
    evidence = CompletionEvidence()
    evidence.record("troika_files", {"action": "write", "path": "a.txt"}, {"ok": False})
    evidence.record("troika_files", {"action": "write", "path": "b.txt"}, {"ok": True})
    assert evidence.unsupported("Готово!")
    evidence.record("troika_files", {"action": "write", "path": "a.txt"}, {"ok": True})
    assert not evidence.unsupported("Готово!")


def test_disabled_delivery_is_not_a_reminder_promise():
    evidence = CompletionEvidence()
    evidence.record("troika_assistant", {"action": "reminder_schedule"}, {
        "ok": True, "action": "reminder_schedule",
        "result": {"message_id": "msg_1", "delivery_enabled": False},
    })
    assert evidence.unsupported("Готово, напоминание установлено.")
    assert "доставка отключена" in evidence.fallback()


def test_reminder_on_phone_is_not_a_second_device_action():
    evidence = CompletionEvidence()
    evidence.record("troika_reminder", {"title": "Вода", "delay_seconds": 120}, {
        "ok": True, "action": "reminder_schedule",
        "result": {"message_id": "msg_1", "title": "Вода", "due_at": "2026-10-03T10:02:00Z", "delivery_enabled": True},
    })
    assert not evidence.unsupported("Напоминание установлено на телефоне. Напомню через две минуты.")
    assert "Вода" in evidence.fallback()
    assert "10:02" in evidence.fallback()
    assert "Часть" not in evidence.fallback()
    assert evidence.unsupported("Напоминание установлено и приложение открыто.")


def test_launched_timer_has_set_receipt():
    evidence = CompletionEvidence()
    evidence.record("android_set_timer", {"seconds": 120}, {"ok": True})
    assert not evidence.unsupported("Таймер на телефоне запущен.")


def test_saved_html_proves_created_website_but_not_publication():
    evidence = CompletionEvidence()
    evidence.record("troika_files", {"action": "write", "path": "coffee.html"}, {"ok": True, "entry": {"path": "coffee.html"}})
    assert not evidence.unsupported("Файл сайта coffee.html создан.")
    assert not evidence.unsupported("Сайт создан и сохранён в coffee.html.")
    assert evidence.unsupported("Файл missing.html создан.")
    assert evidence.unsupported("Сайт опубликован.")


def test_opening_search_is_not_reading_results():
    evidence = CompletionEvidence()
    evidence.record("android_web_search", {"query": "weather"}, {"ok": True})
    assert evidence.unsupported("Я прочитала результаты поиска.")


def test_separate_ledgers_do_not_reuse_previous_turn():
    first, second = CompletionEvidence(), CompletionEvidence()
    document(first)
    assert second.unsupported("Документ создан.", "Создай документ")


def test_success_for_one_domain_does_not_prove_two_domains():
    evidence = CompletionEvidence()
    document(evidence)
    assert evidence.unsupported("Файл и задача созданы.")


def test_different_successful_operations_can_share_sentence():
    evidence = CompletionEvidence()
    document(evidence)
    evidence.record("troika_assistant", {"action": "reminder_schedule"}, {
        "ok": True, "action": "reminder_schedule",
        "result": {"message_id": "msg_1", "delivery_enabled": True},
    })
    assert not evidence.unsupported("Документ создан и напоминание установлено.")
    assert not evidence.unsupported("Напомню завтра.")


def test_cannot_promise_reminder_without_schedule():
    assert CompletionEvidence().unsupported("Напомню завтра.", "Напомни завтра")


def test_actual_web_extract_content_proves_reading():
    evidence = CompletionEvidence()
    evidence.record("web_extract", {"urls": ["https://example.com"]}, {
        "results": [{"url": "https://example.com", "content": "Article", "error": None}],
    })
    assert not evidence.unsupported("Я прочитала страницу сайта.")


def test_filename_must_match_actual_artifact():
    evidence = CompletionEvidence()
    document(evidence)
    assert not evidence.unsupported("Файл report.docx создан.")
    assert evidence.unsupported("Файл invented.docx создан.")


def test_server_artifact_does_not_prove_phone_save():
    evidence = CompletionEvidence()
    document(evidence)
    assert evidence.unsupported("Файл сохранён на телефоне.")
    assert evidence.unsupported("Файл сохранён на компьютере.")


def test_mutations_and_denials_disable_automatic_replay():
    evidence = CompletionEvidence()
    assert evidence.may_retry()
    document(evidence)
    assert not evidence.may_retry()
    denied = CompletionEvidence()
    denied.record("troika_files", {"action": "delete", "path": "a.txt"}, {"ok": False, "error": "approval_denied"})
    assert not denied.may_retry()


def test_all_files_claim_cannot_hide_failed_file():
    evidence = CompletionEvidence()
    document(evidence)
    evidence.record("troika_create_pdf", {"title": "Второй файл"}, {"ok": False})
    assert evidence.unsupported("Все файлы созданы.")


def test_entity_cancelled_status_is_not_a_failed_task_update():
    evidence = CompletionEvidence()
    evidence.record("troika_assistant", {"action": "task_update", "task_id": "task_1"}, {
        "ok": True, "action": "task_update", "result": {"id": "task_1", "status": "cancelled"},
    })
    assert not evidence.unsupported("Задача обновлена.")
