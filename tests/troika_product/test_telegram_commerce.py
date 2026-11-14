"""Customer flows, ownership, durable delivery, and disabled checkout."""

from dataclasses import replace
import json
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from troika_product.telegram_commerce.api import TelegramError
from troika_product.telegram_commerce.config import Settings
from troika_product.telegram_commerce.content import screen
from troika_product.telegram_commerce.service import Service
from troika_product.telegram_commerce.store import Store


@pytest.fixture
def system(tmp_path):
    settings = Settings("test_shop_bot", "test_support_bot", (900,), 900, "https://example.com", tmp_path / "assets", tmp_path, "12345678:" + "a" * 35, "22345678:" + "b" * 35, Fernet.generate_key().decode())
    store = Store(tmp_path / "support.sqlite", settings.encryption_key)
    return settings, store, Service(settings, store, {})


def update(number, user=100, text=None, action=None, *, chat=None, reply=None, bot_id=22345678):
    message = {"message_id": number, "chat": {"id": chat or user, "type": "private" if not chat else "supergroup"}, "from": {"id": user, "is_bot": False}}
    if text is not None:
        message["text"] = text
    if reply:
        message["reply_to_message"] = {"message_id": reply}
    if action:
        sender = message["from"]
        message["from"] = {"id": bot_id, "is_bot": True}
        return {"update_id": number, "callback_query": {"id": f"callback-{number}", "from": sender, "data": action, "message": message}}
    return {"update_id": number, "message": message}


def messages(store, role="support"):
    return [store.open(row["payload"]) for row in store.pending(role) if row["method"] in {"sendMessage", "sendPhoto"}]


def ticket(service, *, user=100, start=1, body="Микрофон не работает"):
    service.process("support", update(start, user, action="topic:voice"))
    service.process("support", update(start + 1, user, text=body))


def test_ticket_is_encrypted_and_duplicate_update_is_ignored(system):
    _, store, service = system
    ticket(service)
    service.process("support", update(2, text="Микрофон не работает"))
    with store.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
        row = c.execute("SELECT body FROM messages").fetchone()[0]
        assert store.open(row) == "Микрофон не работает"
    assert "Микрофон не работает".encode() not in store.path.read_bytes()
    assert any(m["chat_id"] == 900 and "№1" in m["text"] for m in messages(store))


def test_customer_cannot_access_another_ticket_or_operator_controls(system):
    _, store, service = system
    ticket(service)
    service.process("support", update(3, 101, action="resume:1"))
    service.process("support", update(4, 101, action="close:1"))
    service.process("support", update(5, 101, action="reply:1"))
    with store.transaction() as c:
        assert c.execute("SELECT status FROM tickets WHERE id=1").fetchone()[0] == "open"
        assert not c.execute("SELECT 1 FROM sessions WHERE user_id=101").fetchone()
    customer = " ".join(m["text"] for m in messages(store) if m["chat_id"] == 101)
    assert "Микрофон не работает" not in customer


def test_operator_must_use_the_configured_inbox(system):
    _, store, service = system
    ticket(service)
    service.process("support", update(3, 900, action="close:1", chat=-123))
    with store.transaction() as c:
        assert c.execute("SELECT status FROM tickets").fetchone()[0] == "open"
    service.process("support", update(4, 900, action="close:1"))
    with store.transaction() as c:
        assert c.execute("SELECT status FROM tickets").fetchone()[0] == "closed"
        assert not c.execute("SELECT 1 FROM sessions").fetchone()


def test_operator_reply_uses_server_mapping_and_escapes_customer_html(system):
    _, store, service = system
    ticket(service, body="<b>личный текст</b>")
    operator_row = next(r for r in store.pending("support") if store.open(r["payload"]).get("_ticket_id") == 1)
    store.delivered(operator_row, {"message_id": 700})
    service.process("support", update(3, 900, text="Проверьте <микрофон>", reply=700))
    assert any(m["chat_id"] == 100 and "Проверьте &lt;микрофон&gt;" in m["text"] for m in messages(store))
    service.process("support", update(4, 101, text="Поддельный ответ", reply=700))
    with store.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE sender='operator'").fetchone()[0] == 1


def test_operator_can_preview_customer_flow_without_losing_admin_inbox(system):
    _, store, service = system
    service.process("support", update(1, 900, text="/start"))
    assert "Входящие оператора" in json.dumps(messages(store)[-1], ensure_ascii=False)
    service.process("support", update(2, 900, action="admin"))
    assert "Входящие поддержки" in messages(store)[-1]["text"]


def test_restart_keeps_offset_ticket_and_encrypted_delivery(system):
    settings, store, service = system
    ticket(service)
    restarted = Store(store.path, settings.encryption_key)
    second = Service(settings, restarted, {})
    second.process("support", update(2, text="повтор"))
    with restarted.transaction() as c:
        assert restarted.offset(c, "support") == 3
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert messages(restarted)


def test_forget_removes_only_owners_data_and_pending_delivery(system):
    _, store, service = system
    ticket(service)
    ticket(service, user=101, start=3, body="Чужой вопрос")
    service.process("support", update(5, 100, action="forget:confirm"))
    with store.transaction() as c:
        assert [r[0] for r in c.execute("SELECT user_id FROM tickets")] == [101]
        assert not c.execute("SELECT 1 FROM customers WHERE user_id=100").fetchone()
        assert not c.execute("SELECT 1 FROM rate_limits WHERE user_id=100").fetchone()
    assert all("Микрофон не работает" not in json.dumps(m, ensure_ascii=False) for m in messages(store))


def test_waitlist_consent_and_stop_do_not_create_payments(system):
    _, store, service = system
    service.process("shop", update(1, action="plan:pro"))
    service.process("shop", update(2, action="waitlist"))
    with store.transaction() as c:
        assert c.execute("SELECT waitlist FROM customers").fetchone()[0] == 1
    service.process("shop", update(3, text="/stop"))
    with store.transaction() as c:
        assert c.execute("SELECT waitlist FROM customers").fetchone()[0] == 0
    assert all(r["method"] != "sendInvoice" for r in store.pending("shop"))


def test_payment_queries_are_rejected_once_and_deep_link_selects_topic(system):
    _, store, service = system
    payment = {"update_id": 1, "pre_checkout_query": {"id": "pay-1"}}
    service.process("shop", payment)
    service.process("shop", payment)
    answers = [store.open(r["payload"]) for r in store.pending("shop")]
    assert len(answers) == 1 and answers[0]["ok"] is False
    service.process("support", update(2, text="/start payment"))
    with store.transaction() as c:
        assert c.execute("SELECT topic FROM sessions").fetchone()[0] == "payment"


def test_message_validation_and_open_ticket_limit(system):
    _, store, service = system
    service.process("support", update(1, action="topic:other"))
    service.process("support", update(2, text="x" * 2501))
    with store.transaction() as c:
        assert not c.execute("SELECT 1 FROM tickets").fetchone()
    for start in (3, 5, 7, 9):
        ticket(service, start=start)
    with store.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 3


def test_config_refuses_payments_missing_operators_and_shared_tokens(system, monkeypatch, tmp_path):
    settings, _, _ = system
    path = tmp_path / "settings.yaml"
    base = {"shop_username": settings.shop_username, "support_username": settings.support_username, "operator_ids": [900], "payments_enabled": False}
    import yaml
    for key, value in (("TROIKA_SHOP_BOT_TOKEN", settings.shop_token), ("TROIKA_SUPPORT_BOT_TOKEN", settings.support_token), ("TROIKA_TELEGRAM_ENCRYPTION_KEY", settings.encryption_key)):
        monkeypatch.setenv(key, value)
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    assert Settings.load(path).operator_ids == (900,)
    for change in ({"payments_enabled": True}, {"operator_ids": []}, {"website": "http://example.com"}, {"support_username": settings.shop_username}):
        path.write_text(yaml.safe_dump({**base, **change}), encoding="utf-8")
        with pytest.raises(ValueError):
            Settings.load(path)


@pytest.mark.asyncio
async def test_network_failure_retries_and_blocked_user_does_not_stop_other_delivery(system):
    _, store, service = system
    class FakeClient:
        def __init__(self): self.calls = 0
        async def call(self, method, payload):
            self.calls += 1
            if self.calls == 1: raise TelegramError(403)
            return {"message_id": 9000 + self.calls}
    service.clients["support"] = FakeClient()
    ticket(service)
    await service.deliver("support")
    with store.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE failed=1").fetchone()[0] == 1
        assert not c.execute("SELECT 1 FROM outbox WHERE failed=0").fetchone()
    service.clients["support"].calls = 0
    class Offline:
        async def call(self, method, payload): raise TelegramError(503)
    service.clients["support"] = Offline()
    service.process("support", update(3, text="Дополнение"))
    await service.deliver("support")
    with store.transaction() as c:
        row = c.execute("SELECT attempts,retry_at FROM outbox WHERE failed=0 ORDER BY id LIMIT 1").fetchone()
        assert row[0] == 1 and row[1] > 0


def test_switching_buttons_removes_only_the_clicked_bot_menu(system):
    _, store, service = system
    service.process("shop", update(1, action="plans", bot_id=12345678))
    rows = store.pending("shop")
    removals = [store.open(row["payload"]) for row in rows if row["method"] == "deleteMessage"]
    assert removals == [{"chat_id": 100, "message_id": 1}]
    assert any(row["method"] == "sendMessage" for row in rows)
    service.process("shop", update(2, action="home", bot_id=99999999))
    assert sum(row["method"] == "deleteMessage" for row in store.pending("shop")) == 1
    service.process("support", update(3, action="faq", chat=-123))
    assert not any(row["method"] == "deleteMessage" for row in store.pending("support"))


def test_navigation_cleanup_preserves_ticket_records_and_survives_data_deletion(system):
    _, store, service = system
    ticket(service)
    service.process("support", update(3, 900, action="reply:1"))
    service.process("support", update(4, 100, action="forget:confirm"))
    removals = [store.open(r["payload"]) for r in store.pending("support") if r["method"] == "deleteMessage"]
    assert {"chat_id": 900, "message_id": 3} not in removals
    assert removals == [{"chat_id": 100, "message_id": 4}]


def all_screens(settings):
    from troika_product.telegram_commerce.content import FAQ
    from troika_product.subscription_policy import PLANS
    shop = ["home", "plans", "pay", "download", "device", "about", "help", *("plan:" + key for key in PLANS)]
    support = ["home", "faq", "contact", *("faq:" + key for key in FAQ)]
    return [("shop", action) for action in shop] + [("support", action) for action in support]


def test_screens_fit_telegram_limits_and_use_known_button_styles(system):
    settings, _, _ = system
    for role, action in all_screens(settings):
        text, markup, photo = screen(settings, role, action)
        assert "устарела" not in text, (role, action)
        assert len(text) <= (1024 if photo else 4096)
        for row in markup["inline_keyboard"]:
            assert row
            for item in row:
                assert item.get("style") in {None, "primary", "success", "danger"}
                assert ("url" in item) != ("callback_data" in item)
                if "callback_data" in item:
                    assert len(item["callback_data"].encode()) <= 64
                    # Every callback a screen offers leads somewhere for its bot.
                    if item["callback_data"] not in {"waitlist", "admin", "tickets"} and not item["callback_data"].startswith("topic:"):
                        assert "устарела" not in screen(settings, role, item["callback_data"])[0]


def test_plan_copy_follows_the_subscription_policy(system, monkeypatch):
    settings, _, _ = system
    from types import MappingProxyType
    from troika_product import subscription_policy as policy
    changed = MappingProxyType({**policy.PLANS, "plus": replace(policy.PLANS["plus"], price_rub=12345, monthly_tokens=7_500_000)})
    monkeypatch.setattr(policy, "PLANS", changed)
    overview = screen(settings, "shop", "plans")[0]
    detail = screen(settings, "shop", "plan:plus")[0]
    assert "12 345 ₽" in overview and "7,5 млн" in overview
    assert "12 345 ₽" in detail and "790" not in detail
    assert "устарела" in screen(settings, "shop", "plan:unknown")[0]


def test_shop_commands_open_their_screens(system):
    _, store, service = system
    for number, command in enumerate(("/download", "/device", "/pay", "/tariffs", "/support"), start=1):
        service.process("shop", update(number, text=command))
    texts = [m["text"] for m in messages(store, "shop")]
    assert ["Скачать" in texts[0], "Подключить устройство" in texts[1], "Оплата" in texts[2], "Тарифы" in texts[3], "Помощь" in texts[4]] == [True] * 5


def test_ticket_status_view_and_customer_close_are_owner_only(system):
    _, store, service = system
    ticket(service)
    service.process("support", update(3, action="tickets"))
    assert "ждёт оператора" in messages(store)[-1]["text"]
    operator_row = next(r for r in store.pending("support") if store.open(r["payload"]).get("_ticket_id") == 1)
    store.delivered(operator_row, {"message_id": 700})
    service.process("support", update(4, 900, text="Проверьте настройки", reply=700))
    service.process("support", update(5, action="ticket:1"))
    view = messages(store)[-1]["text"]
    assert "есть ответ" in view and "Микрофон не работает" in view and "Проверьте настройки" in view
    service.process("support", update(6, 101, action="ticket:1"))
    service.process("support", update(7, 101, action="done:1"))
    stranger = " ".join(m["text"] for m in messages(store) if m["chat_id"] == 101)
    assert "Микрофон" not in stranger
    with store.transaction() as c:
        assert c.execute("SELECT status FROM tickets").fetchone()[0] == "open"
    service.process("support", update(8, action="done:1"))
    with store.transaction() as c:
        assert c.execute("SELECT status FROM tickets").fetchone()[0] == "closed"
    assert any(m["chat_id"] == 900 and "Клиент закрыл обращение №1" in m["text"] for m in messages(store))


def test_support_deep_links_open_only_known_topics(system):
    _, store, service = system
    service.process("support", update(1, text="/start install"))
    with store.transaction() as c:
        assert c.execute("SELECT topic FROM sessions").fetchone()[0] == "start"
    service.process("support", update(2, text="/start <script>"))
    with store.transaction() as c:
        assert not c.execute("SELECT 1 FROM sessions").fetchone()
    assert "Поддержка Тройки" in messages(store)[-1]["text"]


@pytest.mark.asyncio
async def test_worker_loops_used_by_the_runner_deliver_queued_messages(system):
    import asyncio
    _, store, service = system
    sent = []
    class Client:
        async def call(self, method, payload):
            sent.append(method)
            return {"message_id": len(sent)}
    service.clients["shop"] = Client()
    service.process("shop", update(1, text="/start"))
    task = asyncio.create_task(service.deliveries("shop"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if sent:
            break
    task.cancel()
    assert sent == ["sendMessage"] and not store.pending("shop")
    assert callable(service.poll)
