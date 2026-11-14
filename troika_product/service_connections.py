"""Owner-scoped connections to account services over MCP (OAuth or token).

* Secrets are encrypted with Fernet (``TROIKA_PRODUCT_SERVICE_KEY``) in the
  account database; the table is removed with the account and only names and
  dates appear in an export.
* OAuth uses the service's MCP authorization (discovery, dynamic client
  registration, PKCE) through the MCP SDK. The browser returns to the Troika
  server callback; the ``state`` value binds the callback to one pending flow
  of one owner and expires after ``FLOW_TTL`` seconds.
* Token services receive the owner's personal token as a bearer header.
* Only reviewed directory entries (fixed HTTPS URL) can be connected.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FLOW_TTL = 600.0
CALLBACK_PATH = "/v1/account/services/oauth/callback"
MAX_TOKEN_LENGTH = 4096
TABLE = """
CREATE TABLE IF NOT EXISTS troika_service_connections (
    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
    server_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    secret BLOB NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, server_id)
)
"""


class ServiceAuthRequired(Exception):
    """Stored credentials are missing or no longer accepted."""


class ServiceConnectionStore:
    def __init__(self, database: Path, key: str):
        from cryptography.fernet import Fernet
        self.database = Path(database)
        self.cipher = Fernet(key.encode("ascii") if isinstance(key, str) else key)
        with self._connect() as connection:
            connection.execute(TABLE)

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def save(self, user_id: str, server_id: str, kind: str, secret: dict) -> None:
        payload = self.cipher.encrypt(json.dumps(secret, separators=(",", ":")).encode("utf-8"))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO troika_service_connections (user_id, server_id, kind, secret, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, server_id) DO UPDATE SET "
                "kind = excluded.kind, secret = excluded.secret, updated_at = excluded.updated_at",
                (user_id, server_id, kind, payload, time.time()),
            )

    def load(self, user_id: str, server_id: str) -> tuple[str, dict] | None:
        from cryptography.fernet import InvalidToken
        with self._connect() as connection:
            row = connection.execute(
                "SELECT kind, secret FROM troika_service_connections WHERE user_id = ? AND server_id = ?",
                (user_id, server_id),
            ).fetchone()
        if row is None:
            return None
        try:
            return row["kind"], json.loads(self.cipher.decrypt(row["secret"]))
        except (InvalidToken, ValueError):
            return None

    def connected(self, user_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT server_id FROM troika_service_connections WHERE user_id = ?", (user_id,),
            ).fetchall()
        return {str(row["server_id"]) for row in rows}

    def delete(self, user_id: str, server_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM troika_service_connections WHERE user_id = ? AND server_id = ?",
                (user_id, server_id),
            )


# --- configuration ---------------------------------------------------------

@dataclass
class ServiceConfig:
    store: ServiceConnectionStore | None = None
    public_url: str = ""

    @property
    def enabled(self) -> bool:
        return self.store is not None

    @property
    def redirect_uri(self) -> str:
        return self.public_url.rstrip("/") + CALLBACK_PATH if self.public_url else ""


_config = ServiceConfig()


def configure(database: Path | None, key: str, public_url: str) -> ServiceConfig:
    """Enable connections only with an encryption key and an HTTPS public URL."""
    global _config
    store = None
    if database is not None and key:
        try:
            store = ServiceConnectionStore(database, key)
        except (ValueError, TypeError):
            store = None
    url = public_url.strip() if isinstance(public_url, str) else ""
    if url and not url.startswith("https://"):
        url = ""
    _config = ServiceConfig(store=store, public_url=url)
    return _config


def config() -> ServiceConfig:
    return _config


# --- MCP SDK storage --------------------------------------------------------

class _Storage:
    """TokenStorage backed by the encrypted row of one owner and server."""

    def __init__(self, store: ServiceConnectionStore, user_id: str, server_id: str, persist: bool = True):
        self.store, self.user_id, self.server_id, self.persist = store, user_id, server_id, persist
        self.tokens: dict | None = None
        self.client: dict | None = None
        self.expires_at: float | None = None
        loaded = store.load(user_id, server_id) if persist else None
        if loaded and loaded[0] == "oauth":
            self.tokens = loaded[1].get("tokens")
            self.client = loaded[1].get("client")
            self.expires_at = loaded[1].get("expires_at")

    def _write(self) -> None:
        if self.persist and self.tokens:
            self.store.save(self.user_id, self.server_id, "oauth",
                            {"tokens": self.tokens, "client": self.client, "expires_at": self.expires_at})

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        return OAuthToken.model_validate(self.tokens) if self.tokens else None

    async def set_tokens(self, tokens) -> None:
        self.tokens = tokens.model_dump(mode="json", exclude_none=True)
        self.expires_at = time.time() + tokens.expires_in if tokens.expires_in else None
        self._write()

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        return OAuthClientInformationFull.model_validate(self.client) if self.client else None

    async def set_client_info(self, client_info) -> None:
        self.client = client_info.model_dump(mode="json", exclude_none=True)
        self._write()


def _client_metadata(redirect_uri: str):
    from mcp.shared.auth import OAuthClientMetadata
    return OAuthClientMetadata(
        client_name="Troika", redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"], response_types=["code"],
        token_endpoint_auth_method="none",
    )


async def _no_interaction(_url: str) -> None:
    raise ServiceAuthRequired("sign-in required")


async def _no_callback() -> tuple[str, str | None]:
    raise ServiceAuthRequired("sign-in required")


def _oauth_provider(storage: _Storage, url: str, redirect_handler=_no_interaction, callback_handler=_no_callback):
    from mcp.client.auth import OAuthClientProvider
    provider = OAuthClientProvider(url, _client_metadata(_config.redirect_uri), storage,
                                   redirect_handler=redirect_handler, callback_handler=callback_handler)
    if storage.tokens:
        # Reload stored state, including the expiry the SDK otherwise forgets,
        # so an expired access token is refreshed instead of re-authorizing.
        from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
        provider.context.current_tokens = OAuthToken.model_validate(storage.tokens)
        provider.context.client_info = (OAuthClientInformationFull.model_validate(storage.client)
                                        if storage.client else None)
        provider.context.token_expiry_time = storage.expires_at
        provider._initialized = True
    return provider


def auth_for(entry: dict, user_id: str):
    """httpx auth (or headers) for a stored connection; raises if missing."""
    if not _config.enabled:
        raise ServiceAuthRequired("connections disabled")
    loaded = _config.store.load(user_id, entry["id"])
    if loaded is None:
        raise ServiceAuthRequired("not connected")
    kind, secret = loaded
    if kind == "token":
        return None, {"Authorization": f"Bearer {secret['token']}"}
    storage = _Storage(_config.store, user_id, entry["id"])
    return _oauth_provider(storage, entry["url"]), {}


# --- pending OAuth flows ----------------------------------------------------

@dataclass
class _Flow:
    user_id: str
    server_id: str
    created: float
    state: str = ""
    url: str = ""
    status: str = "starting"
    url_ready: asyncio.Event = field(default_factory=asyncio.Event)
    callback: asyncio.Future | None = None
    task: asyncio.Task | None = None


_flows: dict[str, _Flow] = {}
_flows_lock = threading.Lock()


def _prune() -> None:
    now = time.monotonic()
    with _flows_lock:
        for flow_id, flow in list(_flows.items()):
            if now - flow.created > FLOW_TTL:
                if flow.task and not flow.task.done():
                    flow.task.cancel()
                _flows.pop(flow_id, None)


async def start_oauth(entry: dict, user_id: str, list_tools) -> tuple[str, str]:
    """Begin sign-in on the running loop; returns (flow_id, authorization URL).

    ``list_tools(entry, auth)`` performs one authenticated request so the SDK
    runs discovery, registration and the authorization redirect.
    """
    if not _config.enabled or not _config.redirect_uri:
        raise ServiceAuthRequired("connections disabled")
    _prune()
    loop = asyncio.get_running_loop()
    flow_id = secrets.token_urlsafe(24)
    flow = _Flow(user_id=user_id, server_id=entry["id"], created=time.monotonic())
    flow.callback = loop.create_future()
    # Tokens are written only after the whole sign-in succeeds.
    storage = _Storage(_config.store, user_id, entry["id"], persist=False)

    async def redirect(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ServiceAuthRequired("insecure authorization endpoint")
        flow.url = url
        flow.state = (parse_qs(parsed.query).get("state") or [""])[0]
        flow.status = "waiting"
        flow.url_ready.set()

    async def callback() -> tuple[str, str | None]:
        return await asyncio.wait_for(flow.callback, FLOW_TTL)

    async def run() -> None:
        try:
            provider = _oauth_provider(storage, entry["url"], redirect, callback)
            await list_tools(entry, provider)
            storage.persist = True
            storage._write()
            flow.status = "connected" if storage.tokens else "failed"
        except asyncio.CancelledError:
            flow.status = "expired"
            raise
        except Exception:
            flow.status = "failed"
        finally:
            flow.url_ready.set()

    flow.task = loop.create_task(run())
    with _flows_lock:
        _flows[flow_id] = flow
    try:
        await asyncio.wait_for(flow.url_ready.wait(), 45)
    except asyncio.TimeoutError:
        flow.task.cancel()
        raise ServiceAuthRequired("authorization server did not respond")
    if not flow.url or not flow.state:
        raise ServiceAuthRequired("authorization was not offered")
    return flow_id, flow.url


def flow_status(flow_id: str, user_id: str) -> str | None:
    _prune()
    with _flows_lock:
        flow = _flows.get(flow_id)
    if flow is None or flow.user_id != user_id:
        return None
    return flow.status


def complete_oauth(state: str, code: str | None, error: str | None) -> bool:
    """Resolve the pending flow with the browser callback; single use."""
    if not state:
        return False
    with _flows_lock:
        flow = next((item for item in _flows.values()
                     if item.state and secrets.compare_digest(item.state, state)), None)
    if flow is None or flow.callback is None or flow.callback.done():
        return False
    if error or not code:
        flow.callback.set_exception(ServiceAuthRequired("authorization denied"))
        return False
    flow.callback.set_result((code, state))
    return True


def valid_token(value: Any) -> bool:
    return (isinstance(value, str) and 8 <= len(value) <= MAX_TOKEN_LENGTH
            and not any(char.isspace() for char in value))
