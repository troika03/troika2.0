"""Source packaging rejects incomplete deliverables before device transfer."""

import io
import json
import zipfile

import pytest

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_documents_tool
from troika_product.development import build_project
from troika_product.device_delivery import DeviceDeliveryStore


def project(**changes):
    files = {
        "index.html": '<input id="grams"><script src="index.js"></script>',
        "index.js": "exports.calories = (per100, grams) => per100 * grams / 100;",
        "test_calories.js": "const {calories}=require('./index');\n"
                            "const test=require('node:test');\n"
                            "const assert=require('node:assert/strict');\n"
                            "test('portion',()=>assert.equal(calories(150,80),120));",
        "README.md": "Open index.html. Run node --test test_calories.js.",
    }
    files.update(changes)
    return {"title": "Source packaging fixture", "files": [
        {"path": path, "content": content} for path, content in files.items()]}


@pytest.mark.parametrize("files", [
    [{"path": "main.py", "content": 'print("Hello World")'}],
    [{"path": "README.md", "content": "Build a web app"}],
    [{"path": "index.js", "content": ""},
     {"path": "README.md", "content": "Run tests"},
     {"path": "test_calc.js", "content": "assert(true)"}],
    [{"path": "index.js", "content": 'console.log("Hello, world!");'},
     {"path": "README.md", "content": "Run node index.js"},
     {"path": "test_calc.js", "content": "assert(true)"}],
])
def test_incomplete_source_is_not_delivered(monkeypatch, files):
    store = DeviceDeliveryStore()
    monkeypatch.setattr(troika_documents_tool, "device_deliveries", store)
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "owner", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token"}
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        result = json.loads(troika_documents_tool._handle_project({"files": files}))
    finally:
        for name in overrides:
            clear_session_override(name)
    assert not result["ok"]
    assert result["error"] == "project_generation_failed"
    assert "retry" in result["message"]
    assert "artifact" not in result
    assert store.list_pending("owner", "phone") == []


@pytest.mark.parametrize("missing", ["README.md", "test_calories.js", "index.js"])
def test_documentation_and_tests_are_required(missing):
    args = project()
    # Remove HTML too to model a project with documentation/tests but no implementation.
    args["files"] = [f for f in args["files"] if f["path"] != missing
                     and not (missing == "index.js" and f["path"] == "index.html")]
    with pytest.raises(ValueError, match="Incomplete source project"):
        build_project(args, require_complete=True)


def test_complete_source_is_preserved_without_execution(tmp_path):
    marker = tmp_path / "executed"
    args = project(**{"main.py": f"open({str(marker)!r}, 'w').write('bad')"})
    data, checks = build_project(args, require_complete=True)
    assert not marker.exists()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in args["files"]:
            assert archive.read(entry["path"]).decode("utf-8") == entry["content"]
        assert json.loads(archive.read("troika-project.json"))["execution"] == "not_run"
    assert any(c["scope"] == "python_syntax" for c in checks)


def test_hello_world_is_allowed_as_part_of_a_real_implementation():
    build_project(project(**{"demo.py": 'print("Hello World")'}), require_complete=True)


def test_browser_tests_can_use_the_conventional_test_js_name():
    args = project()
    for entry in args["files"]:
        if entry["path"] == "test_calories.js":
            entry["path"] = "test.js"
    build_project(args, require_complete=True)
@pytest.mark.parametrize('plan', ['free', 'plus', ''])
def test_legacy_project_tool_denies_non_pro_before_packing_or_model_calls(monkeypatch, plan):
    def forbidden(*args, **kwargs): raise AssertionError('Generation reached before Pro gate')
    monkeypatch.setattr(troika_documents_tool, 'build_project', forbidden)
    overrides = {'TROIKA_PRODUCT_MODE': '1', 'TROIKA_PRODUCT_PLAN': plan,
        'TROIKA_PRODUCT_DELIVERY_MODE': 'device', 'TROIKA_PRODUCT_USER_ID': 'owner',
        'TROIKA_PRODUCT_DEVICE_ID': 'phone', 'TROIKA_PRODUCT_TOKEN_ID': 'token'}
    try:
        for key, value in overrides.items(): set_session_override(key, value)
        result = json.loads(troika_documents_tool._handle_project({'task': 'Build a website'}))
    finally:
        for key in overrides: clear_session_override(key)
    assert result['error'] == 'development_pro_required' and not result['ok']
