"""Measure synthetic, direct OpenRouter calls without accessing Troika accounts.

Example: python scripts/troika_latency_probe.py --output probe.jsonl --samples 10

The output is an exclusively created JSONL file: independent attempts, then
successful-only latency summaries. Existing files are never
overwritten. Credentials come only from OPENROUTER_API_KEY or an explicit
--env-file; no user profile is discovered. No response text, error body, request
headers, credential, or user-supplied prompt is written to the report.

These measurements exclude product authentication, context, network delivery,
STT and TTS. The phrase measurement uses the existing deterministic stream guard;
it does not run final product completion verification. Quality is a small
Russian-language/arithmetic heuristic, not a semantic quality evaluation.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.think_scrubber import StreamingThinkScrubber
from troika_product.streaming import GuardedTextStream


OPENROUTER_URL = "https://openrouter.ai/api/v1"
MAX_SAMPLES = 100
MAX_ATTEMPTS = 200
MIN_INTERVAL = 3.2
MAX_TIMEOUT = 120.0
MAX_STREAM_BYTES = 1_048_576
MAX_EVENT_BYTES = 65536
SCENARIOS = {
    "greeting": "Привет!",
    "planning": (
        "Составь краткий план поездки для вымышленной семьи: бюджет 12000 рублей, "
        "билеты 3500 на каждого из двух взрослых, ребёнок бесплатно, жильё 4200. "
        "Посчитай остаток, назови ограничение и предложи два решения. "
        "Не ищи в интернете."
    ),
}
REASONING_MODES = {"disabled": {"enabled": False}, "low": {"effort": "low"}}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9][A-Za-z0-9_.:+-]{0,119}")
# Exact public provider names only. Unknown metadata is deliberately omitted.
_PROVIDERS = frozenset({
    "OpenAI", "Anthropic", "Google", "Google AI Studio", "Google Vertex",
    "DeepInfra", "Together", "Together AI", "Fireworks", "Groq", "Cerebras",
    "NVIDIA", "Novita", "Chutes", "SambaNova", "SiliconFlow", "Parasail",
    "Mistral", "Amazon Bedrock", "Azure", "xAI", "OpenRouter",
    "Nvidia", "Poolside", "Thinking Machines", "Minimax", "Cohere", "Recursive", "Dots",
})
_FINISH_REASONS = frozenset({"stop", "length", "error", "content_filter", "tool_calls"})
_USAGE_COUNTS = ("prompt_tokens", "completion_tokens", "total_tokens")


class ProbeError(Exception):
    """An internal, fixed error code, safe to serialize without exception text."""


@dataclass(frozen=True)
class VerifiedCatalog:
    requested_models: tuple[str, ...]
    public_model_ids: frozenset[str]


def validate_catalog(data, requested_models):
    """Check every selected model's entire pricing map before any model call."""
    models = tuple(requested_models)
    if (not models or len(models) != len(set(models))
            or any(not isinstance(model, str) or not _MODEL_ID.fullmatch(model) for model in models)):
        raise ProbeError("invalid_models")
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ProbeError("invalid_catalog")
    catalog = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model = entry.get("id")
        if not isinstance(model, str) or not _MODEL_ID.fullmatch(model):
            continue
        if model in catalog:
            raise ProbeError("ambiguous_catalog")
        catalog[model] = entry
    for model in models:
        if model not in catalog:
            raise ProbeError("model_not_in_catalog")
        prices = catalog[model].get("pricing")
        if not isinstance(prices, dict) or not {"prompt", "completion"} <= prices.keys():
            raise ProbeError("catalog_price_missing")
        for value in prices.values():
            if type(value) not in (str, int, float):
                raise ProbeError("catalog_price_invalid")
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                raise ProbeError("catalog_price_invalid") from None
            if not number.is_finite():
                raise ProbeError("catalog_price_invalid")
            if number != 0:
                raise ProbeError("catalog_price_not_zero")
    return VerifiedCatalog(models, frozenset(catalog))


def _bounded_json(response, limit):
    raw = bytearray()
    for chunk in response.iter_bytes():
        if len(raw) + len(chunk) > limit:
            raise ProbeError("response_too_large")
        raw.extend(chunk)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ProbeError("invalid_json") from None


def fetch_catalog(client, timeout=40.0):
    """Read the public catalog from the fixed endpoint without credentials."""
    try:
        with client.stream("GET", OPENROUTER_URL + "/models", timeout=timeout) as response:
            if response.status_code != 200:
                raise ProbeError("catalog_http_error")
            return _bounded_json(response, 16 * MAX_STREAM_BYTES)
    except httpx.TimeoutException:
        raise ProbeError("catalog_timeout") from None
    except httpx.RequestError:
        raise ProbeError("catalog_transport_error") from None


def _error_code(value, default):
    # Bodies are inspected only in RAM and never copied to output or exceptions.
    try:
        text = json.dumps(value, ensure_ascii=False).lower()
    except (ValueError, TypeError):
        return default
    if "reasoning is mandatory" in text and "cannot be disabled" in text:
        return "reasoning_required"
    return default


def _usage(value):
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in _USAGE_COUNTS
              if type(value.get(key)) is int and 0 <= value[key] <= 10**12}
    cost = value.get("cost")
    if type(cost) in (int, float) and 0 <= cost <= 10**12 and math.isfinite(cost):
        result["cost"] = cost
    return result


def _events(response, deadline, clock):
    """Bound bytes and elapsed time before assembling any SSE lines or events."""
    parts = []
    pending = bytearray()
    size = 0
    event_size = 0
    for raw in response.iter_bytes():
        if clock() >= deadline:
            raise ProbeError("timeout")
        size += len(raw)
        if size > MAX_STREAM_BYTES:
            raise ProbeError("response_too_large")
        pending.extend(raw)
        while (boundary := pending.find(b"\n")) >= 0:
            if boundary > MAX_EVENT_BYTES:
                raise ProbeError("response_too_large")
            try:
                line = pending[:boundary].decode("utf-8").rstrip("\r")
            except UnicodeError:
                raise ProbeError("malformed_stream") from None
            del pending[:boundary + 1]
            if not line:
                if parts:
                    yield "\n".join(parts)
                    parts.clear()
                    event_size = 0
            elif line.startswith("data:"):
                event_size += boundary
                if event_size > MAX_EVENT_BYTES:
                    raise ProbeError("response_too_large")
                parts.append(line[5:].lstrip(" "))
            # Comments, event names, ids, and retry directives carry no model text.
        if len(pending) > MAX_EVENT_BYTES:
            raise ProbeError("response_too_large")
    if pending:
        # A data field without its terminating newline is an incomplete event.
        raise ProbeError("incomplete_stream")
    if parts:
        yield "\n".join(parts)


def measure(client, *, catalog, model, scenario="greeting", reasoning="low",
            api_key, index=1, timeout=40.0, max_tokens=1536, clock=time.perf_counter):
    """Return one independent numeric/allowlisted attempt, with no retry.

    The clock and HTTP client can be replaced by deterministic offline fixtures.
    The HTTP timeout bounds each blocking operation; the same elapsed budget is
    checked between byte chunks, including comments. No automatic redirect occurs
    with the CLI's client. No final guard suffix is emitted by this direct probe.
    """
    if not isinstance(catalog, VerifiedCatalog) or model not in catalog.requested_models:
        raise ProbeError("model_not_verified")
    if scenario not in SCENARIOS or reasoning not in REASONING_MODES:
        raise ProbeError("invalid_scenario")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise ProbeError("invalid_timeout")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ProbeError("invalid_max_tokens")
    payload = {
        "model": model, "stream": True, "max_tokens": max_tokens, "n": 1,
        "stream_options": {"include_usage": True},
        "reasoning": dict(REASONING_MODES[reasoning]),
        "messages": [
            {"role": "system", "content": "Ты — Тройка. Отвечай по-русски кратко и ясно."},
            {"role": "user", "content": SCENARIOS[scenario]},
        ],
        "provider": {"max_price": {"prompt": 0, "completion": 0}, "allow_fallbacks": False},
    }
    # Use the same bytes for measurement and transmission. This is the JSON
    # request body size, excluding HTTP headers, TLS, and transport framing.
    request_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    start = clock()
    row = {
        "request_id": uuid.uuid4().hex, "path": "direct_openrouter",
        "scenario": scenario, "requested_model": model, "reasoning": reasoning,
        "index": index, "model_calls": 1, "max_tokens": max_tokens,
        "input_bytes": len(request_body),
        "http_status": None, "headers_seconds": None, "first_text_seconds": None,
        "first_phrase_seconds": None, "total_seconds": None,
        "actual_model": None, "provider": None, "characters": 0, "usage": {},
        "finish_reason": None, "stream_done": False, "error": None, "error_phase": None,
        "quality_method": "heuristic", "quality_heuristic_pass": None,
    }
    visible = []
    scrubber = StreamingThinkScrubber()

    def phrase(_text):
        if row["first_phrase_seconds"] is None:
            row["first_phrase_seconds"] = clock() - start

    guard = GuardedTextStream(phrase, SCENARIOS[scenario])

    def content(delta):
        text = scrubber.feed(delta)
        if not text:
            return
        if text.strip() and row["first_text_seconds"] is None:
            row["first_text_seconds"] = clock() - start
        row["characters"] += len(text)
        if row["characters"] > 65536:
            raise ProbeError("response_too_large")
        visible.append(text)
        guard.feed(text)

    try:
        with client.stream(
            "POST", OPENROUTER_URL + "/chat/completions", content=request_body,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
        ) as response:
            row["http_status"] = response.status_code
            row["headers_seconds"] = clock() - start
            if response.status_code != 200:
                row["error_phase"] = "http"
                row["error"] = "http_" + str(response.status_code)
                try:
                    row["error"] = _error_code(_bounded_json(response, 65536), row["error"])
                except ProbeError:
                    pass
            else:
                row["error_phase"] = "stream"
                for event in _events(response, start + timeout, clock):
                    if event == "[DONE]":
                        row["stream_done"] = True
                        break
                    try:
                        chunk = json.loads(event)
                    except ValueError:
                        raise ProbeError("malformed_stream") from None
                    if not isinstance(chunk, dict):
                        raise ProbeError("malformed_stream")
                    actual = chunk.get("model")
                    if isinstance(actual, str) and actual in catalog.public_model_ids:
                        row["actual_model"] = actual
                    provider = chunk.get("provider")
                    if isinstance(provider, str) and provider in _PROVIDERS:
                        row["provider"] = provider
                    row["usage"].update(_usage(chunk.get("usage")))
                    if chunk.get("error") is not None:
                        row["error"] = _error_code(chunk["error"], "stream_error")
                        break
                    choices = chunk.get("choices", [])
                    if not isinstance(choices, list) or len(choices) > 1:
                        raise ProbeError("malformed_stream")
                    for choice in choices:
                        if not isinstance(choice, dict):
                            raise ProbeError("malformed_stream")
                        finish = choice.get("finish_reason")
                        if finish is not None:
                            row["finish_reason"] = finish if isinstance(finish, str) and finish in _FINISH_REASONS else "unknown"
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, dict):
                            raise ProbeError("malformed_stream")
                        text = delta.get("content")
                        if isinstance(text, str):
                            content(text)
                    if row["finish_reason"] == "error":
                        row["error"] = "stream_error"
                        break
                if row["error"] is None:
                    finish = row["finish_reason"]
                    if finish == "length":
                        row["error"] = "length_limit"
                    elif finish == "content_filter":
                        row["error"] = "content_filtered"
                    elif finish == "tool_calls":
                        row["error"] = "unexpected_tool_call"
                    elif not row["stream_done"] or finish != "stop":
                        row["error"] = "incomplete_stream"
                    elif row["first_text_seconds"] is None:
                        row["error"] = "empty_response"
                if row["error"] is None:
                    text = "".join(visible)
                    row["quality_heuristic_pass"] = bool(re.search(r"[А-Яа-яЁё]", text)) and (
                        len(text) < 500 if scenario == "greeting" else bool(re.search(r"(?<!\d)800(?!\d)", text)))
                    row["error_phase"] = None
    except httpx.TimeoutException:
        row["error"], row["error_phase"] = "timeout", "transport"
    except httpx.RequestError:
        row["error"], row["error_phase"] = "transport_error", "transport"
    except ProbeError as error:
        row["error"] = error.args[0]
        row["error_phase"] = "stream"
    except Exception:
        row["error"], row["error_phase"] = "probe_error", "probe"
    row["total_seconds"] = clock() - start
    for key in ("headers_seconds", "first_text_seconds", "first_phrase_seconds", "total_seconds"):
        if row[key] is not None:
            row[key] = round(max(0.0, row[key]), 6)
    return row


def percentile(values, quantile):
    """Nearest-rank percentile; an empty sample has no percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)] if ordered else None


def summarize(rows):
    """Keep all attempt/error denominators; compute latency from successes only."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["requested_model"], row["reasoning"], row["scenario"], row["max_tokens"])].append(row)
    summaries = []
    for (model, reasoning, scenario, max_tokens), group in sorted(groups.items()):
        good = [row for row in group if row["error"] is None]
        timings = {}
        for key in ("headers_seconds", "first_text_seconds", "first_phrase_seconds", "total_seconds"):
            values = [row[key] for row in good if row[key] is not None]
            timings[key] = {"samples": len(values), "p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}
        summaries.append({
            "requested_model": model, "reasoning": reasoning, "scenario": scenario, "max_tokens": max_tokens,
            "attempts": len(group), "successes": len(good), "failures": len(group) - len(good),
            "errors": dict(sorted(Counter(row["error"] for row in group if row["error"] is not None).items())),
            "quality_method": "heuristic", "quality_heuristic_checked": len(good),
            "quality_heuristic_passes": sum(row["quality_heuristic_pass"] is True for row in good),
            "successful_only_seconds": timings,
        })
    return summaries


def run_probe(client, *, catalog_data, models, api_key, samples=10,
              scenarios=("greeting", "planning"), reasoning_modes=("low",),
              timeout=40.0, max_tokens=1536, interval=MIN_INTERVAL, clock=time.perf_counter,
              sleep=time.sleep, on_attempt=None):
    """Validate the complete plan, then measure every attempt independently."""
    if (type(samples) is not int or not 1 <= samples <= MAX_SAMPLES
            or not scenarios or not reasoning_modes or not models
            or len(set(scenarios)) != len(scenarios) or len(set(reasoning_modes)) != len(reasoning_modes)
            or any(case not in SCENARIOS for case in scenarios)
            or any(mode not in REASONING_MODES for mode in reasoning_modes)
            or len(models) * len(scenarios) * len(reasoning_modes) * samples > MAX_ATTEMPTS):
        raise ProbeError("invalid_probe_plan")
    if (type(interval) not in (int, float) or not math.isfinite(interval) or interval < MIN_INTERVAL
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT
            or type(max_tokens) is not int or not 1 <= max_tokens <= 8192):
        raise ProbeError("invalid_probe_limits")
    catalog = validate_catalog(catalog_data, models)
    rows = []
    for model in models:
        for reasoning in reasoning_modes:
            for scenario in scenarios:
                for index in range(1, samples + 1):
                    started = clock()
                    row = measure(client, catalog=catalog, model=model, scenario=scenario,
                                  reasoning=reasoning, api_key=api_key, index=index, timeout=timeout,
                                  max_tokens=max_tokens, clock=clock)
                    rows.append(row)
                    if on_attempt is not None:
                        on_attempt(row)
                    if len(rows) < len(models) * len(scenarios) * len(reasoning_modes) * samples:
                        sleep(max(0.0, interval - (clock() - started)))
    return {"attempts": rows, "summary": summarize(rows)}


def _api_key(env_file):
    if env_file is None:
        key = os.environ.get("OPENROUTER_API_KEY")
    else:
        from dotenv import dotenv_values
        try:
            if not Path(env_file).is_file():
                raise ProbeError("env_file_unavailable")
            key = dotenv_values(env_file, interpolate=False).get("OPENROUTER_API_KEY")
        except (OSError, UnicodeError):
            raise ProbeError("env_file_unavailable") from None
    if not isinstance(key, str) or not 16 <= len(key) <= 512 or any(char.isspace() for char in key):
        raise ProbeError("api_key_unavailable")
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file; existing files are rejected.")
    parser.add_argument("--env-file", type=Path, help="Explicit dotenv file; otherwise use OPENROUTER_API_KEY.")
    parser.add_argument("--model", action="append", dest="models", help="Exact public catalog ID; repeat to compare models.")
    parser.add_argument("--scenario", choices=SCENARIOS, action="append", dest="scenarios")
    parser.add_argument("--reasoning", choices=REASONING_MODES, action="append", dest="reasoning_modes")
    parser.add_argument("--samples", type=int, default=10, help="Per group, 1–100; total attempts cannot exceed 200.")
    parser.add_argument("--max-tokens", type=int, default=1536, help="Output cap, 1–8192 tokens; default 1536, including reasoning.")
    parser.add_argument("--timeout", type=float, default=40.0, help="HTTP operation timeout and SSE elapsed budget, at most 120 seconds.")
    parser.add_argument("--interval", type=float, default=MIN_INTERVAL, help="Minimum seconds between attempt starts, at least 3.2.")
    args = parser.parse_args(argv)
    try:
        key = _api_key(args.env_file)
        with args.output.open("x", encoding="utf-8") as output:
            def write(kind, value):
                output.write(json.dumps({"type": kind, **value}, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()

            try:
                with httpx.Client(timeout=40, trust_env=False, follow_redirects=False,
                                  transport=httpx.HTTPTransport(retries=0, trust_env=False)) as client:
                    catalog = fetch_catalog(client, min(MAX_TIMEOUT, max(0.1, args.timeout)))
                    result = run_probe(
                        client, catalog_data=catalog, models=args.models or ["openrouter/free"], api_key=key,
                        samples=args.samples, scenarios=args.scenarios or ("greeting", "planning"),
                        reasoning_modes=args.reasoning_modes or ("low",), timeout=args.timeout,
                        max_tokens=args.max_tokens, interval=args.interval,
                        on_attempt=lambda row: write("attempt", row),
                    )
                    write("summary", {"scope": "direct_openrouter_synthetic", "groups": result["summary"],
                                      "interval_seconds": args.interval, "timeout_seconds": args.timeout,
                                      "max_tokens": args.max_tokens,
                                      "quality_method": "heuristic", "production_measured": False})
            except ProbeError as error:
                write("error", {"error": error.args[0]})
                return 1
    except FileExistsError:
        print("probe_output_exists", file=sys.stderr)
        return 1
    except (OSError, ProbeError):
        print("probe_setup_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
