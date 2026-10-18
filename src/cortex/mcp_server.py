"""Model Context Protocol (MCP) server implementation for agent-cortex."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig, load_config
from cortex.models.chunk import (
    ChunkCategory,
    ChunkScope,
    CompactSearchResult,
    RepoContractChunk,
    TechSummary,
    TechUsage,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

__all__ = [
    "CompactSearchResult",
    "RepoContractChunk",
    "TechSummary",
    "TechUsage",
    "cortex_version",
    "create_cortex_mcp_server",
    "main",
    "server",
]


def cortex_version() -> str:
    """Return active version and system identity of agent-cortex."""
    from cortex import __version__

    return f"agent-cortex v{__version__}"


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

    lazy_config = config
    lazy_pipeline = pipeline
    lazy_storage = storage
    lazy_client = client

    def get_config() -> CortexConfig:
        nonlocal lazy_config
        if lazy_config is None:
            lazy_config = load_config()
        return lazy_config

    def get_remote_client() -> CortexClient | None:
        nonlocal lazy_client
        if lazy_client is not None:
            return lazy_client
        if lazy_pipeline is not None or lazy_storage is not None:
            return None
        cfg = get_config()
        if cfg.remote.hub_url:
            lazy_client = CortexClient(mode="remote", config=cfg)
            return lazy_client
        return None

    def get_pipeline() -> HybridRetrievalPipeline:
        nonlocal lazy_pipeline
        if lazy_pipeline is None:
            cfg = get_config()
            lazy_pipeline = HybridRetrievalPipeline.from_config(cfg)
        return lazy_pipeline

    def get_storage() -> StorageManager:
        nonlocal lazy_storage
        if lazy_storage is None:
            cfg = get_config()
            lazy_storage = StorageManager(cfg.storage.data_dir)
        return lazy_storage

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

        remote_client = get_remote_client()
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
            pipe = get_pipeline()
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

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_repo_contracts(
                repo=cleaned_repo,
                contract_type=contract_type,
                limit=limit,
            )

        categories = resolve_contract_categories(contract_type)
        mgr = get_storage()
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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.list_technologies(tech_name=tech_name, repo=repo)

        mgr = get_storage()
        records = mgr.get_technologies(repo=repo)
        return aggregate_tech_summary(records, tech_name=tech_name)

    return server


# Global default server instance
server: MCPServer = create_cortex_mcp_server()


def main() -> None:
    """Main entrypoint for cortex-mcp."""
    server.run("stdio")


if __name__ == "__main__":
    main()
