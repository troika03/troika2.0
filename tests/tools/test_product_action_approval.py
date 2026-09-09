"""Tests for one-time confirmation of hosted product device actions."""

import threading

from tools.approval import (
    get_gateway_approval_choices,
    register_gateway_notify,
    request_gateway_approval,
    resolve_gateway_approval,
    reset_current_session_key,
    set_current_session_key,
    unregister_gateway_notify,
)


def test_product_action_requires_one_time_confirmation() -> None:
    session_key = "product-action-test"
    notified = threading.Event()
    received: list[dict] = []
    result: dict = {}

    def notify(data: dict) -> None:
        received.append(data)
        notified.set()

    def ask() -> None:
        token = set_current_session_key(session_key)
        try:
            result.update(
                request_gateway_approval("phone.open_app", "Open Maps on this phone.")
            )
        finally:
            reset_current_session_key(token)

    register_gateway_notify(session_key, notify)
    worker = threading.Thread(target=ask)
    worker.start()
    try:
        assert notified.wait(timeout=2)
        assert received[0]["choices"] == ["once", "deny"]
        assert get_gateway_approval_choices(session_key) == ("once", "deny")
        assert resolve_gateway_approval(session_key, "once") == 1
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert result == {"approved": True, "user_consent": True, "choice": "once"}
    finally:
        unregister_gateway_notify(session_key)
        worker.join(timeout=2)


def test_product_action_fails_closed_without_a_gateway_listener() -> None:
    token = set_current_session_key("product-no-listener")
    try:
        result = request_gateway_approval("phone.open_app", "Open Maps on this phone.")
    finally:
        reset_current_session_key(token)

    assert result["approved"] is False
    assert result["reason"] == "approval_listener_unavailable"
