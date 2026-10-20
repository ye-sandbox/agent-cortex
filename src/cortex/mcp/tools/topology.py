"""Portfolio topology and dependency matrix MCP tool registry."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cortex.models.topology import (
    PortfolioDependencyMatrix,
    PortfolioTopologyGraph,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_topology_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register portfolio topology and dependency matrix tools on MCPServer."""

    @server.tool(
        name="cortex_get_portfolio_topology",
        description=(
            "Synthesize and visualize cross-repository portfolio topology, coupling metrics "
            "(Ca, Ce, instability), and architectural graphs "
            "(Mermaid flowchart, DOT, or Cytoscape)."
        ),
    )
    def cortex_get_portfolio_topology(
        format: str = "mermaid",
        direction: str = "LR",
        include_internal: bool = False,
        min_weight: int = 1,
    ) -> str:
        """Query portfolio architecture topology graph and metrics."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            res = remote_client.get_portfolio_topology(
                format=format,
                direction=direction,
                include_internal=include_internal,
                min_weight=min_weight,
            )
        else:
            client = ctx.create_in_process_client()
            res = client.get_portfolio_topology(
                format=format,
                direction=direction,
                include_internal=include_internal,
                min_weight=min_weight,
            )

        if isinstance(res, PortfolioTopologyGraph):
            return json.dumps(res.model_dump(mode="json"), indent=2)
        if isinstance(res, dict):
            return json.dumps(res, indent=2)
        return str(res)

    @server.tool(
        name="cortex_get_dependency_matrix",
        description=(
            "Synthesize cross-repository dependency NxN matrix, architectural coupling metrics "
            "(Afferent Ca, Efferent Ce, Instability), and circular dependency warnings."
        ),
    )
    def cortex_get_dependency_matrix(
        min_weight: int = 0,
    ) -> PortfolioDependencyMatrix:
        """Query cross-repository dependency NxN matrix and coupling metrics."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependency_matrix(min_weight=min_weight)

        client = ctx.create_in_process_client()
        return client.get_dependency_matrix(min_weight=min_weight)
