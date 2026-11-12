"""Rendered evidence, executed failures and complete coverage are independent gates."""

import base64
import json
from types import SimpleNamespace

import pytest
from troika_product.development_agent import DevelopmentAgent
from troika_product.development_team import DevelopmentTeam
from troika_product.development_verification import IsolatedChecks, visual_review


def reply(value):
    return SimpleNamespace(
        model="synthetic-free-reviewer",
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps(value))
            )
        ],
    )


def test_large_project_reviews_every_file_in_bounded_batches():
    sources = {
        f"module_{n}.py": f"def value_{n}(): return {n}\n" + ("# fixture\n" * 400)
        for n in range(70)
    }
    sources.update({
        "README.md": "Run pytest.",
        "test_module.py": "from module_1 import value_1\ndef test_value(): assert value_1()==1",
    })
    reviewed = []

    def model(messages, *args):
        data = json.loads(messages[1]["content"])
        reviewed.extend(data["sources"])
        assert len(json.dumps(data["sources"]).encode()) < 60000
        assert len(data["source_inventory"]) == len(sources)
        return reply({
            "reviewed_files": list(data["sources"]),
            "summary": "Read this source batch.",
            "issues": [],
            "files_to_write": [],
        })

    report = DevelopmentAgent(call=model).review(
        "Preserve the application", {}, sources
    )
    assert report["status"] == "passed" and report["source_batches"] > 1
    assert set(reviewed) == set(sources) and len(reviewed) == len(sources)
    assert report["execution"] == "not_run"


def test_available_languages_use_only_fixed_execution_recipes():
    checks = object.__new__(IsolatedChecks)
    requests = []
    checks.request = lambda body: (
        requests.append(body) or {"status": "passed", "tests": 1}
    )
    assert (
        checks.execution({
            "app.tsx": "export default 1",
            "app.test.tsx": 'test("render",()=>{})',
        })["status"]
        == "passed"
    )
    assert requests[0]["kind"] == "react_tests"
    assert (
        checks.execution({"test_value.py": "def test_value(): assert True"})["status"]
        == "passed"
    )
    assert requests[1]["kind"] == "python_tests"
    assert checks.execution({"main.rs": "fn main() {}"})["status"] == "not_supported"
    assert len(requests) == 2


def test_budget_continuation_reuses_bound_checks_and_invalidates_changed_sources(
    monkeypatch,
):
    from copy import deepcopy

    calls = []

    def review(self, task, plan, sources):
        calls.append("source")
        return {
            "status": "passed",
            "execution": "not_run",
            "reviewed_files": list(sources),
            "summary": "Reviewed",
            "issues": [],
            "files_to_write": [],
        }

    monkeypatch.setattr(DevelopmentAgent, "review", review)
    checker = SimpleNamespace(
        version="fixed-sandbox-fixture-v1",
        execution=lambda _: (
            calls.append("tests") or {"status": "passed", "checks": [{"tests": 1}]}
        ),
        project=lambda _: {"status": "not_applicable"},
    )
    sources = {"main.py": "def value(): return 1"}
    first = DevelopmentTeam(call=lambda *args: None, checker=checker)
    resumed = DevelopmentTeam(call=lambda *args: None, checker=checker)
    try:
        plan = {
            "files": [
                {"path": "main.py", "purpose": "Return value", "write_required": True}
            ]
        }
        assert first.review("Same task", plan, sources)["status"] == "passed"
        resumed.verified_pages = deepcopy(first.verified_pages)
        plan["files"][0]["write_required"] = False
        assert resumed.review("Same task", plan, sources)["execution"] == "passed"
        assert calls == ["source", "tests"]
        resumed.review("Same task", {}, {"main.py": "def value(): return 2"})
        assert calls == ["source", "tests", "source", "tests"]
        resumed.review("Changed task", {}, sources)
        assert calls[-2:] == ["source", "tests"] and len(calls) == 6
        checker.version = "fixed-sandbox-fixture-v2"
        resumed.review("Changed task", {}, sources)
        assert len(calls) == 8
    finally:
        first.pool.shutdown()
        resumed.pool.shutdown()


def test_source_plan_cannot_be_delivered_as_an_office_document():
    from tests.troika_product.test_development_team import SpecialistModel

    original = SpecialistModel()
    plans = []

    def model(messages, *args):
        result = original(messages, *args)
        data = json.loads(messages[1]["content"])
        if not any(
            key in data
            for key in ("file", "syntax_checks", "design_task", "document_task")
        ):
            value = json.loads(result.choices[0].message.content)
            plans.append(value)
            value["output_kind"] = "docx" if len(plans) == 1 else "project"
            return reply(value)
        return result

    team = DevelopmentTeam(call=model)
    result = team.run("Build a Python library and its real tests")
    assert len(plans) == 2 and "document" not in result
    assert "main.py" in {f["path"] for f in result["files"]}


def test_absent_feature_is_a_project_finding_without_an_invented_source_citation():
    issue = {
        "path": "main.py",
        "line": 0,
        "evidence": "",
        "scenario": "call missing function",
        "expected": "function exists",
        "actual": "function missing",
    }
    DevelopmentAgent.validate_findings([issue], {"main.py": "def present(): return 1"})
    assert issue["path"] == "*" and issue["evidence"] == ""
    invalid = {**issue, "path": "main.py", "line": 100, "evidence": "invented source"}
    with pytest.raises(ValueError, match="valid numbered lines are 1..1"):
        DevelopmentAgent.validate_findings(
            [invalid], {"main.py": "def present(): return 1"}
        )


def test_current_repair_overrides_completed_plan_without_mutating_checkpoint():
    plan = {"files": [{"path": "styles.css", "purpose": "Styles", "write_required": False}]}
    sources = {"styles.css": "a{color:'broken}"}
    def model(messages, *args):
        data = json.loads(messages[1]["content"])
        assert data["plan"]["files"][0]["write_required"] is True
        assert data["review"]["status"] == "needs_changes"
        return reply({"content": "a{color:black;}"})
    DevelopmentAgent(call=model).write("Fix styles", plan, sources,
        {"path": "styles.css", "purpose": "Fix syntax"}, {"status": "needs_changes"})
    assert sources["styles.css"] == "a{color:black;}"
    assert plan["files"][0]["write_required"] is False


def test_repair_applies_unique_edits_without_replacing_unrelated_source():
    from troika_product.development_agent import response_format
    calls = []
    def model(messages, *args):
        calls.append(messages)
        data = json.loads(messages[1]["content"])
        assert data["repair_mode"]
        assert "replacements" in response_format(messages)["json_schema"]["schema"]["properties"]
        # An ambiguous match is rejected and the writer gets one structured retry.
        return reply({"replacements": [{"old_text": "color" if len(calls)==1 else "a{color:'broken}",
            "new_text": "a{color:black;}"}]})
    sources = {"styles.css": "a{color:'broken}\nb{color:white;}\n/* keep this */"}
    DevelopmentAgent(call=model).write("Fix CSS", {}, sources,
        {"path": "styles.css", "purpose": "Fix syntax"}, {"status": "needs_changes"})
    assert len(calls) == 2
    assert sources["styles.css"] == "a{color:black;}\nb{color:white;}\n/* keep this */"


def test_visual_reviewer_receives_actual_image_and_returns_concrete_repairs():
    def model(messages, *args):
        content = messages[1]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "390px" in content[0]["text"] and '"observed": 0' in content[0]["text"]
        return reply({
            "summary": "Mobile content is clipped.",
            "issues": [
                {
                    "severity": "major",
                    "path": "index.html",
                    "message": "390px: button clipped",
                    "fix": "Remove the fixed minimum width.",
                }
            ],
        })

    team = DevelopmentTeam(call=model, checker=SimpleNamespace())
    try:
        result = visual_review(
            team,
            "A responsive page",
            {},
            {
                "status": "rendered",
                "image": {
                    "data": base64.b64encode(b"\xff\xd8fixture").decode(),
                    "panels": ["390px"],
                },
                "metrics": [
                    {"width": 1440, "scroll_samples": [{"requested": 0, "observed": 0},
                                                       {"requested": 120, "observed": 120}]},
                    {"width": 390, "scroll_samples": [{"requested": 0, "observed": 0},
                                                      {"requested": 640, "observed": 0}]},
                ],
            },
            ["index.html"],
        )
        assert result["status"] == "needs_changes" and len(result["image_sha256"]) == 64
        assert "data" not in result
        assert [item["status"] for item in result["browser_scroll"]] == ["verified", "unconfirmed"]
        report = DevelopmentAgent.report_text({"visual_details": result, "status": "needs_changes",
                                              "summary": "", "issues": [], "reviewed_files": [], "repairs": 0})
        assert "120 → 120" in report and "640 → 0" in report
        assert "Позиция прокрутки не подтверждена" in report
        with pytest.raises(ValueError, match="Invalid rendered preview"):
            visual_review(
                team,
                "page",
                {},
                {"status": "rendered", "image": {"data": "aGVsbG8="}},
                ["index.html"],
            )
    finally:
        team.pool.shutdown()


@pytest.mark.parametrize("failure", ["tests", "overflow"])
def test_positive_model_verdict_cannot_override_executed_or_visible_failure(
    monkeypatch, failure
):
    monkeypatch.setattr(
        DevelopmentAgent,
        "review",
        lambda *args: {
            "status": "passed",
            "execution": "not_run",
            "reviewed_files": ["index.html"],
            "summary": "Source reviewed.",
            "issues": [],
            "files_to_write": [],
        },
    )
    checker = SimpleNamespace(
        execution=lambda _: {
            "status": "failed" if failure == "tests" else "passed",
            "checks": [{"output": "AssertionError: real failure", "tests": 1}],
        },
        project=lambda _: {
            "status": "rendered",
            "image": {
                "data": base64.b64encode(b"\xff\xd8fixture").decode(),
                "panels": ["390px"],
            },
            "metrics": [{"width": 390, "content_width": 700, "javascript_errors": []}],
        },
    )
    team = DevelopmentTeam(
        call=lambda *args: reply({"summary": "Looks good", "issues": []}),
        checker=checker,
    )
    try:
        result = team.review(
            "Responsive app",
            {},
            {"index.html": "<button>Go</button>", "app.js": "export const n=1"},
        )
        assert result["status"] == "needs_changes" and result["files_to_write"]
        assert any(i["severity"] == "major" for i in result["issues"])
        if failure == "tests":
            assert result["execution"] == "failed" and team.calls == 0
        else:
            assert result["visual_review"] == "needs_changes"
    finally:
        team.pool.shutdown()
