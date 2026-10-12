"""Optional per-provider-call guard shared by main and auxiliary clients.

The core exposes a generic boundary; account policy belongs to the injected
guard. No guard means the original client and behavior are returned unchanged.
"""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps


class ProviderCallBlocked(RuntimeError):
    """A policy refusal must not trigger retries or a more expensive fallback."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_current_guard = ContextVar("provider_call_guard", default=None)
_current_client_cache = ContextVar("provider_call_client_cache", default=None)


@contextmanager
def provider_metering_scope(guard):
    token = _current_guard.set(guard)
    cache_token = _current_client_cache.set({} if guard is not None else None)
    try:
        yield
    finally:
        _current_client_cache.reset(cache_token)
        _current_guard.reset(token)


def current_provider_guard():
    return _current_guard.get()


def current_provider_client_cache():
    """Guarded clients must never live in a process-wide cross-account cache."""
    return _current_client_cache.get()


def provider_context_target(target):
    """Carry the active account into one background worker invocation."""
    if current_provider_guard() is None:
        return target
    context = copy_context()

    @wraps(target)
    def scoped(*args, **kwargs):
        return context.run(target, *args, **kwargs)

    return scoped


def uncertain_provider_error(error):
    """A watchdog cannot determine whether an in-flight request was billed."""
    guard = current_provider_guard()
    if guard is None or isinstance(error, ProviderCallBlocked):
        return error
    guard.block_pending_calls()
    return ProviderCallBlocked(
        "resource_usage_unknown",
        "Вызов прерван без сверки расхода; резерв сохранён, повторы остановлены.",
    )


def require_metered_api_mode(mode):
    guard = current_provider_guard()
    if guard is not None and mode != "chat_completions":
        raise ProviderCallBlocked(
            "unmetered_provider_route",
            "Этот маршрут модели пока не поддерживает учёт AI-ресурса.",
        )


def wrap_provider_client(client, *, provider=None, async_mode=False):
    guard = current_provider_guard()
    if guard is None or client is None:
        return client
    if isinstance(client, _GuardedClient):
        if client._guard is guard:
            return client
        client = client._original
    # Hidden SDK retries would send several billable attempts under one hold.
    if getattr(client, "max_retries", None) != 0:
        raise ProviderCallBlocked(
            "unmetered_sdk_retries",
            "Внутренние повторы провайдера должны быть отключены для учёта ресурса.",
        )
    return _GuardedClient(client, guard, provider, async_mode)


def metered_client_resolver(resolve):
    """Reject adapters that bypass the guarded SDK while a guard is active."""

    @wraps(resolve)
    def checked(*args, **kwargs):
        client, model = resolve(*args, **kwargs)
        if current_provider_guard() is not None and client is not None:
            if not isinstance(client, _GuardedClient):
                raise ProviderCallBlocked(
                    "unmetered_provider_route",
                    "Этот вспомогательный маршрут ещё не поддерживает учёт ресурса.",
                )
            client._check_scope()
        return client, model

    return checked


class _GuardedClient:
    def __init__(self, client, guard, provider, async_mode):
        self._original, self._guard = client, guard
        self._provider, self._async_mode = provider, async_mode
        self.chat = _Chat(self)

    def __getattr__(self, name):
        if name in {
            "responses",
            "audio",
            "images",
            "embeddings",
            "batches",
            "beta",
            "with_raw_response",
            "with_streaming_response",
        }:
            raise ProviderCallBlocked(
                "unmetered_provider_route",
                "Этот вызов провайдера ещё не подключён к учёту ресурса.",
            )
        return getattr(self._original, name)

    def with_options(self, **kwargs):
        self._check_scope()
        kwargs["max_retries"] = 0
        return wrap_provider_client(
            self._original.with_options(**kwargs),
            provider=self._provider,
            async_mode=self._async_mode,
        )

    copy = with_options

    def _check_scope(self):
        if current_provider_guard() is not self._guard:
            raise ProviderCallBlocked(
                "resource_scope_changed",
                "Вызов модели не принадлежит текущей задаче аккаунта.",
            )

    def _begin(self, kwargs):
        self._check_scope()
        return self._guard.begin_call(
            kwargs,
            provider=self._provider,
            base_url=str(getattr(self._original, "base_url", "")),
        )


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        raise ProviderCallBlocked(
            "unmetered_provider_route",
            "Доступен только учитываемый вызов chat.completions.create.",
        )

    def create(self, **kwargs):
        if self._client._async_mode:
            return self._create_async(kwargs)
        lease, bounded = self._client._begin(kwargs)
        try:
            response = self._client._original.chat.completions.create(**bounded)
            if not bounded.get("stream"):
                lease.succeeded(response)
        except BaseException as error:
            lease.failed(error)
            raise
        if bounded.get("stream"):
            return _Stream(response, lease)
        return response

    async def _create_async(self, kwargs):
        lease, bounded = self._client._begin(kwargs)
        try:
            response = await self._client._original.chat.completions.create(**bounded)
            if not bounded.get("stream"):
                lease.succeeded(response)
        except BaseException as error:
            lease.failed(error)
            raise
        if bounded.get("stream"):
            return _AsyncStream(response, lease)
        return response


class _Stream:
    def __init__(self, stream, lease):
        self._stream, self._lease = stream, lease

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def __iter__(self):
        try:
            for chunk in self._stream:
                if (
                    chunk.get("usage")
                    if isinstance(chunk, dict)
                    else getattr(chunk, "usage", None)
                ) is not None:
                    self._lease.succeeded(chunk)
                yield chunk
            self._lease.require_settled()
        except BaseException as error:
            self._lease.failed(error)
            raise

    def close(self):
        # Missing final usage retains the hold; close cannot imply free work.
        if not self._lease.settled:
            self._lease.failed(None)
        return self._stream.close()

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *args):
        if not self._lease.settled:
            self._lease.failed(None)
        return self._stream.__exit__(*args)


class _AsyncStream(_Stream):
    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                if (
                    chunk.get("usage")
                    if isinstance(chunk, dict)
                    else getattr(chunk, "usage", None)
                ) is not None:
                    self._lease.succeeded(chunk)
                yield chunk
            self._lease.require_settled()
        except BaseException as error:
            self._lease.failed(error)
            raise

    async def close(self):
        if not self._lease.settled:
            self._lease.failed(None)
        return await self._stream.close()

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        if not self._lease.settled:
            self._lease.failed(None)
        return await self._stream.__aexit__(*args)
