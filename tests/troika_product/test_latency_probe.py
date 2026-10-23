"""Offline behavioral checks for synthetic latency measurement and safe reports."""

import json

import httpx
import pytest

from scripts import troika_latency_probe as probe


MODEL = "fixture/public:free"
ACTUAL_MODEL = "fixture/actual:free"
KEY = "fixture-only-api-key"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TimedStream(httpx.SyncByteStream):
    def __init__(self, clock, frames):
        self.clock, self.frames = clock, frames

    def __iter__(self):
        for delay, data in self.frames:
            self.clock.now += delay
            if isinstance(data, Exception):
                raise data
            yield data.encode("utf-8")


def catalog(*models):
    return {"data": [{"id": model, "pricing": {"prompt": "0", "completion": "0", "request": "0"}}
                     for model in models or (MODEL, ACTUAL_MODEL)]}


def event(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


def delta(text=None, *, finish=None, **extra):
    return event({"choices": [{"delta": {} if text is None else {"content": text}, "finish_reason": finish}], **extra})


def success_frames(text="Привет!"):
    return [(0.2, delta(text)), (0.3, delta(finish="stop")), (0, "data: [DONE]\n\n")]


def measured(frames=None, *, status=200, body=None, scenario="greeting"):
    clock = Clock()
    requests = []

    def handler(request):
        requests.append(request)
        clock.now += 0.1
        if body is not None:
            return httpx.Response(status, json=body)
        return httpx.Response(status, stream=TimedStream(clock, frames if frames is not None else success_frames()))

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        row = probe.measure(client, catalog=probe.validate_catalog(catalog(), [MODEL]),
                            model=MODEL, api_key=KEY, scenario=scenario, clock=clock)
    return row, requests


def test_first_text_and_guarded_phrase_exclude_comments_role_reasoning_and_usage():
    frames = [
        (0.2, ": keepalive\n\n"),
        (0.3, event({"choices": [{"delta": {"role": "assistant", "reasoning": "private reasoning"}}]})),
        (0.4, delta("   ")),
        (0.5, delta("Привет")),
        (0.6, delta("!")),
        (0.7, event({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})),
        (0.1, delta(finish="stop")),
        (0.1, "data: [DONE]\n\n"),
    ]
    row, requests = measured(frames)
    assert row["error"] is None
    assert row["headers_seconds"] == pytest.approx(0.1)
    assert row["first_text_seconds"] == pytest.approx(1.5)
    assert row["first_phrase_seconds"] == pytest.approx(2.1)
    assert row["total_seconds"] == pytest.approx(3.0)
    assert row["usage"] == {"prompt_tokens": 10, "completion_tokens": 3}
    assert row["quality_method"] == "heuristic" and row["quality_heuristic_pass"] is True
    assert len(requests) == row["model_calls"] == 1
    request = requests[0]
    assert str(request.url) == probe.OPENROUTER_URL + "/chat/completions"
    payload = json.loads(request.content)
    assert payload["provider"] == {"max_price": {"prompt": 0, "completion": 0}, "allow_fallbacks": False}
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == row["max_tokens"] == 1536
    assert row["input_bytes"] == len(request.content)
    assert request.headers["Content-Type"] == "application/json"


def test_split_thinking_tags_do_not_become_visible_text_or_a_phrase():
    row, _ = measured([
        (0.1, delta("<thi")), (0.2, delta("nk>private reasoning. ")),
        (0.3, delta("</think>")), (0.4, delta("Привет!")),
        (0.1, delta(finish="stop")), (0, "data: [DONE]\n\n"),
    ])
    assert row["error"] is None and row["characters"] == len("Привет!")
    assert row["first_text_seconds"] == row["first_phrase_seconds"] == pytest.approx(1.1)
    assert "private" not in json.dumps(row)


def test_safe_phrase_waits_for_guard_and_no_final_runtime_claim_is_simulated():
    row, _ = measured(success_frames("Файл сохранён на телефоне."))
    assert row["error"] is None and row["first_text_seconds"] is not None
    assert row["first_phrase_seconds"] is None
    assert row["quality_method"] == "heuristic"


@pytest.mark.parametrize("status,body,error", [
    (400, {"error": {"message": "Reasoning is mandatory for this endpoint and cannot be disabled."}}, "reasoning_required"),
    (400, {"error": {"message": "Provider returned error", "metadata": {"raw": "Reasoning is mandatory and cannot be disabled."}}}, "reasoning_required"),
    (429, {"error": {"message": "PRIVATE key=fixture-secret"}}, "http_429"),
    (503, {"error": {"message": "PRIVATE internal failure"}}, "http_503"),
])
def test_http_failures_are_independent_and_never_serialize_error_bodies(status, body, error):
    row, requests = measured(status=status, body=body)
    assert row["error"] == error and row["error_phase"] == "http"
    assert row["http_status"] == status and len(requests) == 1
    assert row["first_text_seconds"] is None and row["quality_heuristic_pass"] is None
    report = json.dumps(row)
    assert "PRIVATE" not in report and "fixture-secret" not in report and "mandatory" not in report


@pytest.mark.parametrize("frames,error", [
    ([], "incomplete_stream"),
    ([(0.1, delta("Привет!")), (0.1, event({"error": {"message": "PRIVATE upstream"}}))], "stream_error"),
    ([(0.1, delta("Привет!", finish="error"))], "stream_error"),
    ([(0.1, delta("Привет!", finish="stop"))], "incomplete_stream"),
    ([(0.1, delta("Привет!")), (0, "data: [DONE]\n\n")], "incomplete_stream"),
    ([(0.1, delta("Привет!", finish="length")), (0, "data: [DONE]\n\n")], "length_limit"),
    ([(0.1, delta("Привет!", finish="content_filter")), (0, "data: [DONE]\n\n")], "content_filtered"),
    ([(0.1, delta("   ", finish="stop")), (0, "data: [DONE]\n\n")], "empty_response"),
    ([(0.1, "data: PRIVATE malformed event\n\n")], "malformed_stream"),
])
def test_http_200_does_not_hide_stream_or_completion_failures(frames, error):
    row, requests = measured(frames)
    assert row["http_status"] == 200 and row["error"] == error
    assert row["error_phase"] == "stream" and row["quality_heuristic_pass"] is None
    assert len(requests) == 1 and "PRIVATE" not in json.dumps(row)


def test_allowlisted_identifiers_and_strict_numeric_usage_exclude_provider_content():
    row, _ = measured([
        (0.1, delta("Привет!", model=ACTUAL_MODEL, provider="Google")),
        (0.1, event({"model": "secret/private-user-text", "provider": "PRIVATE provider text",
                     "choices": [], "usage": {
                         "prompt_tokens": True, "completion_tokens": "4", "total_tokens": -1,
                         "cost": float("nan"), "unknown": "PRIVATE", "details": {"api_key": KEY},
                     }})),
        (0.1, delta(finish="stop")), (0, "data: [DONE]\n\n"),
    ])
    assert row["actual_model"] == ACTUAL_MODEL and row["provider"] == "Google"
    assert row["usage"] == {}
    serialized = json.dumps(row, allow_nan=False)
    assert "PRIVATE" not in serialized and KEY not in serialized and "secret/" not in serialized
    assert "Привет" not in serialized
    assert probe._usage({"prompt_tokens": 3, "completion_tokens": 0, "cost": 0.0}) == {
        "prompt_tokens": 3, "completion_tokens": 0, "cost": 0.0,
    }
    assert probe._usage({"cost": 10**400}) == {}


def test_observed_public_provider_name_is_retained_without_arbitrary_strings():
    row, _ = measured([
        (0.1, delta("Привет!", provider="Nvidia")),
        (0.1, delta(finish="stop")), (0, "data: [DONE]\n\n"),
    ])
    assert row["provider"] == "Nvidia"


@pytest.mark.parametrize("prices,error", [
    ({"prompt": "0"}, "catalog_price_missing"),
    ({"prompt": "0", "completion": "0", "request": "0.001"}, "catalog_price_not_zero"),
    ({"prompt": "0", "completion": "0", "internal_reasoning": "-1"}, "catalog_price_not_zero"),
    ({"prompt": "NaN", "completion": "0"}, "catalog_price_invalid"),
    ({"prompt": "Infinity", "completion": "0"}, "catalog_price_invalid"),
    ({"prompt": False, "completion": "0"}, "catalog_price_invalid"),
    ({"prompt": "unknown", "completion": "0"}, "catalog_price_invalid"),
])
def test_entire_selected_catalog_is_checked_before_any_model_calls(prices, error):
    data = catalog()
    data["data"][1]["pricing"] = prices
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        with pytest.raises(probe.ProbeError, match=error):
            probe.run_probe(client, catalog_data=data, models=[MODEL, ACTUAL_MODEL], api_key=KEY,
                            samples=1, scenarios=("greeting",))
    assert calls == []


@pytest.mark.parametrize("catalog_data,models", [
    ({"data": "malformed"}, [MODEL]),
    (catalog(), ["fixture/not-in-catalog"]),
    (catalog(), ["https://private.invalid/chat/completions"]),
    ({"data": catalog()["data"] * 2}, [MODEL]),
])
def test_invalid_catalog_or_model_route_prevents_all_dispatch(catalog_data, models):
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        with pytest.raises(probe.ProbeError):
            probe.run_probe(client, catalog_data=catalog_data, models=models, api_key=KEY,
                            samples=1, scenarios=("greeting",))
    assert requests == []


def test_measure_rejects_unverified_catalog_and_unselected_model_without_dispatch():
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        for verified, model in [(None, MODEL), (probe.validate_catalog(catalog(), [MODEL]), ACTUAL_MODEL)]:
            with pytest.raises(probe.ProbeError, match="model_not_verified"):
                probe.measure(client, catalog=verified, model=model, api_key=KEY)
    assert requests == []


def test_timeout_and_transport_failures_use_fixed_codes_without_retry():
    for exception, expected in [(httpx.ReadTimeout("PRIVATE credential"), "timeout"),
                                (httpx.ConnectError("PRIVATE credential"), "transport_error")]:
        clock = Clock()
        requests = []

        def handler(request):
            requests.append(request)
            raise exception

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            row = probe.measure(client, catalog=probe.validate_catalog(catalog(), [MODEL]), model=MODEL,
                                api_key=KEY, clock=clock)
        assert row["error"] == expected and len(requests) == 1
        assert "PRIVATE" not in json.dumps(row)


def test_comment_only_stream_has_elapsed_and_size_bounds():
    row, _ = measured([(41, ": keepalive\n\n")])
    assert row["error"] == "timeout" and row["first_text_seconds"] is None
    row, _ = measured([(0, ": " + "x" * probe.MAX_STREAM_BYTES + "\n\n")])
    assert row["error"] == "response_too_large"


def test_byte_chunks_without_newlines_are_bounded_before_line_assembly():
    row, _ = measured([(0, "x" * 20000)] * 4)
    assert row["error"] == "response_too_large" and row["first_text_seconds"] is None
    row, _ = measured([(21, "x"), (21, "y")])
    assert row["error"] == "timeout" and row["total_seconds"] == pytest.approx(42.1)


def test_failed_attempts_remain_in_denominator_and_next_attempt_still_runs():
    clock = Clock()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "PRIVATE"}})
        return httpx.Response(200, stream=TimedStream(clock, success_frames()))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe.run_probe(client, catalog_data=catalog(), models=[MODEL], api_key=KEY,
                                 samples=2, scenarios=("greeting",), clock=clock, sleep=clock.sleep)
    assert len(calls) == 2 and clock.sleeps == [pytest.approx(3.2)]
    summary = result["summary"][0]
    assert summary["attempts"] == 2 and summary["successes"] == 1 and summary["failures"] == 1
    assert summary["errors"] == {"http_429": 1}
    assert summary["quality_heuristic_checked"] == summary["quality_heuristic_passes"] == 1
    assert summary["successful_only_seconds"]["first_text_seconds"]["samples"] == 1


def test_nearest_rank_percentiles_use_only_successful_samples_and_expose_counts():
    base, _ = measured()
    rows = [{**base, "first_text_seconds": float(index), "total_seconds": float(index + 1),
             "first_phrase_seconds": None} for index in range(1, 21)]
    rows.extend({**base, "error": "timeout", "first_text_seconds": 0.001} for _ in range(5))
    summary = probe.summarize(rows)[0]
    assert (summary["attempts"], summary["successes"], summary["failures"]) == (25, 20, 5)
    assert summary["errors"] == {"timeout": 5}
    assert summary["successful_only_seconds"]["first_text_seconds"] == {"samples": 20, "p50": 10.0, "p95": 19.0}
    assert summary["successful_only_seconds"]["first_phrase_seconds"] == {"samples": 0, "p50": None, "p95": None}
    assert probe.percentile([], 0.95) is None and probe.summarize([]) == []


def test_different_output_caps_are_not_combined_in_one_latency_group():
    row, _ = measured()
    summary = probe.summarize([row, {**row, "max_tokens": row["max_tokens"] + 1}])
    assert len(summary) == 2 and all(group["attempts"] == 1 for group in summary)


@pytest.mark.parametrize("options", [
    {"samples": 101}, {"samples": 0}, {"samples": True},
    {"samples": 100, "reasoning_modes": ("low", "disabled")},
    {"interval": 3.19}, {"interval": float("nan")},
    {"timeout": 0}, {"timeout": 121}, {"timeout": float("inf")},
    {"max_tokens": 0}, {"max_tokens": 8193},
    {"scenarios": ("private_prompt",)}, {"reasoning_modes": ("low", "low")},
])
def test_invalid_or_unbounded_plans_make_no_model_calls(options):
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        with pytest.raises(probe.ProbeError):
            probe.run_probe(client, catalog_data=catalog(), models=[MODEL], api_key=KEY, **options)
    assert requests == []


def test_catalog_fetch_is_fixed_and_never_receives_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=catalog())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe.fetch_catalog(client) == catalog()
    assert len(requests) == 1 and str(requests[0].url) == probe.OPENROUTER_URL + "/models"
    assert "Authorization" not in requests[0].headers


def test_cli_requires_output_and_never_overwrites_an_existing_artifact(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        probe.main([])
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    output = tmp_path / "preserve.jsonl"
    output.write_text("existing WIP", encoding="utf-8")
    monkeypatch.setattr(probe, "fetch_catalog", lambda *_args: pytest.fail("must not reach network"))
    assert probe.main(["--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "existing WIP"


def test_cli_writes_only_safe_attempts_and_summary_with_fixed_client_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    clock = Clock()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=catalog())
        return httpx.Response(200, stream=TimedStream(clock, success_frames()))

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    options = {}

    def client_factory(**kwargs):
        options.update(kwargs)
        return client

    monkeypatch.setattr(probe.httpx, "Client", client_factory)
    output = tmp_path / "new.jsonl"
    assert probe.main(["--output", str(output), "--model", MODEL, "--samples", "1",
                       "--scenario", "greeting", "--max-tokens", "2048"]) == 0
    lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [line["type"] for line in lines] == ["attempt", "summary"]
    assert lines[0]["max_tokens"] == lines[1]["max_tokens"] == 2048
    assert lines[1]["production_measured"] is False
    assert options["trust_env"] is False and options["follow_redirects"] is False
    assert len(calls) == 2 and "Authorization" not in calls[0].headers
    assert KEY not in output.read_text(encoding="utf-8")


def test_credentials_require_explicit_source_without_dotenv_interpolation(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(probe.ProbeError, match="api_key_unavailable"):
        probe._api_key(None)
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    assert probe._api_key(None) == KEY
    env_file = tmp_path / "chosen.env"
    env_file.write_text("OPENROUTER_API_KEY=explicit-${PRIVATE_TOKEN}-fixture\n", encoding="utf-8")
    monkeypatch.setenv("PRIVATE_TOKEN", "do-not-read")
    assert probe._api_key(env_file) == "explicit-${PRIVATE_TOKEN}-fixture"


def test_planning_quality_is_only_a_labeled_arithmetic_heuristic():
    row, _ = measured(success_frames("Остаток 800 рублей. Можно сократить расходы или увеличить бюджет."), scenario="planning")
    assert row["quality_method"] == "heuristic" and row["quality_heuristic_pass"] is True
    row, _ = measured(success_frames("Остаток 900 рублей."), scenario="planning")
    assert row["error"] is None and row["quality_heuristic_pass"] is False
