"""Account resource scope shared by text and reviewed tool adapters."""

import uuid
import threading
from agent.provider_metering import ProviderCallBlocked
from troika_product.llm_metering import LLMMeter, PriceCatalogue
from troika_product.resource_ledger import (
    ConcurrencyLimitExceeded,
    FeatureLimitExceeded,
    ResourceConflict,
    ResourceLedger,
)


def resource_config():
    from hermes_cli.config import load_config

    return load_config().get("platforms", {}).get("api_server", {}).get("extra", {})


def configured_ledger(registry, config):
    return ResourceLedger(
        registry,
        subsidy_limit_tokens=config.get("product_resource_subsidy_tokens", 33_333_333),
    )


class ResourceRuntime(LLMMeter):
    def __init__(self, registry, principal, *, run_key, config):
        ceiling = config.get("product_resource_task_tokens", 250_000)
        if type(ceiling) is not int or not 1 <= ceiling <= 10_000_000:
            raise ValueError("invalid task resource ceiling")
        super().__init__(
            configured_ledger(registry, config),
            principal,
            run_key=run_key,
            catalogue=PriceCatalogue.from_config(
                config.get("product_resource_prices", {})
            ),
            run_token_limit=ceiling,
        )
        self._heartbeat_stop = threading.Event()
        from troika_product.working_context import WorkingContext
        self.context = WorkingContext(
            self, enabled=config.get("product_compact_context_enabled", False)
        )
        self._budget_lock = threading.Lock()
        self._expensive_approved = False
        self._expensive_threshold = config.get(
            "product_resource_approval_tokens", 100000
        )
        if (
            type(self._expensive_threshold) is not int
            or not 1 <= self._expensive_threshold <= 10000000
        ):
            raise ValueError("invalid expensive-task approval threshold")

    def approve_resource_cost(self, upper_tokens, *, premium=False):
        from troika_product.subscription_policy import plan_policy
        from tools.approval import request_gateway_approval

        with self._budget_lock:
            summary = self.ledger.summary(self.principal)
            if premium and plan_policy(summary["plan"]).feature_limit("premium") == 0:
                raise ProviderCallBlocked(
                    "subscription_feature_not_available",
                    "Дорогая модель недоступна на текущем тарифе.",
                )
            committed = self.ledger.run_commitment(self.principal, self.run_key)
            needed = committed + upper_tokens
            if needed > committed + summary["remaining"]:
                raise ProviderCallBlocked(
                    "monthly_resource_exhausted",
                    "Недостаточно AI-токенов для следующего шага.",
                )
            if needed <= self.run_token_limit and (
                self._expensive_approved or upper_tokens < self._expensive_threshold
            ):
                return
            proposed = max(self.run_token_limit, needed)
            if proposed > 10000000:
                raise ProviderCallBlocked(
                    "resource_output_unbounded",
                    "Задача превышает максимальный допустимый расход.",
                )
            consent = request_gateway_approval(
                "resource_budget",
                (
                    f"Задача потратила или зарезервировала {committed} расчётных AI-токенов. "
                    f"Следующий шаг резервирует до {upper_tokens}. "
                    f"Разрешить общий предел задачи {proposed} AI-токенов? "
                    "Спишется фактический расход; неиспользованный резерв вернётся."
                ),
                choices=("once", "deny"),
            )
            if not consent.get("approved") or not consent.get("user_consent"):
                self.stopped = True
                raise ProviderCallBlocked(
                    "resource_budget_approval_required",
                    "Продолжение не подтверждено; новый платный вызов остановлен.",
                )
            self.run_token_limit = proposed
            self._expensive_approved = True

    def start(self):
        try:
            self.ledger.start_run(self.principal, self.run_key)
        except ConcurrencyLimitExceeded as error:
            raise ProviderCallBlocked(
                "subscription_concurrency_exceeded",
                "Сначала заверши текущую задачу на аккаунте.",
            ) from error

        def heartbeat():
            while not self._heartbeat_stop.wait(45):
                try:
                    self.ledger.heartbeat_run(self.principal, self.run_key)
                except (PermissionError, ResourceConflict):
                    self.stopped = True
                    return

        threading.Thread(
            target=heartbeat, daemon=True, name="troika-resource-lease"
        ).start()

    def finish(self):
        self.stopped = True
        self.context.clear()
        try:
            for event, counts in self.diagnostics.audit_events().items():
                self.ledger.registry.record_audit_event(
                    event, principal=self.principal, run_id=self.run_key, details=counts,
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Token counters unavailable")
        self.diagnostics.clear()
        if self.context.enabled:
            try:
                self.ledger.registry.record_audit_event(
                    "context.prepared", principal=self.principal, run_id=self.run_key,
                    details=dict(self.context.stats),
                )
            except Exception:
                # Optional numeric diagnostics must not prevent releasing the
                # run lease. No message text or exception body is logged.
                import logging
                logging.getLogger(__name__).warning("Context counters unavailable")
        self._heartbeat_stop.set()
        try:
            self.ledger.finish_run(self.principal, self.run_key)
        except PermissionError:
            # A revoked device cannot mutate account state. Its finite process
            # lease expires; dispatched money holds remain for reconciliation.
            pass

    def begin_call(self, *args, **kwargs):
        if self.stopped:
            raise ProviderCallBlocked("resource_run_stopped", "Задача остановлена.")
        try:
            self.ledger.heartbeat_run(self.principal, self.run_key)
        except ResourceConflict as error:
            raise ProviderCallBlocked(
                "resource_run_stopped",
                "Срок активной задачи истёк; новые вызовы остановлены.",
            ) from error
        return super().begin_call(*args, **kwargs)

    def prepare_payload(self, payload, *, client):
        if self.stopped:
            raise ProviderCallBlocked("resource_run_stopped", "Задача остановлена.")
        return self.context.prepare(payload, client=client)

    def begin_tool(self, name, arguments):
        if self.stopped:
            raise ProviderCallBlocked("resource_run_stopped", "Задача остановлена.")
        self.ledger.heartbeat_run(self.principal, self.run_key)
        if name in {"vision_analyze", "image_generate", "image_pollinations_url"}:
            raise ProviderCallBlocked(
                "unmetered_provider_route",
                "Учёт расходов этого инструмента ещё не подключён.",
            )
        if name in {"web_search", "web_extract", "web_research"}:
            from agent.web_search_registry import (
                get_active_search_provider,
                get_active_extract_provider,
            )

            provider = (
                get_active_extract_provider()
                if name == "web_extract"
                else get_active_search_provider()
            )
            if provider is None or provider.name != "searxng":
                raise ProviderCallBlocked(
                    "resource_price_unavailable",
                    "Цена поискового сервиса ещё не подтверждена.",
                )
        feature = {
            "web_search": "search",
            "web_extract": "search",
            "web_research": "deep_research",
            "troika_screen_snapshot": "snapshot",
        }.get(name)
        # Capability IDs are stable even when concrete document tool names vary.
        from troika_product.capabilities import TOOL_CAPABILITY

        capability = TOOL_CAPABILITY.get(name)
        if capability == "documents" and arguments.get("action") not in {
            "list",
            "read",
            "export",
        }:
            feature = "documents"
        if capability == "development" and arguments.get("action") not in {
            "list",
            "read",
            "export",
        }:
            feature = "development"
        if feature is None:
            return None
        try:
            hold = self.ledger.reserve(
                self.principal,
                operation_key=str(uuid.uuid4()),
                run_key=self.run_key,
                kind="tool",
                tokens=0,
                pricing_version="local-tools-2026-10-13",
                feature=feature,
            )
            self.ledger.mark_dispatched(self.principal, hold.id)
            return hold
        except FeatureLimitExceeded as error:
            raise ProviderCallBlocked(
                "subscription_feature_not_available",
                "Лимит этой функции на тарифе исчерпан.",
            ) from error

    def finish_tool(self, hold, *, successful):
        if hold is not None:
            self.ledger.settle(
                self.principal, hold.id, charged_tokens=0, successful=successful
            )
