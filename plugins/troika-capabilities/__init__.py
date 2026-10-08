"""Register the hosted product gateway through the generic plugin API."""


def register(ctx):
    from gateway.session_context import get_session_env
    from troika_product.capabilities import (
        CALL_SCHEMA, CALL_TOOL, ROUTER_TOOLSET, SEARCH_SCHEMA, SEARCH_TOOL,
        discover, execute,
    )

    def product_mode():
        return get_session_env("TROIKA_PRODUCT_MODE", "") == "1"

    product_mode._hermes_skip_availability_cache = True

    ctx.register_tool(name=SEARCH_TOOL, toolset=ROUTER_TOOLSET,
                      schema=SEARCH_SCHEMA, handler=discover, check_fn=product_mode)
    ctx.register_tool(name=CALL_TOOL, toolset=ROUTER_TOOLSET,
                      schema=CALL_SCHEMA, handler=execute, check_fn=product_mode)
