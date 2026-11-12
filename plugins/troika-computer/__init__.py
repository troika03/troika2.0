"""Expose the Computer Use pilots through Hermes' plugin API."""


def register(ctx):
    from functools import partial
    from troika_product.computer_agent import (
        ComputerAgentRun, SCHEMA, TOOL, TOOLSET, WINDOWS_SCHEMA, WINDOWS_TOOL,
        WindowsBrowserAgentRun, WindowsEditorAgentRun, available_for, execute,
    )
    from troika_product.computer_windows_browser import TOOL as BROWSER_TOOL, browser_schema

    ctx.register_tool(name=TOOL, toolset=TOOLSET, schema=SCHEMA, handler=execute,
                      check_fn=available_for(ComputerAgentRun.mode))
    ctx.register_tool(name=WINDOWS_TOOL, toolset=TOOLSET, schema=WINDOWS_SCHEMA,
                      handler=partial(execute, mode=WindowsEditorAgentRun.mode),
                      check_fn=available_for(WindowsEditorAgentRun.mode))
    ctx.register_tool(name=BROWSER_TOOL, toolset=TOOLSET, schema=browser_schema(),
                      handler=partial(execute, mode=WindowsBrowserAgentRun.mode),
                      check_fn=available_for(WindowsBrowserAgentRun.mode))
