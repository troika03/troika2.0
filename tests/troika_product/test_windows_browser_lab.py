import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.troika_windows_browser_lab import BrowserLab, ORIGIN, _fixture_route, _run_model, _verified
from scripts.troika_static_preview import StaticProjectPreview
from scripts.troika_browser_run import BrowserRunClient, _view_for_report
from troika_product.computer_control import ComputerControlError
from troika_product.computer_windows_browser import _matches_action, device_command


@pytest.mark.parametrize(("url", "method", "allowed"), [
    (ORIGIN + "overview", "GET", True),
    (ORIGIN + "details", "POST", False),
    (ORIGIN + "overview?other=1", "GET", False),
    ("https://troika-browser.test/overview", "GET", False),
    ("http://127.0.0.1/overview", "GET", False),
])
def test_only_fixture_pages_receive_a_response(url, method, allowed):
    route = Mock(request=SimpleNamespace(url=url, method=method))
    _fixture_route(route)
    assert route.fulfill.called is allowed
    assert route.abort.called is not allowed


def test_browser_rejects_external_or_unapproved_navigation_before_opening_windows():
    browser = Mock()
    lab = BrowserLab(browser)
    approve = Mock(return_value=False)
    external = {"action": "open", "page": "https://example.invalid"}
    assert lab.step(external, approve) == {"error": "invalid_action"}
    approve.assert_not_called()
    assert lab.step({"action": "open", "page": "overview"}, approve) == {"error": "denied"}
    browser.new_context.assert_not_called()
    assert lab.step({"action": "inspect"}, approve)["view"] == {"page": None, "open_pages": []}


def project_request(url, *, navigation=False):
    return Mock(request=SimpleNamespace(url=url, method="GET", is_navigation_request=lambda: navigation))


def test_project_preview_serves_only_selected_html_and_bounded_static_assets(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_bytes(b"<h1>Local project</h1>")
    (site / "other.html").write_bytes(b"<h1>Another page</h1>")
    css = site / "page.css"
    css.write_bytes(b"body{color:red}")
    (site / "page.js").write_bytes(b"alert(1)")
    (tmp_path / "outside.css").write_bytes(b"private")
    preview = StaticProjectPreview(site, "index.html")
    index = project_request(ORIGIN + "index.html", navigation=True)
    preview.route(index)
    assert index.fulfill.call_args.kwargs["body"] == b"<h1>Local project</h1>"
    style = project_request(ORIGIN + "page.css?v=1")
    preview.route(style)
    css.write_bytes(b"body{color:blue}")
    preview.route(style)
    assert style.fulfill.call_args.kwargs["body"] == b"body{color:red}"
    for name, navigation in (("other.html", True), ("page.js", False), ("%2e%2e/outside.css", False),
                             ("page.css%3Astream", False), ("page.css", True)):
        blocked = project_request(ORIGIN + name, navigation=navigation)
        preview.route(blocked)
        blocked.abort.assert_called_once()
        blocked.fulfill.assert_not_called()


def test_project_preview_rejects_hardlinked_assets(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_bytes(b"<h1>Local project</h1>")
    external = tmp_path / "outside.css"
    external.write_bytes(b"private")
    try:
        os.link(external, site / "asset.css")
    except OSError:
        pytest.skip("test volume has no hardlink support")
    blocked = project_request(ORIGIN + "asset.css")
    StaticProjectPreview(site, "index.html").route(blocked)
    blocked.abort.assert_called_once()
    blocked.fulfill.assert_not_called()


@pytest.mark.parametrize(("url", "closed"), [(ORIGIN + "details", False), (ORIGIN + "overview", True)])
def test_scroll_rejects_a_closed_or_replaced_page(url, closed):
    lab = BrowserLab(Mock())
    page = Mock(url=url)
    page.is_closed.return_value = closed
    lab.pages["overview"] = (page, 1)
    lab.active = "overview"
    with pytest.raises(ComputerControlError, match="browser_target_lost"):
        lab.step({"action": "scroll", "direction": "down"}, lambda _: True)
    page.mouse.wheel.assert_not_called()


def model_call(command):
    call = Mock(id="tool_call_1", function=SimpleNamespace(arguments=json.dumps(command)))
    call.model_dump.return_value = {"id": call.id}
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


def test_model_stops_on_denial():
    provider = Mock()
    provider.tool_step.return_value = model_call({"action": "open", "page": "overview"})
    browser = Mock()
    receipts = _run_model(BrowserLab(browser), provider, "Открой обзор", lambda _: False, float("inf"))
    assert receipts == [{"error": "denied"}]
    provider.tool_step.assert_called_once()
    browser.new_context.assert_not_called()


def test_replayed_model_call_does_not_dispatch_twice():
    provider = Mock()
    provider.tool_step.return_value = model_call({"action": "inspect"})
    lab = Mock()
    lab.step.return_value = {"action": "inspect"}
    with pytest.raises(ComputerControlError, match="browser_action_replayed"):
        _run_model(lab, provider, "Осмотри обзор", lambda _: True, float("inf"))
    lab.step.assert_called_once()


def test_model_reply_after_deadline_cannot_dispatch(monkeypatch):
    clock = iter((0.0, 2.0))
    monkeypatch.setattr("scripts.troika_windows_browser_lab.time", SimpleNamespace(monotonic=lambda: next(clock)))
    provider = Mock()
    provider.tool_step.return_value = model_call({"action": "open", "page": "overview"})
    lab = Mock()
    with pytest.raises(ComputerControlError, match="grant_expired"):
        _run_model(lab, provider, "Открой обзор", lambda _: True, 1.0)
    lab.step.assert_not_called()


def test_verification_requires_observed_scroll_to_survive_window_switch():
    delivery = {"page": "overview", "y": 640, "headings": ["Доставка"]}
    scroll = {"action": "scroll", "view": delivery}
    other_window = {"action": "open", "view": {"page": "details"}}
    returned = {"action": "switch", "view": delivery}
    assert _verified([scroll, other_window, returned], delivery)
    assert not _verified([other_window, scroll, returned], delivery)
    assert not _verified([scroll, other_window, returned], {**delivery, "y": 660})


def test_browser_run_cannot_verify_scroll_on_another_page_or_without_movement():
    command = SimpleNamespace(action="scroll", arguments={"direction": "down"})
    before = {"page": "overview", "open_pages": ["overview", "details"], "y": 320}
    assert not _matches_action(command, before, before)
    assert not _matches_action(command, before, {**before, "page": "details", "y": 640})
    assert not _matches_action(command, before, {**before, "y": 100})
    assert _matches_action(command, before, {**before, "y": 640})


def test_browser_click_requires_the_observed_link_and_verified_section():
    command = SimpleNamespace(action="click", arguments={"link_id": 2})
    before = {"page": "overview", "open_pages": ["overview"],
              "links": [{"id": 2, "label": "Delivery", "fragment": "delivery"}]}
    after = {**before, "fragment": "delivery", "at_section": True, "links": []}
    assert _matches_action(command, before, after)
    assert not _matches_action(command, before, {**after, "at_section": False})
    assert not _matches_action(command, before, {**after, "fragment": "other"})
    assert not _matches_action(command, {**before, "links": []}, after)


def test_device_rechecks_the_visible_link_after_approval():
    client = BrowserRunClient("http://127.0.0.1:8642", "run_" + "a" * 32, "b" * 32, "fixture-token")
    client.review = Mock(return_value="active")
    link = {"id": 2, "label": "Delivery", "fragment": "delivery"}
    original = {"links": [link]}
    lab = Mock()
    lab.inspect.side_effect = [original, {"links": [{**link, "fragment": "other"}]}]
    approve = Mock(return_value=True)
    try:
        result = client._perform(lab, "browser", {"inspect_action_id": "previous"}, {"action": "click", "link_id": 2},
                                 approve, "ask", float("inf"), "previous", original)
        assert result == ("stale_state", None)
        assert approve.call_args.args[0]["label"] == "Delivery"
        lab.step.assert_not_called()
    finally:
        client.close()


def test_stop_during_pointer_movement_prevents_the_click_and_clears_the_pointer():
    lab = BrowserLab(Mock(), visible_pointer=True)
    page = Mock(url=ORIGIN + "overview")
    page.is_closed.return_value = False
    lab.pages["overview"] = (page, 1)
    lab.active = "overview"
    lab._focus = Mock()
    link = {"id": 1, "label": "Delivery", "fragment": "delivery", "point": [72, 160]}
    assert lab._click(link, None, lambda: False) is None
    page.mouse.move.assert_called_with(72, 160)
    page.mouse.click.assert_not_called()
    assert page.evaluate.call_args.args[1] == [0, 0, None]


def test_click_coordinates_stay_on_the_device():
    link = {"id": 1, "label": "Delivery", "fragment": "delivery"}
    view = {"page": "overview", "open_pages": ["overview"], "headings": [], "y": 0, "max_y": 640,
            "fragment": None, "at_section": False, "links": [{**link, "point": [72, 160]}]}
    assert _view_for_report(view, True, True)["links"] == [link]


def test_closing_before_browser_consent_revokes_the_pending_grant():
    grant = "b" * 32
    client = BrowserRunClient("http://127.0.0.1:8642", "run_" + "a" * 32, grant, "fixture-token")
    client._send = Mock(return_value={"status": "pending", "grant_id": grant})
    try:
        assert client.review() == "pending"
    finally:
        client.close()
    assert [entry.args for entry in client._send.call_args_list] == [("review",), ("stop",)]


def test_shared_computer_tool_respects_the_approved_application_scope():
    with pytest.raises(ComputerControlError, match="app_not_approved"):
        device_command({"app": "notepad", "action": "open"}, ("overview",), ("browser",))
    assert device_command({"app": "notepad", "action": "write", "text": "Тройка"}, (), ("notepad",)) == (
        "notepad", "write", {"text": "Тройка"},
    )
