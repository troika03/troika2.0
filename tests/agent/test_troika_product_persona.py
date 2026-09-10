from run_agent import AIAgent
from gateway.session_context import clear_session_override, set_session_override


def test_product_mode_uses_troika_identity_instead_of_stale_soul(monkeypatch):
    """A stale Hermes SOUL.md cannot rename an authenticated product session."""

    monkeypatch.setattr(
        "run_agent.load_soul_md",
        lambda: "You are Hermes Agent, an intelligent AI assistant created by Nous Research.",
    )
    set_session_override("TROIKA_PRODUCT_MODE", "1")
    try:
        agent = AIAgent(
            model="openrouter/free",
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            provider="openrouter",
            max_iterations=1,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        stable = agent._build_system_prompt_parts()["stable"]
    finally:
        clear_session_override("TROIKA_PRODUCT_MODE")

    assert stable.startswith("# Тройка — кто ты")
    assert "Ты — **Тройка**" in stable
    assert "You are Hermes Agent" not in stable
    assert "Не называй себя Hermes" in stable
