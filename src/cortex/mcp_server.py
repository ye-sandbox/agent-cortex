"""MCP server entrypoint for agent-cortex."""

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="cortex",
    instructions="agent-cortex: Cross-repository semantic memory and portfolio knowledge engine.",
)


@server.tool(name="cortex_version", description="Return agent-cortex version")
def cortex_version() -> str:
    """Return the active version of agent-cortex."""
    from cortex import __version__

    return f"agent-cortex v{__version__}"


def main() -> None:
    """Main entrypoint for cortex-mcp."""
    server.run("stdio")


if __name__ == "__main__":
    main()
