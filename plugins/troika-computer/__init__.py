"""Expose the Computer Use pilots through Hermes' plugin API."""


def register(ctx):
    from troika_product.computer_agent import (
        ComputerAgentRun, SCHEMA, TOOL, TOOLSET, WINDOWS_TOOL,
        available_for, execute, execute_windows, windows_available,
    )
    from troika_product.computer_windows_browser import computer_schema

    ctx.register_tool(name=TOOL, toolset=TOOLSET, schema=SCHEMA, handler=execute,
                      check_fn=available_for(ComputerAgentRun.mode))
    ctx.register_tool(name=WINDOWS_TOOL, toolset=TOOLSET, schema=computer_schema(),
                      handler=execute_windows, check_fn=windows_available)
