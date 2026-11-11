"""Product-scoped loop policy and finite ordinary agent execution."""

from dataclasses import replace
import json
import logging
import threading
import time

from agent.provider_metering import ProviderCallBlocked
from agent.tool_guardrails import ToolCallGuardrailConfig, ToolCallGuardrailController


_READ_ACTIONS = {
    "troika_assistant": frozenset({"project_list", "note_list", "task_list", "memory_list"}),
    "troika_context": frozenset({"history_search", "history_read", "persona_read"}),
    "troika_files": frozenset({"list", "read", "search", "stat"}),
}
_READ_TOOLS = frozenset({
    "troika_tool_search", "web_search", "web_extract", "web_research",
    "troika_file_search", "android_status", "android_battery", "android_network",
}) | frozenset(f"{tool}.{action}" for tool, actions in _READ_ACTIONS.items() for action in actions)
_MAX_SIGNATURE_ARGUMENT_BYTES = 1024 * 1024


def guardrail_call(name, arguments):
    """Normalize known routed calls; execution still validates every argument."""
    from troika_product.capabilities import CALL_TOOL, TOOL_CAPABILITY, routed_call

    arguments = dict(arguments)
    if name == CALL_TOOL and isinstance(arguments.get("arguments"), str):
        raw = arguments["arguments"]
        try:
            if len(raw.encode("utf-8")) <= _MAX_SIGNATURE_ARGUMENT_BYTES:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    arguments["arguments"] = parsed
        except (ValueError, UnicodeError, RecursionError):
            pass
    tool, arguments = routed_call(name, arguments)
    if tool in TOOL_CAPABILITY:
        action = arguments.get("action")
        if isinstance(action, str) and action in _READ_ACTIONS.get(tool, ()):
            tool = f"{tool}.{action}"
    return tool, arguments


class ProductToolGuardrailController(ToolCallGuardrailController):
    """Use the gateway's explicit outcome before legacy display heuristics."""

    halt_message = (
        "Я остановила повторяющиеся попытки: новые действия не дают результата. "
        "Выполнение всей просьбы не подтверждено."
    )

    def after_call(self, tool_name, args, result, *, failed=None):
        from troika_product.capabilities import CALL_TOOL

        if tool_name == CALL_TOOL and isinstance(result, str):
            try:
                if len(result.encode("utf-8")) <= _MAX_SIGNATURE_ARGUMENT_BYTES:
                    envelope = json.loads(result)
                    if isinstance(envelope, dict) and type(envelope.get("ok")) is bool:
                        failed = not envelope["ok"]
            except (ValueError, UnicodeError, RecursionError):
                pass
        return super().after_call(tool_name, args, result, failed=failed)


def install_agent_policy(agent, config, guard=None):
    """Install product-only policy without changing CLI defaults or toolsets."""
    enabled = config.get("product_tool_loop_guardrails_enabled", True)
    if type(enabled) is not bool:
        raise ValueError("invalid product tool guardrail setting")
    previous = getattr(getattr(agent, "_tool_guardrails", None), "config", None)
    if not isinstance(previous, ToolCallGuardrailConfig):
        previous = ToolCallGuardrailConfig()
    agent._tool_guardrails = ProductToolGuardrailController(
        replace(previous, hard_stop_enabled=enabled, idempotent_tools=previous.idempotent_tools | _READ_TOOLS),
        call_resolver=guardrail_call,
    )
    bind = getattr(guard, "bind_agent_deadline", None)
    if callable(bind):
        bind(agent)


class AgentDeadline:
    """A monotonic deadline activated only for ordinary bound agents."""

    def __init__(self, seconds):
        if type(seconds) is not int or not 1 <= seconds <= 86400:
            raise ValueError("invalid product agent timeout")
        self.seconds = seconds
        self._lock = threading.RLock()
        self._dispatch_lock = threading.RLock()
        self._deadline = None
        self._timer = None
        self._interrupts = []
        self._expired = False
        self._closed = False

    def bind(self, interrupt):
        self.check()
        with self._lock:
            if self._closed:
                raise ProviderCallBlocked("resource_run_stopped", "Задача остановлена.")
            if self._expired:
                raise ProviderCallBlocked(
                    "resource_run_deadline_exceeded",
                    "Время задачи истекло; новые действия остановлены.",
                )
            if interrupt not in self._interrupts:
                self._interrupts.append(interrupt)
            if self._deadline is None:
                self._deadline = time.monotonic() + self.seconds
                self._schedule(self.seconds)

    def _schedule(self, seconds):
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self):
        with self._dispatch_lock:
            with self._lock:
                if self._closed or self._expired or self._deadline is None:
                    return
                remaining = self._deadline - time.monotonic()
                if remaining > 0:
                    self._schedule(remaining)
                    return
                self._expired = True
                if self._timer is not None:
                    self._timer.cancel()
                interrupts = tuple(self._interrupts)
                self._interrupts.clear()
            for interrupt in interrupts:
                try:
                    interrupt()
                except Exception:
                    logging.getLogger(__name__).warning("Agent deadline interrupt unavailable")

    def check(self):
        with self._lock:
            due = (not self._closed and not self._expired and self._deadline is not None
                   and time.monotonic() >= self._deadline)
        if due:
            self._expire()
        with self._lock:
            if self._expired:
                raise ProviderCallBlocked(
                    "resource_run_deadline_exceeded",
                    "Время задачи истекло; новые действия остановлены.",
                )

    def close(self):
        with self._dispatch_lock:
            with self._lock:
                self._closed = True
                if self._timer is not None:
                    self._timer.cancel()
                self._interrupts.clear()
