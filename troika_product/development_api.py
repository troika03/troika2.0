"""HTTP relay for local development checks, with no server code execution."""
from aiohttp import web

from troika_product.development_checks import development_checks


def register_development_routes(app, adapter, *, store=development_checks):
    async def body_json(request):
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest()
        return body

    def identity(request):
        error = adapter._check_auth(request)
        if error is not None:
            raise web.HTTPUnauthorized()
        principal = adapter._product_principal(request)
        if principal is None or adapter._access_registry is None:
            raise web.HTTPForbidden()
        return principal

    async def targets(request):
        principal = identity(request)
        devices = adapter._access_registry.list_devices(principal)
        return web.json_response({"devices": [device.to_dict() for device in devices
            if device.status == "active" and device.platform == "windows"
            and store.available(principal.user_id, device.id)]})

    async def worker(request):
        principal = identity(request)
        devices = adapter._access_registry.list_devices(principal)
        device = next((d for d in devices if d.current), None)
        if device is None or device.platform != "windows":
            raise web.HTTPForbidden()
        body = await body_json(request)
        if type(body.get("enabled")) is not bool:
            raise web.HTTPBadRequest()
        store.heartbeat(principal.user_id, principal.device_id, body["enabled"])
        return web.json_response({"job": store.claim(principal.user_id, principal.device_id)
                                  if body["enabled"] and body.get("claim", True) is True else None})

    async def jobs(request):
        principal = identity(request)
        job_id = request.match_info.get("check_id")
        if job_id:
            if request.method == "DELETE":
                if not store.cancel(principal.user_id, principal.device_id, job_id):
                    raise web.HTTPNotFound()
                return web.json_response({"state": "cancelled"})
            job = store.get(principal.user_id, principal.device_id, job_id)
            if job is None:
                raise web.HTTPNotFound()
            return web.json_response(job)
        body = await body_json(request)
        target = body.get("target_device_id")
        devices = adapter._access_registry.list_devices(principal)
        if not any(d.id == target and d.status == "active" and d.platform == "windows" for d in devices):
            raise web.HTTPNotFound()
        try:
            result = store.create(principal.user_id, principal.device_id, target, body.get("mode"), body.get("files"), body.get("workflow_id"))
        except (ValueError, TypeError):
            return web.json_response({"error": "check_unavailable_or_invalid"}, status=400)
        return web.json_response(result, status=202)

    async def report(request):
        principal = identity(request)
        body = await body_json(request)
        try:
            accepted = store.finish(principal.user_id, principal.device_id, request.match_info["check_id"],
                                    body.get("lease"), body.get("report"))
        except ValueError:
            raise web.HTTPBadRequest()
        if not accepted:
            raise web.HTTPConflict()
        return web.json_response({"accepted": True})

    app.router.add_get("/v1/development/devices", targets)
    app.router.add_post("/v1/development/worker", worker)
    app.router.add_post("/v1/development/checks", jobs)
    app.router.add_get("/v1/development/checks/{check_id}", jobs)
    app.router.add_delete("/v1/development/checks/{check_id}", jobs)
    app.router.add_post("/v1/development/checks/{check_id}/report", report)
