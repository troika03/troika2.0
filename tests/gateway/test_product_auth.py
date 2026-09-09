"""Product-auth integration checks for the OpenAI-compatible API server."""

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter


class _Request(dict):
    """Minimal aiohttp request surface used by auth helper unit tests."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.headers = {"Authorization": f"Bearer {token}"}
        self.remote = "127.0.0.1"
        self.transport = None
        self.method = "GET"
        self.path_qs = "/v1/chat/completions"


def _adapter_with_two_users(tmp_path):
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
                "key": "legacy-bootstrap-key",
            },
        )
    )
    registry = adapter._access_registry
    assert registry is not None
    first_user = registry.create_user("one@example.com")
    second_user = registry.create_user("two@example.com")
    first_token = registry.issue_device_token(
        registry.create_device(first_user, name="Pixel", platform="android")
    )
    second_token = registry.issue_device_token(
        registry.create_device(second_user, name="iPhone", platform="ios")
    )
    return adapter, first_token, second_token


def test_product_auth_ignores_legacy_server_key_and_derives_memory_scope(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)

    legacy_request = _Request("legacy-bootstrap-key")
    assert adapter._check_auth(legacy_request).status == 401

    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    scope, error = adapter._parse_session_key_header(request)
    assert error is None
    assert scope is not None and scope.startswith("troika:usr_")


def test_product_session_owner_cannot_be_impersonated(tmp_path) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first = _Request(first_token)
    second = _Request(second_token)
    assert adapter._check_auth(first) is None
    assert adapter._check_auth(second) is None

    assert adapter._authorize_product_session(first, "private-session", claim=True) is None
    assert adapter._authorize_product_session(second, "private-session", claim=True).status == 403
