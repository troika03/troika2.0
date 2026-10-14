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


TERMINAL = {"completed", "failed", "cancelled"}


def error(code, message, status=400):
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


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
    active = sum(value.get("status") not in TERMINAL
                 for run, value in adapter._run_statuses.items()
                 if adapter._run_owners.get(run, (None,))[0] == principal.user_id)
    if active >= limit:
        return error("concurrent_runs_exhausted", "Активные задачи заняли слоты тарифа. Остановите задачу или дождитесь результата.", 429)
    return None


async def start_development_run(adapter, request, body, *, team_factory=DevelopmentTeam):
    principal = adapter._product_principal(request)
    if principal is None or adapter._access_registry is None:
        return error("product_identity_required", "Войдите в аккаунт.", 401)
    if adapter._access_registry.subscription_summary(principal)["plan"] != "pro":
        return error("development_pro_required", "Разработка доступна только в Pro.", 403)
    from troika_product.own_provider import current_credentials
    own = current_credentials()
    if own is not None and (own.provider != "openrouter" or not own.model.endswith(":free")):
        return error("development_free_model_required", "Автопилот использует только проверенные бесплатные модели. В личном API выберите подходящую модель :free или отключите личный API.")
    task = body.get("input")
    initial = body.get("files")
    key = body.get("idempotency_key")
    if (not isinstance(task, str) or not task.strip() or len(task) > 20000
            or not isinstance(key, str) or not 8 <= len(key) <= 128
            or body.get("free_only", True) is not True):
        return error("invalid_development_request", "Проверьте описание проекта. Этот автопилот использует только бесплатные модели.")
    try:
        _paths({"request.txt": task})
        if initial is not None:
            build_project({"files": initial})
            _paths({f["path"]: f["content"] for f in initial})
    except (ValueError, TypeError):
        return error("invalid_project_sources", "Проверьте пути, размер и отсутствие секретов в исходниках.")
    keys = adapter.__dict__.setdefault("_development_keys", {})
    identity = (principal.user_id, principal.device_id, key)
    digest = hashlib.sha256(json.dumps([task, initial], ensure_ascii=False).encode()).hexdigest()
    if identity in keys:
        run_id, previous = keys[identity]
        if previous != digest:
            return error("idempotency_conflict", "Повторный запрос изменился.", 409)
        if run_id in adapter._run_statuses:
            return web.json_response({"run_id": run_id, "status": adapter._run_statuses[run_id]["status"]}, status=202)
        keys.pop(identity)
    for old, (run_id, _) in list(keys.items()):
        if run_id not in adapter._run_statuses:
            keys.pop(old, None)
    active = [run for run, value in adapter._run_statuses.items()
              if value.get("status") not in TERMINAL]
    background = [run for run in active if adapter._run_owners.get(run, (None,))[0] == principal.user_id
                  and adapter._run_statuses[run].get("workflow") == "development"]
    owner_active = [run for run in active if adapter._run_owners.get(run, (None,))[0] == principal.user_id]
    if len(background) >= 4 or len(owner_active) >= 5 or len(active) >= adapter._MAX_CONCURRENT_RUNS - 1:
        return error("development_capacity", "Фоновые слоты заняты. Один слот сохраняется для разговора.", 429)
    quota = adapter._consume_product_request_quota(request)
    if quota is not None:
        return quota
    run_id = "run_" + uuid.uuid4().hex
    session_id = "development-" + uuid.uuid4().hex
    denied = adapter._authorize_product_session(request, session_id, claim=True)
    if denied is not None:
        return denied
    keys[identity] = (run_id, digest)
    loop = asyncio.get_running_loop()
    stopped = threading.Event()
    workers = {}
    reports = []
    queue = asyncio.Queue(maxsize=256)
    adapter._run_streams[run_id] = queue
    adapter._run_streams_created[run_id] = time.time()
    adapter._run_owners[run_id] = (principal.user_id, principal.device_id)
    title = str(body.get("title") or "Проект")[:100]
    adapter._set_run_status(run_id, "queued", session_id=session_id, workflow="development",
                            title=title, stage="queued", workers=[], reports=[], free_only=True)

    def cancelled():
        if stopped.is_set():
            return True
        try:
            return adapter._access_registry.subscription_summary(principal)["plan"] != "pro"
        except (PermissionError, ValueError):
            return True

    def progress(**event):
        def update():
            if stopped.is_set() or adapter._run_statuses[run_id]["status"] in TERMINAL:
                return
            worker_id = event.get("worker_id")
            if worker_id:
                workers[worker_id] = {"id": worker_id, "role": event["role"],
                                      "status": event["worker_state"], "task": event["message"][:200]}
            if event.get("report"):
                reports.append({"id": len(reports) + 1, "text": event["report"][:500],
                                "stage": event["stage"], "timestamp": time.time()})
            adapter._set_run_status(run_id, "running", stage=event["stage"],
                                    message=event["message"][:200], workers=list(workers.values())[-80:],
                                    reports=reports[-40:], api_calls=event["calls"])
            if not queue.full():
                queue.put_nowait({"event": "development.progress", "run_id": run_id,
                                  "stage": event["stage"]})
        loop.call_soon_threadsafe(update)

    team = team_factory(cancelled=cancelled, progress=progress, max_workers=3)
    class Handle:
        def interrupt(self, reason=""):
            stopped.set()
    adapter._active_run_agents[run_id] = Handle()

    def execute():
        scope = getattr(adapter, "_resource_call_scope", lambda *a: nullcontext())(principal, run_id)
        with scope:
            return team.run(task, initial)

    async def run_and_close():
        try:
            result = await asyncio.to_thread(execute)
            if cancelled():
                raise InterruptedError()
            kind, mime = "zip", "application/zip"
            if result.get("document"):
                from troika_product.document_generation import generate_docx, generate_pptx
                kind = result["document"]["kind"]
                args = DevelopmentTeam.document_args(kind, result["document"]["args"])
                data = (generate_pptx if kind == "pptx" else generate_docx)(args)
                mime = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[kind]
            else:
                data, _ = build_project({"title": title, **result}, require_complete=True)
            if cancelled():
                raise InterruptedError()
            artifact = device_deliveries.create(principal.user_id, principal.device_id, title,
                                                kind, mime, data)
            report = ("Проект создан. " if result["review"]["status"] == "passed" else "Черновик создан. ") + (
                "Ревью не нашло блокирующих ошибок. " if result["review"]["status"] == "passed"
                else "Остались блокирующие замечания; они записаны в отчёте. ") + "Тесты не запускались. Результат готов к скачиванию."
            reports.append({"id": len(reports) + 1, "text": report, "stage": "completed", "timestamp": time.time()})
            adapter._set_run_status(run_id, "completed", stage="completed", artifact=artifact,
                                    reports=reports[-40:], review=result["review"],
                                    file_count=len(result["files"]), execution="not_run")
        except (asyncio.CancelledError, InterruptedError):
            stopped.set()
            reports.append({"id": len(reports) + 1, "text": "Проект остановлен. Новые обращения к моделям не отправляются.",
                            "stage": "cancelled", "timestamp": time.time()})
            adapter._set_run_status(run_id, "cancelled", stage="cancelled",
                                    reports=reports[-40:],
                                    message="Остановлено. Новые вызовы моделей не отправляются.")
        except Exception as exc:
            # Never expose provider request bodies or API keys to clients/logs.
            code = getattr(exc, "code", None)
            if not isinstance(code, str) or code not in {"monthly_resource_exhausted", "resource_budget_approval_required",
                            "resource_price_unavailable", "resource_usage_unknown", "resource_byok_request_failed"}:
                code = "development_failed"
            message = ("Бесплатная модель временно недоступна. Платный вызов не выполнен."
                       if getattr(exc, "status_code", None) in {404, 429, 503}
                       else "Автопилот не завершил проект. Результат не объявлен проверенным.")
            message = {
                "monthly_resource_exhausted": "Месячных AI-токенов не хватает. Проект остановлен до новых обращений к модели.",
                "resource_budget_approval_required": "Достигнут предел AI-токенов задачи. Проект остановлен; продолжение с новым бюджетом пока недоступно.",
                "resource_price_unavailable": "Учёт бесплатного автопилота ещё не настроен. Проект остановлен до вызова модели.",
                "resource_usage_unknown": "Провайдер не подтвердил расход токенов. Новые обращения остановлены до сверки.",
                "resource_byok_request_failed": "Личный API не выполнил запрос. Проверь ключ, бесплатную модель и лимит провайдера; ключ Тройки не использован.",
            }.get(code, message)
            reports.append({"id": len(reports) + 1, "text": message, "stage": "failed", "timestamp": time.time()})
            adapter._set_run_status(run_id, "failed", stage="failed", reports=reports[-40:],
                                    error={"code": code, "message": message})
        finally:
            stopped.set()
            for worker in workers.values():
                if worker["status"] == "running":
                    worker["status"] = "completed" if adapter._run_statuses[run_id]["status"] == "completed" else "cancelled"
            adapter._active_run_agents.pop(run_id, None)
            adapter._active_run_tasks.pop(run_id, None)
            snapshot = adapter._run_statuses[run_id]
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({"event": "run." + snapshot["status"], "run_id": run_id,
                              "artifact": snapshot.get("artifact"), "error": snapshot.get("error")})
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)

    future = asyncio.create_task(run_and_close())
    adapter._active_run_tasks[run_id] = future
    adapter._background_tasks.add(future)
    future.add_done_callback(adapter._background_tasks.discard)
    return web.json_response({"run_id": run_id, "session_id": session_id, "status": "queued"}, status=202)


def register_autopilot_routes(app, adapter):
    async def projects(request):
        denied = adapter._check_auth(request)
        if denied is not None:
            return denied
        principal = adapter._product_principal(request)
        if principal is None:
            return error("product_identity_required", "Войдите в аккаунт.", 401)
        result = [value for run, value in adapter._run_statuses.items()
                  if value.get("workflow") == "development"
                  and adapter._run_owners.get(run) == (principal.user_id, principal.device_id)]
        return web.json_response({"enabled": adapter._access_registry.subscription_summary(principal)["plan"] == "pro",
                                  "projects": sorted(result, key=lambda v: v["created_at"], reverse=True)[:40]})
    app.router.add_get("/v1/development/projects", projects)
