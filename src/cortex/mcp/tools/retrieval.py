"""Retrieval and repository contract inspection MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.models.chunk import (
    ChunkCategory,
    ChunkScope,
    CompactSearchResult,
    RepoContractChunk,
    TechSummary,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def cortex_version() -> str:
    """Return active version and system identity of agent-cortex."""
    from cortex import __version__

    return f"agent-cortex v{__version__}"


def register_retrieval_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register semantic search, contract inspection, and tech discovery tools on MCPServer."""
    server.tool(
        name="cortex_version",
        description="Return active version and system identity of agent-cortex.",
    )(cortex_version)

    @server.tool(
        name="cortex_search",
        description=(
            "Search across portfolio documentation, OpenAPI contracts, and infrastructure "
            "definitions with semantic hybrid retrieval and compact anchors."
        ),
    )
    def cortex_search(
        query: str,
        limit: int = 10,
        scope: str | None = None,
        category: str | None = None,
        repo: str | None = None,
        rerank: bool = True,
    ) -> list[CompactSearchResult]:
        """Perform semantic hybrid retrieval across the indexed knowledge base."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        scopes: list[ChunkScope] | None = None
        if scope:
            scopes = []
            for s in scope.split(","):
                s_clean = s.strip().lower()
                if s_clean:
                    scopes.append(ChunkScope(s_clean))

        cat: ChunkCategory | None = None
        if category:
            cat = ChunkCategory(category.strip().lower())

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            raw_results = remote_client.search(
                query=cleaned_query,
                limit=limit,
                scopes=scopes,
                category=cat,
                repo=repo,
                rerank=rerank,
            )
        else:
            pipe = ctx.get_pipeline()
            raw_results = pipe.search(
                query=cleaned_query,
                limit=limit,
                scopes=scopes,
                category=cat,
                repo=repo,
                rerank=rerank,
            )

        output: list[CompactSearchResult] = []
        for r in raw_results:
            snippet = r.snippet or (r.content[:200] + "..." if len(r.content) > 200 else r.content)
            output.append(
                CompactSearchResult(
                    anchor=r.format_anchor(),
                    repo=r.repo,
                    file_path=r.file_path,
                    category=r.category.value,
                    scope=r.scope.value,
                    score=round(r.score, 4),
                    snippet=snippet,
                    tags=r.tags,
                    content=r.content,
                )
            )
        return output

    @server.tool(
        name="cortex_get_repo_contracts",
        description=(
            "Retrieve high-level API routes (OpenAPI endpoints), Docker Compose services, "
            "and architectural invariant chunks for a specific repository."
        ),
    )
    def cortex_get_repo_contracts(
        repo: str,
        contract_type: str | None = None,
        limit: int = 50,
    ) -> list[RepoContractChunk]:
        """Inspect OpenAPI contracts, Docker compose services, and architectural invariants."""
        cleaned_repo = repo.strip()
        if not cleaned_repo:
            return []

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_repo_contracts(
                repo=cleaned_repo,
                contract_type=contract_type,
                limit=limit,
            )

        categories = resolve_contract_categories(contract_type)
        mgr = ctx.get_storage()
        records = mgr.get_repo_contracts(
            repo=cleaned_repo,
            categories=categories,
            limit=limit,
        )
        return format_contract_chunks(cleaned_repo, records)

    @server.tool(
        name="cortex_list_technologies",
        description=(
            "Discover technology tags, frameworks, and infrastructure used across the repository "
            "portfolio or find which repositories utilize a specific technology."
        ),
    )
    def cortex_list_technologies(
        tech_name: str | None = None,
        repo: str | None = None,
    ) -> TechSummary:
        """Discover and aggregate technology stacks across portfolio repositories."""
        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.list_technologies(tech_name=tech_name, repo=repo)

        mgr = ctx.get_storage()
        records = mgr.get_technologies(repo=repo)
        return aggregate_tech_summary(records, tech_name=tech_name)
