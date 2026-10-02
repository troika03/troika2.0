from run_agent import AIAgent
from unittest.mock import Mock
from gateway.session_context import clear_session_override, set_session_override


def test_product_mode_uses_troika_identity_instead_of_stale_soul(monkeypatch):
    """A stale Hermes SOUL.md cannot rename an authenticated product session."""

    monkeypatch.setattr(
        "run_agent.load_soul_md",
        lambda: "You are Hermes Agent, an intelligent AI assistant created by Nous Research.",
    )
    operator_context = Mock(return_value="OPERATOR_ONLY_CONTEXT")
    global_memory = Mock(return_value="GLOBAL_SOMA_CONTEXT")
    environment = Mock(return_value="OPERATOR_ENVIRONMENT")
    monkeypatch.setattr("run_agent.build_context_files_prompt", operator_context)
    monkeypatch.setattr("run_agent.build_environment_hints", environment)
    monkeypatch.setattr("tools.soma_tool.soma_context_hint", global_memory)
    set_session_override("TROIKA_PRODUCT_MODE", "1")
    try:
        agent = AIAgent(
            model="openrouter/free",
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
            max_iterations=1,
            quiet_mode=True,
            skip_context_files=False,
            skip_memory=True,
        )
        parts = agent._build_system_prompt_parts()
        stable = parts["stable"]
    finally:
        clear_session_override("TROIKA_PRODUCT_MODE")

    assert stable.startswith("# Тройка — кто ты")
    assert "Ты — **Тройка**" in stable
    assert "You are Hermes Agent" not in stable
    assert "Не называй себя Hermes" in stable
    operator_context.assert_not_called()
    environment.assert_not_called()
    global_memory.assert_not_called()
    assert "Active Hermes profile:" not in stable
    assert parts["context"] == ""
