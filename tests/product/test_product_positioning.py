"""Regression checks for the public Troika 1.0 product promise."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PUBLIC_COPY = "\n".join((
    README,
    (ROOT / "assets" / "troika-banner.svg").read_text(encoding="utf-8"),
    (ROOT / "hermes-android" / "lib" / "screens" / "auth_screen.dart").read_text(
        encoding="utf-8"
    ),
    (
        ROOT / "hermes-android" / "lib" / "screens" / "onboarding_screen.dart"
    ).read_text(encoding="utf-8"),
    (ROOT / "hermes-android" / "README.md").read_text(encoding="utf-8"),
    (ROOT / "website" / "docs" / "index.mdx").read_text(encoding="utf-8"),
    (ROOT / "website" / "docusaurus.config.ts").read_text(encoding="utf-8"),
))


def test_readme_uses_the_canonical_product_promise_and_segments() -> None:
    assert "Скажи Тройке, что нужно сделать" in README
    assert "выполнит работу, сохранит результат" in README
    for segment in (
        "Студент",
        "Начинающий специалист",
        "Разработчик или power user",
        "Обычный пользователь",
    ):
        assert segment in README


def test_normal_product_copy_does_not_sell_internal_or_experimental_features() -> None:
    for forbidden_claim in (
        "150+ инструментов",
        "поток мыслей",
        "сама пишет себе инструменты",
        "DAEMON",
        "GROUND",
        "Kali-стол",
        "24/7",
    ):
        assert forbidden_claim not in PUBLIC_COPY
