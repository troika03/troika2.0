"""Expose the simulator through Hermes' plugin API."""


def register(ctx):
    from troika_product.computer_agent import SCHEMA, TOOL, TOOLSET, available, execute

    ctx.register_tool(name=TOOL, toolset=TOOLSET, schema=SCHEMA, handler=execute, check_fn=available)
