"""The API developer writes real files and never treats prose as execution."""

import io
import json
from types import SimpleNamespace
import zipfile

import pytest

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_documents_tool
from troika_product.development_agent import DevelopmentAgent
from troika_product.device_delivery import DeviceDeliveryStore


FILES = {
    "main.py": "def add(a, b):\n    return a - b\n",
    "test_add.py": "import unittest\nfrom main import add\nclass TestAdd(unittest.TestCase):\n"
                   "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
    "README.md": "Run python -m unittest discover. Import add from main.py.",
}


def response(value, reason="stop"):
    return SimpleNamespace(model="configured-api-model", choices=[SimpleNamespace(
        finish_reason=reason, message=SimpleNamespace(content=json.dumps(value)))])


class Model:
    def __init__(self, *, coverage=True, correct=True):
        self.requests = []
        self.coverage = coverage
        self.correct = correct

    def __call__(self, messages, tokens, timeout):
        self.requests.append(messages)
        data = json.loads(messages[1]["content"])
        if "file" in data:
            path = data["file"]["path"]
            content = FILES[path]
            if data.get("review") and self.correct:
                content = content.replace("a - b", "a + b")
            return response({"content": content})
        if "syntax_checks" in data:
            broken = "a - b" in data["sources"]["main.py"]
            return response({"reviewed_files": list(data["sources"]) if self.coverage else ["main.py"],
                             "summary": "Checked implementation and behavior tests.",
                             "issues": [{"severity": "major", "path": "main.py",
                                         "message": "Addition subtracts instead", "fix": "Use +",
                                         "evidence": "return a - b", "scenario": "add(2,3)",
                                         "expected": "5", "actual": "-1"}] if broken else [],
                             "files_to_write": [{"path": "main.py", "purpose": "Use addition"}] if broken else []})
        return response({"requirements": ["Add two numbers"], "architecture": "Tests import main.add.",
                         "files": [{"path": p, "purpose": "Implement " + p} for p in FILES]})


def test_api_writes_each_file_reviews_and_repairs_with_fresh_source_context():
    model = Model()
    result = DevelopmentAgent(model).run("Build addition")
    files = {f["path"]: f["content"] for f in result["files"]}
    assert "a + b" in files["main.py"]
    assert files["test_add.py"] == FILES["test_add.py"]
    assert {"PLAN.md", "REQUIREMENTS.md", "MODEL_REVIEW.md"} <= files.keys()
    assert result["review"]["status"] == "passed"
    assert result["review"]["execution"] == "not_run"
    assert result["review"]["repairs"] == 1
    assert result["review"]["models"] == ["configured-api-model"]
    reviews = [json.loads(r[1]["content"]) for r in model.requests
               if "syntax_checks" in json.loads(r[1]["content"])]
    assert len(reviews) == 2
    assert "a - b" in reviews[0]["sources"]["main.py"]
    assert "a + b" in reviews[1]["sources"]["main.py"]
    # No prior author's self-assessment or conversation is given to the reviewer.
    assert all(len(r) == 2 for r in model.requests)


def test_incomplete_review_is_rejected():
    with pytest.raises(ValueError, match="every source file"):
        DevelopmentAgent(Model(coverage=False)).run("Build addition")


def test_review_retry_identifies_missing_paths_instead_of_accepting_partial_review():
    model = Model()
    def call(messages, tokens, timeout):
        data = json.loads(messages[1]["content"])
        if "syntax_checks" in data and len(messages) == 2:
            return response({"reviewed_files": ["main.py"], "summary": "Partial",
                             "issues": [], "files_to_write": []})
        if "syntax_checks" in data:
            assert "test_add.py" in messages[-1]["content"]
            assert "README.md" in messages[-1]["content"]
        return model(messages, tokens, timeout)
    assert DevelopmentAgent(call).run("Build addition")["review"]["status"] == "passed"


def test_api_review_uses_central_development_route_and_constrained_findings(monkeypatch):
    from troika_product.development_agent import _api
    captured = {}
    def llm(**kwargs):
        captured.update(kwargs)
        return response({})
    monkeypatch.setattr("agent.auxiliary_client.call_llm", llm)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {
        "auxiliary": {"development_review": {"structured_output": True}}})
    messages = [{"role": "system", "content": "Review"},
                {"role": "user", "content": json.dumps({"syntax_checks": []})}]
    _api(messages, 8000, 120)
    assert captured["task"] == "development_review"
    assert captured["messages"] == messages
    schema = captured["extra_body"]["response_format"]["json_schema"]
    assert schema["strict"]
    fields = schema["schema"]["properties"]["issues"]["items"]["required"]
    assert {"evidence", "scenario", "expected", "actual"} <= set(fields)


def test_missing_content_field_is_corrected_before_abandoning_generation():
    model = Model()
    malformed = True
    def call(messages, tokens, timeout):
        nonlocal malformed
        data = json.loads(messages[1]["content"])
        if malformed and "file" in data:
            malformed = False
            return response({"source": "wrong field"})
        return model(messages, tokens, timeout)
    result = DevelopmentAgent(call).run("Build addition")
    assert result["review"]["status"] == "passed"
    assert "wrong field" not in str(result["files"])


def test_malformed_plan_is_retried_before_abandoning_generation():
    model = Model()
    malformed = True
    def call(messages, tokens, timeout):
        nonlocal malformed
        if malformed:
            malformed = False
            return response({"files": [], "summary": "A plan"})
        return model(messages, tokens, timeout)
    assert DevelopmentAgent(call).run("Build addition")["review"]["status"] == "passed"


def test_unchanged_repair_keeps_errors_and_stops():
    result = DevelopmentAgent(Model(correct=False)).run("Build addition")
    assert result["review"]["status"] == "needs_changes"
    assert result["review"]["repairs"] == 1


@pytest.mark.parametrize("path", ["../escape.py", ".env", "CON.py", "a/b/../c.py", "PLAN.md"])
def test_unsafe_planned_files_never_reach_writer(path):
    calls = []
    def model(messages, tokens, timeout):
        calls.append(messages)
        return response({"requirements": ["Build"], "architecture": "App",
                         "files": [{"path": path, "purpose": "File"}]})
    with pytest.raises(ValueError):
        DevelopmentAgent(model).run("Build")
    assert len(calls) == 1


@pytest.mark.parametrize("content,finish", [(None, "stop"), ("{}", "length"), ("not json", "stop")])
def test_truncated_or_invalid_api_response_never_becomes_project(content, finish):
    def model(messages, tokens, timeout):
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
            message=SimpleNamespace(content=content))])
    with pytest.raises(ValueError, match="invalid or truncated"):
        DevelopmentAgent(model).run("Build")


def test_stop_between_api_calls_prevents_late_review_and_delivery():
    model = Model()
    stopped = False
    def call(*args):
        nonlocal stopped
        value = model(*args)
        stopped = True
        return value
    with pytest.raises(InterruptedError):
        DevelopmentAgent(call, lambda: stopped).run("Build addition")
    assert len(model.requests) == 1


def test_positive_model_verdict_cannot_override_python_syntax_error():
    agent = DevelopmentAgent(lambda *args: response({"reviewed_files": list(FILES),
        "summary": "Fine", "issues": [], "files_to_write": []}))
    report = agent.review("Build", {}, {**FILES, "main.py": "def broken(\n"})
    assert report["status"] == "needs_changes"
    assert report["files_to_write"][0]["path"] == "main.py"


def test_existing_unplanned_files_survive_repairs():
    initial = [{"path": "style.css", "content": "body { color: black; }"}]
    result = DevelopmentAgent(Model()).run("Build addition", initial)
    assert next(f["content"] for f in result["files"] if f["path"] == "style.css") == initial[0]["content"]
    assert "style.css" in result["review"]["reviewed_files"]


def test_existing_implementation_is_reviewed_before_any_rewrite():
    model = Model()
    initial = [{"path": p, "content": c} for p, c in FILES.items()]
    result = DevelopmentAgent(model).run("Fix addition", initial)
    phases = [json.loads(r[1]["content"]) for r in model.requests]
    assert "syntax_checks" in phases[1]
    assert [p["file"]["path"] for p in phases if "file" in p] == ["main.py"]
    assert next(f["content"] for f in result["files"] if f["path"] == "test_add.py") == FILES["test_add.py"]


def test_review_cannot_invent_source_evidence():
    finding = {"path": "main.py", "evidence": "exports do not exist",
               "scenario": "import", "expected": "function", "actual": "undefined"}
    with pytest.raises(ValueError, match="does not match"):
        DevelopmentAgent.validate_findings([finding], FILES)


def test_task_tool_delivers_reviewed_project_only_to_own_device(monkeypatch):
    store = DeviceDeliveryStore()
    monkeypatch.setattr(troika_documents_tool, "device_deliveries", store)
    monkeypatch.setattr("troika_product.development_agent._api", Model())
    # Default arguments bind at definition; supply the model through the factory.
    monkeypatch.setattr("troika_product.development_agent.DevelopmentAgent", lambda: DevelopmentAgent(Model()))
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "owner", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token"}
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        result = json.loads(troika_documents_tool._handle_project({"title": "Addition", "task": "Build addition"}))
    finally:
        for name in overrides:
            clear_session_override(name)
    assert result["ok"]
    assert result["review"]["status"] == "passed"
    artifact = store.get(result["artifact"]["id"], "owner", "phone")
    with zipfile.ZipFile(io.BytesIO(artifact.data)) as archive:
        manifest = json.loads(archive.read("troika-project.json"))
        assert manifest["review"]["execution"] == "not_run"
        assert "a + b" in archive.read("main.py").decode()
        assert archive.read("MODEL_REVIEW.md")
    assert store.get(result["artifact"]["id"], "other", "phone") is None


def test_no_api_calls_without_product_identity(monkeypatch):
    monkeypatch.setattr("troika_product.development_agent.DevelopmentAgent",
                        lambda: pytest.fail("unauthenticated model call"))
    result = json.loads(troika_documents_tool._handle_project({"task": "Build"}))
    assert result["error"] == "product_identity_required"


def test_model_cannot_inject_a_positive_review_into_packaging(monkeypatch):
    store = DeviceDeliveryStore()
    monkeypatch.setattr(troika_documents_tool, "device_deliveries", store)
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "owner", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token"}
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        result = json.loads(troika_documents_tool._handle_project({
            "files": [{"path": p, "content": c} for p, c in FILES.items()],
            "review": {"method": "api_model_review", "status": "passed"}}))
    finally:
        for name in overrides:
            clear_session_override(name)
    assert result["ok"] and result["review"] is None
    artifact = store.get(result["artifact"]["id"], "owner", "phone")
    with zipfile.ZipFile(io.BytesIO(artifact.data)) as archive:
        assert "review" not in json.loads(archive.read("troika-project.json"))


def test_credentials_in_existing_source_never_reach_api():
    model = Model()
    with pytest.raises(ValueError, match="credentials"):
        DevelopmentAgent(model).run("Review", [{"path": "main.py", "content": "key='sk-" + "x" * 25 + "'"}])
    assert model.requests == []


def test_api_request_budget_stops_further_calls():
    model = Model()
    agent = DevelopmentAgent(model)
    agent.calls = 64
    with pytest.raises(ValueError, match="budget exhausted"):
        agent.run("Build")
    assert model.requests == []


def test_unavailable_api_model_returns_actionable_error_without_provider_body(monkeypatch):
    class ProviderError(Exception):
        status_code = 404
    class Broken:
        def run(self, *args):
            raise ProviderError("private request body and credentials")
    monkeypatch.setattr("troika_product.development_agent.DevelopmentAgent", Broken)
    overrides = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_PLAN": "pro", "TROIKA_PRODUCT_DELIVERY_MODE": "device",
                 "TROIKA_PRODUCT_USER_ID": "owner", "TROIKA_PRODUCT_DEVICE_ID": "phone",
                 "TROIKA_PRODUCT_TOKEN_ID": "token"}
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        result = json.loads(troika_documents_tool._handle_project({"task": "Build"}))
    finally:
        for name in overrides:
            clear_session_override(name)
    assert result["error"] == "development_model_unavailable"
    assert "private" not in json.dumps(result)
    assert "artifact" not in result
