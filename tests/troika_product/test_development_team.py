"""Specialists share one bounded Run and exchange actual versioned sources."""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from troika_product.development_team import DevelopmentTeam, free_api


SOURCES = {
    "main.py": "def add(a, b):\n    return a + b\n",
    "ui.html": "<!doctype html><html><body><h1>Addition</h1></body></html>",
    "README.md": "Run python -m unittest discover. Tests import main.add.",
    "test_add.py": "import unittest\nfrom main import add\nclass TestAdd(unittest.TestCase):\n"
                   "    def test_add(self):\n        self.assertEqual(add(2,3), 5)\n",
}


class SpecialistModel:
    def __init__(self, *, cycle=False):
        self.cycle = cycle
        self.calls = []
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def __call__(self, messages, tokens, timeout):
        data = json.loads(messages[1]["content"])
        with self.lock:
            self.calls.append(data)
        if "file" in data:
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(.03)
            content = SOURCES[data["file"]["path"]]
            if data["file"]["path"] == "test_add.py":
                assert "main.py" in data["sources"]
            assert data["plan"]["design"]["direction"] == "Restrained editorial layout"
            with self.lock:
                self.active -= 1
            value = {"content": content}
        elif "design_task" in data:
            value = {key: "Restrained editorial layout" for key in (
                "direction", "audience", "typography", "palette", "layout", "interaction", "review_criteria")}
        elif "syntax_checks" in data:
            assert set(SOURCES) <= data["sources"].keys()
            assert "DESIGN.md" in data["sources"]
            value = {"reviewed_files": list(data["sources"]), "summary": "Reviewed sources",
                     "issues": [], "files_to_write": []}
        else:
            value = {"requirements": ["Add two numbers"], "architecture": "Tests import main.add",
                     "files": [{"path": p, "purpose": "Implement " + p,
                                "depends_on": ["main.py"] if p == "test_add.py" else
                                ["test_add.py"] if p == "main.py" and self.cycle else []}
                               for p in SOURCES]}
        return SimpleNamespace(model="verified-free-model", choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(value)))])


def test_team_plans_designs_runs_bounded_workers_and_reviews_their_actual_sources():
    model = SpecialistModel()
    events = []
    team = DevelopmentTeam(call=model, progress=lambda **e: events.append(e), max_workers=3)
    result = team.run("Build addition with browser UI")
    assert 1 < model.maximum <= 3
    assert result["review"]["api_calls"] == len(model.calls)
    assert result["review"]["status"] == "passed"
    assert result["review"]["execution"] == "not_run"
    assert result["review"]["visual_review"] == "not_checked"
    assert {"planner", "designer", "developer", "verifier"} <= {e["role"] for e in events}
    assert "Дизайн выбран" in " ".join(e["report"] for e in events)
    assert {f["path"] for f in result["files"]} >= {*SOURCES, "DESIGN.md"}


def test_cyclic_plan_does_not_start_design_or_writers():
    model = SpecialistModel(cycle=True)
    with pytest.raises(ValueError, match="cycle"):
        DevelopmentTeam(call=model).run("Build")
    assert len(model.calls) == 2


def test_stop_blocks_specialist_results_and_never_calls_a_paid_fallback():
    stopped = threading.Event()
    model = SpecialistModel()
    def call(*args):
        result = model(*args)
        stopped.set()
        return result
    with pytest.raises(InterruptedError):
        DevelopmentTeam(call=call, cancelled=stopped.is_set).run("Build")
    assert len(model.calls) == 1


def test_free_route_rejects_resolver_that_returns_a_paid_model(monkeypatch):
    class Client:
        base_url = "https://openrouter.ai/api/v1"
    monkeypatch.setattr("agent.auxiliary_client.get_text_auxiliary_client",
                        lambda **kw: (Client(), "openai/gpt-5.4-mini"))
    with pytest.raises(ValueError, match="paid fallback"):
        free_api([], 10, 1)


def test_existing_project_refreshes_design_even_without_missing_files():
    model = SpecialistModel()
    initial = [{"path": p, "content": c} for p, c in {**SOURCES, "DESIGN.md": "Old design"}.items()]
    result = DevelopmentTeam(call=model).run("Review existing project", initial)
    assert not any("file" in call for call in model.calls)
    assert "Restrained editorial layout" in next(f["content"] for f in result["files"] if f["path"] == "DESIGN.md")


@pytest.mark.parametrize("kind", ["pptx", "docx"])
def test_document_author_and_independent_verifier_preserve_paragraphs_and_bullets(kind):
    from io import BytesIO
    from zipfile import ZipFile
    from troika_product.document_generation import generate_docx, generate_pptx
    calls = []
    def model(messages, tokens, timeout):
        data = json.loads(messages[1]["content"])
        calls.append(data)
        if "design_task" in data:
            assert data["renderer"]["format"] == kind
            assert data["renderer"]["font"] == "Arial"
            if kind == "pptx":
                assert set(data["renderer"]["layouts"]) == {"cover", "content", "split", "statement"}
            value = {k: "White background, readable dark type" for k in (
                "direction", "audience", "typography", "palette", "layout", "interaction", "review_criteria")}
        elif "document_task" in data:
            value = {"title": "Example", "slides" if kind == "pptx" else "sections": [
                {"title" if kind == "pptx" else "heading": "Overview", "body": "Paragraph remains intact",
                 "bullets": ["First fact", "Second fact"]}]}
        elif "syntax_checks" in data:
            assert "Paragraph remains intact" in data["sources"]["content.json"]
            value = {"reviewed_files": ["content.json"], "summary": "Reviewed content",
                     "issues": [], "files_to_write": []}
        else:
            value = {"requirements": ["Create a document"], "architecture": "Typed document content",
                     "output_kind": kind, "files": [{"path": "content.json", "purpose": "Document", "depends_on": []}]}
        return SimpleNamespace(model="free-document-model", choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(value)))])
    result = DevelopmentTeam(call=model).run("Create " + kind)
    rendered = (generate_pptx if kind == "pptx" else generate_docx)(
        DevelopmentTeam.document_args(kind, result["document"]["args"]))
    with ZipFile(BytesIO(rendered)) as archive:
        text = "".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml"))
        if kind == "pptx":
            assert len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]) == 1
    assert all(fragment in text for fragment in ("Paragraph remains intact", "First fact", "Second fact"))
    assert len(calls) == 4
    assert result["review"]["status"] == "passed"
    assert result["review"]["visual_review"] == "not_checked"


def test_free_route_has_no_automatic_provider_retry(monkeypatch):
    requests = []
    class Client:
        base_url = "https://openrouter.ai/api/v1"
        def with_options(self, **options):
            assert options == {"max_retries": 0}
            return self
        @property
        def chat(self):
            return SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **args):
            requests.append(args)
            raise RuntimeError("Unavailable")
    monkeypatch.setattr("agent.auxiliary_client.get_text_auxiliary_client", lambda **kw: (Client(), "openrouter/free"))
    monkeypatch.setattr("troika_product.development_team._free_candidates", lambda client: ("verified/code:free",))
    messages = [{"role": "system", "content": "JSON"}, {"role": "user", "content": json.dumps({"file": {}})}]
    with pytest.raises(RuntimeError):
        free_api(messages, 10, 1)
    assert len(requests) == 1 and requests[0]["model"] == "verified/code:free"
    assert set(requests[0]["extra_body"]) == {"reasoning", "response_format"}


def test_free_route_tries_next_verified_model_after_rate_limit(monkeypatch):
    attempted = []
    models = ("first:free", "second:free")

    class RateLimit(Exception):
        status_code = 429

    def complete(**kwargs):
        attempted.append(kwargs["model"])
        if kwargs["model"] == models[0]:
            raise RateLimit()
        return "completed"

    client = SimpleNamespace(base_url="https://openrouter.ai/api/v1",
                             chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    client.with_options = lambda **kwargs: client
    monkeypatch.setattr("agent.auxiliary_client.get_text_auxiliary_client", lambda **kwargs: (client, "openrouter/free"))
    monkeypatch.setattr("troika_product.development_team._free_candidates", lambda client: models)
    messages = [{"role": "system", "content": "JSON"}, {"role": "user", "content": '{"file":"add.py"}'}]
    assert free_api(messages, 10, 2) == "completed"
    assert attempted == list(models)


def test_free_catalog_rejects_hidden_fees_missing_prices_and_weak_json_routes():
    from troika_product.development_team import eligible_free_models
    model = {"id": "vendor/code:free", "description": "Coding", "context_length": 256000,
             "pricing": {"prompt": "0", "completion": "0"},
             "supported_parameters": ["structured_outputs"],
             "architecture": {"output_modalities": ["text"]}}
    assert eligible_free_models([model]) == (model["id"],)
    for changed in (
        {"pricing": {"prompt": "0"}}, {"pricing": {"prompt": "0", "completion": "0", "request": "0.1"}},
        {"pricing": {"prompt": "0", "completion": "NaN"}}, {"context_length": 64000},
        {"pricing": {"prompt": "0", "completion": "1e-999"}},
        {"supported_parameters": ["response_format"]}, {"id": "vendor/paid"},
    ):
        assert eligible_free_models([{**model, **changed}]) == ()

def test_positive_model_review_cannot_accept_tests_copying_real_functions():
    from troika_product.development_agent import DevelopmentAgent
    sources = {'main.js': 'function add(a, b) { return a+b; }\nmodule.exports={add};',
               'test.js': "const assert=require('assert');\nfunction add(a,b) {return a+b;}\nassert.equal(add(1,2),3);",
               'README.md': 'Run node test.js.'}
    def model(messages, tokens, timeout):
        return SimpleNamespace(model='reviewer', choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps({'reviewed_files':list(sources), 'summary':'Fine',
                'issues':[], 'files_to_write':[]})))])
    review = DevelopmentAgent(call=model).review('Implement addition', {}, sources)
    assert review['status'] == 'needs_changes'
    assert any(item['path'] == 'test.js' for item in review['files_to_write'])
    assert 'без импорта' in review['issues'][0]['message']


def test_test_linkage_accepts_a_wrapper_loading_the_real_module():
    from troika_product.development_agent import _copied_test_checks
    sources = {'main.js':'function add(a,b) {return a+b;}\nmodule.exports={add};',
               'test.js':"function add(a,b) {return require('./main').add(a,b);}"}
    assert _copied_test_checks(sources) == []

def test_numbered_review_cites_the_actual_current_line_and_rejects_invalid_line():
    from troika_product.development_agent import DevelopmentAgent
    sources = {'main.js': 'const a = 1;\nconst a = 1;\n'}
    issue = {'path':'main.js','line':2,'evidence':'','scenario':'Load module',
             'expected':'One declaration','actual':'Duplicate declaration'}
    DevelopmentAgent.validate_findings([issue], sources)
    assert issue['line'] == 2 and issue['evidence'] == 'const a = 1;'
    issue.update(line=3, evidence='')
    with pytest.raises(ValueError, match='evidence'):
        DevelopmentAgent.validate_findings([issue], sources)

def test_existing_file_marked_for_change_is_written_before_review():
    base = SpecialistModel()
    def model(messages, tokens, timeout):
        response = base(messages, tokens, timeout)
        data = json.loads(messages[1]['content'])
        if not any(k in data for k in ('file','syntax_checks','design_task')):
            value = json.loads(response.choices[0].message.content)
            for item in value['files']: item['write_required'] = item['path'] == 'main.py'
            response.choices[0].message.content = json.dumps(value)
        return response
    initial = [{'path':p,'content':c} for p,c in {**SOURCES,'main.py':'def add(a,b):\n    return a-b\n'}.items()]
    result = DevelopmentTeam(call=model).run('Fix subtraction bug', initial)
    assert [c['file']['path'] for c in base.calls if 'file' in c] == ['main.py']
    assert next(f['content'] for f in result['files'] if f['path']=='main.py') == SOURCES['main.py']

def test_stop_in_shared_free_queue_never_sends_a_late_model_request(monkeypatch):
    import troika_product.development_team as module
    class Client:
        base_url = 'https://openrouter.ai/api/v1'
        def with_options(self, **kwargs): return self
    monkeypatch.setattr('agent.auxiliary_client.get_text_auxiliary_client', lambda **kw:(Client(),'openrouter/free'))
    monkeypatch.setattr(module,'_free_candidates',lambda client:('verified/model:free',))
    module._FREE_REQUESTS.acquire(); module._FREE_REQUESTS.acquire()
    try:
        with pytest.raises(InterruptedError, match='waiting'):
            free_api([],10,1,cancelled=lambda:True)
    finally:
        module._FREE_REQUESTS.release(); module._FREE_REQUESTS.release()

def test_verified_free_selection_keeps_monthly_usage_metering(tmp_path, monkeypatch):
    from decimal import Decimal
    from agent.provider_metering import provider_metering_scope, wrap_provider_client
    from troika_product.access import AccessRegistry
    from troika_product.llm_metering import LLMMeter, ModelPrice, PriceCatalogue
    from troika_product.resource_ledger import ResourceLedger
    from troika_product.subscription_policy import TokenPrices
    registry = AccessRegistry(tmp_path / 'meter.db')
    user = registry.create_user('development@example.invalid', plan='pro')
    device = registry.create_device(user, name='test', platform='android')
    principal = registry.authenticate(registry.issue_device_token(device))
    price = ModelPrice(TokenPrices('free-test', *[Decimal(0)] * 4), debit_mode='model_tokens')
    meter = LLMMeter(ResourceLedger(registry), principal, run_key='autopilot-meter',
        catalogue=PriceCatalogue({('openrouter', 'openrouter/free'): price}))
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    meter.ledger.grant_monthly(principal, starts_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=30), event_key='test-pro-period')
    calls = []
    class Client:
        base_url = 'https://openrouter.ai/api/v1'
        max_retries = 0
        def with_options(self, **kwargs): return self
        @property
        def chat(self): return SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=30, completion_tokens=20, cost=0,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0)), choices=[])
    monkeypatch.setattr('troika_product.development_team._free_candidates', lambda client: ('verified/code:free',))
    monkeypatch.setattr('agent.auxiliary_client.get_text_auxiliary_client',
        lambda **kw: (wrap_provider_client(Client()), 'openrouter/free'))
    with provider_metering_scope(meter):
        free_api([{'role':'system','content':'JSON'}, {'role':'user','content':json.dumps({'file':{}})}], 100, 1)
    assert len(calls) == 1 and calls[0]['model'] == 'verified/code:free'
    assert 'models' not in calls[0]['extra_body']
    assert meter.ledger.summary(principal)['spent'] == 50
    assert meter.ledger.summary(principal)['reserved'] == 0


@pytest.mark.parametrize('provider,model', [
    ('openrouter', 'paid/model'), ('openrouter', 'openrouter/free'), ('openai', 'fake:free'),
    ('openrouter', 'unverified/model:free')])
def test_personal_model_cannot_override_verified_free_route(monkeypatch, provider, model):
    from agent.provider_metering import provider_metering_scope
    from troika_product.own_provider import OwnCredentials
    guard = SimpleNamespace(credentials=OwnCredentials(provider, model, 'personal-fixture-key-1234'))
    class Client:
        base_url = 'https://openrouter.ai/api/v1'
        def with_options(self, **kwargs): return self
    monkeypatch.setattr('agent.auxiliary_client.get_text_auxiliary_client', lambda **kw: (Client(), 'openrouter/free'))
    monkeypatch.setattr('troika_product.development_team._free_candidates', lambda client: ('verified/code:free',))
    with provider_metering_scope(guard), pytest.raises(ValueError, match='free'):
        free_api([], 100, 1)

def test_verified_personal_free_model_uses_only_personal_key_and_zero_subscription_debit(tmp_path, monkeypatch):
    from agent.provider_metering import provider_metering_scope, wrap_provider_client
    from troika_product.access import AccessRegistry
    from troika_product.own_provider import OwnCredentials, OwnProviderRuntime
    registry = AccessRegistry(tmp_path / 'personal.db')
    user = registry.create_user('personal-development@example.invalid', plan='pro')
    device = registry.create_device(user, name='test', platform='android')
    principal = registry.authenticate(registry.issue_device_token(device))
    own = OwnProviderRuntime(registry, principal, run_key='personal-development', config={},
        credentials=OwnCredentials('openrouter', 'verified/code:free', 'personal-fixture-key-1234'))
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.base_url = kwargs['base_url']; self.api_key = kwargs['api_key']; self.max_retries = 0
        def with_options(self, **kwargs): return self
        @property
        def chat(self): return SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls.append((self.api_key, kwargs['model']))
            return SimpleNamespace(choices=[])
    monkeypatch.setattr('openai.OpenAI', Client)
    monkeypatch.setattr('troika_product.development_team._free_candidates', lambda client: ('verified/code:free',))
    monkeypatch.setattr('agent.auxiliary_client.get_text_auxiliary_client',
        lambda **kw: (wrap_provider_client(SimpleNamespace()), 'openrouter/free'))
    own.start()
    try:
        with provider_metering_scope(own):
            free_api([{'role':'system','content':'JSON'}, {'role':'user','content':json.dumps({'file':{}})}], 100, 1)
        assert calls == [('personal-fixture-key-1234', 'verified/code:free')]
        assert own.ledger.export_rows(principal)['operations'] == []
    finally:
        own.finish()
