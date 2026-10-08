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
