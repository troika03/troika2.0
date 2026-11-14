"""Deterministic storefront, ticket inbox, and durable update processing."""

import asyncio
from html import escape
import re
import time

from .api import TelegramError
from .content import DANGER, DEEP_LINKS, PRIMARY, STATUS, SUCCESS, TOPICS, button, home_row, keyboard, screen, topic_label

NAVIGATION = {"home", "plans", "about", "faq", "contact", "tickets", "waitlist", "waitlist:off", "forget:confirm", "admin", "pay", "download", "device", "help"}
NAVIGATION_PREFIXES = ("plan:", "faq:", "topic:", "resume:", "ticket:", "done:")
SHOP_COMMANDS = {"/tariffs": "plans", "/download": "download", "/device": "device", "/pay": "pay", "/support": "help"}


class Service:
    def __init__(self, settings, store, clients):
        self.settings, self.store, self.clients = settings, store, clients

    def send(self, c, role, chat_id, text, markup=None, *, photo=None, ticket_id=None):
        data = {"chat_id": chat_id, "parse_mode": "HTML"}
        if markup:
            data["reply_markup"] = markup
        if photo and (self.settings.assets / photo).is_file():
            data.update(caption=text, _photo=photo)
            method = "sendPhoto"
        else:
            data.update(text=text, link_preview_options={"is_disabled": True})
            method = "sendMessage"
        self.store.queue(c, role, method, data, ticket_id=ticket_id)

    def show(self, c, role, user_id, action):
        text, markup, photo = screen(self.settings, role, action)
        if role == "support" and user_id in self.settings.operator_ids and action == "home":
            markup["inline_keyboard"].append([button("🗂 Входящие оператора", "admin", style=PRIMARY)])
        self.send(c, role, user_id, text, markup, photo=photo)

    def process(self, role, update):
        update_id = update.get("update_id")
        if type(update_id) is not int:
            return
        with self.store.transaction() as c:
            if update_id < self.store.offset(c, role):
                return
            query = update.get("pre_checkout_query")
            if query:
                self.store.queue(c, role, "answerPreCheckoutQuery", {"pre_checkout_query_id": query["id"], "ok": False, "error_message": "Продажи пока не открыты."})
            callback = update.get("callback_query")
            message = update.get("message")
            if callback:
                self.store.queue(c, role, "answerCallbackQuery", {"callback_query_id": callback["id"]})
                message = callback.get("message", {})
            if message:
                user = callback.get("from", {}) if callback else message.get("from", {})
                user_id = user.get("id")
                chat = message.get("chat", {})
                if type(user_id) is int and user_id > 0 and not user.get("is_bot"):
                    operator = role == "support" and user_id in self.settings.operator_ids and chat.get("id") == self.settings.operator_chat_id
                    operator_action = operator and (
                        (callback and (callback.get("data", "") == "admin" or re.fullmatch(r"(?:reply|close):\d+", callback.get("data", ""))))
                        or (not callback and (message.get("text", "").split(maxsplit=1)[0:1] == ["/admin"] or c.execute("SELECT 1 FROM operator_replies WHERE chat_id=? AND message_id=?", (chat.get("id"), message.get("reply_to_message", {}).get("message_id"))).fetchone()))
                    )
                    handled = False
                    if operator_action:
                        self.operator(c, user_id, message, callback)
                        handled = True
                    elif chat.get("type") == "private" and chat.get("id") == user_id:
                        if not self.store.limit(c, user_id):
                            c.execute("INSERT OR IGNORE INTO customers(user_id,created_at) VALUES(?,?)", (user_id, time.time()))
                            self.customer(c, role, user_id, message, callback)
                            handled = True
                    if handled and callback and chat.get("type") == "private" and chat.get("id") == user_id:
                        action = callback.get("data", "")
                        navigation = action in NAVIGATION or action.startswith(NAVIGATION_PREFIXES)
                        token = self.settings.shop_token if role == "shop" else self.settings.support_token
                        author = message.get("from", {})
                        message_id = message.get("message_id")
                        # Remove only this bot's navigation message in the clicking
                        # customer's private chat. Ticket records stay intact.
                        if navigation and author.get("id") == int(token.split(":", 1)[0]) and author.get("is_bot") is True and type(message_id) is int and message_id > 0:
                            self.store.queue(c, role, "deleteMessage", {"chat_id": user_id, "message_id": message_id})
            c.execute("INSERT INTO offsets VALUES(?,?) ON CONFLICT(bot) DO UPDATE SET next_id=excluded.next_id", (role, update_id + 1))

    def customer(self, c, role, user_id, message, callback):
        text = message.get("text", "")
        action = callback.get("data", "") if callback else None
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if callback and len(action.encode("utf-8")) > 64:
            return
        payload = text.split(maxsplit=1)[1].strip() if command == "/start" and len(text.split(maxsplit=1)) > 1 else ""
        if role == "support" and not callback and payload in DEEP_LINKS:
            self.support_customer(c, user_id, "", "", "topic:" + DEEP_LINKS[payload])
        elif command in {"/start", "/menu", "/help", "/cancel"} or action == "home":
            if role == "support":
                c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.show(c, role, user_id, "home")
        elif command == "/privacy":
            self.send(c, role, user_id, "<b>🔒 Ваши данные</b>\n\nБот хранит Telegram ID, согласие на уведомление и обращения. Текст обращений зашифрован в базе ботов; оператор видит только присланное в поддержку. Telegram хранит сообщения по своей политике.\n\n/stop — отключить уведомления.\n/delete_me — удалить данные в базе ботов. Сообщения в Telegram это не удаляет.", keyboard([button("📄 Политика приватности", url=self.settings.website + "/privacy/")], home_row()))
        elif command == "/delete_me":
            self.send(c, role, user_id, "<b>🗑 Удалить данные?</b>\n\nОбращения и настройки в базе ботов будут удалены. Копии сообщений в Telegram останутся.", keyboard([button("🗑 Удалить мои данные", "forget:confirm", style=DANGER)], [button("Отмена", "home")]))
        elif action == "forget:confirm":
            self.store.forget(c, user_id)
            self.send(c, role, user_id, "✅ Данные в базе ботов удалены. Сообщения в Telegram можно удалить в самом Telegram.", keyboard(home_row()))
        elif command == "/stop" or action == "waitlist:off":
            c.execute("UPDATE customers SET waitlist=0 WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.send(c, role, user_id, "🔕 Уведомление о старте продаж отключено.", keyboard(home_row()))
        elif role == "shop":
            if action == "waitlist":
                c.execute("UPDATE customers SET waitlist=1 WHERE user_id=?", (user_id,))
                self.send(c, role, user_id, "<b>🔔 Готово!</b>\n\nПришлём одно сообщение здесь, когда откроем продажи. Оплата и автоматические списания не включены.", keyboard([button("🔕 Отключить уведомление", "waitlist:off")], home_row()))
            elif command == "/paysupport":
                self.send(c, role, user_id, "<b>💳 Вопрос об оплате</b>\n\nНапишите в поддержку — тема «Тариф и оплата» откроется сразу.", keyboard([button("🛟 Поддержка оплаты", url=self.settings.bot_url("support") + "?start=payment", style=PRIMARY)], home_row()))
            elif command in SHOP_COMMANDS:
                self.show(c, role, user_id, SHOP_COMMANDS[command])
            elif callback:
                self.show(c, role, user_id, action)
            else:
                self.show(c, role, user_id, "home")
        elif role == "support":
            self.support_customer(c, user_id, text, command, action)

    @staticmethod
    def status(c, ticket):
        if ticket["status"] != "open":
            return "closed"
        last = c.execute("SELECT sender FROM messages WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (ticket["id"],)).fetchone()
        return "answered" if last and last["sender"] == "operator" else "waiting"

    def support_customer(self, c, user_id, text, command, action):
        if command == "/paysupport":
            self.support_customer(c, user_id, text, "", "topic:payment")
        elif command == "/support" or action == "contact":
            self.show(c, "support", user_id, "contact")
        elif command == "/tickets" or action == "tickets":
            rows = c.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()
            lines = [f"<b>№{r['id']}</b> · {escape(topic_label(r['topic']))}\n      {STATUS[self.status(c, r)]}" for r in rows]
            body = "<b>📋 Ваши обращения</b>\n\n" + ("\n".join(lines) if lines else "Обращений пока нет. Если что-то не работает — напишите нам.")
            self.send(c, "support", user_id, body, keyboard(
                *[[button(f"Открыть №{r['id']}", f"ticket:{r['id']}")] for r in rows if r["status"] == "open"],
                [button("✍️ Новое обращение", "contact", style=PRIMARY)],
                home_row(),
            ))
        elif action and re.fullmatch(r"ticket:\d+", action):
            ticket = c.execute("SELECT * FROM tickets WHERE id=? AND user_id=?", (int(action[7:]), user_id)).fetchone()
            if not ticket:
                self.send(c, "support", user_id, "Обращение недоступно.", keyboard([button("📋 Мои обращения", "tickets")]))
                return
            rows = c.execute("SELECT sender,body FROM messages WHERE ticket_id=? ORDER BY id DESC LIMIT 4", (ticket["id"],)).fetchall()
            history = "\n\n".join(("👤 <b>Вы:</b> " if r["sender"] == "customer" else "🛟 <b>Поддержка:</b> ") + escape(self.store.open(r["body"])[:600]) for r in reversed(rows))
            open_ = ticket["status"] == "open"
            self.send(c, "support", user_id, f"<b>Обращение №{ticket['id']}</b> · {escape(topic_label(ticket['topic']))}\n{STATUS[self.status(c, ticket)]}\n\n{history or 'Сообщений нет.'}", keyboard(
                [button("✍️ Дописать", f"resume:{ticket['id']}", style=PRIMARY), button("✅ Вопрос решён", f"done:{ticket['id']}", style=SUCCESS)] if open_ else None,
                [button("← Мои обращения", "tickets")],
                home_row(),
            ))
        elif action and re.fullmatch(r"done:\d+", action):
            ticket = c.execute("SELECT * FROM tickets WHERE id=? AND user_id=? AND status='open'", (int(action[5:]), user_id)).fetchone()
            if not ticket:
                self.send(c, "support", user_id, "Обращение уже закрыто или недоступно.", keyboard([button("📋 Мои обращения", "tickets")]))
                return
            c.execute("UPDATE tickets SET status='closed',updated_at=? WHERE id=?", (time.time(), ticket["id"]))
            c.execute("DELETE FROM sessions WHERE ticket_id=?", (ticket["id"],))
            self.send(c, "support", user_id, f"✅ <b>Обращение №{ticket['id']} закрыто.</b>\n\nРады, что вопрос решён! Если появится новый — мы рядом.", keyboard([button("✍️ Новое обращение", "contact")], home_row()))
            self.send(c, "support", self.settings.operator_chat_id, f"✅ Клиент закрыл обращение №{ticket['id']} · {escape(topic_label(ticket['topic']))}.")
        elif action and action.startswith("topic:") and action[6:] in TOPICS:
            topic = action[6:]
            c.execute("INSERT INTO sessions VALUES(?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET topic=excluded.topic,ticket_id=NULL", (user_id, topic))
            self.send(c, "support", user_id, f"<b>{escape(topic_label(topic))}</b>\n\n✍️ Опишите проблему одним сообщением:\n• что делали;\n• что ожидали и что получилось;\n• Android или Windows и версия приложения.\n\n🔒 Пароли и ключи не присылайте.", keyboard([button("Отменить", "home")]))
        elif action and re.fullmatch(r"resume:\d+", action):
            ticket = c.execute("SELECT * FROM tickets WHERE id=? AND user_id=? AND status='open'", (int(action[7:]), user_id)).fetchone()
            if ticket:
                c.execute("INSERT INTO sessions VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET topic=excluded.topic,ticket_id=excluded.ticket_id", (user_id, ticket["topic"], ticket["id"]))
                self.send(c, "support", user_id, f"✍️ Напишите дополнение к обращению №{ticket['id']} следующим сообщением.", keyboard([button("Отменить", "home")]))
            else:
                self.send(c, "support", user_id, "Обращение недоступно или уже закрыто.", keyboard([button("📋 Мои обращения", "tickets")]))
        elif action:
            self.show(c, "support", user_id, action)
        else:
            session = c.execute("SELECT * FROM sessions WHERE user_id=?", (user_id,)).fetchone()
            if not session:
                self.show(c, "support", user_id, "contact")
                return
            if not text or text.startswith("/"):
                self.send(c, "support", user_id, "Пришлите описание текстом. Вложения пока не принимаются; приватные файлы отправлять не нужно.")
                return
            if len(text) > 2500:
                self.send(c, "support", user_id, "✂️ Сократите сообщение до 2 500 символов.")
                return
            ticket_id = session["ticket_id"]
            if ticket_id:
                ticket = c.execute("SELECT * FROM tickets WHERE id=? AND user_id=? AND status='open'", (ticket_id, user_id)).fetchone()
                if not ticket:
                    c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                    self.show(c, "support", user_id, "contact")
                    return
                headline = f"➕ <b>Дополнение · №{ticket_id}</b>"
            else:
                count = c.execute("SELECT COUNT(*) FROM tickets WHERE user_id=? AND status='open'", (user_id,)).fetchone()[0]
                if count >= 3:
                    self.send(c, "support", user_id, "У вас уже три открытых обращения. Продолжите одно из них.", keyboard([button("📋 Мои обращения", "tickets", style=PRIMARY)]))
                    return
                now = time.time()
                ticket_id = c.execute("INSERT INTO tickets(user_id,topic,created_at,updated_at) VALUES(?,?,?,?)", (user_id, session["topic"], now, now)).lastrowid
                c.execute("UPDATE sessions SET ticket_id=? WHERE user_id=?", (ticket_id, user_id))
                headline = f"🆕 <b>Обращение №{ticket_id}</b>"
            self.store.message(c, ticket_id, "customer", text)
            c.execute("UPDATE tickets SET updated_at=? WHERE id=?", (time.time(), ticket_id))
            self.send(c, "support", self.settings.operator_chat_id, f"{headline} · {escape(topic_label(session['topic']))}\n\n{escape(text)}\n\n↩️ Ответьте на это сообщение или нажмите «Ответить».", self.ticket_controls(ticket_id), ticket_id=ticket_id)
            self.send(c, "support", user_id, f"📨 <b>Обращение №{ticket_id} принято.</b>\n\nОтвет оператора придёт в этот чат. Можно дописать детали следующим сообщением.", keyboard([button("📋 Мои обращения", "tickets")], home_row()))

    @staticmethod
    def ticket_controls(ticket_id):
        return keyboard([button("✍️ Ответить", f"reply:{ticket_id}", style=PRIMARY), button("✅ Закрыть", f"close:{ticket_id}", style=SUCCESS)])

    def operator(self, c, user_id, message, callback):
        chat = self.settings.operator_chat_id
        text = message.get("text", "")
        action = callback.get("data", "") if callback else ""
        match = re.fullmatch(r"(reply|close):(\d+)", action)
        if match:
            operation, number = match.group(1), int(match.group(2))
            ticket = c.execute("SELECT * FROM tickets WHERE id=? AND status='open'", (number,)).fetchone()
            if not ticket:
                self.send(c, "support", chat, "Обращение уже закрыто или удалено.")
                return
            if operation == "reply":
                rows = c.execute("SELECT sender,body FROM messages WHERE ticket_id=? ORDER BY id DESC LIMIT 4", (number,)).fetchall()
                history = "\n\n".join(("👤 <b>Клиент:</b> " if r["sender"] == "customer" else "🛟 <b>Оператор:</b> ") + escape(self.store.open(r["body"])[:600]) for r in reversed(rows))
                self.send(c, "support", chat, f"<b>Обращение №{number}</b> · {escape(topic_label(ticket['topic']))}\n\n{history}\n\n↩️ Напишите ответ ответом на это сообщение.", {"force_reply": True, "selective": True}, ticket_id=number)
            else:
                c.execute("UPDATE tickets SET status='closed',updated_at=? WHERE id=?", (time.time(), number))
                c.execute("DELETE FROM sessions WHERE ticket_id=?", (number,))
                self.send(c, "support", ticket["user_id"], f"✅ <b>Обращение №{number} закрыто.</b>\n\nЕсли вопрос остался — создайте новое обращение.", keyboard([button("✍️ Написать оператору", "contact", style=PRIMARY)], home_row()))
                self.send(c, "support", chat, f"✅ Обращение №{number} закрыто.")
            return
        replied = message.get("reply_to_message", {}).get("message_id")
        row = c.execute("SELECT ticket_id FROM operator_replies WHERE chat_id=? AND message_id=?", (chat, replied)).fetchone() if replied else None
        if row and text and not text.startswith("/"):
            ticket = c.execute("SELECT * FROM tickets WHERE id=? AND status='open'", (row[0],)).fetchone()
            if not ticket:
                self.send(c, "support", chat, "Обращение уже закрыто или удалено.")
                return
            if len(text) > 2500:
                self.send(c, "support", chat, "✂️ Сократите ответ до 2 500 символов.")
                return
            self.store.message(c, ticket["id"], "operator", text)
            c.execute("UPDATE tickets SET updated_at=? WHERE id=?", (time.time(), ticket["id"]))
            self.send(c, "support", ticket["user_id"], f"💬 <b>Ответ поддержки · №{ticket['id']}</b>\n\n{escape(text)}", keyboard(
                [button("✍️ Ответить", f"resume:{ticket['id']}", style=PRIMARY), button("✅ Вопрос решён", f"done:{ticket['id']}", style=SUCCESS)],
                [button("📋 Мои обращения", "tickets")],
            ))
            self.send(c, "support", chat, f"📤 Ответ по обращению №{ticket['id']} поставлен в очередь доставки.")
        elif text == "/admin" or action == "admin":
            rows = c.execute("SELECT * FROM tickets WHERE status='open' ORDER BY updated_at DESC LIMIT 20").fetchall()
            lines = [f"<b>№{r['id']}</b> · {escape(topic_label(r['topic']))} · {STATUS[self.status(c, r)]}" for r in rows]
            waiting = sum(self.status(c, r) == "waiting" for r in rows)
            head = f"<b>🗂 Входящие поддержки</b>\nОткрыто: {len(rows)} · ждут ответа: {waiting}\n\n"
            self.send(c, "support", chat, head + ("\n".join(lines) or "Открытых обращений нет. 🎉"), keyboard(*[[button(f"✍️ №{r['id']}", f"reply:{r['id']}", style=PRIMARY), button("✅ Закрыть", f"close:{r['id']}", style=SUCCESS)] for r in rows], [button("🔄 Обновить", "admin")]))

    async def deliver(self, role):
        for row in self.store.pending(role):
            try:
                result = await self.clients[role].call(row["method"], self.store.open(row["payload"]))
            except TelegramError as error:
                self.store.retry(row, permanent=error.code in {400, 401, 403, 404}, delay=error.retry_after)
                if error.code == 429 or error.code >= 500:
                    break
            else:
                self.store.delivered(row, result)

    async def poll(self, role):
        client = self.clients[role]
        while True:
            try:
                with self.store.transaction() as c:
                    offset = self.store.offset(c, role)
                updates = await client.call("getUpdates", {"offset": offset, "timeout": 25, "limit": 50, "allowed_updates": ["message", "callback_query", "pre_checkout_query"]})
                for update in updates:
                    self.process(role, update)
                (self.settings.state / (role + ".heartbeat")).write_text(str(time.time()), encoding="utf-8")
            except TelegramError as error:
                if error.code in {401, 409}:
                    raise RuntimeError(f"{role}: credential rejected or another poller is active") from None
                await asyncio.sleep(min(30, error.retry_after or 5))
