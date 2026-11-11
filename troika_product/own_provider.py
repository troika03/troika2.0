"""Request-scoped personal provider keys, with no hosted inference fallback."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from agent.provider_metering import ProviderCallBlocked
from troika_product.resource_runtime import ResourceRuntime

_credentials = ContextVar("troika_personal_provider", default=None)
ENDPOINTS = {"openrouter": "https://openrouter.ai/api/v1",
             "openai": "https://api.openai.com/v1"}


@dataclass(frozen=True)
class OwnCredentials:
    provider: str
    model: str
    key: str = field(repr=False)

    def __post_init__(self):
        if (self.provider not in ENDPOINTS or not 1 <= len(self.model) <= 200
                or any(c.isspace() for c in self.model)
                or not 16 <= len(self.key) <= 512 or any(c.isspace() for c in self.key)):
            raise ProviderCallBlocked("resource_byok_invalid", "Проверь провайдера, модель и свой API-ключ.")


def bind_request(headers, *, enabled):
    _credentials.set(None)
    key = headers.get("X-Troika-Provider-Key", "")
    if not key:
        if headers.get("X-Troika-Provider") or headers.get("X-Troika-Provider-Model"):
            raise ProviderCallBlocked("resource_byok_invalid", "Для своего API нужен личный ключ.")
        return
    if enabled is not True:
        raise ProviderCallBlocked("resource_byok_disabled", "Подключение личного API пока недоступно.")
    _credentials.set(OwnCredentials(headers.get("X-Troika-Provider", ""),
                                    headers.get("X-Troika-Provider-Model", ""), key))


def current_credentials():
    return _credentials.get()


class _PersonalLease:
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.settled = False

    def succeeded(self, response):
        if not self.settled:
            self.diagnostics.received(response)
            self.settled = True

    def require_settled(self):
        pass

    def failed(self, error):
        raise ProviderCallBlocked("resource_byok_request_failed",
                                  "Личный API не выполнил запрос. Проверь ключ, модель и баланс провайдера; ключ Тройки не использован.") from None


class OwnProviderRuntime(ResourceRuntime):
    """Retain account permissions/task slots while personal LLM calls debit zero."""
    def __init__(self, *args, credentials, **kwargs):
        super().__init__(*args, **kwargs)
        self.credentials = credentials
        self._personal_clients = []

    def prepare_client(self, client, *, async_mode=False):
        if getattr(client, "_troika_personal_scope", None) is self:
            return client
        from openai import OpenAI, AsyncOpenAI
        cls = AsyncOpenAI if async_mode else OpenAI
        own = cls(api_key=self.credentials.key, base_url=ENDPOINTS[self.credentials.provider],
                  max_retries=0, timeout=120)
        own._troika_personal_scope = self
        self._personal_clients.append(own)
        return own

    def begin_call(self, payload, *, provider, base_url):
        self.check_deadline()
        if self.stopped or base_url.rstrip("/") != ENDPOINTS[self.credentials.provider]:
            raise ProviderCallBlocked("resource_byok_scope_invalid", "Маршрут личного API остановлен.")
        self.ledger.heartbeat_run(self.principal, self.run_key)
        bounded = dict(payload, model=self.credentials.model)
        # Only a fixed SDK endpoint receives this personal key. Dynamic routing
        # still uses that key; it cannot select a company-funded client.
        bounded.setdefault("max_tokens", 8192)
        bounded.pop("extra_headers", None)
        bounded.pop("extra_query", None)
        if bounded.get("stream"):
            bounded["stream_options"] = {**(bounded.get("stream_options") or {}), "include_usage": True}
        self.diagnostics.dispatched(bounded)
        return _PersonalLease(self.diagnostics), bounded

    def finish(self):
        super().finish()
        for client in self._personal_clients:
            client.api_key = ""
        self._personal_clients.clear()
        self.credentials = None
