"""Register the hosted product gateway through the generic plugin API."""


def register(ctx):
    from gateway.session_context import get_session_env
    from troika_product.capabilities import (
        CALL_SCHEMA, CALL_TOOL, ROUTER_TOOLSET, SEARCH_SCHEMA, SEARCH_TOOL,
        discover, execute,
    )
    from troika_product.computer_agent import available as computer_run_bound

    def product_mode():
        return get_session_env("TROIKA_PRODUCT_MODE", "") == "1" and not computer_run_bound()

    product_mode._hermes_skip_availability_cache = True

    ctx.register_tool(name=SEARCH_TOOL, toolset=ROUTER_TOOLSET,
                      schema=SEARCH_SCHEMA, handler=discover, check_fn=product_mode)
    ctx.register_tool(name=CALL_TOOL, toolset=ROUTER_TOOLSET,
                      schema=CALL_SCHEMA, handler=execute, check_fn=product_mode)
    from troika_product.working_context import CONTEXT_SCHEMA, compact_enabled, context_tool

    def context_available():
        return product_mode() and compact_enabled() and get_session_env("TROIKA_CONTEXT_DISCOVERY", "") == "1"

    context_available._hermes_skip_availability_cache = True
    ctx.register_tool(name="troika_context", toolset=ROUTER_TOOLSET,
                      schema=CONTEXT_SCHEMA, handler=context_tool, check_fn=context_available)
