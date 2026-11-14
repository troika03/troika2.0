"""Encrypted support storage and transactional Telegram delivery queue."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from cryptography.fernet import Fernet


class Store:
    def __init__(self, path: Path, encryption_key: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.cipher = path, Fernet(encryption_key.encode("ascii"))
        with self.transaction() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS offsets (bot TEXT PRIMARY KEY, next_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS customers (user_id INTEGER PRIMARY KEY, waitlist INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (user_id INTEGER PRIMARY KEY, topic TEXT, ticket_id INTEGER);
                CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, topic TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS ticket_owner ON tickets(user_id, status);
                CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE, sender TEXT NOT NULL, body BLOB NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT NOT NULL, method TEXT NOT NULL, payload BLOB NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS operator_replies (chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, PRIMARY KEY(chat_id,message_id));
                CREATE TABLE IF NOT EXISTS rate_limits (user_id INTEGER NOT NULL, bucket INTEGER NOT NULL, used INTEGER NOT NULL, PRIMARY KEY(user_id,bucket));
            """)

    @contextmanager
    def transaction(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA secure_delete=ON")
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def seal(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def open(self, value):
        return json.loads(self.cipher.decrypt(value))

    def queue(self, c, bot, method, payload, *, ticket_id=None):
        value = dict(payload)
        if ticket_id:
            value["_ticket_id"] = ticket_id
        c.execute("INSERT INTO outbox(bot,method,payload) VALUES(?,?,?)", (bot, method, self.seal(value)))

    def message(self, c, ticket_id, sender, text):
        c.execute("INSERT INTO messages(ticket_id,sender,body,created_at) VALUES(?,?,?,?)", (ticket_id, sender, self.seal(text), time.time()))

    @staticmethod
    def offset(c, bot):
        row = c.execute("SELECT next_id FROM offsets WHERE bot=?", (bot,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def limit(c, user_id):
        bucket = int(time.time() // 60)
        c.execute("DELETE FROM rate_limits WHERE bucket < ?", (bucket - 2,))
        c.execute("INSERT INTO rate_limits VALUES(?,?,1) ON CONFLICT(user_id,bucket) DO UPDATE SET used=used+1", (user_id, bucket))
        return c.execute("SELECT used FROM rate_limits WHERE user_id=? AND bucket=?", (user_id, bucket)).fetchone()[0] > 25

    def pending(self, bot):
        with self.transaction() as c:
            return [dict(row) for row in c.execute("SELECT * FROM outbox WHERE bot=? AND failed=0 AND retry_at<=? ORDER BY id LIMIT 30", (bot, time.time()))]

    def delivered(self, row, result):
        with self.transaction() as c:
            payload = self.open(row["payload"])
            if payload.get("_ticket_id") and isinstance(result, dict) and "message_id" in result:
                c.execute("INSERT OR REPLACE INTO operator_replies VALUES(?,?,?)", (payload["chat_id"], result["message_id"], payload["_ticket_id"]))
            c.execute("DELETE FROM outbox WHERE id=?", (row["id"],))

    def retry(self, row, *, permanent=False, delay=None):
        with self.transaction() as c:
            attempts = row["attempts"] + 1
            c.execute("UPDATE outbox SET attempts=?,retry_at=?,failed=? WHERE id=?", (attempts, time.time() + (delay if delay is not None else min(300, 2 ** min(attempts, 8))), int(permanent), row["id"]))

    def forget(self, c, user_id):
        ids = [r[0] for r in c.execute("SELECT id FROM tickets WHERE user_id=?", (user_id,))]
        for ticket in ids:
            c.execute("DELETE FROM operator_replies WHERE ticket_id=?", (ticket,))
        c.execute("DELETE FROM tickets WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM customers WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM rate_limits WHERE user_id=?", (user_id,))
        for row in c.execute("SELECT id,payload FROM outbox").fetchall():
            payload = self.open(row["payload"])
            if payload.get("chat_id") == user_id or payload.get("_ticket_id") in ids:
                c.execute("DELETE FROM outbox WHERE id=?", (row["id"],))
