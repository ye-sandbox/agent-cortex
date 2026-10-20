"""Contract drift audit MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.models.drift import ContractDriftReport

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_drift_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register contract drift audit tools on MCPServer."""

    @server.tool(
        name="cortex_get_contract_drift",
        description=(
            "Audit architectural contract drift and breaking changes across portfolio "
            "repositories (OpenAPI routes, Docker Compose services, and exported code signatures)."
        ),
    )
    def cortex_get_contract_drift(
        repo: str | None = None,
        breaking_only: bool = False,
        cross_repo_only: bool = False,
    ) -> ContractDriftReport:
        """Audit architectural contract drift and breaking changes."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_contract_drift(
                repo=repo,
                breaking_only=breaking_only,
                cross_repo_only=cross_repo_only,
            )

        client = ctx.create_in_process_client()
        return client.get_contract_drift(
            repo=repo,
            breaking_only=breaking_only,
            cross_repo_only=cross_repo_only,
        )
