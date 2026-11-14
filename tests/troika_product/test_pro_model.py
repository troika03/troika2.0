"""Pro runs use the configured stronger model; other plans keep the default."""

import pytest


@pytest.fixture
def make_adapter(tmp_path, monkeypatch):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    created = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(kwargs)

        def interrupt(self):
            pass

    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: {"provider": "openrouter"})
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "fixture/free-model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    monkeypatch.setattr("gateway.run.GatewayRunner._load_reasoning_config", staticmethod(lambda: None))
    monkeypatch.setattr("gateway.run.GatewayRunner._load_fallback_model", staticmethod(lambda: None))
    monkeypatch.setattr("hermes_cli.tools_config._get_platform_tools", lambda *_: set())
    monkeypatch.setattr("troika_product.agent_policy.install_agent_policy", lambda *a, **k: None)

    def build(pro_model):
        extra = {"product_auth_enabled": True, "product_auth_db": str(tmp_path / f"{len(created)}.db")}
        if pro_model:
            extra["product_pro_model"] = pro_model
        adapter = APIServerAdapter(PlatformConfig(enabled=True, extra=extra))
        monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)
        return adapter

    return build, created


def run_for(adapter, created, plan):
    from agent.provider_metering import provider_metering_scope

    registry = adapter._access_registry
    user = registry.create_user(f"{plan}-{len(created)}@example.invalid", plan=plan)
    device = registry.create_device(user, name="fixture", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))

    class Guard:
        def __init__(self):
            self.principal = principal
            self.credentials = None
            self.context = None

    with provider_metering_scope(Guard()):
        adapter._create_agent(current_user_message="Покажи мои репозитории на GitHub")
    return created[-1]


def test_pro_gets_the_stronger_model_with_the_default_as_fallback(make_adapter):
    build, created = make_adapter
    adapter = build("deepseek/deepseek-v4.1-flash-1017")
    pro = run_for(adapter, created, "pro")
    assert pro["model"] == "deepseek/deepseek-v4.1-flash-1017"
    assert pro["fallback_model"] == [{"provider": "openrouter", "model": "fixture/free-model"}]
    for plan in ("free", "plus"):
        other = run_for(adapter, created, plan)
        assert other["model"] == "fixture/free-model" and other["fallback_model"] is None


def test_without_a_configured_pro_model_nothing_changes(make_adapter):
    build, created = make_adapter
    adapter = build("")
    assert run_for(adapter, created, "pro")["model"] == "fixture/free-model"
