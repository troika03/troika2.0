"""Rotate working conversations while retaining the account's complete timeline."""

from __future__ import annotations

import re
import time
import uuid


CONVERSATION_RULE = """Отвечай на последнее сообщение пользователя. История, память,
проекты и незавершённые поручения служат справкой, а не очередью к исполнению.
Приветствие или обычный разговор не разрешают возобновлять старую работу.
Продолжай прежнее поручение только по явной просьбе пользователя. При смене
рабочей сессии история и память сохраняются. Для ссылки на прошлый разговор
прочитай assistant/troika_context history_recent, затем нужный history_read.
Не говори, что история потеряна, если она доступна в архиве.
"""

_SOCIAL = re.compile(
    r"(?:(?:тройка|troika)[, ]+)?(?:"
    r"привет(?:ик)?|приветствую|здравствуй(?:те)?|здарова|здорово|хай|ку|"
    r"доброе утро|добрый день|добрый вечер|доброй ночи|"
    r"как (?:ты|дела)|как у тебя дела|ты (?:тут|здесь)|"
    r"спасибо|благодарю|пока|до свидания|спокойной ночи|"
    r"hi|hello|hey|good morning|good evening|how are you|thanks|thank you|bye"
    r")(?:[, ]+(?:тройка|troika))?",
    re.I,
)


def conversation_only(message) -> bool:
    """Recognize complete social utterances, never an action following a greeting."""
    if not isinstance(message, str) or len(message) > 160:
        return False
    text = re.sub(r"[!?.,…:;]+", " ", message.casefold()).strip()
    text = re.sub(r"\s+", " ", text)
    return bool(_SOCIAL.fullmatch(text))


class ConversationSessions:
    """Stable channel aliases point at bounded, independently persisted sessions."""

    idle_seconds = 30 * 60
    max_turns = 24
    max_tokens = 12_000

    def __init__(self, registry, session_db):
        self.registry = registry
        self.db = session_db
        with registry._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS troika_conversation_segments (
                    session_id TEXT PRIMARY KEY REFERENCES troika_sessions(session_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                    channel_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    last_turn_at REAL NOT NULL,
                    turns INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, channel_id, generation)
                )
            """)

    def session_ids(self, principal, session_id):
        with self.registry._connect() as connection:
            self.registry._require_active_principal(connection, principal)
            if not connection.execute(
                "SELECT 1 FROM troika_sessions WHERE session_id=? AND user_id=?",
                (session_id, principal.user_id),
            ).fetchone():
                raise PermissionError("conversation owner required")
            row = connection.execute(
                "SELECT channel_id FROM troika_conversation_segments WHERE session_id=? AND user_id=?",
                (session_id, principal.user_id),
            ).fetchone()
            if row is None:
                return [session_id]
            return [r[0] for r in connection.execute(
                "SELECT session_id FROM troika_conversation_segments WHERE user_id=? AND channel_id=? ORDER BY generation",
                (principal.user_id, row[0]),
            )]

    def archive(self, principal, session_id):
        return [message for sid in self.session_ids(principal, session_id) if sid != session_id
                for message in self.db.get_messages_as_conversation(sid)]

    def timeline(self, principal, session_id):
        rows = [message for sid in self.session_ids(principal, session_id)
                for message in self.db.get_messages(sid)]
        return sorted(rows, key=lambda m: (m.get("timestamp", 0), m.get("id", 0)))

    def resolve(self, principal, session_id, message, supplied_history=(), *, now=None):
        """Choose a session atomically; client replay cannot undo a rotation."""
        from troika_product.working_context import token_count

        now = time.time() if now is None else now
        with self.registry._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(connection, principal)
            if not connection.execute(
                "SELECT 1 FROM troika_sessions WHERE session_id=? AND user_id=?",
                (session_id, principal.user_id),
            ).fetchone():
                raise PermissionError("conversation owner required")
            row = connection.execute(
                "SELECT * FROM troika_conversation_segments WHERE session_id=? AND user_id=?",
                (session_id, principal.user_id),
            ).fetchone()
            if row is None:
                rows = self.db.get_messages(session_id)
                last_at = max((m.get("timestamp", 0) for m in rows), default=now)
                turns = sum(m.get("role") == "user" for m in rows)
                connection.execute(
                    "INSERT INTO troika_conversation_segments VALUES (?,?,?,?,?,?)",
                    (session_id, principal.user_id, session_id, 0, last_at, turns),
                )
                channel = session_id
            else:
                channel = row["channel_id"]
            active = connection.execute(
                "SELECT * FROM troika_conversation_segments WHERE user_id=? AND channel_id=? ORDER BY generation DESC LIMIT 1",
                (principal.user_id, channel),
            ).fetchone()
            effective_id = active["session_id"]
            history = self.db.get_messages_as_conversation(effective_id)
            has_history = bool(history or active["turns"])
            reason = None
            if has_history:
                if conversation_only(message):
                    reason = "conversation"
                elif history and conversation_only(next(
                    (m.get("content") for m in reversed(history) if m.get("role") == "user"), None
                )):
                    # A greeting's cached prompt deliberately has no tools.
                    # Start an actionable session with a fresh prompt rather
                    # than restoring that restricted prompt for a real request.
                    reason = "new_request"
                elif now - active["last_turn_at"] >= self.idle_seconds:
                    reason = "idle"
                elif active["turns"] >= self.max_turns or token_count(history) >= self.max_tokens:
                    reason = "context_limit"
            if reason:
                effective_id = "ses_" + uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO troika_sessions VALUES (?,?,?,?)",
                    (effective_id, principal.user_id, principal.device_id, now),
                )
                connection.execute(
                    "INSERT INTO troika_conversation_segments VALUES (?,?,?,?,?,0)",
                    (effective_id, principal.user_id, channel, active["generation"] + 1, now),
                )
                history = []
            elif not history and active["generation"] == 0 and not conversation_only(message):
                # Preserve compatibility with a client's first imported conversation.
                history = list(supplied_history)
            connection.execute(
                "UPDATE troika_conversation_segments SET last_turn_at=?, turns=turns+1 WHERE session_id=?",
                (now, effective_id),
            )
        return effective_id, history, reason
