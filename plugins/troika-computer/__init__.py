"""Expose the Computer Use pilots through Hermes' plugin API."""


def register(ctx):
    from functools import partial
    from troika_product.computer_agent import (
        ComputerAgentRun, SCHEMA, TOOL, TOOLSET, WINDOWS_SCHEMA, WINDOWS_TOOL,
        WindowsEditorAgentRun, available_for, execute,
    )

    ctx.register_tool(name=TOOL, toolset=TOOLSET, schema=SCHEMA, handler=execute,
                      check_fn=available_for(ComputerAgentRun.mode))
    ctx.register_tool(name=WINDOWS_TOOL, toolset=TOOLSET, schema=WINDOWS_SCHEMA,
                      handler=partial(execute, mode=WindowsEditorAgentRun.mode),
                      check_fn=available_for(WindowsEditorAgentRun.mode))
