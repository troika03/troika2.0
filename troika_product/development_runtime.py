"""Development workflow on the existing Run transport, independent of chat."""

import asyncio
from contextlib import nullcontext
import hashlib
import json
import threading
import time
import uuid

from aiohttp import web

from troika_product.development import build_project
from troika_product.development_agent import _paths
from troika_product.development_team import DevelopmentTeam
from troika_product.device_delivery import device_deliveries


TERMINAL = {
    "completed",
    "failed",
    "cancelled",
    "paused",
    "waiting_budget",
    "interrupted",
}


def error(code, message, status=400):
    return web.json_response(
        {"error": {"code": code, "message": message}}, status=status
    )


def check_foreground_capacity(adapter, request):
    """Enforce the account Run cap even while monthly metering is disabled."""
    principal = adapter._product_principal(request)
    if principal is None or adapter._access_registry is None:
        return None
    from troika_product.subscription_policy import plan_policy

    plan = adapter._access_registry.subscription_summary(principal)["plan"]
    if plan not in {"free", "plus", "pro"}:
        return None  # Legacy diagnostic principals keep their existing policy.
    limit = plan_policy(plan).concurrent_runs
    active = sum(
        value.get("status") not in TERMINAL
        for run, value in adapter._run_statuses.items()
        if adapter._run_owners.get(run, (None,))[0] == principal.user_id
    )
    if active >= limit:
        return error(
            "concurrent_runs_exhausted",
            "Активные задачи заняли слоты тарифа. Остановите задачу или дождитесь результата.",
            429,
        )
    return None


async def start_development_run(
    adapter, request, body, *, team_factory=None, resume=None
):
    team_factory = team_factory or DevelopmentTeam
    principal = adapter._product_principal(request)
    if principal is None or adapter._access_registry is None:
        return error("product_identity_required", "Войдите в аккаунт.", 401)
    if adapter._access_registry.subscription_summary(principal)["plan"] != "pro":
        return error(
            "development_pro_required", "Разработка доступна только в Pro.", 403
        )
    from troika_product.own_provider import current_credentials

    own = current_credentials()
    if own is not None and (
        own.provider != "openrouter" or not own.model.endswith(":free")
    ):
        return error(
            "development_free_model_required",
            "Автопилот использует только проверенные бесплатные модели. В личном API выберите подходящую модель :free или отключите личный API.",
        )
    task = body.get("input")
    initial = body.get("files")
    key = body.get("idempotency_key")
    budget = body.get(
        "budget_tokens",
        min(
            250000,
            getattr(adapter, "_product_resource_config", {}).get(
                "product_resource_task_tokens", 250000
            ),
        ),
    )
    budget_approved = body.get("budget_approved") is True and "budget_tokens" in body
    if (
        not isinstance(task, str)
        or not task.strip()
        or len(task) > 20000
        or not isinstance(key, str)
        or not 8 <= len(key) <= 128
        or body.get("free_only", True) is not True
        or type(budget) is not int
        or not 10000 <= budget <= 250000
    ):
        return error(
            "invalid_development_request",
            "Проверьте описание проекта. Этот автопилот использует только бесплатные модели.",
        )
    try:
        _paths({"request.txt": task})
        if initial is not None:
            build_project({"files": initial})
            _paths({f["path"]: f["content"] for f in initial})
    except (ValueError, TypeError):
        return error(
            "invalid_project_sources",
            "Проверьте пути, размер и отсутствие секретов в исходниках.",
        )
    keys = adapter.__dict__.setdefault("_development_keys", {})
    identity = (principal.user_id, principal.device_id, key)
    digest = (
        resume["request_hash"]
        if resume
        else hashlib.sha256(
            json.dumps(
                [task, initial, budget, budget_approved],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    from troika_product.development_sessions import DevelopmentSessions

    sessions = DevelopmentSessions(adapter._access_registry)
    try:
        previous = sessions.request(principal, key, digest)
    except ValueError:
        return error("idempotency_conflict", "Повторный запрос изменился.", 409)
    if previous:
        status = adapter._run_statuses.get(previous["run_id"], {}).get(
            "status", "interrupted"
        )
        return web.json_response(
            {
                "run_id": previous["run_id"],
                "project_id": previous["project_id"],
                "status": status,
            },
            status=202,
        )
    if identity in keys:
        run_id, previous = keys[identity]
        if previous != digest:
            return error("idempotency_conflict", "Повторный запрос изменился.", 409)
        if run_id in adapter._run_statuses:
            return web.json_response(
                {"run_id": run_id, "status": adapter._run_statuses[run_id]["status"]},
                status=202,
            )
        keys.pop(identity)
    for old, (run_id, _) in list(keys.items()):
        if run_id not in adapter._run_statuses:
            keys.pop(old, None)
    active = [
        run
        for run, value in adapter._run_statuses.items()
        if value.get("status") not in TERMINAL
    ]
    background = [
        run
        for run in active
        if adapter._run_owners.get(run, (None,))[0] == principal.user_id
        and adapter._run_statuses[run].get("workflow") == "development"
    ]
    owner_active = [
        run
        for run in active
        if adapter._run_owners.get(run, (None,))[0] == principal.user_id
    ]
    if (
        len(background) >= 4
        or len(owner_active) >= 5
        or len(active) >= adapter._MAX_CONCURRENT_RUNS - 1
    ):
        return error(
            "development_capacity",
            "Фоновые слоты заняты. Один слот сохраняется для разговора.",
            429,
        )
    quota = adapter._consume_product_request_quota(request)
    if quota is not None:
        return quota
    run_id = "run_" + uuid.uuid4().hex
    session_id = "development-" + uuid.uuid4().hex
    denied = adapter._authorize_product_session(request, session_id, claim=True)
    if denied is not None:
        return denied
    from troika_product.development_sessions import DevelopmentSessions

    sessions = DevelopmentSessions(adapter._access_registry)
    project_id = resume["project_id"] if resume else run_id
    try:
        if resume:
            sessions.resume(
                principal,
                project_id,
                resume["revision"],
                resume["checkpoint"],
                run_id,
                budget_tokens=resume["budget_tokens"],
                approved=resume["budget_approved"],
                request=(key, digest),
            )
        else:
            sessions.create(
                principal,
                project_id,
                run_id,
                budget_tokens=budget,
                approved=budget_approved,
                personal_mode=own is not None,
                request=(key, digest),
            )
    except PermissionError:
        return error("project_unavailable", "Проект недоступен этому устройству.", 404)
    except ValueError:
        return error(
            "checkpoint_conflict",
            "Версия проекта изменилась. Обновите контрольную копию.",
            409,
        )
    keys[identity] = (run_id, digest)
    loop = asyncio.get_running_loop()
    stopped = threading.Event()
    paused = threading.Event()
    workers = {}
    reports = []
    queue = asyncio.Queue(maxsize=256)
    adapter._run_streams[run_id] = queue
    adapter._run_streams_created[run_id] = time.time()
    adapter._run_owners[run_id] = (principal.user_id, principal.device_id)
    title = str(body.get("title") or "Проект")[:100]
    adapter._set_run_status(
        run_id,
        "queued",
        session_id=session_id,
        workflow="development",
        title=title,
        stage="queued",
        workers=[],
        reports=[],
        free_only=True,
        project_id=project_id,
    )

    def cancelled():
        if stopped.is_set():
            return True
        try:
            return (
                adapter._access_registry.subscription_summary(principal)["plan"]
                != "pro"
            )
        except (PermissionError, ValueError):
            return True

    def progress(**event):
        def update():
            if stopped.is_set() or adapter._run_statuses[run_id]["status"] in TERMINAL:
                return
            worker_id = event.get("worker_id")
            if worker_id:
                workers[worker_id] = {
                    "id": worker_id,
                    "role": event["role"],
                    "status": event["worker_state"],
                    "task": event["message"][:200],
                }
            if event.get("report"):
                reports.append({
                    "id": len(reports) + 1,
                    "text": event["report"][:500],
                    "stage": event["stage"],
                    "timestamp": time.time(),
                })
            adapter._set_run_status(
                run_id,
                "running",
                stage=event["stage"],
                message=event["message"][:200],
                workers=list(workers.values())[-80:],
                reports=reports[-40:],
                api_calls=event["calls"],
            )
            if not queue.full():
                queue.put_nowait({
                    "event": "development.progress",
                    "run_id": run_id,
                    "stage": event["stage"],
                })

        loop.call_soon_threadsafe(update)

    team = team_factory(cancelled=cancelled, progress=progress, max_workers=3)

    def checkpoint(value):
        value = json.loads(json.dumps(value, ensure_ascii=False))
        revision, checkpoint_hash = sessions.checkpoint(
            principal, project_id, run_id, value
        )
        snapshots = adapter.__dict__.setdefault("_development_snapshots", {})
        snapshots[project_id] = {
            "revision": revision,
            "digest": checkpoint_hash,
            "checkpoint": value,
            "expires_at": time.time() + 600,
        }

        def updated():
            if run_id in adapter._run_statuses:
                adapter._set_run_status(
                    run_id,
                    adapter._run_statuses[run_id]["status"],
                    checkpoint_revision=revision,
                    checkpoint_digest=checkpoint_hash,
                )

            def expire():
                current = snapshots.get(project_id)
                if (
                    current
                    and current["revision"] == revision
                    and current["expires_at"] <= time.time()
                ):
                    snapshots.pop(project_id, None)

            loop.call_later(601, expire)

        loop.call_soon_threadsafe(updated)

    if hasattr(team, "configure_checkpoint"):
        restored = (
            resume["checkpoint"] if resume and not resume.get("instruction") else None
        )
        team.configure_checkpoint(checkpoint, restored)
        team.checkpoint_task = task
        checkpoint({
            "version": 1,
            "task": task,
            "files": initial or [],
            "plan": restored.get("plan") if restored else None,
            "design": restored.get("design", {}) if restored else {},
            "completed": restored.get("completed", []) if restored else [],
            "verified_pages": restored.get("verified_pages", {}) if restored else {},
        })

    class Handle:
        def interrupt(self, reason=""):
            paused.clear()
            stopped.set()

        def pause(self):
            paused.set()
            stopped.set()

    adapter._active_run_agents[run_id] = Handle()

    def execute():
        scope = getattr(adapter, "_resource_call_scope", lambda *a: nullcontext())(
            principal, run_id
        )
        with scope:
            if resume or budget_approved:
                from agent.provider_metering import current_provider_guard

                guard = current_provider_guard()
                if guard is not None:
                    guard.run_token_limit = (
                        resume["budget_tokens"] if resume else budget
                    )
                    guard._expensive_approved = (
                        resume["budget_approved"] if resume else budget_approved
                    )
            return team.run(task, initial)

    async def run_and_close():
        try:
            result = await asyncio.to_thread(execute)
            if cancelled():
                raise InterruptedError()
            kind, mime = "zip", "application/zip"
            if result.get("document"):
                from troika_product.document_generation import (
                    generate_docx,
                    generate_pptx,
                )

                kind = result["document"]["kind"]
                args = DevelopmentTeam.document_args(kind, result["document"]["args"])
                data = (generate_pptx if kind == "pptx" else generate_docx)(args)
                mime = {
                    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }[kind]
            else:
                data, _ = build_project(
                    {"title": title, **result}, require_complete=True
                )
            if cancelled():
                raise InterruptedError()
            artifact = device_deliveries.create(
                principal.user_id, principal.device_id, title, kind, mime, data
            )
            report = (
                (
                    "Проект создан. "
                    if result["review"]["status"] == "passed"
                    else "Черновик создан. "
                )
                + (
                    "Ревью не нашло блокирующих ошибок. "
                    if result["review"]["status"] == "passed"
                    else "Остались блокирующие замечания; они записаны в отчёте. "
                )
                + (
                    "Тесты прошли в изолированной среде. "
                    if result["review"].get("execution") == "passed"
                    else "Тесты завершились с ошибками. "
                    if result["review"].get("execution") == "failed"
                    else "Тесты не запускались. "
                )
                + "Результат готов к скачиванию."
            )
            reports.append({
                "id": len(reports) + 1,
                "text": report,
                "stage": "completed",
                "timestamp": time.time(),
            })
            adapter._set_run_status(
                run_id,
                "completed",
                stage="completed",
                artifact=artifact,
                reports=reports[-40:],
                review=result["review"],
                file_count=len(result["files"]),
                execution=result["review"].get("execution", "not_run"),
            )
        except (asyncio.CancelledError, InterruptedError):
            stopped.set()
            state = "paused" if paused.is_set() else "cancelled"
            text = (
                "Проект на паузе. Завершённые файлы сохранены в контрольной копии."
                if paused.is_set()
                else "Проект остановлен. Новые обращения к моделям не отправляются."
            )
            reports.append({
                "id": len(reports) + 1,
                "text": text,
                "stage": state,
                "timestamp": time.time(),
            })
            adapter._set_run_status(
                run_id,
                state,
                stage=state,
                reports=reports[-40:],
                message="Остановлено. Новые вызовы моделей не отправляются.",
            )
        except Exception as exc:
            # Never expose provider request bodies or API keys to clients/logs.
            continuation = isinstance(exc, ValueError) and str(exc) in {
                "Development API budget exhausted; project was not declared verified",
                "Development API timeout",
            }
            code = getattr(exc, "code", None)
            if not isinstance(code, str) or code not in {
                "monthly_resource_exhausted",
                "resource_budget_approval_required",
                "resource_price_unavailable",
                "resource_usage_unknown",
                "resource_byok_request_failed",
            }:
                code = "development_failed"
            if continuation:
                code = "development_checkpoint_continuation"
            message = (
                "Бесплатная модель временно недоступна. Платный вызов не выполнен."
                if getattr(exc, "status_code", None) in {404, 429, 503}
                else "Автопилот не завершил проект. Результат не объявлен проверенным."
            )
            message = {
                "development_checkpoint_continuation": "Промежуточная копия сохранена. Продолжение использует только оставшийся подтверждённый бюджет.",
                "monthly_resource_exhausted": "Месячных AI-токенов не хватает. Проект остановлен до новых обращений к модели.",
                "resource_budget_approval_required": "Достигнут предел AI-токенов задачи. Контрольная копия сохранена; можно подтвердить дополнительный бюджет и продолжить.",
                "resource_price_unavailable": "Учёт бесплатного автопилота ещё не настроен. Проект остановлен до вызова модели.",
                "resource_usage_unknown": "Провайдер не подтвердил расход токенов. Новые обращения остановлены до сверки.",
                "resource_byok_request_failed": "Личный API не выполнил запрос. Проверь ключ, бесплатную модель и лимит провайдера; ключ Тройки не использован.",
            }.get(code, message)
            state = (
                "interrupted"
                if continuation
                else "waiting_budget"
                if code
                in {"monthly_resource_exhausted", "resource_budget_approval_required"}
                else "failed"
            )
            reports.append({
                "id": len(reports) + 1,
                "text": message,
                "stage": state,
                "timestamp": time.time(),
            })
            adapter._set_run_status(
                run_id,
                state,
                stage=state,
                reports=reports[-40:],
                error={"code": code, "message": message},
            )
        finally:
            stopped.set()
            for worker in workers.values():
                if worker["status"] == "running":
                    worker["status"] = (
                        "completed"
                        if adapter._run_statuses[run_id]["status"] == "completed"
                        else "cancelled"
                    )
            adapter._active_run_agents.pop(run_id, None)
            adapter._active_run_tasks.pop(run_id, None)
            snapshot = adapter._run_statuses[run_id]
            try:
                sessions.state(principal, project_id, run_id, snapshot["status"])
            except PermissionError:
                pass
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({
                "event": "run." + snapshot["status"],
                "run_id": run_id,
                "artifact": snapshot.get("artifact"),
                "error": snapshot.get("error"),
            })
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)

    future = asyncio.create_task(run_and_close())
    adapter._active_run_tasks[run_id] = future
    adapter._background_tasks.add(future)
    future.add_done_callback(adapter._background_tasks.discard)
    return web.json_response(
        {"run_id": run_id, "session_id": session_id, "status": "queued"}, status=202
    )


def register_autopilot_routes(app, adapter):
    from troika_product.development_sessions import DevelopmentSessions, IDLE

    session_cache = None

    def store():
        nonlocal session_cache
        if session_cache is None:
            session_cache = DevelopmentSessions(adapter._access_registry)
        return session_cache

    def owned(request):
        denied = adapter._check_auth(request)
        if denied is not None:
            return denied, None, None
        principal = adapter._product_principal(request)
        if principal is None:
            return (
                error("product_identity_required", "Войдите в аккаунт.", 401),
                None,
                None,
            )
        try:
            record = store().get(principal, request.match_info["project_id"])
            return None, principal, record
        except PermissionError:
            return (
                error(
                    "project_unavailable", "Проект недоступен этому устройству.", 404
                ),
                None,
                None,
            )

    async def checkpoint_route(request):
        denied, principal, record = owned(request)
        if denied is not None:
            return denied
        project_id = record["id"]
        if request.method == "POST":
            try:
                body = await request.json()
                store().acknowledge(
                    principal, project_id, body.get("revision"), body.get("digest")
                )
            except (ValueError, AttributeError):
                return error(
                    "checkpoint_conflict",
                    "Контрольная копия изменилась. Получите новую версию.",
                    409,
                )
            return web.json_response({"ok": True})
        value = adapter.__dict__.get("_development_snapshots", {}).get(project_id)
        if value is None or value["expires_at"] <= time.time():
            return error(
                "device_checkpoint_required",
                "Продолжение доступно из локальной контрольной копии устройства.",
                404,
            )
        import base64
        from troika_product.development_sessions import checkpoint_bytes

        return web.json_response(
            {
                **value,
                "payload": base64.b64encode(
                    checkpoint_bytes(value["checkpoint"])
                ).decode(),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def control(request):
        denied, principal, record = owned(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            return error("invalid_control", "Некорректное действие.")
        action = body.get("action") if isinstance(body, dict) else None
        if action not in {"pause", "stop"}:
            return error("invalid_control", "Выберите паузу или остановку.")
        handle = adapter._active_run_agents.get(record["run_id"])
        if handle:
            if action == "pause" and hasattr(handle, "pause"):
                handle.pause()
            else:
                handle.interrupt("Project stop")
            adapter._set_run_status(
                record["run_id"],
                "pausing" if action == "pause" else "stopping",
                stage="pausing" if action == "pause" else "stopping",
            )
            # Let in-flight calls settle; cancellation cannot abort an SDK thread.
            return web.json_response(
                {"status": "pausing" if action == "pause" else "stopping"}, status=202
            )
        if record["state"] in {"completed", "failed", "cancelled"}:
            return web.json_response({"status": record["state"]})
        state = "paused" if action == "pause" else "cancelled"
        store().state(principal, record["id"], record["run_id"], state)
        snapshot = adapter._run_statuses.get(record["run_id"])
        if snapshot:
            adapter._set_run_status(record["run_id"], state, stage=state)
        return web.json_response({"status": state})

    async def resume_route(request):
        denied, principal, record = owned(request)
        if denied is not None:
            return denied
        if adapter._access_registry.subscription_summary(principal)["plan"] != "pro":
            return error(
                "development_pro_required", "Разработка доступна только в Pro.", 403
            )
        from troika_product.own_provider import current_credentials

        if record["personal_mode"] and current_credentials() is None:
            return error(
                "personal_key_required",
                "Для продолжения этого проекта нужен личный API-ключ. Ключ Тройки не использован.",
                409,
            )
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError()
            key = body.get("idempotency_key")
            if not isinstance(key, str) or not 8 <= len(key) <= 128:
                raise ValueError()
            request_hash = hashlib.sha256(
                json.dumps(
                    [record["id"], body], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
            previous = store().request(principal, key, request_hash)
            if previous:
                return web.json_response(
                    {
                        "run_id": previous["run_id"],
                        "project_id": previous["project_id"],
                        "status": adapter._run_statuses.get(previous["run_id"], {}).get(
                            "status", "interrupted"
                        ),
                    },
                    status=202,
                )
            state = body.get("checkpoint")
            budget = body.get("budget_tokens")
            from troika_product.development_sessions import checkpoint_bytes

            checkpoint_bytes(state)
            reuse_budget = body.get("reuse_budget") is True
            approved = True
            if reuse_budget:
                if record["state"] in {
                    "waiting_budget",
                    "failed",
                    "cancelled",
                    "completed",
                }:
                    raise ValueError()
                from troika_product.resource_runtime import configured_ledger

                ledger = configured_ledger(
                    adapter._access_registry,
                    getattr(adapter, "_product_resource_config", {}),
                )
                budget = record["budget_tokens"] - ledger.run_commitment(
                    principal, record["run_id"]
                )
                approved = bool(record["budget_approved"])
            if (
                type(budget) is not int
                or not (1 if reuse_budget else 10000) <= budget <= 250000
            ):
                raise ValueError()
            instruction = body.get("instruction", "")
            if not isinstance(instruction, str) or len(instruction) > 8000:
                raise ValueError()
            task = state["task"] + (
                "\n\nУточнение пользователя:\n" + instruction
                if instruction.strip()
                else ""
            )
            if len(task) > 20000:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            return error(
                "invalid_resume",
                "Проверьте локальную копию, уточнение и дополнительный бюджет от 10 000 до 250 000 AI-токенов.",
            )
        if (
            record["run_id"] not in adapter._run_statuses
            and record["state"] not in IDLE
        ):
            store().state(principal, record["id"], record["run_id"], "interrupted")
        request_body = {
            "input": task,
            "files": state["files"] or None,
            "title": body.get("title") or "Продолжение проекта",
            "free_only": True,
            "idempotency_key": body.get("idempotency_key"),
        }
        return await start_development_run(
            adapter,
            request,
            request_body,
            resume={
                "project_id": record["id"],
                "revision": body.get("revision"),
                "checkpoint": state,
                "budget_tokens": budget,
                "budget_approved": approved,
                "instruction": instruction,
                "request_hash": request_hash,
            },
        )

    async def projects(request):
        denied = adapter._check_auth(request)
        if denied is not None:
            return denied
        principal = adapter._product_principal(request)
        if principal is None:
            return error("product_identity_required", "Войдите в аккаунт.", 401)
        result = [
            value
            for run, value in adapter._run_statuses.items()
            if value.get("workflow") == "development"
            and adapter._run_owners.get(run) == (principal.user_id, principal.device_id)
        ]
        known = {value.get("project_id", value["run_id"]) for value in result}
        for record in store().list(principal):
            if record["id"] in known:
                for value in result:
                    if value.get("project_id", value["run_id"]) == record["id"]:
                        value.update(
                            checkpoint_revision=record["revision"],
                            checkpoint_digest=record["digest"],
                            checkpoint_confirmed=record["confirmed"],
                            budget_tokens=record["budget_tokens"],
                        )
                continue
            state = record["state"] if record["state"] in IDLE else "interrupted"
            result.append({
                "project_id": record["id"],
                "run_id": record["run_id"],
                "status": state,
                "stage": state,
                "created_at": record["created_at"],
                "checkpoint_revision": record["revision"],
                "checkpoint_digest": record["digest"],
                "checkpoint_confirmed": record["confirmed"],
                "recoverable": record["revision"] > 0,
                "reports": [],
                "workers": [],
            })
        # Only the latest attempt of each logical project is displayed.
        latest = {}
        for value in sorted(result, key=lambda v: v["created_at"]):
            latest[value.get("project_id", value["run_id"])] = value
        return web.json_response(
            {
                "enabled": adapter._access_registry.subscription_summary(principal)[
                    "plan"
                ]
                == "pro",
                "checkpoint_protocol": 1,
                "projects": sorted(
                    latest.values(), key=lambda v: v["created_at"], reverse=True
                )[:40],
            },
            headers={"Cache-Control": "no-store"},
        )

    app.router.add_get("/v1/development/projects", projects)
    app.router.add_get(
        "/v1/development/projects/{project_id}/checkpoint", checkpoint_route
    )
    app.router.add_post(
        "/v1/development/projects/{project_id}/checkpoint/received", checkpoint_route
    )
    app.router.add_post("/v1/development/projects/{project_id}/control", control)
    app.router.add_post("/v1/development/projects/{project_id}/resume", resume_route)
