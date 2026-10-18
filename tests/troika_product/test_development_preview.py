"""Preview framing must preserve page boundaries for the image reviewer."""
import base64
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace


def load_worker(monkeypatch):
    # The container resource limiter is POSIX-only; this test never executes it.
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "resource", SimpleNamespace())
    path = Path(__file__).parents[2] / "deploy" / "preview" / "worker.py"
    spec = importlib.util.spec_from_file_location("preview_worker_fixture", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def test_landscape_pages_do_not_gain_portrait_white_space(monkeypatch):
    from PIL import Image

    worker = load_worker(monkeypatch)
    data = io.BytesIO()
    Image.new("RGB", (1280, 720), "white").save(data, format="PNG")
    result = worker.contact_sheet([("page-1", data.getvalue()), ("page-2", data.getvalue())])
    sheet = Image.open(io.BytesIO(base64.b64decode(result["data"])))
    assert sheet.height < 500
    assert result["panels"] == ["page-1", "page-2"]
    for bound in result["panel_bounds"]:
        assert abs(bound["width"] / bound["height"] - 16 / 9) < .01
        assert bound["y"] + bound["height"] <= sheet.height
    assert sheet.getpixel((5, sheet.height - 5))[0] < 230


def test_invalid_styles_block_browser_tests_with_actual_parser_diagnostic(monkeypatch):
    worker = load_worker(monkeypatch)
    calls = []
    def command(arguments):
        calls.append(arguments)
        return 1, "styles.css:4:12: Unterminated string token"
    monkeypatch.setattr(worker, "command", command)
    result = worker.run_tests("node_tests", {"styles.css": "a{color:'unterminated}", "app.test.cjs": ""})
    assert result["status"] == "failed" and result["tests"] == 0
    assert "Unterminated string token" in result["output"]
    assert len(calls) == 1 and calls[0][1].endswith("css_check.mjs")
