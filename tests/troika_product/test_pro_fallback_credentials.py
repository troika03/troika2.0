"""A hosted Pro refusal can fall back without a second environment credential."""

from tests.troika_product.test_pro_model import make_adapter, run_for


def test_pro_fallback_can_resolve_with_only_the_primary_runtime_key(make_adapter, monkeypatch):
    from agent import auxiliary_client

    runtime = {"provider": "openrouter", "api_key": "fixture-hosted-key",
               "base_url": "https://openrouter.ai/api/v1"}
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: dict(runtime))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", lambda *_: (False, None))
    build, created = make_adapter
    config = run_for(build("fixture/pro-model"), created, "pro")
    fallback = config["fallback_model"][0]
    client, model = auxiliary_client.resolve_provider_client(
        fallback["provider"], model=fallback["model"],
        explicit_base_url=fallback.get("base_url"), explicit_api_key=fallback.get("api_key"),
    )
    assert client is not None
    try:
        assert client.api_key == runtime["api_key"]
        assert str(client.base_url).rstrip("/") == runtime["base_url"]
        assert model == "fixture/free-model"
    finally:
        client.close()


def test_hosted_credentials_do_not_enable_fallback_for_non_pro(make_adapter, monkeypatch):
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: {
        "provider": "openrouter", "api_key": "fixture-hosted-key"})
    build, created = make_adapter
    adapter = build("fixture/pro-model")
    for plan in ("free", "plus"):
        assert run_for(adapter, created, plan)["fallback_model"] is None
