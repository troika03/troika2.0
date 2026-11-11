"""Opt-in HTTP entry point for the synthetic Computer Use contract."""

import asyncio
import json

from troika_product.computer_control import ComputerControlError, ComputerDryRun


_MAX_BODY = 4096
_OPERATIONS = {"request", "review", "consent", "action", "stop"}


def _unique_keys(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate request field")
    return obj


def register_computer_dry_run_routes(app, adapter):
    if adapter._access_registry is None or not adapter._computer_dry_run_enabled:
        return
    from aiohttp import web

    def run_owner(run_id):
        status = adapter._run_statuses.get(run_id, {})
        task = adapter._active_run_tasks.get(run_id)
        if (task is not None and not task.done() and "workflow" not in status
                and status.get("status") in {"queued", "running", "waiting_for_approval"}):
            return adapter._run_owners.get(run_id)
        return None

    control = ComputerDryRun(adapter._access_registry, run_owner)
    adapter._computer_dry_run = control

    def response(payload, status=200):
        return web.json_response(payload, status=status, headers={"Cache-Control": "private, no-store"})

    async def pending(request):
        auth_error = adapter._check_auth(request)
        if auth_error is not None:
            return auth_error
        principal = adapter._product_principal(request)
        if principal is None:
            return response({"error": {"code": "authentication_required"}}, 401)
        try:
            return response(control.pending_for_device(principal))
        except ComputerControlError as exc:
            return response({"error": {"code": exc.code}}, exc.status)

    async def handle(request):
        auth_error = adapter._check_auth(request)
        if auth_error is not None:
            return auth_error
        principal = adapter._product_principal(request)
        if principal is None:
            return response({"error": {"code": "authentication_required"}}, 401)
        operation = request.match_info["operation"]
        if operation not in _OPERATIONS:
            return response({"error": {"code": "not_found"}}, 404)
        try:
            try:
                await request.content.readexactly(_MAX_BODY + 1)
            except asyncio.IncompleteReadError as exc:
                body = json.loads(exc.partial, object_pairs_hook=_unique_keys)
            else:
                return response({"error": {"code": "request_too_large"}}, 413)
        except (ValueError, RecursionError):
            return response({"error": {"code": "invalid_request"}}, 400)
        try:
            payload = control.execute(principal, request.match_info["run_id"], operation, body)
        except ComputerControlError as exc:
            return response({"error": {"code": exc.code}}, exc.status)
        return response(payload, 201 if operation == "request" else 200)

    async def cleanup(_app):
        control.clear()
        if adapter._computer_dry_run is control:
            adapter._computer_dry_run = None

    app.router.add_post("/v1/runs/{run_id}/computer-dry-run/{operation}", handle)
    app.router.add_get("/v1/computer-dry-run/requests", pending)
    app.on_cleanup.append(cleanup)
