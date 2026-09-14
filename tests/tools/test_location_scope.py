"""Isolation tests for saved device-location fingerprints."""

from pathlib import Path

from tools import location_tool


def test_named_locations_are_scoped_to_the_current_session(tmp_path, monkeypatch) -> None:
    """Two users may use the same place name without reading each other's data."""
    db_path = Path(tmp_path) / "locations.db"
    monkeypatch.setattr(location_tool, "_db_path", lambda: db_path)
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool._DEVICE_CONTEXT_CACHE.update(
        {
            "user-one": {"bssid": "aa:aa:aa:aa:aa:aa", "network_type": "wifi"},
            "user-two": {"bssid": "bb:bb:bb:bb:bb:bb", "network_type": "wifi"},
        }
    )

    assert location_tool._set({"name": "home"}, "user-one")["ok"]
    assert location_tool._set({"name": "home"}, "user-two")["ok"]

    one = location_tool._get({}, "user-one")
    two = location_tool._get({}, "user-two")
    assert one["location"] == "home"
    assert two["location"] == "home"

    assert location_tool._forget({"name": "home"}, "user-one")["deleted"] == 1
    assert location_tool._list("user-one")["count"] == 0
    assert location_tool._list("user-two")["count"] == 1


def test_location_context_can_be_cleared_after_consent_revocation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(location_tool, "_cache_file", lambda: tmp_path / "context.json")
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool.remember_device_context("user-one", {"lat": 55.7, "lon": 37.6})

    location_tool.clear_device_context("user-one")
    assert location_tool.get_device_context("user-one") == {}


def test_account_scope_deletion_clears_context_and_saved_locations(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "locations.db"
    cache_path = tmp_path / "context.json"
    monkeypatch.setattr(location_tool, "_db_path", lambda: db_path)
    monkeypatch.setattr(location_tool, "_cache_file", lambda: cache_path)
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool._DEVICE_CONTEXT_CACHE.update(
        {
            "user-one": {"bssid": "aa"},
            "user-two": {"bssid": "bb"},
        }
    )
    location_tool._set({"name": "home"}, "user-one")
    location_tool._set({"name": "home"}, "user-two")

    location_tool.delete_location_scope("user-one")

    assert location_tool.get_device_context("user-one") == {}
    assert location_tool.get_device_context("user-two") == {"bssid": "bb"}
    assert location_tool._list("user-one")["count"] == 0
    assert location_tool._list("user-two")["count"] == 1
    assert "user-one" not in cache_path.read_text(encoding="utf-8")


def test_reverse_geocoding_is_off_without_operator_feature_flag(monkeypatch) -> None:
    location_tool._GEOCODE_CACHE.clear()
    monkeypatch.delenv("TROIKA_EXTERNAL_GEOCODING_ENABLED", raising=False)

    def should_not_connect(*_args, **_kwargs):
        raise AssertionError("external geocoding must be disabled")

    monkeypatch.setattr(location_tool.urllib.request, "build_opener", should_not_connect)
    assert location_tool.reverse_geocode(55.7, 37.6) is None
