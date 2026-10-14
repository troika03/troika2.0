"""Bounded specialist workers for one development Run, with shared call budget."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context
import json
import uuid
import threading
import time
from decimal import Decimal, InvalidOperation


_FREE_REQUESTS = threading.BoundedSemaphore(2)
_FREE_CATALOG_LOCK = threading.Lock()
_FREE_CATALOG = (0.0, ())


def eligible_free_models(models):
    """Do not infer zero cost from a suffix or a missing completion price."""
    eligible = []
    for model in models:
        prices = model.get("pricing", {})
        try:
            free = ("prompt" in prices and "completion" in prices
                    and all(Decimal(str(value)).is_finite() and Decimal(str(value)) == 0
                            for value in prices.values()))
        except (TypeError, ValueError, InvalidOperation):
            free = False
        if (free and isinstance(model.get("id"), str) and model["id"].endswith(":free")
                and "structured_outputs" in model.get("supported_parameters", [])
                and int(model.get("context_length") or 0) >= 128000
                and "text" in model.get("architecture", {}).get("output_modalities", [])):
            eligible.append(model)
    # Coding descriptions rank ahead of general models, then context capacity.
    eligible.sort(key=lambda m: ("reasoning_effort" in m.get("supported_parameters", []),
                                 "cod" in (m.get("description", "") + m["id"]).lower(),
                                 int(m.get("context_length") or 0)), reverse=True)
    return tuple(m["id"] for m in eligible[:3])


def _free_candidates(client):
    global _FREE_CATALOG
    with _FREE_CATALOG_LOCK:
        if time.monotonic() - _FREE_CATALOG[0] < 300 and _FREE_CATALOG[1]:
            return _FREE_CATALOG[1]
        page = client.models.list(timeout=15)
        models = [model.model_dump() for model in page.data]
        selected = eligible_free_models(models)
        if not selected:
            raise ValueError("No verified free structured development model is available")
        _FREE_CATALOG = (time.monotonic(), selected)
        return selected


class DocumentRequested(Exception):
    def __init__(self, plan):
        self.plan = plan

from troika_product.development_agent import DevelopmentAgent, _paths, response_format


def free_api(messages, tokens, timeout, cancelled=None):
    """Use current verified zero-price models; no paid auxiliary fallback."""
    from agent.auxiliary_client import get_text_auxiliary_client

    from agent.provider_metering import current_provider_guard
    from troika_product.own_provider import current_credentials
    guard = current_provider_guard()
    own = current_credentials() or getattr(guard, "credentials", None)
    if own is not None and (own.provider != "openrouter" or not own.model.endswith(":free")):
        raise ValueError("Personal development requires a verified free model; paid fallback is disabled")
    if own is not None and getattr(guard, "credentials", None) is None:
        raise ValueError("Personal development route is unavailable; company fallback is disabled")
    client, model = get_text_auxiliary_client(task="development_free")
    if client is None or model != "openrouter/free":
        raise ValueError("Free development route is unavailable; paid fallback is disabled")
    # The resolved client retains central SDK metering. Calling it directly avoids
    # call_llm's automatic fallback to another (potentially paid) provider.
    from urllib.parse import urlparse
    endpoint = urlparse(str(client.base_url))
    if endpoint.hostname != "openrouter.ai" or endpoint.scheme != "https" or endpoint.port not in {None, 443}:
        raise ValueError("Free development requires the verified OpenRouter endpoint")
    client = client.with_options(max_retries=0)
    models = _free_candidates(client)
    if own is not None:
        if own.model not in models:
            raise ValueError("Personal model is not in the verified free development catalogue")
        models = (own.model,)
    elif guard is not None:
        # Only this task can extend its local price catalogue after the official
        # zero-price check. Keep the subscription's raw-token accounting policy.
        from agent.provider_metering import ProviderCallBlocked
        from troika_product.llm_metering import PriceCatalogue
        entry = guard.catalogue.entries.get(("openrouter", "openrouter/free"))
        if entry is None or entry.debit_mode != "model_tokens":
            raise ProviderCallBlocked("resource_price_unavailable", "Учёт бесплатного автопилота ещё не настроен.")
        guard.catalogue = PriceCatalogue({**guard.catalogue.entries,
            **{("openrouter", candidate): entry for candidate in models}})
    deadline = time.monotonic() + timeout
    while True:
        if cancelled and cancelled():
            raise InterruptedError("Development stopped while waiting for free model")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Free development queue timeout")
        if _FREE_REQUESTS.acquire(timeout=min(.25, remaining)):
            break
    try:
        if cancelled and cancelled():
            raise InterruptedError("Development stopped before free model request")
        return client.chat.completions.create(
            model=models[0], messages=messages, max_tokens=tokens, timeout=timeout,
            extra_body={"reasoning": {"enabled": False},
                        "response_format": response_format(messages)})
    finally:
        _FREE_REQUESTS.release()


class DevelopmentTeam(DevelopmentAgent):
    def __init__(self, *, call=free_api, cancelled=None, progress=None, max_workers=3):
        self.raw_call = call
        super().__init__(call=self._model_call, cancelled=cancelled)
        self.progress = progress or (lambda **event: None)
        self.max_workers = max(1, min(3, max_workers))
        self.design = {}
        self.design_written = False
        self.dependencies = {}
        self.pending = {}
        self.pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="troika-worker")

    def _model_call(self, messages, tokens, timeout):
        for attempt in range(3):
            if self.cancelled():
                raise InterruptedError("Development stopped")
            try:
                remaining = min(timeout, max(1, self.deadline - time.monotonic()))
                if self.raw_call is free_api:
                    return free_api(messages, tokens, remaining, cancelled=self.cancelled)
                return self.raw_call(messages, tokens, remaining)
            except Exception as error:
                if getattr(error, "status_code", None) != 429 or attempt == 2:
                    raise
                self.emit("waiting_limit", message="Жду свободный лимит бесплатной модели",
                          report="Бесплатная модель перегружена. Подожду и повторю; платные вызовы отключены.")
                end = min(self.deadline, time.monotonic() + 15 * (attempt + 1))
                while time.monotonic() < end:
                    self.guard()
                    time.sleep(max(0, min(1, end - time.monotonic())))
                with self._lock:
                    self.guard()
                    self.calls += 1

    def emit(self, stage, *, role="", worker_id="", state="", message="", report=""):
        self.progress(stage=stage, role=role, worker_id=worker_id, worker_state=state,
                      message=message, report=report, calls=self.calls)

    def ask(self, instruction, data, tokens=8000, validate=None):
        planning = not any(key in data for key in ("file", "syntax_checks", "design_task", "document_task"))
        if planning:
            tokens = max(tokens, 8000)
            self.emit("planning", role="planner", worker_id="planner", state="running",
                      message="Составляю план проекта")
            data = {**data, "autopilot": True}
            instruction += (' Каждый files элемент содержит depends_on: массив путей файлов, '
                            'которые должны быть готовы раньше. Укажи публичные контракты в purpose. '
                            'Общие модули создаются до зависимых экранов и тестов. Не создавай циклы. '
                            'Краткий purpose: 1–2 предложения. Не повторяй всю задачу в каждом файле.')
            instruction += (' write_required=true для файлов, которые нужно создать или изменить по '
                            'текущей задаче. Если пользователь просит исправление ошибки или новую функцию, '
                            'пометь затронутые существующие файлы true: они будут переписаны по плану. '
                            'write_required=false только для сохраняемых файлов и аудита без изменений.')
            instruction += (' output_kind=project для сайта или приложения, pptx для презентации, '
                            'docx для документа. Для pptx/docx планируй содержание, без Python-скрипта '
                            'для создания документа: его соберёт разрешённый renderer.')
        original_validation = validate
        if planning:
            def validate(value):
                if original_validation:
                    original_validation(value)
                value["files"] = self.items(value.get("files"), data.get("sources", {}), metadata=True)
                paths = {f["path"] for f in value["files"]}
                if not paths:
                    raise ValueError("Empty specialist plan")
                graph = {}
                for item in value["files"]:
                    if not isinstance(item.get("write_required", False), bool):
                        raise ValueError("write_required must be a boolean")
                    deps = item.get("depends_on", [])
                    if (not isinstance(deps, list) or not all(isinstance(d, str) and d in paths for d in deps)
                            or item["path"] in deps):
                        raise ValueError("Invalid specialist dependency graph: depends_on must name another path in files")
                    graph[item["path"]] = deps
                completed = set()
                while len(completed) < len(paths):
                    ready = {p for p in paths - completed if set(graph[p]) <= completed}
                    if not ready:
                        raise ValueError("Specialist dependency graph contains a cycle")
                    completed.update(ready)
        result = super().ask(instruction, data, tokens, validate)
        if planning:
            result["files"] = self.items(result["files"], data.get("sources", {}), metadata=True)
            paths = {f["path"] for f in result["files"]}
            for f in result["files"]:
                deps = f.get("depends_on", [])
                if (not isinstance(deps, list) or not all(isinstance(d, str) and d in paths for d in deps)
                        or f["path"] in deps):
                    raise ValueError("Invalid specialist dependency graph")
                self.dependencies[f["path"]] = deps
            completed = set()
            while len(completed) < len(paths):
                ready = {p for p in paths - completed if set(self.dependencies[p]) <= completed}
                if not ready:
                    raise ValueError("Specialist dependency graph contains a cycle")
                completed.update(ready)
            result["files"] = sorted(result["files"], key=lambda f: self._depth(f["path"]))
            self.emit("planning", role="planner", worker_id="planner", state="completed",
                      report=(f"План готов: {len(paths)} файлов. Перехожу к дизайну." if result.get("output_kind", "project") == "project"
                              else "План готов. Перехожу к дизайну документа."))
            self.emit("designing", role="designer", worker_id="designer", state="running",
                      message="Выбираю дизайн под задачу")
            def check_design(value):
                for key in ("direction", "audience", "typography", "palette", "layout", "interaction", "review_criteria"):
                    if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 2500:
                        raise ValueError("Designer supplied no concrete design specification")
            self.design = super().ask(
                'Сам выбери выразительный, подходящий задаче дизайн без изображения образца. '
                'Для сайта опиши сетку, типографику, ритм, состояния, адаптацию и уместную анимацию; '
                'для приложения — сценарии и доступность; для документов — спокойную профессиональную '
                'вёрстку, белый фон и тёмный текст. Не применяй один неоновый шаблон ко всем задачам. '
                'У сайта выбери один запоминающийся элемент, связанный с предметом. '
                'palette задаёт 4–6 конкретных hex-цветов, typography — 1–2 шрифта с ролями и размерами. '
                'Пустые градиенты вместо содержательных изображений и одинаковые карточки для всех '
                'разделов не выполняют дизайн. Если изображений нет, выбери осмысленную композицию '
                'текста или создаваемую кодом иллюстрацию по теме. Проверь план на шаблонность. '
                'Навигация должна помещаться на телефоне, фокус клавиатуры виден, reduced motion соблюдён. '
                'Текст кнопок и результата описывает фактическое действие, без ложной отправки или обещаний. '
                'Верни JSON с direction, audience, typography, palette, layout, interaction, review_criteria. '
                'Это конкретная спецификация для разработчиков, а не рассуждения.',
                {"task": data["task"], "plan": result, "design_task": True}, 8000, check_design)
            _paths({"DESIGN.md": json.dumps(self.design, ensure_ascii=False)})
            result["design"] = self.design
            self.emit("designing", role="designer", worker_id="designer", state="completed",
                      report="Дизайн выбран. " + self.design["direction"][:220])
            if result.get("output_kind") in {"pptx", "docx"}:
                raise DocumentRequested(result)
        return result

    def _depth(self, path):
        return 0 if not self.dependencies[path] else 1 + max(self._depth(d) for d in self.dependencies[path])

    def write(self, task, plan, sources, item, review=None):
        self.update_design(sources)
        for dep in self.dependencies.get(item["path"], []):
            if dep in self.pending:
                self.pending[dep].result()
        active = [future for future in self.pending.values() if not future.done()]
        if len(active) >= self.max_workers:
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
        worker = "writer-" + uuid.uuid4().hex[:12]
        def work():
            stage = "repairing" if review else "implementing"
            self.emit(stage, role="developer", worker_id=worker, state="running", message=item["path"])
            with self._lock:
                snapshot = dict(sources)
            super(DevelopmentTeam, self).write(task, plan, snapshot, item, review)
            with self._lock:
                self.guard()
                _paths({**sources, item["path"]: snapshot[item["path"]]})
                sources[item["path"]] = snapshot[item["path"]]
            self.emit(stage, role="developer", worker_id=worker, state="completed", message=item["path"])
        context = copy_context()
        self.pending[item["path"]] = self.pool.submit(context.run, work)

    def review(self, task, plan, sources):
        for future in list(self.pending.values()):
            future.result()
        self.pending.clear()
        self.update_design(sources)
        self.emit("reviewing", role="verifier", worker_id="verifier", state="running",
                  message="Проверяю текущую версию целиком")
        result = super().review(task, plan, sources)
        self.emit("reviewing", role="verifier", worker_id="verifier", state="completed",
                  report="Ревью исходников завершено. " + (
                      "Нашёл ошибки; исправляю." if result["status"] == "needs_changes"
                      else "Блокирующих замечаний нет. Тесты не запускались."))
        return result

    def update_design(self, sources):
        if self.design and not self.design_written:
            with self._lock:
                content = "# Дизайн\n\n" + "\n\n".join(
                    key + ": " + value for key, value in self.design.items())
                _paths({**sources, "DESIGN.md": content})
                sources["DESIGN.md"] = content
                self.design_written = True

    def run(self, task, initial=None):
        try:
            try:
                result = super().run(task, initial)
            except DocumentRequested as document:
                result = self.create_document(task, document.plan)
            result["review"]["visual_review"] = "not_checked"
            result["review"]["max_workers"] = self.max_workers
            return result
        finally:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def create_document(self, task, plan):
        kind = plan["output_kind"]
        args, report = {}, None
        for attempt in range(4):
            self.emit("implementing" if attempt == 0 else "repairing", role="author",
                      worker_id="author", state="running", message="Создаю содержание документа")
            def validate(value):
                items = value.get("slides" if kind == "pptx" else "sections")
                if (not isinstance(value.get("title"), str) or not value["title"].strip()
                        or not isinstance(items, list) or not 1 <= len(items) <= 40):
                    raise ValueError("Document author returned incomplete content")
                for item in items:
                    if (not isinstance(item, dict) or not isinstance(item.get("body"), str)
                            or not isinstance(item.get("title" if kind == "pptx" else "heading"), str)
                            or not isinstance(item.get("bullets"), list)
                            or not all(isinstance(b, str) for b in item["bullets"])):
                        raise ValueError("Invalid document section")
                _paths({"content.json": json.dumps(value, ensure_ascii=False)})
                from troika_product.document_generation import generate_docx, generate_pptx
                render_args = self.document_args(kind, value)
                (generate_pptx if kind == "pptx" else generate_docx)(render_args)
            args = super().ask(
                'Создай законченное содержание по задаче и дизайн-спецификации. '
                'Для презентации верни title и slides: title, body, bullets. '
                'slides содержит все слайды, включая титульный при необходимости. '
                'Соблюдай запрошенное число слайдов. Текст краткий: максимум 6 строк на слайде. '
                'Для документа верни title и sections: heading, body, bullets. '
                'Не выдумывай факты и источники; укажи допущения, если исходных данных нет. '
                'Не возвращай код генератора вместо документа. Сохраняй исходную задачу при исправлениях.',
                {"task": task, "plan": plan, "document_task": kind,
                 "previous": args, "review": report}, validate=validate)
            self.emit("implementing", role="author", worker_id="author", state="completed",
                      message="Содержание создано")
            source = {"content.json": json.dumps(args, ensure_ascii=False, indent=2)}
            def review_valid(value):
                if value.get("reviewed_files") != ["content.json"]:
                    raise ValueError("Document review is incomplete")
                self.validate_findings(value.get("issues"), source)
                if not isinstance(value.get("summary"), str):
                    raise ValueError("Document reviewer supplied no summary")
                if any(i.get("severity") not in {"critical", "major", "minor"} for i in value["issues"]):
                    raise ValueError("Invalid document review severity")
            self.emit("reviewing", role="verifier", worker_id="verifier", state="running",
                      message="Проверяю содержание по требованиям")
            report = super().ask(
                'Независимо проверь содержание документа по исходной задаче. Проверь полноту, '
                'логику, выдуманные факты, читаемость и соответствие дизайн-спецификации. '
                'В reviewed_files укажи content.json. Для каждого замечания укажи severity, '
                'path=content.json, message, fix, точную одну строку evidence из JSON, '
                'scenario, expected, actual. line — номер строки content.json, evidence пустой; '
                'runtime подставит реальную строку. Верни summary и files_to_write=[]. '
                'Рендер не просматривался: не заявляй визуальную проверку или успешное открытие файла.',
                {"task": task, "plan": plan, "sources": source,
                 "source_lines": {"content.json": "\n".join(f"{n}: {line}" for n, line in enumerate(source["content.json"].splitlines(), 1))},
                 "syntax_checks": []}, validate=review_valid)
            blocking = any(i["severity"] in {"critical", "major"} for i in report["issues"])
            self.emit("reviewing", role="verifier", worker_id="verifier", state="completed",
                      report="Содержание проверено. " + ("Исправляю замечания." if blocking else
                                                         "Блокирующих замечаний нет. Рендер ещё не проверен."))
            if not blocking:
                break
        report.update(method="api_model_review", status="needs_changes" if blocking else "passed",
                      execution="not_run", visual_review="not_checked", repairs=attempt,
                      api_calls=self.calls, models=sorted(self.models))
        return {"document": {"kind": kind, "args": args},
                "files": [{"path": p, "content": c} for p, c in source.items()], "review": report}

    @staticmethod
    def document_args(kind, value):
        key = "slides" if kind == "pptx" else "sections"
        items = []
        for item in value[key]:
            body = item["body"]
            bullets = item["bullets"]
            combined = "\n".join(([body] if body else []) + bullets)
            items.append({**item, "content": combined, "body": combined, "bullets": []})
        return {"title": value["title"], key: items, "include_cover": False}
