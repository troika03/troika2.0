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
_FREE_VISION_CATALOG = (0.0, ())


def eligible_free_models(models):
    """Do not infer zero cost from a suffix or a missing completion price."""
    eligible = []
    for model in models:
        prices = model.get("pricing", {})
        try:
            free = (
                "prompt" in prices
                and "completion" in prices
                and all(
                    Decimal(str(value)).is_finite() and Decimal(str(value)) == 0
                    for value in prices.values()
                )
            )
        except (TypeError, ValueError, InvalidOperation):
            free = False
        if (
            free
            and isinstance(model.get("id"), str)
            and model["id"].endswith(":free")
            and "structured_outputs" in model.get("supported_parameters", [])
            and int(model.get("context_length") or 0) >= 128000
            and "text" in model.get("architecture", {}).get("output_modalities", [])
        ):
            eligible.append(model)
    # Coding descriptions rank ahead of general models, then context capacity.
    eligible.sort(
        key=lambda m: (
            "reasoning_effort" in m.get("supported_parameters", []),
            "cod" in (m.get("description", "") + m["id"]).lower(),
            int(m.get("context_length") or 0),
        ),
        reverse=True,
    )
    return tuple(m["id"] for m in eligible[:3])


def _free_candidates(client, *, vision=False):
    global _FREE_CATALOG, _FREE_VISION_CATALOG
    with _FREE_CATALOG_LOCK:
        cached = _FREE_VISION_CATALOG if vision else _FREE_CATALOG
        if time.monotonic() - cached[0] < 300 and cached[1]:
            return cached[1]
        page = client.models.list(timeout=15)
        models = [model.model_dump() for model in page.data]
        if vision:
            models = [
                model
                for model in models
                if "image" in model.get("architecture", {}).get("input_modalities", [])
            ]
        selected = eligible_free_models(models)
        if not selected:
            raise ValueError(
                "No verified free structured development model is available"
            )
        if vision:
            _FREE_VISION_CATALOG = (time.monotonic(), selected)
        else:
            _FREE_CATALOG = (time.monotonic(), selected)
        return selected


class DocumentRequested(Exception):
    def __init__(self, plan):
        self.plan = plan


from troika_product.development_agent import DevelopmentAgent, _paths, response_format


def free_api(messages, tokens, timeout, cancelled=None, *, vision=False, schema=None):
    """Use current verified zero-price models; no paid auxiliary fallback."""
    from agent.auxiliary_client import get_text_auxiliary_client

    from agent.provider_metering import current_provider_guard
    from troika_product.own_provider import current_credentials

    guard = current_provider_guard()
    own = current_credentials() or getattr(guard, "credentials", None)
    if own is not None and (
        own.provider != "openrouter" or not own.model.endswith(":free")
    ):
        raise ValueError(
            "Personal development requires a verified free model; paid fallback is disabled"
        )
    if own is not None and getattr(guard, "credentials", None) is None:
        raise ValueError(
            "Personal development route is unavailable; company fallback is disabled"
        )
    client, model = get_text_auxiliary_client(task="development_free")
    if client is None or model != "openrouter/free":
        raise ValueError(
            "Free development route is unavailable; paid fallback is disabled"
        )
    # The resolved client retains central SDK metering. Calling it directly avoids
    # call_llm's automatic fallback to another (potentially paid) provider.
    from urllib.parse import urlparse

    endpoint = urlparse(str(client.base_url))
    if (
        endpoint.hostname != "openrouter.ai"
        or endpoint.scheme != "https"
        or endpoint.port not in {None, 443}
    ):
        raise ValueError("Free development requires the verified OpenRouter endpoint")
    client = client.with_options(max_retries=0)
    models = (
        _free_candidates(client, vision=True) if vision else _free_candidates(client)
    )
    if own is not None:
        if own.model not in models:
            raise ValueError(
                "Personal model is not in the verified free development catalogue"
            )
        models = (own.model,)
    elif guard is not None:
        # Only this task can extend its local price catalogue after the official
        # zero-price check. Keep the subscription's raw-token accounting policy.
        from agent.provider_metering import ProviderCallBlocked
        from troika_product.llm_metering import PriceCatalogue

        entry = guard.catalogue.entries.get(("openrouter", "openrouter/free"))
        if entry is None or entry.debit_mode != "model_tokens":
            raise ProviderCallBlocked(
                "resource_price_unavailable",
                "Учёт бесплатного автопилота ещё не настроен.",
            )
        guard.catalogue = PriceCatalogue({
            **guard.catalogue.entries,
            **{("openrouter", candidate): entry for candidate in models},
        })
    deadline = time.monotonic() + timeout
    while True:
        if cancelled and cancelled():
            raise InterruptedError("Development stopped while waiting for free model")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Free development queue timeout")
        if _FREE_REQUESTS.acquire(timeout=min(0.25, remaining)):
            break
    try:
        if cancelled and cancelled():
            raise InterruptedError("Development stopped before free model request")
        return client.chat.completions.create(
            model=models[0],
            messages=messages,
            max_tokens=tokens,
            timeout=timeout,
            extra_body={
                "reasoning": {"enabled": False},
                "response_format": schema if vision else response_format(messages),
            },
        )
    finally:
        _FREE_REQUESTS.release()


class DevelopmentTeam(DevelopmentAgent):
    def __init__(
        self,
        *,
        call=free_api,
        cancelled=None,
        progress=None,
        max_workers=3,
        checker=None,
    ):
        self.raw_call = call
        super().__init__(call=self._model_call, cancelled=cancelled)
        self.progress = progress or (lambda **event: None)
        self.max_workers = max(1, min(3, max_workers))
        self.design = {}
        self.design_written = False
        self.dependencies = {}
        self.pending = {}
        self.pool = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="troika-worker"
        )
        self.checkpoint_callback = None
        self.resume_state = None
        self.checkpoint_plan = None
        self.completed_files = set()
        self.checkpoint_task = ""
        self.checker = checker
        self._checks_resolved = checker is not None
        self.verified_pages = {}
        self.checkpoint_sources = {}

    def verification_checks(self):
        if not self._checks_resolved:
            from troika_product.development_verification import IsolatedChecks

            self.checker = IsolatedChecks.configured()
            if self.checker is not None:
                self.checker.cancelled = self.cancelled
            self._checks_resolved = True
        return self.checker

    def configure_checkpoint(self, callback, state=None):
        self.checkpoint_callback = callback
        self.resume_state = state
        if state:
            self.completed_files = set(state.get("completed", []))
            self.design = state.get("design", {})
            self.checkpoint_plan = state.get("plan")
            self.verified_pages = state.get("verified_pages", {})

    def save_checkpoint(self, sources):
        if self.checkpoint_callback:
            with self._lock:
                value = {
                    "version": 1,
                    "task": self.checkpoint_task,
                    "files": [{"path": p, "content": c} for p, c in sources.items()],
                    "plan": self.checkpoint_plan,
                    "design": self.design,
                    "completed": sorted(self.completed_files.intersection(sources)),
                    "verified_pages": self.verified_pages,
                }
                self.checkpoint_callback(value)

    def _model_call(self, messages, tokens, timeout):
        for attempt in range(3):
            if self.cancelled():
                raise InterruptedError("Development stopped")
            try:
                remaining = min(timeout, max(1, self.deadline - time.monotonic()))
                if self.raw_call is free_api:
                    return free_api(
                        messages, tokens, remaining, cancelled=self.cancelled
                    )
                return self.raw_call(messages, tokens, remaining)
            except Exception as error:
                if getattr(error, "status_code", None) != 429 or attempt == 2:
                    raise
                self.emit(
                    "waiting_limit",
                    message="Жду свободный лимит бесплатной модели",
                    report="Бесплатная модель перегружена. Подожду и повторю; платные вызовы отключены.",
                )
                end = min(self.deadline, time.monotonic() + 15 * (attempt + 1))
                while time.monotonic() < end:
                    self.guard()
                    time.sleep(max(0, min(1, end - time.monotonic())))
                with self._lock:
                    self.guard()
                    self.calls += 1

    def emit(self, stage, *, role="", worker_id="", state="", message="", report=""):
        self.progress(
            stage=stage,
            role=role,
            worker_id=worker_id,
            worker_state=state,
            message=message,
            report=report,
            calls=self.calls,
        )

    def ask(self, instruction, data, tokens=8000, validate=None):
        planning = not any(
            key in data
            for key in ("file", "syntax_checks", "design_task", "document_task")
        )
        if planning:
            self.checkpoint_task = data["task"]
            self.save_checkpoint(self.checkpoint_sources)
            tokens = max(tokens, 8000)
            self.emit(
                "planning",
                role="planner",
                worker_id="planner",
                state="running",
                message="Составляю план проекта",
            )
            data = {**data, "autopilot": True}
            instruction += (
                " Каждый files элемент содержит depends_on: массив путей файлов, "
                "которые должны быть готовы раньше. Укажи публичные контракты в purpose. "
                "Общие модули создаются до зависимых экранов и тестов. Не создавай циклы. "
                "Краткий purpose: 1–2 предложения. Не повторяй всю задачу в каждом файле."
            )
            instruction += (
                " write_required=true для файлов, которые нужно создать или изменить по "
                "текущей задаче. Если пользователь просит исправление ошибки или новую функцию, "
                "пометь затронутые существующие файлы true: они будут переписаны по плану. "
                "write_required=false только для сохраняемых файлов и аудита без изменений."
            )
            instruction += (
                " output_kind=project для сайта или приложения, pptx для презентации, "
                "docx для документа. Для pptx/docx планируй содержание, без Python-скрипта "
                "для создания документа: его соберёт разрешённый renderer."
            )
            instruction += (
                " Для нового проекта без обязательного стека предпочитай HTML/CSS/JS или React/TypeScript "
                "с обычным CSS. Изолированная проверка имеет Python+pytest, Node 24 node:test, React 19, "
                "Vitest 5, jsdom и Testing Library; установки пакетов и внешней сети нет. "
                "Нужный пользователю стек сохраняй, даже если автоматическая проверка его не поддерживает. "
                "Обязательный внешний ресурс не заменяй выдуманным. Для автономного preview используй "
                "локальные SVG/Canvas/CSS и системные шрифты. Не добавляй Vite/Tailwind, если задача их не требует."
            )
        original_validation = validate
        if planning:

            def validate(value):
                if original_validation:
                    original_validation(value)
                value["files"] = self.items(
                    value.get("files"), data.get("sources", {}), metadata=True
                )
                paths = {f["path"] for f in value["files"]}
                if not paths:
                    raise ValueError("Empty specialist plan")
                if value.get("output_kind") in {"docx", "pptx"}:
                    from pathlib import PurePosixPath
                    from troika_product.development import _SOURCE_SUFFIXES

                    if any(
                        PurePosixPath(path).suffix.lower() in _SOURCE_SUFFIXES
                        for path in paths
                    ):
                        raise ValueError(
                            "The plan promises source code files: output_kind must be project, not docx/pptx. "
                            "Preserve the requested code and file contracts. For an explicitly requested Office document, "
                            "plan only content.json, never a code generator."
                        )
                graph = {}
                for item in value["files"]:
                    if not isinstance(item.get("write_required", False), bool):
                        raise ValueError("write_required must be a boolean")
                    deps = item.get("depends_on", [])
                    if (
                        not isinstance(deps, list)
                        or not all(isinstance(d, str) and d in paths for d in deps)
                        or item["path"] in deps
                    ):
                        raise ValueError(
                            "Invalid specialist dependency graph: depends_on must name another path in files"
                        )
                    graph[item["path"]] = deps
                completed = set()
                while len(completed) < len(paths):
                    ready = {p for p in paths - completed if set(graph[p]) <= completed}
                    if not ready:
                        raise ValueError("Specialist dependency graph contains a cycle")
                    completed.update(ready)

        if planning and self.resume_state and self.resume_state.get("plan"):
            result = json.loads(json.dumps(self.resume_state["plan"]))
            if validate:
                validate(result)
            for item in result.get("files", []):
                if item.get("path") in self.completed_files:
                    item["write_required"] = False
        else:
            result = super().ask(instruction, data, tokens, validate)
        if planning:
            result["files"] = self.items(
                result["files"], data.get("sources", {}), metadata=True
            )
            paths = {f["path"] for f in result["files"]}
            for f in result["files"]:
                deps = f.get("depends_on", [])
                if (
                    not isinstance(deps, list)
                    or not all(isinstance(d, str) and d in paths for d in deps)
                    or f["path"] in deps
                ):
                    raise ValueError("Invalid specialist dependency graph")
                self.dependencies[f["path"]] = deps
            completed = set()
            while len(completed) < len(paths):
                ready = {
                    p
                    for p in paths - completed
                    if set(self.dependencies[p]) <= completed
                }
                if not ready:
                    raise ValueError("Specialist dependency graph contains a cycle")
                completed.update(ready)
            result["files"] = sorted(
                result["files"], key=lambda f: self._depth(f["path"])
            )
            self.emit(
                "planning",
                role="planner",
                worker_id="planner",
                state="completed",
                report=(
                    f"План готов: {len(paths)} файлов. Перехожу к дизайну."
                    if result.get("output_kind", "project") == "project"
                    else "План готов. Перехожу к дизайну документа."
                ),
            )
            self.emit(
                "designing",
                role="designer",
                worker_id="designer",
                state="running",
                message="Выбираю дизайн под задачу",
            )

            def check_design(value):
                for key in (
                    "direction",
                    "audience",
                    "typography",
                    "palette",
                    "layout",
                    "interaction",
                    "review_criteria",
                ):
                    if (
                        not isinstance(value.get(key), str)
                        or not value[key].strip()
                        or len(value[key]) > 2500
                    ):
                        raise ValueError(
                            "Designer supplied no concrete design specification"
                        )

            renderer = {}
            if result.get("output_kind") in {"pptx", "docx"}:
                renderer = {
                    "format": result["output_kind"],
                    "background": "white",
                    "text": "dark gray",
                    "font": "Arial",
                    "editable": ["title", "body", "bullets"],
                    "unsupported": ["custom fonts", "icons", "images", "absolute positioning", "custom shapes"],
                }
                if result["output_kind"] == "pptx":
                    renderer.update(
                        aspect_ratio="16:9",
                        layouts={
                            "cover": "large title near the middle, short subtitle below",
                            "content": "top left title, short text below",
                            "split": "top left title, text split into two columns",
                            "statement": "top left title, large first statement below",
                        },
                        title_pt=28,
                        body_pt=21,
                    )
                    renderer["editable"].append("layout")
                else:
                    renderer.update(page="A4", body_pt=11, paragraph_spacing="fixed")
            previous_design = self.design if self.resume_state else None
            self.design = previous_design or super().ask(
                "Сам выбери выразительный, подходящий задаче дизайн без изображения образца. "
                "Для сайта опиши сетку, типографику, ритм, состояния, адаптацию и уместную анимацию; "
                "для приложения — сценарии и доступность; для документов — спокойную профессиональную "
                "вёрстку, белый фон и тёмный текст. Не применяй один неоновый шаблон ко всем задачам. "
                "У сайта выбери один запоминающийся элемент, связанный с предметом. "
                "palette задаёт 4–6 конкретных hex-цветов, typography — 1–2 шрифта с ролями и размерами. "
                "Пустые градиенты вместо содержательных изображений и одинаковые карточки для всех "
                "разделов не выполняют дизайн. Если изображений нет, выбери осмысленную композицию "
                "текста или создаваемую кодом иллюстрацию по теме. Проверь план на шаблонность. "
                "Навигация должна помещаться на телефоне, фокус клавиатуры виден, reduced motion соблюдён. "
                "Текст кнопок и результата описывает фактическое действие, без ложной отправки или обещаний. "
                "Если дан renderer, проектируй только в его возможностях: не обещай другие шрифты, "
                "иконки, точные координаты, схемы или композиции, которые он не поддерживает. "
                "Запрошенные пользователем возможности за пределами renderer явно отрази как ограничение, "
                "не объявляй их выполненными. Для PPTX выбирай поддерживаемую композицию каждого слайда "
                "и краткий текст по смыслу, без выдуманных требований к сантиметрам. "
                "Верни JSON с direction, audience, typography, palette, layout, interaction, review_criteria. "
                "Это конкретная спецификация для разработчиков, а не рассуждения.",
                {"task": data["task"], "plan": result, "design_task": True, "renderer": renderer},
                8000,
                check_design,
            )
            _paths({"DESIGN.md": json.dumps(self.design, ensure_ascii=False)})
            result["design"] = self.design
            self.checkpoint_plan = result
            self.save_checkpoint(data.get("sources", {}))
            self.emit(
                "designing",
                role="designer",
                worker_id="designer",
                state="completed",
                report="Дизайн выбран. " + self.design["direction"][:220],
            )
            if result.get("output_kind") in {"pptx", "docx"}:
                raise DocumentRequested(result)
        return result

    def _depth(self, path):
        return (
            0
            if not self.dependencies[path]
            else 1 + max(self._depth(d) for d in self.dependencies[path])
        )

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
            self.emit(
                stage,
                role="developer",
                worker_id=worker,
                state="running",
                message=item["path"],
            )
            with self._lock:
                snapshot = dict(sources)
            super(DevelopmentTeam, self).write(task, plan, snapshot, item, review)
            with self._lock:
                self.guard()
                _paths({**sources, item["path"]: snapshot[item["path"]]})
                sources[item["path"]] = snapshot[item["path"]]
                self.completed_files.add(item["path"])
                self.save_checkpoint(sources)
            self.emit(
                stage,
                role="developer",
                worker_id=worker,
                state="completed",
                message=item["path"],
            )

        context = copy_context()
        self.pending[item["path"]] = self.pool.submit(context.run, work)

    def review(self, task, plan, sources):
        for future in list(self.pending.values()):
            future.result()
        self.pending.clear()
        self.update_design(sources)
        self.save_checkpoint(sources)
        self.emit(
            "reviewing",
            role="verifier",
            worker_id="verifier",
            state="running",
            message="Проверяю текущую версию целиком",
        )
        checks = self.verification_checks()
        proof, proof_key = {}, ""
        if checks is not None and getattr(checks, "version", ""):
            import hashlib
            from pathlib import Path
            from troika_product import development_agent

            review_plan = json.loads(json.dumps(plan))
            for item in review_plan.get("files", []):
                item.pop("write_required", None)
            proof_key = hashlib.sha256(
                json.dumps(
                    [task, review_plan, sources, checks.version],
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
                + Path(development_agent.__file__).read_bytes()
                + Path(__file__).read_bytes()
            ).hexdigest()
            saved = self.verified_pages.get("project_checks", {})
            if saved.get("key") == proof_key:
                candidate = saved.get("source", {})
                if candidate.get("status") == "passed" and set(
                    candidate.get("reviewed_files", [])
                ) == set(sources):
                    proof = json.loads(json.dumps(saved))
        result = (
            json.loads(json.dumps(proof["source"]))
            if proof
            else super().review(task, plan, sources)
        )
        if proof_key and result["status"] == "passed" and not proof:
            proof = {"key": proof_key, "source": json.loads(json.dumps(result))}
            self.verified_pages["project_checks"] = proof
            self.save_checkpoint(sources)
        if checks is not None and result["status"] == "passed":
            self.guard()
            self.emit("testing", message="Проверяю тесты в изолированной среде")
            execution = proof.get("execution") or checks.execution(sources)
            self.guard()
            if proof_key and execution["status"] == "passed":
                proof["execution"] = json.loads(json.dumps(execution))
                self.verified_pages["project_checks"] = proof
                self.save_checkpoint(sources)
            result["execution"] = execution["status"]
            result["execution_details"] = execution
            if execution["status"] == "failed":
                output = "\n".join(
                    str(c.get("output", ""))[:10000]
                    for c in execution.get("checks", [])
                )
                result["issues"].append({
                    "severity": "major",
                    "path": "*",
                    "message": "Исполнение тестов обнаружило ошибку",
                    "fix": "Исправить реализацию или окружение, не ослабляя проверки.\n"
                    + output,
                })
                result["files_to_write"] = [
                    {
                        "path": p,
                        "purpose": "Исправить настоящий сбой тестов.\n" + output,
                    }
                    for p in sources
                    if p.endswith((
                        ".py",
                        ".js",
                        ".cjs",
                        ".mjs",
                        ".json",
                        ".ts",
                        ".tsx",
                        ".jsx",
                        ".css",
                    ))
                ]
                result["status"] = "needs_changes"
            else:
                self.emit(
                    "visual_review",
                    role="visual_verifier",
                    worker_id="visual-verifier",
                    state="running",
                    message="Смотрю готовый интерфейс",
                )
                render = checks.project(sources)
                self.guard()
                from troika_product.development_verification import visual_review

                paths = [p for p in sources if not p.endswith(".md")]
                visual = visual_review(self, task, self.design, render, paths)
                if visual["status"] not in {
                    "passed",
                    "needs_changes",
                    "not_applicable",
                }:
                    raise ValueError(
                        "Visual verification is unavailable; no passed result was accepted"
                    )
                deterministic = []
                for metric in render.get("metrics", []):
                    if metric.get("content_width", 0) > metric.get("width", 0) + 1:
                        target = next(
                            (p for p in sources if p.endswith(".css")), paths[0]
                        )
                        deterministic.append({
                            "severity": "major",
                            "path": target,
                            "message": "Горизонтальное переполнение при ширине "
                            + str(metric["width"])
                            + "px",
                            "fix": "Устранить горизонтальное переполнение, сохранив содержимое и навигацию.",
                        })
                    if metric.get("javascript_errors"):
                        target = next(
                            (
                                p
                                for p in sources
                                if p.endswith((".js", ".mjs", ".html"))
                            ),
                            paths[0],
                        )
                        deterministic.append({
                            "severity": "major",
                            "path": target,
                            "message": "Ошибка JavaScript в настоящем браузере",
                            "fix": "Исправить "
                            + str(metric["javascript_errors"])[:1500],
                        })
                visual.setdefault("issues", []).extend(deterministic)
                if deterministic:
                    visual["status"] = "needs_changes"
                result["visual_review"] = visual["status"]
                result["visual_details"] = visual
                result["issues"].extend(visual["issues"])
                if visual["status"] == "needs_changes":
                    result["status"] = "needs_changes"
                    for issue in visual["issues"]:
                        if issue["severity"] == "major" and not any(
                            f["path"] == issue["path"] for f in result["files_to_write"]
                        ):
                            result["files_to_write"].append({
                                "path": issue["path"],
                                "purpose": issue["fix"],
                            })
                self.emit(
                    "visual_review",
                    role="visual_verifier",
                    worker_id="visual-verifier",
                    state="completed",
                    report="Готовый интерфейс проверен по изображению."
                    if visual["status"] == "passed"
                    else "Визуальная проверка: " + visual["status"],
                )
        self.emit(
            "reviewing",
            role="verifier",
            worker_id="verifier",
            state="completed",
            report="Ревью исходников завершено. "
            + (
                "Нашёл ошибки; исправляю."
                if result["status"] == "needs_changes"
                else "Блокирующих замечаний нет. Исполнение тестов: "
                + result.get("execution", "not_run")
                + "."
            ),
        )
        return result

    def update_design(self, sources):
        if self.design and not self.design_written:
            with self._lock:
                content = "# Дизайн\n\n" + "\n\n".join(
                    key + ": " + value for key, value in self.design.items()
                )
                _paths({**sources, "DESIGN.md": content})
                sources["DESIGN.md"] = content
                self.design_written = True

    def run(self, task, initial=None):
        self.checkpoint_sources = {f["path"]: f["content"] for f in (initial or [])}
        try:
            try:
                result = super().run(task, initial)
            except DocumentRequested as document:
                result = self.create_document(task, document.plan)
            result["review"].setdefault("visual_review", "not_checked")
            result["review"]["max_workers"] = self.max_workers
            return result
        finally:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def create_document(self, task, plan):
        kind = plan["output_kind"]
        args, report = {}, None
        if self.resume_state:
            try:
                args = json.loads(
                    next(
                        f["content"]
                        for f in self.resume_state["files"]
                        if f["path"] == "content.json"
                    )
                )
            except (ValueError, StopIteration):
                pass
        for attempt in range(4):
            self.emit(
                "implementing" if attempt == 0 else "repairing",
                role="author",
                worker_id="author",
                state="running",
                message="Создаю содержание документа",
            )

            def validate(value):
                items = value.get("slides" if kind == "pptx" else "sections")
                if (
                    not isinstance(value.get("title"), str)
                    or not value["title"].strip()
                    or not isinstance(items, list)
                    or not 1 <= len(items) <= 40
                ):
                    raise ValueError("Document author returned incomplete content")
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("body"), str)
                        or not isinstance(
                            item.get("title" if kind == "pptx" else "heading"), str
                        )
                        or not isinstance(item.get("bullets"), list)
                        or not all(isinstance(b, str) for b in item["bullets"])
                    ):
                        raise ValueError("Invalid document section")
                _paths({"content.json": json.dumps(value, ensure_ascii=False)})
                from troika_product.document_generation import (
                    generate_docx,
                    generate_pptx,
                )

                render_args = self.document_args(kind, value)
                (generate_pptx if kind == "pptx" else generate_docx)(render_args)

            if not args or attempt:
                args = super().ask(
                    "Создай законченное содержание по задаче и дизайн-спецификации. "
                    "Для презентации верни title и slides: title, body, bullets. "
                    "Для каждого слайда выбери layout: cover для титула, content для содержания, "
                    "split для двух сопоставимых групп, statement для одной ключевой мысли. "
                    "Выбирай композицию по смыслу, избегай одинаковых слайдов. "
                    "slides содержит все слайды, включая титульный при необходимости. "
                    "Соблюдай запрошенное число слайдов. Если пользователь ограничил строки, "
                    "его предел важнее. Иначе максимум 6 коротких строк на слайде. "
                    "Для документа верни title и sections: heading, body, bullets. "
                    "Не выдумывай факты, цены, бесплатные предложения, контакты, существующий сайт "
                    "или подтверждённые услуги. Для концепции описывай предложения как идеи. "
                    "Используй язык задачи, без случайных иностранных слов. "
                    "При исправлении устрани каждое critical/major из required_fixes; "
                    "повтор предыдущего содержания с теми же нарушениями не выполняет задачу. "
                    "Не возвращай код генератора вместо документа. Сохраняй исходную задачу при исправлениях.",
                    {
                        "task": task,
                        "plan": plan,
                        "document_task": kind,
                        "previous": args,
                        "review": report,
                        "required_fixes": [
                            i
                            for i in (report or {}).get("issues", [])
                            if i.get("severity") in {"critical", "major"}
                        ],
                    },
                    validate=validate,
                )
            else:
                validate(args)
            self.emit(
                "implementing",
                role="author",
                worker_id="author",
                state="completed",
                message="Содержание создано",
            )
            source = {"content.json": json.dumps(args, ensure_ascii=False, indent=2)}
            self.completed_files.add("content.json")
            self.save_checkpoint(source)

            def review_valid(value):
                if value.get("reviewed_files") != ["content.json"]:
                    raise ValueError("Document review is incomplete")
                self.validate_findings(value.get("issues"), source)
                if not isinstance(value.get("summary"), str):
                    raise ValueError("Document reviewer supplied no summary")
                if any(
                    i.get("severity") not in {"critical", "major", "minor"}
                    for i in value["issues"]
                ):
                    raise ValueError("Invalid document review severity")

            self.emit(
                "reviewing",
                role="verifier",
                worker_id="verifier",
                state="running",
                message="Проверяю содержание по требованиям",
            )
            report = super().ask(
                "Независимо проверь содержание документа по исходной задаче. Проверь полноту, "
                "логику, выдуманные факты, читаемость и соответствие дизайн-спецификации. "
                "В reviewed_files укажи content.json. Для каждого замечания укажи severity, "
                "path=content.json, message, fix, точную одну строку evidence из JSON, "
                "scenario, expected, actual. line — номер строки content.json, evidence пустой; "
                "runtime подставит реальную строку. Верни summary и files_to_write=[]. "
                "Рендер не просматривался: не заявляй визуальную проверку или успешное открытие файла.",
                {
                    "task": task,
                    "plan": plan,
                    "sources": source,
                    "source_lines": {
                        "content.json": "\n".join(
                            f"{n}: {line}"
                            for n, line in enumerate(
                                source["content.json"].splitlines(), 1
                            )
                        )
                    },
                    "syntax_checks": [],
                },
                validate=review_valid,
            )
            blocking = any(
                i["severity"] in {"critical", "major"} for i in report["issues"]
            )
            if not blocking and self.verification_checks() is not None:
                visual = self.review_document(task, kind, args, source)
                report["visual_review"] = visual["status"]
                report["visual_details"] = visual["checks"]
                report["issues"].extend(visual["issues"])
                blocking = visual["status"] == "needs_changes"
            self.emit(
                "reviewing",
                role="verifier",
                worker_id="verifier",
                state="completed",
                report="Содержание проверено. "
                + (
                    "Исправляю замечания."
                    if blocking
                    else "Блокирующих замечаний нет. Визуальная проверка: "
                    + report.get("visual_review", "not_checked")
                    + "."
                ),
            )
            if not blocking:
                break
        report.update(
            method="api_model_review",
            status="needs_changes" if blocking else "passed",
            execution="not_run",
            repairs=attempt,
            api_calls=self.calls,
            models=sorted(self.models),
        )
        return {
            "document": {"kind": kind, "args": args},
            "files": [{"path": p, "content": c} for p, c in source.items()],
            "review": report,
        }

    def review_document(self, task, kind, args, source):
        from troika_product.development_verification import visual_review
        from troika_product import document_generation
        import hashlib
        from pathlib import Path

        checks = self.verification_checks()
        key = hashlib.sha256(
            (
                json.dumps([kind, args], sort_keys=True, ensure_ascii=False)
                + getattr(checks, "version", "")
                + hashlib.sha256(
                    Path(document_generation.__file__).read_bytes()
                ).hexdigest()
            ).encode()
        ).hexdigest()
        page = 1
        details = []
        issues = []
        self.emit(
            "visual_review",
            role="visual_verifier",
            worker_id="visual-verifier",
            state="running",
            message="Проверяю настоящий рендер страниц",
        )
        while page is not None:
            self.guard()
            cached = (
                self.verified_pages.get(key + ":" + str(page))
                if getattr(checks, "version", "")
                else None
            )
            if cached is None:
                rendered = checks.document(
                    kind, self.document_args(kind, args), page_start=page
                )
                self.guard()
                visual = visual_review(
                    self, task, self.design, rendered, ["content.json"]
                )
                if visual["status"] not in {"passed", "needs_changes"}:
                    raise ValueError("Document visual verification is unavailable")
                if visual["status"] == "passed":
                    self.verified_pages[key + ":" + str(page)] = visual
                    self.save_checkpoint(source)
            else:
                visual = cached
            details.append(visual)
            issues.extend(visual["issues"])
            if any(i["severity"] == "major" for i in visual["issues"]):
                break
            page = visual.get("next_page")
        return {
            "status": "needs_changes"
            if any(i["severity"] == "major" for i in issues)
            else "passed",
            "issues": issues,
            "checks": details,
        }

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
