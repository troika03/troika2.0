"""Authenticated HTTP routes for the opt-in Computer Use pilots."""

import asyncio
from functools import partial
import json
import struct

from troika_product.computer_control import ComputerControlError, ComputerDryRun


_MAX_BODY = 4096
_GRANT_OPERATIONS = {"request", "review", "consent", "stop"}


def _unique_keys(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate request field")
    return obj


def register_computer_dry_run_routes(app, adapter):
    if adapter._access_registry is None or not adapter._computer_dry_run_enabled:
        return
    _register_routes(app, adapter, "_computer_dry_run", "computer-dry-run",
                     ComputerDryRun, _GRANT_OPERATIONS | {"action"})


def register_windows_computer_lab_routes(app, adapter):
    if (adapter._access_registry is None or not adapter._computer_windows_lab_enabled
            or adapter._host != "127.0.0.1"):
        return
    from troika_product.computer_windows_lab import MODE, WindowsComputerLab

    _register_routes(app, adapter, "_computer_windows_lab", "computer-windows-lab",
                     WindowsComputerLab, _GRANT_OPERATIONS | {"take", "report"}, mode=MODE)


def register_windows_browser_routes(app, adapter):
    if (adapter._access_registry is None or not adapter._computer_windows_browser_enabled
            or adapter._host != "127.0.0.1"):
        return
    from hermes_cli.config import get_env_value
    from troika_product.computer_openrouter_vision import OpenRouterVision
    from troika_product.computer_windows_browser import MODE, WindowsBrowserLab

    try:
        openrouter = OpenRouterVision(adapter._computer_windows_browser_model, get_env_value("OPENROUTER_API_KEY"))
    except ValueError:
        return
    _register_routes(app, adapter, "_computer_windows_browser", "computer-windows-browser",
                     partial(WindowsBrowserLab, openrouter=openrouter),
                     _GRANT_OPERATIONS | {"take", "report"}, mode=MODE)


def register_windows_computer_vision_routes(app, adapter):
    if (adapter._access_registry is None or not adapter._computer_windows_vision_enabled
            or adapter._host != "127.0.0.1"):
        return
    from troika_product.computer_windows_vision import MODE, WindowsVisionLab

    adapter._computer_windows_vision_config_error = False
    openrouter = None
    if adapter._computer_windows_vision_fixture and adapter._computer_windows_vision_model is not None:
        adapter._computer_windows_vision_config_error = True
        return
    if not adapter._computer_windows_vision_fixture:
        from hermes_cli.config import get_env_value
        from troika_product.computer_openrouter_vision import OpenRouterVision

        try:
            openrouter = OpenRouterVision(adapter._computer_windows_vision_model, get_env_value("OPENROUTER_API_KEY"))
        except ValueError:
            adapter._computer_windows_vision_config_error = True
            return
    _register_routes(app, adapter, "_computer_windows_vision", "computer-windows-vision",
                     partial(WindowsVisionLab, openrouter=openrouter), _GRANT_OPERATIONS | {"frame"}, mode=MODE)
    if openrouter is not None and adapter._computer_windows_lab_enabled:
        from troika_product.computer_windows_assisted import MODE as ASSISTED_MODE, WindowsAssistedLab

        _register_routes(app, adapter, "_computer_windows_assisted", "computer-windows-assisted",
                         partial(WindowsAssistedLab, openrouter=openrouter),
                         _GRANT_OPERATIONS | {"approve_frame", "frame", "take", "report"}, mode=ASSISTED_MODE)


async def _receive_frame(request, control, principal):
    from troika_product.computer_control import MAX_OBSERVATION_SECONDS
    from troika_product.computer_frames import MAX_FRAME_BYTES, clean_png

    run_id = request.match_info["run_id"]
    header = request.headers.get("X-Troika-Frame-Remaining-Ms", "")
    if (request.content_type != "image/png" or "Content-Encoding" in request.headers
            or not request.content_length or request.content_length > MAX_FRAME_BYTES
            or not 1 <= len(header) <= 5 or not header.isascii() or not header.isdecimal()):
        raise ComputerControlError("invalid_frame", 400)
    remaining_ms = int(header)
    if not 1 <= remaining_ms <= MAX_OBSERVATION_SECONDS * 1000:
        raise ComputerControlError("invalid_frame", 400)
    body = {"version": 1, "grant_id": request.headers.get("X-Troika-Grant-Id")}
    now = control.execute(principal, run_id, "check_frame", body)
    try:
        try:
            raw = await asyncio.wait_for(request.content.readexactly(request.content_length), timeout=remaining_ms / 1000)
            frame = await asyncio.to_thread(clean_png, raw)
        except (OSError, ValueError, SyntaxError, struct.error, asyncio.IncompleteReadError, asyncio.TimeoutError):
            raise ComputerControlError("invalid_frame", 400) from None
        return control.execute(principal, run_id, "frame", {**body, "frame": frame,
                                                            "expires_at": now + remaining_ms / 1000})
    finally:
        control.release_upload(principal, run_id, body["grant_id"])


def _register_routes(app, adapter, attribute, path, factory, operations, *, mode=None):
    from aiohttp import web

    def run_owner(run_id):
        status = adapter._run_statuses.get(run_id, {})
        task = adapter._active_run_tasks.get(run_id)
        # The simulation also supports ordinary test Runs. A native grant
        # must belong to a Run that opted into that same native mode.
        if mode is not None and status.get("mode") != mode:
            return None
        if mode is None and status.get("mode") in {
            "windows_lab", "windows_vision_lab", "windows_assisted_lab", "windows_browser_lab",
        }:
            return None
        if (task is not None and not task.done() and "workflow" not in status
                and status.get("status") in {"queued", "running", "waiting_for_approval"}):
            return adapter._run_owners.get(run_id)
        return None

    control = factory(adapter._access_registry, run_owner)
    setattr(adapter, attribute, control)

    def response(payload, status=200):
        return web.json_response(payload, status=status, headers={"Cache-Control": "private, no-store"})

    async def pending(request):
        if mode is not None and request.remote != "127.0.0.1":
            return response({"error": {"code": "not_found"}}, 404)
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
        if mode is not None and request.remote != "127.0.0.1":
            return response({"error": {"code": "not_found"}}, 404)
        auth_error = adapter._check_auth(request)
        if auth_error is not None:
            return auth_error
        principal = adapter._product_principal(request)
        if principal is None:
            return response({"error": {"code": "authentication_required"}}, 401)
        operation = request.match_info["operation"]
        if operation not in operations:
            return response({"error": {"code": "not_found"}}, 404)
        if operation == "frame":
            try:
                return response(await _receive_frame(request, control, principal))
            except ComputerControlError as exc:
                return response({"error": {"code": exc.code}}, exc.status)
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
        if getattr(adapter, attribute) is control:
            setattr(adapter, attribute, None)

    app.router.add_post(f"/v1/runs/{{run_id}}/{path}/{{operation}}", handle)
    app.router.add_get(f"/v1/{path}/requests", pending)
    app.on_cleanup.append(cleanup)
