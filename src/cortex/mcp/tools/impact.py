"""Impact analysis and blast radius simulation MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.models.impact import (
    BlastRadiusSimulationReport,
    ImpactTraceResult,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_impact_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register blast radius simulation and impact trace tools on MCPServer."""

    @server.tool(
        name="cortex_simulate_blast_radius",
        description=(
            "Simulate cross-repository change blast radius, evaluate architectural risk score, "
            "trace transitive caller chains, and synthesize AI agent planning advisories."
        ),
    )
    def cortex_simulate_blast_radius(
        repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        change_kind: str = "MODIFIED",
        max_depth: int = 5,
    ) -> BlastRadiusSimulationReport:
        """Simulate change blast radius and synthesize AI agent planning advisories."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.simulate_blast_radius(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                change_kind=change_kind,
                max_depth=max_depth,
            )

        client = ctx.create_in_process_client()
        return client.simulate_blast_radius(
            repo=repo,
            symbol=symbol,
            file_path=file_path,
            change_kind=change_kind,
            max_depth=max_depth,
        )

    @server.tool(
        name="cortex_trace_impact",
        description=(
            "Trace incoming transitive caller chains, impacted components, and circular "
            "dependency loops across portfolio repositories."
        ),
    )
    def cortex_trace_impact(
        repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        max_depth: int = 5,
    ) -> ImpactTraceResult:
        """Trace incoming transitive caller chains and cycle paths."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            chains, nodes, cycles = remote_client.trace_impact(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                max_depth=max_depth,
            )
        else:
            client = ctx.create_in_process_client()
            chains, nodes, cycles = client.trace_impact(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                max_depth=max_depth,
            )

        return ImpactTraceResult(
            target_repo=repo,
            symbol=symbol,
            file_path=file_path,
            total_chains=len(chains),
            caller_chains=chains,
            total_impacted_nodes=len(nodes),
            impacted_nodes=nodes,
            cycles_detected=cycles,
        )
