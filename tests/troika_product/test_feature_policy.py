from toolsets import resolve_toolset
from troika_product.feature_policy import (
    EXPERIMENTAL_FEATURES,
    FORBIDDEN_PRODUCT_TOOLS,
    experimental_feature_flags,
    product_toolsets,
)


def test_every_experimental_product_feature_defaults_off(monkeypatch):
    for feature in EXPERIMENTAL_FEATURES:
        monkeypatch.delenv(feature.environment_key, raising=False)

    flags = experimental_feature_flags()

    assert set(flags) == {feature.key for feature in EXPERIMENTAL_FEATURES}
    assert not any(flags.values())


def test_explicit_flag_does_not_widen_hosted_product_toolset(monkeypatch):
    monkeypatch.setenv("TROIKA_PRODUCT_GROUND_ENABLED", "true")

    assert experimental_feature_flags()["ground"] is True
    assert product_toolsets(
        screen_snapshot_enabled=False, external_vision_enabled=False
    ) == ["troika-product"]


def test_normal_product_toolset_has_scope_and_no_experimental_tools():
    tools = set(resolve_toolset("troika-product"))

    assert {
        "troika_assistant",
        "web_search",
        "web_extract",
        "web_research",
        "troika_create_docx",
        "troika_create_pdf",
        "troika_create_pptx",
        "troika_files",
        "troika_file_search",
        "troika_terminal",
        "android_status",
    } <= tools
    assert not tools.intersection(FORBIDDEN_PRODUCT_TOOLS)


def test_screen_snapshot_needs_both_closed_beta_flags():
    assert product_toolsets(
        screen_snapshot_enabled=True, external_vision_enabled=False
    ) == ["troika-product"]
    assert product_toolsets(
        screen_snapshot_enabled=False, external_vision_enabled=True
    ) == ["troika-product"]
    assert product_toolsets(
        screen_snapshot_enabled=True, external_vision_enabled=True
    ) == ["troika-product", "troika-screen-snapshot"]
