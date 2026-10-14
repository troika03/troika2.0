"""Personal SDKs must never spend company keys or subscription balances."""
from types import SimpleNamespace
import pytest
from agent.provider_metering import provider_metering_scope, wrap_provider_client, ProviderCallBlocked
from troika_product.own_provider import OwnCredentials, OwnProviderRuntime, bind_request, current_credentials
from troika_product.access import AccessRegistry


def test_key_validation_and_representation_never_expose_credentials():
    key = "personal-key-fixture-123456"
    own = OwnCredentials("openrouter", "openrouter/free", key)
    assert key not in repr(own)
    with pytest.raises(ProviderCallBlocked):
        bind_request({"X-Troika-Provider": "openrouter"}, enabled=True)
    assert current_credentials() is None
    with pytest.raises(ProviderCallBlocked):
        OwnCredentials("arbitrary-host", "model", key)


@pytest.mark.parametrize("fail", [False, True])
def test_personal_key_replaces_every_sdk_and_preserves_exhausted_balance(tmp_path, monkeypatch, fail):
    registry = AccessRegistry(tmp_path / "access.db")
    user = registry.create_user("own@example.invalid", plan="free")
    device = registry.create_device(user, name="personal", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    own = OwnProviderRuntime(registry, principal, run_key="personal-run", config={},
                             credentials=OwnCredentials("openrouter", "personal/model", "personal-fixture-key-1234"))
    ledger = own.ledger
    balance = ledger.summary(principal)["remaining"]
    hold = ledger.reserve(principal, operation_key="consume", run_key="before", kind="tool",
                          tokens=balance, pricing_version="test")
    ledger.mark_dispatched(principal, hold.id)
    ledger.settle(principal, hold.id, charged_tokens=balance)
    calls = []
    class PersonalClient:
        def __init__(self, **kwargs):
            self.api_key = kwargs['api_key']; self.base_url = kwargs['base_url']; self.max_retries = kwargs['max_retries']
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append((self.api_key, kwargs['model']))
            if fail: raise RuntimeError("private provider failure")
            return SimpleNamespace(choices=[])
    monkeypatch.setattr("openai.OpenAI", PersonalClient)
    hosted = SimpleNamespace(max_retries=2, chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: pytest.fail("Company key must not be sent"))))
    own.start()
    try:
        with provider_metering_scope(own):
            guarded = wrap_provider_client(hosted)
            if fail:
                with pytest.raises(ProviderCallBlocked, match="Личный API"):
                    guarded.chat.completions.create(model="company/model", messages=[{"role":"user","content":"hello"}])
            else:
                guarded.chat.completions.create(model="company/model", messages=[{"role":"user","content":"hello"}])
        assert calls == [("personal-fixture-key-1234", "personal/model")]
        assert ledger.summary(principal)["remaining"] == 0
        assert len(ledger.export_rows(principal)["operations"]) == 1
    finally: own.finish()
