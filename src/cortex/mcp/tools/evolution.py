"""Contract evolution timeline and changelog synthesis MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from cortex.models.evolution import (
    ArchitecturalChangelog,
    ContractEvolutionTimeline,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_evolution_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register contract evolution timeline and changelog synthesis tools on MCPServer."""

    @server.tool(
        name="cortex_get_contract_timeline",
        description=(
            "Retrieve chronological history of architectural contract mutations across "
            "repositories, optionally filtering by repo, contract type, or breaking severity."
        ),
    )
    def cortex_get_contract_timeline(
        repo: str | None = None,
        contract_type: str | None = None,
        change_kind: str | None = None,
        breaking_only: bool = False,
        limit: int = 100,
    ) -> ContractEvolutionTimeline:
        """Query contract evolution timeline."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_contract_timeline(
                repo=repo,
                contract_type=contract_type,
                change_kind=change_kind,
                breaking_only=breaking_only,
                limit=limit,
            )

        client = ctx.create_in_process_client()
        return client.get_contract_timeline(
            repo=repo,
            contract_type=contract_type,
            change_kind=change_kind,
            breaking_only=breaking_only,
            limit=limit,
        )

    @server.tool(
        name="cortex_synthesize_changelog",
        description=(
            "Synthesize structured portfolio architectural changelog from contract mutations, "
            "highlighting breaking changes, deprecations, and affected downstream repositories."
        ),
    )
    def cortex_synthesize_changelog(
        repo: str | None = None,
        group_by: str = "release",
        breaking_only: bool = False,
        limit: int = 200,
    ) -> ArchitecturalChangelog:
        """Synthesize portfolio architectural contract changelog."""
        group_key: Literal["release", "date", "repo"] = (
            "date" if group_by == "date" else ("repo" if group_by == "repo" else "release")
        )
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.synthesize_changelog(
                repo=repo,
                group_by=group_key,
                breaking_only=breaking_only,
                limit=limit,
            )

        client = ctx.create_in_process_client()
        return client.synthesize_changelog(
            repo=repo,
            group_by=group_key,
            breaking_only=breaking_only,
            limit=limit,
        )
