"""Model Context Protocol (MCP) server for agent-cortex."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig
from cortex.mcp.context import ServerContext
from cortex.mcp.tools import (
    register_drift_tools,
    register_evolution_tools,
    register_graph_tools,
    register_impact_tools,
    register_intent_tools,
    register_retrieval_tools,
    register_topology_tools,
)
from cortex.mcp.tools.retrieval import cortex_version
from cortex.models.chunk import (
    CompactSearchResult,
    RepoContractChunk,
    TechSummary,
    TechUsage,
)
from cortex.models.intent import (
    ChangeIntentSimulationReport,
    RepoMigrationPatch,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

__all__ = [
    "ChangeIntentSimulationReport",
    "CompactSearchResult",
    "RepoContractChunk",
    "RepoMigrationPatch",
    "ServerContext",
    "TechSummary",
    "TechUsage",
    "cortex_version",
    "create_cortex_mcp_server",
    "main",
    "register_drift_tools",
    "register_evolution_tools",
    "register_graph_tools",
    "register_impact_tools",
    "register_intent_tools",
    "register_retrieval_tools",
    "register_topology_tools",
    "server",
]


def create_cortex_mcp_server(
    config: CortexConfig | None = None,
    pipeline: HybridRetrievalPipeline | None = None,
    storage: StorageManager | None = None,
    client: CortexClient | None = None,
) -> MCPServer:
    """Factory creating configured MCPServer with all cortex tools registered."""
    server = MCPServer(
        name="cortex",
        instructions=(
            "agent-cortex: Cross-repository semantic memory and portfolio knowledge engine. "
            "Use cortex_search to find relevant documentation and code contracts, "
            "cortex_get_repo_contracts to inspect OpenAPI routes and Compose services for a repo, "
            "and cortex_list_technologies to discover technology stacks across repositories."
        ),
    )
    ctx = ServerContext(
        config=config,
        pipeline=pipeline,
        storage=storage,
        client=client,
    )

    register_retrieval_tools(server, ctx)
    register_graph_tools(server, ctx)
    register_drift_tools(server, ctx)
    register_topology_tools(server, ctx)
    register_impact_tools(server, ctx)
    register_evolution_tools(server, ctx)
    register_intent_tools(server, ctx)

    return server


# Global default server instance
server: MCPServer = create_cortex_mcp_server()


def main() -> None:
    """Main entrypoint for cortex-mcp."""
    server.run("stdio")


if __name__ == "__main__":
    main()
