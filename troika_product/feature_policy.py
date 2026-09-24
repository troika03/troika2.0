"""Troika 1.0 product-scope feature policy.

Legacy Hermes capabilities remain in the repository, but the hosted product
runtime exposes only the reviewed Troika toolset. Experimental capabilities
need an explicit operator flag and a separate reviewed integration before they
can become reachable from the product agent.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ExperimentalFeature:
    """One preserved capability hidden from the normal Troika 1.0 product."""

    key: str
    config_key: str
    environment_key: str


EXPERIMENTAL_FEATURES: tuple[ExperimentalFeature, ...] = (
    ExperimentalFeature(
        "ground", "product_ground_enabled", "TROIKA_PRODUCT_GROUND_ENABLED"
    ),
    ExperimentalFeature(
        "legacy_daemon",
        "product_legacy_daemon_enabled",
        "TROIKA_PRODUCT_LEGACY_DAEMON_ENABLED",
    ),
    ExperimentalFeature(
        "screen_live",
        "product_screen_live_enabled",
        "TROIKA_PRODUCT_SCREEN_LIVE_ENABLED",
    ),
    ExperimentalFeature(
        "camera_live",
        "product_camera_live_enabled",
        "TROIKA_PRODUCT_CAMERA_LIVE_ENABLED",
    ),
    ExperimentalFeature(
        "accessibility_control",
        "product_accessibility_control_enabled",
        "TROIKA_PRODUCT_ACCESSIBILITY_CONTROL_ENABLED",
    ),
    ExperimentalFeature("kali", "product_kali_enabled", "TROIKA_PRODUCT_KALI_ENABLED"),
    ExperimentalFeature(
        "self_improvement",
        "product_self_improvement_enabled",
        "TROIKA_PRODUCT_SELF_IMPROVEMENT_ENABLED",
    ),
    ExperimentalFeature(
        "video_generation",
        "product_video_generation_enabled",
        "TROIKA_PRODUCT_VIDEO_GENERATION_ENABLED",
    ),
    ExperimentalFeature(
        "exotic_messengers",
        "product_exotic_messengers_enabled",
        "TROIKA_PRODUCT_EXOTIC_MESSENGERS_ENABLED",
    ),
    ExperimentalFeature(
        "rare_hermes_tools",
        "product_rare_hermes_tools_enabled",
        "TROIKA_PRODUCT_RARE_HERMES_TOOLS_ENABLED",
    ),
    ExperimentalFeature(
        "autonomous_pc",
        "product_autonomous_pc_enabled",
        "TROIKA_PRODUCT_AUTONOMOUS_PC_ENABLED",
    ),
)


# These tools must never enter the normal hosted product toolset. The list is
# intentionally explicit so tests fail when product routing widens by accident.
FORBIDDEN_PRODUCT_TOOLS = frozenset({
    "ground_start",
    "ground_stop",
    "ground_status",
    "daemon_start",
    "daemon_stop",
    "daemon_status",
    "android_tap",
    "android_type_text",
    "android_swipe",
    "android_read_screen",
    "android_screenshot",
    "workspace_enter",
    "workspace_exit",
    "workspace_status",
    "workspace_confirm",
    "self_improve_propose",
    "self_improve_approve",
    "self_improve_reject",
    "self_improve_revert",
    "video_generate",
    "find_tool",
    "run_tool",
    "telegram_send",
    "send_message",
    "pc_open_app",
    "pc_open_file",
    "pc_gui_control",
    "pc_run",
    "pc_see_screen",
    "terminal",
    "execute_code",
    "delegate_task",
})


def experimental_feature_flags(
    extra: Mapping[str, object] | None = None,
) -> dict[str, bool]:
    """Resolve explicit flags. Every experiment defaults to disabled."""
    config = extra or {}
    return {
        feature.key: _as_bool(
            config.get(feature.config_key, os.getenv(feature.environment_key, "false"))
        )
        for feature in EXPERIMENTAL_FEATURES
    }


def product_toolsets(
    *, screen_snapshot_enabled: bool, external_vision_enabled: bool
) -> list[str]:
    """Return the complete hosted product toolset allowlist."""
    enabled = ["troika-product"]
    if screen_snapshot_enabled and external_vision_enabled:
        enabled.append("troika-screen-snapshot")
    return enabled
