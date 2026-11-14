"""HTTP handlers for the owner's capability preferences."""

import asyncio

from troika_product.capabilities import (
    CapabilityStore, available_schemas, catalogue, catalogue_context,
)


class CapabilityAPI:
    async def _handle_product_capabilities(self, request):
        from aiohttp import web

        auth_error = self._check_auth(request)
        if auth_error is not None:
            return auth_error
        principal = self._product_principal(request)
        if principal is None:
            return web.json_response({"error": {"message": "Product account required"}}, status=404)
        patch = None
        if request.method == "PATCH":
            try:
                body = await request.json()
                if (not isinstance(body, dict) or set(body) != {"enabled"}
                        or not isinstance(body["enabled"], dict)):
                    raise ValueError("expected enabled patch")
                patch = body["enabled"]
            except (ValueError, TypeError, UnicodeError):
                return web.json_response({"error": {"message": "Invalid capability preferences"}}, status=400)

        def read():
            store = CapabilityStore(self._access_registry)
            preferences = store.update(principal, patch) if patch is not None else store.preferences(principal)
            with catalogue_context(self, principal):
                return catalogue(preferences, available_schemas())
        try:
            payload = await asyncio.to_thread(read)
        except PermissionError:
            return web.json_response({"error": {"message": "Active account required"}}, status=401)
        except (ValueError, TypeError):
            return web.json_response({"error": {"message": "Invalid capability preferences"}}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def _handle_product_extensions(self, request):
        """GET/PATCH /v1/account/extensions — skills, MCP and tools for the menu.

        PATCH accepts one of ``{"skills"|"mcp"|"capabilities": {id: bool}}``.
        Only reviewed cloud skills and MCP servers can be connected.
        """
        from aiohttp import web
        from troika_product.extensions import (
            ExtensionStore, connected_services, extension_catalogue, extensions_allowed,
        )

        auth_error = self._check_auth(request)
        if auth_error is not None:
            return auth_error
        principal = self._product_principal(request)
        if principal is None:
            return web.json_response({"error": {"message": "Product account required"}}, status=404)
        skills_patch = capability_patch = mcp_patch = None
        if request.method == "PATCH":
            try:
                body = await request.json()
                if (not isinstance(body, dict) or len(body) != 1
                        or not set(body) <= {"skills", "mcp", "capabilities"}
                        or not isinstance(next(iter(body.values())), dict)):
                    raise ValueError("expected skills or capabilities patch")
                skills_patch = body.get("skills")
                capability_patch = body.get("capabilities")
                mcp_patch = body.get("mcp")
            except (ValueError, TypeError, UnicodeError):
                return web.json_response({"error": {"message": "Invalid extension preferences"}}, status=400)

        def read():
            store = CapabilityStore(self._access_registry)
            extensions = ExtensionStore(self._access_registry)
            allowed = extensions_allowed(self._access_registry, principal)
            connecting = [value for patch in (skills_patch, mcp_patch) if patch
                          for value in patch.values()]
            if not allowed and any(value is True for value in connecting):
                raise ArithmeticError("pro required")
            if capability_patch is not None:
                preferences = store.update(principal, capability_patch)
            else:
                preferences = store.preferences(principal)
            if skills_patch is not None:
                try:
                    connected = extensions.update(principal, skills_patch)
                except PermissionError as error:
                    raise LookupError(str(error)) from error
            else:
                connected = extensions.connected(principal)
            servers = ExtensionStore(self._access_registry, "mcp")
            if mcp_patch is not None:
                # Account services connect through /services/{id}/connect; the
                # patch may only disconnect them.
                from troika_product.extensions import service_mcp
                services_patch = {key: value for key, value in mcp_patch.items() if service_mcp(key)}
                public_patch = {key: value for key, value in mcp_patch.items() if key not in services_patch}
                if any(value is not False for value in services_patch.values()):
                    raise LookupError("account services connect through sign-in")
                for key in services_patch:
                    _disconnect_service(principal.user_id, key)
                try:
                    connected_mcp = (servers.update(principal, public_patch) if public_patch
                                     else servers.connected(principal))
                except PermissionError as error:
                    raise LookupError(str(error)) from error
            else:
                connected_mcp = servers.connected(principal)
            with catalogue_context(self, principal):
                tools = catalogue(preferences, available_schemas())
            return extension_catalogue(connected, tools, connected_mcp,
                                       connected_services(principal.user_id), allowed)
        try:
            payload = await asyncio.to_thread(read)
        except ArithmeticError:
            return web.json_response({"error": {"message": "Скиллы и MCP доступны в тарифе Pro"}}, status=402)
        except LookupError:
            return web.json_response(
                {"error": {"message": "Это нельзя подключить в облаке Тройки"}}, status=403)
        except PermissionError:
            return web.json_response({"error": {"message": "Active account required"}}, status=401)
        except (ValueError, TypeError):
            return web.json_response({"error": {"message": "Invalid extension preferences"}}, status=400)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    def _service_owner(self, request):
        from aiohttp import web
        auth_error = self._check_auth(request)
        if auth_error is not None:
            return None, auth_error
        principal = self._product_principal(request)
        if principal is None:
            return None, web.json_response({"error": {"message": "Product account required"}}, status=404)
        return principal, None

    async def _handle_service_connect(self, request):
        """POST /v1/account/services/{id}/connect — token or OAuth sign-in."""
        from aiohttp import web
        from troika_product import mcp_connector, service_connections
        from troika_product.extensions import ExtensionStore, service_mcp

        principal, error = self._service_owner(request)
        if error is not None:
            return error
        entry = service_mcp(request.match_info.get("server_id"))
        if entry is None:
            return web.json_response({"error": {"message": "Сервис не найден"}}, status=404)
        current = service_connections.config()
        if not current.enabled or (entry["connect"] == "oauth" and not current.redirect_uri):
            return web.json_response(
                {"error": {"message": "Подключение сервисов пока не включено на сервере Тройки"}}, status=503)
        try:
            # Fails closed for a revoked device or a deleted account.
            await asyncio.to_thread(ExtensionStore(self._access_registry, "mcp").connected, principal)
        except PermissionError:
            return web.json_response({"error": {"message": "Active account required"}}, status=401)
        from troika_product.extensions import extensions_allowed
        if not await asyncio.to_thread(extensions_allowed, self._access_registry, principal):
            return web.json_response({"error": {"message": "Скиллы и MCP доступны в тарифе Pro"}}, status=402)
        if entry["connect"] == "token":
            try:
                body = await request.json()
            except (ValueError, UnicodeError):
                body = None
            token = body.get("token") if isinstance(body, dict) and set(body) == {"token"} else None
            if not service_connections.valid_token(token):
                return web.json_response({"error": {"message": "Вставьте токен без пробелов"}}, status=400)
            try:
                await asyncio.wait_for(mcp_connector.probe_async(
                    entry, headers={"Authorization": f"Bearer {token}"}), 30)
            except Exception:
                return web.json_response(
                    {"error": {"message": "Сервис не принял токен. Проверьте права и срок действия."}}, status=400)
            await asyncio.to_thread(current.store.save, principal.user_id, entry["id"], "token", {"token": token})
            mcp_connector.forget(principal.user_id, entry["id"])
            return web.json_response({"status": "connected"}, headers={"Cache-Control": "no-store"})
        try:
            flow_id, url = await service_connections.start_oauth(
                entry, principal.user_id,
                lambda target, auth: mcp_connector.probe_async(target, auth=auth))
        except Exception:
            return web.json_response(
                {"error": {"message": "Сервис сейчас не начал вход. Попробуйте позже."}}, status=502)
        mcp_connector.forget(principal.user_id, entry["id"])
        return web.json_response({"status": "waiting", "flow": flow_id, "authorization_url": url},
                                 headers={"Cache-Control": "no-store"})

    async def _handle_service_flow(self, request):
        """GET /v1/account/services/flows/{flow_id} — sign-in progress."""
        from aiohttp import web
        from troika_product import service_connections
        principal, error = self._service_owner(request)
        if error is not None:
            return error
        status = service_connections.flow_status(request.match_info.get("flow_id", ""), principal.user_id)
        return web.json_response({"status": status or "expired"}, headers={"Cache-Control": "no-store"})

    async def _handle_service_disconnect(self, request):
        """DELETE /v1/account/services/{id} — forget the stored connection."""
        from aiohttp import web
        from troika_product.extensions import service_mcp
        principal, error = self._service_owner(request)
        if error is not None:
            return error
        server_id = request.match_info.get("server_id")
        if service_mcp(server_id) is None:
            return web.json_response({"error": {"message": "Сервис не найден"}}, status=404)
        await asyncio.to_thread(_disconnect_service, principal.user_id, server_id)
        return web.json_response({"status": "disconnected"}, headers={"Cache-Control": "no-store"})

    async def _handle_service_callback(self, request):
        """GET /v1/account/services/oauth/callback — browser return from the service.

        No account header exists here; the single-use ``state`` binds the
        result to one pending flow of one owner.
        """
        from aiohttp import web
        from troika_product import service_connections
        accepted = service_connections.complete_oauth(
            request.query.get("state", ""), request.query.get("code"), request.query.get("error"))
        text = ("Готово. Вернитесь в Тройку — подключение завершится через несколько секунд."
                if accepted else "Вход не завершён. Вернитесь в Тройку и попробуйте ещё раз.")
        page = ('<!doctype html><html lang="ru"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width"><title>Тройка</title>'
                f"<body><p>{text}</p></body></html>")
        return web.Response(text=page, content_type="text/html", status=200 if accepted else 400,
                            headers={"Cache-Control": "no-store"})


def _disconnect_service(user_id: str, server_id: str) -> None:
    from troika_product import mcp_connector, service_connections
    current = service_connections.config()
    if current.enabled:
        current.store.delete(user_id, server_id)
    mcp_connector.forget(user_id, server_id)
