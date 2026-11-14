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
            connection.execute("""
                CREATE TABLE IF NOT EXISTS troika_conversation_titles (
                    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, channel_id)
                )
            """)

    def adopt_continuations(self, user_id, session_ids):
        """Bind compression continuations to the account owning their root.

        Hermes compression ends a session and continues in a new child ID.
        Without an ownership row that child is missing from history, export
        and deletion, and another account could claim it.
        """
        result = []
        now = time.time()
        with self.registry._connect() as connection:
            for root in session_ids:
                result.append(root)
                parent = root
                for child in self.db.get_compression_chain(root)[1:]:
                    owner = connection.execute(
                        "SELECT user_id FROM troika_sessions WHERE session_id=?", (child,),
                    ).fetchone()
                    if owner is None:
                        connection.execute(
                            "INSERT INTO troika_sessions (session_id, user_id, device_id, created_at) "
                            "SELECT ?, user_id, device_id, ? FROM troika_sessions "
                            "WHERE session_id=? AND user_id=?",
                            (child, now, parent, user_id),
                        )
                    elif owner["user_id"] != user_id:
                        break  # never merge another account's conversation
                    result.append(child)
                    parent = child
        return list(dict.fromkeys(result))

    def _channel(self, connection, principal, session_id):
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
        return row[0] if row else session_id

    def session_ids(self, principal, session_id):
        with self.registry._connect() as connection:
            channel = self._channel(connection, principal, session_id)
            segments = [r[0] for r in connection.execute(
                "SELECT session_id FROM troika_conversation_segments WHERE user_id=? AND channel_id=? ORDER BY generation",
                (principal.user_id, channel),
            )] or [session_id]
        return self.adopt_continuations(principal.user_id, segments)

    def tip(self, principal, session_id):
        """Return the live session for a channel, following compression."""
        return self.session_ids(principal, session_id)[-1]

    def rename(self, principal, session_id, title):
        """Set or clear the account-private title of a whole conversation."""
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        clean = re.sub(r"\s+", " ", title).strip()
        if len(clean) > 100 or re.search(r"[\x00-\x1f\x7f]", clean):
            raise ValueError("invalid title")
        with self.registry._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            channel = self._channel(connection, principal, session_id)
            if clean:
                connection.execute(
                    "INSERT INTO troika_conversation_titles VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id, channel_id) DO UPDATE SET "
                    "title=excluded.title, updated_at=excluded.updated_at",
                    (principal.user_id, channel, clean, time.time()),
                )
            else:
                connection.execute(
                    "DELETE FROM troika_conversation_titles WHERE user_id=? AND channel_id=?",
                    (principal.user_id, channel),
                )
        return channel, clean or None

    def delete(self, principal, session_id, *, sessions_dir=None):
        """Delete every message of one conversation; ownership rows remain.

        Keeping the ownership rows means a deleted ID (including the stable
        account home alias) can never be claimed by another account, and the
        next message on the same alias starts an empty conversation.
        """
        ids = self.session_ids(principal, session_id)
        with self.registry._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            channel = self._channel(connection, principal, session_id)
            connection.execute(
                "DELETE FROM troika_conversation_segments WHERE user_id=? AND channel_id=?",
                (principal.user_id, channel),
            )
            connection.execute(
                "DELETE FROM troika_conversation_titles WHERE user_id=? AND channel_id=?",
                (principal.user_id, channel),
            )
        for sid in ids:
            self.db.delete_session(sid, sessions_dir=sessions_dir)
        return channel, ids

    def history(self, principal, *, source=None, limit=50, offset=0):
        """One history entry per conversation channel, owner-filtered in SQL."""
        with self.registry._connect() as connection:
            self.registry._require_active_principal(connection, principal)
            owned = [r[0] for r in connection.execute(
                "SELECT session_id FROM troika_sessions WHERE user_id=?", (principal.user_id,),
            )]
            channel_of = {r[0]: r[1] for r in connection.execute(
                "SELECT session_id, channel_id FROM troika_conversation_segments WHERE user_id=?",
                (principal.user_id,),
            )}
            titles = {r[0]: r[1] for r in connection.execute(
                "SELECT channel_id, title FROM troika_conversation_titles WHERE user_id=?",
                (principal.user_id,),
            )}
        if not owned:
            return []
        # Older compression continuations predate eager ownership binding.
        roots = self.db.list_sessions_rich(
            source=source, limit=len(owned), session_ids=owned,
            project_compression_tips=False,
        )
        owned = self.adopt_continuations(principal.user_id, [s["id"] for s in roots])
        rows = self.db.list_sessions_rich(
            source=source, limit=len(owned), session_ids=owned,
            include_children=True, project_compression_tips=False,
        )
        root_of = {}
        for root in (s["id"] for s in roots):
            for sid in self.db.get_compression_chain(root):
                root_of.setdefault(sid, root)
        groups = {}
        for row in sorted(rows, key=lambda s: (s.get("started_at") or 0, s["id"])):
            root = root_of.get(row["id"])
            if root is None:
                continue  # subagent/branch children stay hidden as before
            channel = channel_of.get(root, root)
            entry = groups.get(channel)
            if entry is None:
                groups[channel] = entry = {
                    "id": channel, "source": row.get("source"), "title": None,
                    "preview": "", "message_count": 0,
                    "started_at": row.get("started_at"), "last_active": row.get("last_active"),
                }
            entry["message_count"] += int(row.get("message_count") or 0)
            entry["last_active"] = max(entry["last_active"] or 0, row.get("last_active") or 0)
            if not entry["preview"] and row.get("preview"):
                entry["preview"] = row["preview"]
            if row.get("title"):
                entry["title"] = row["title"]
        for channel, entry in groups.items():
            if channel in titles:
                entry["title"] = titles[channel]
        items = sorted(groups.values(), key=lambda e: (e["last_active"] or 0, e["id"]), reverse=True)
        return items[offset:offset + limit]

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
