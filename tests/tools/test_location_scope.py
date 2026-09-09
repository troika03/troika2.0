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
