"""Numeric request diagnostics, separate from billing and provider tokenizers.

Only counters leave this object. Prefix bytes live in RAM for one task and are
cleared at completion. No prompt, key, path, model output or text hash is logged.
"""
from copy import deepcopy
import json
import threading

from troika_product.working_context import token_count


def _estimate(value):
    # BPE can be quadratic for very long delimiter-free strings. This is a
    # local estimate: bounded chunks keep diagnostics cheap and deterministic.
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return sum(token_count(text[start:start + 4000]) for start in range(0, len(text), 4000))


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def input_breakdown(payload):
    """Additive cl100k estimates; framing and non-message options are explicit.

    Provider usage is the only actual total. Image bodies are not tokenized as
    text, and their unknown token cost is reported as an unestimated message.
    """
    buckets = dict.fromkeys(("system", "memory", "history", "tool_schemas",
                            "tool_results", "current_request", "framing"), 0)
    messages = payload.get("messages") or []
    current = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    unestimated = 0
    for i, message in enumerate(messages):
        role, content = message.get("role"), message.get("content")
        if content is not None and not isinstance(content, str):
            unestimated += 1
            content = ""
        content = content or ""
        if role in {"system", "developer"}:
            # Memory is an explicit product block within the system message.
            for marker in ("[TROIKA_PRIVATE_USER_MEMORY", "[TROIKA_PRIVATE_PROJECT_CONTEXT"):
                start = content.find(marker)
                if start < 0:
                    continue
                opening = content.find("{", start)
                try:
                    if opening < 0:
                        raise ValueError("missing memory payload")
                    _, end = json.JSONDecoder().raw_decode(content[opening:])
                except (ValueError, TypeError):
                    pass
                else:
                    end += opening
                    buckets["memory"] += _estimate(content[start:end])
                    content = content[:start] + content[end:]
            category = "system"
        elif role == "tool":
            category = "tool_results"
        else:
            category = "current_request" if i == current else "history"
        if content:
            buckets[category] += _estimate(content)
        metadata = {k: v for k, v in message.items() if k != "content"}
        buckets["framing"] += _estimate(metadata) + 4
    if payload.get("tools"):
        buckets["tool_schemas"] = _estimate(payload["tools"])
    options = {k: v for k, v in payload.items() if k in {
        "response_format", "tool_choice", "parallel_tool_calls"}}
    buckets["framing"] += (_estimate(options) if options else 0) + 2
    return buckets, unestimated


class TokenDiagnostics:
    def __init__(self):
        self._lock = threading.RLock()
        self._prefix = None
        self._stats = {"model_calls": 0, "provider_reported_calls": 0,
                       "provider_input_tokens": 0, "provider_output_tokens": 0,
                       "provider_total_tokens": 0, "cache_counter_calls": 0,
                       "provider_cache_read_tokens": 0, "provider_cache_write_tokens": 0,
                       "provider_reasoning_tokens": 0, "reasoning_counter_calls": 0,
                       "subscription_model_tokens": 0, "unestimated_messages": 0,
                       "prefix_comparisons": 0, "stable_prefix_calls": 0,
                       "local_estimated_input_tokens": 0}
        self._buckets = dict.fromkeys(input_breakdown({})[0], 0)

    def dispatched(self, payload):
        buckets, unestimated = input_breakdown(payload)
        # Compare the shared system/schema prefix only. User/history growth
        # should not masquerade as instability in the common product prefix.
        prefix = json.dumps({"tools": payload.get("tools", []), "system": [
            m for m in payload.get("messages", []) if m.get("role") in {"system", "developer"}
        ]}, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._stats["model_calls"] += 1
            self._stats["unestimated_messages"] += unestimated
            if self._prefix is not None:
                self._stats["prefix_comparisons"] += 1
                self._stats["stable_prefix_calls"] += int(prefix == self._prefix)
            self._prefix = prefix
            for key, value in buckets.items():
                self._buckets[key] += value
            self._stats["local_estimated_input_tokens"] += sum(buckets.values())

    def received(self, response, *, charged=0):
        raw = _get(response, "usage")
        prompt, output = _count(_get(raw, "prompt_tokens")), _count(_get(raw, "completion_tokens"))
        with self._lock:
            self._stats["subscription_model_tokens"] += charged
            if prompt is None or output is None:
                return
            self._stats["provider_reported_calls"] += 1
            self._stats["provider_input_tokens"] += prompt
            self._stats["provider_output_tokens"] += output
            self._stats["provider_total_tokens"] += prompt + output
            details = _get(raw, "prompt_tokens_details")
            cached = _get(details, "cached_tokens")
            written = _get(details, "cache_write_tokens")
            cached = _count(cached if cached is not None else _get(raw, "cache_read_input_tokens"))
            written = _count(written if written is not None else _get(raw, "cache_creation_input_tokens"))
            if cached is not None or written is not None:
                self._stats["cache_counter_calls"] += 1
                self._stats["provider_cache_read_tokens"] += cached or 0
                self._stats["provider_cache_write_tokens"] += written or 0
            reasoning = _count(_get(_get(raw, "completion_tokens_details") or _get(raw, "output_tokens_details"), "reasoning_tokens"))
            if reasoning is not None:
                self._stats["reasoning_counter_calls"] += 1
                self._stats["provider_reasoning_tokens"] += reasoning

    def snapshot(self):
        with self._lock:
            return {**self._stats, "local_input_components": deepcopy(self._buckets)}

    def audit_counts(self):
        snapshot = self.snapshot()
        components = snapshot.pop("local_input_components")
        return {**snapshot, **{"local_" + k + "_tokens": v for k, v in components.items()}}

    def audit_events(self):
        counts = self.audit_counts()
        groups = {"tokens.task": {}, "tokens.input": {}, "tokens.provider": {}}
        for key, value in counts.items():
            group = ("tokens.input" if key.startswith("local_") else
                     "tokens.provider" if key.startswith(("provider_", "cache_", "reasoning_")) else "tokens.task")
            groups[group][key] = value
        return groups

    def clear(self):
        with self._lock:
            self._prefix = None


def current_diagnostics():
    from agent.provider_metering import current_provider_guard
    diagnostics = getattr(current_provider_guard(), "diagnostics", None)
    return diagnostics.snapshot() if diagnostics is not None else None
