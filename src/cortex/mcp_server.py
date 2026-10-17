"""Model Context Protocol (MCP) server implementation for agent-cortex."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from cortex.config.loader import CortexConfig, load_config
from cortex.models.chunk import ChunkCategory, ChunkScope
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager


class CompactSearchResult(BaseModel):
    """Token-dense semantic search result item for AI agent consumption."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    anchor: str = Field(..., description="Compact markdown anchor: [repo] path > breadcrumb")
    repo: str = Field(..., description="Repository name")
    file_path: str = Field(..., description="Relative file path")
    category: str = Field(
        ...,
        description="Semantic category (doc, contract, infra, invariant, solution)",
    )
    scope: str = Field(..., description="Access scope (internal, public, confidential)")
    score: float = Field(..., description="Fused relevance score")
    snippet: str = Field(..., description="Concise text snippet")
    tags: list[str] = Field(default_factory=list, description="Associated technology tags")
    content: str = Field(..., description="Full chunk content")


class RepoContractChunk(BaseModel):
    """Targeted contract or architectural invariant definition for a repository."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    anchor: str = Field(..., description="Compact markdown anchor")
    repo: str = Field(..., description="Repository name")
    file_path: str = Field(..., description="Contract or manifest file path")
    category: str = Field(..., description="Semantic category (contract, infra, invariant)")
    breadcrumb: str = Field(..., description="Operation or service hierarchy")
    tags: list[str] = Field(default_factory=list, description="Technology and endpoint tags")
    content: str = Field(..., description="Contract or service definition content")


class TechUsage(BaseModel):
    """Aggregate usage metadata for a technology across repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    technology: str = Field(..., description="Normalized technology tag or framework name")
    repositories: list[str] = Field(
        default_factory=list,
        description="Repositories utilizing this technology",
    )
    chunk_count: int = Field(
        ...,
        description="Total occurrences or references in indexed portfolio",
    )


class TechSummary(BaseModel):
    """Portfolio technology discovery summary."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    total_technologies: int = Field(..., description="Total unique technologies identified")
    technologies: list[TechUsage] = Field(
        default_factory=list,
        description="List of technologies with repo mappings",
    )


def cortex_version() -> str:
    """Return active version and system identity of agent-cortex."""
    from cortex import __version__

    return f"agent-cortex v{__version__}"


def create_cortex_mcp_server(
    config: CortexConfig | None = None,
    pipeline: HybridRetrievalPipeline | None = None,
    storage: StorageManager | None = None,
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

    def get_pipeline() -> HybridRetrievalPipeline:
        nonlocal lazy_pipeline
        if lazy_pipeline is None:
            cfg = lazy_config or load_config()
            lazy_pipeline = HybridRetrievalPipeline.from_config(cfg)
        return lazy_pipeline

    def get_storage() -> StorageManager:
        nonlocal lazy_storage
        if lazy_storage is None:
            cfg = lazy_config or load_config()
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

        categories: list[str] | None = None
        if contract_type:
            ct = contract_type.strip().lower()
            if ct in ("openapi", "api", "contract"):
                categories = ["contract"]
            elif ct in ("compose", "docker", "infra"):
                categories = ["infra"]
            elif ct in ("invariant", "rule", "invariants"):
                categories = ["invariant"]
            elif ct == "all":
                categories = ["contract", "infra", "invariant"]
            else:
                categories = [ct]
        else:
            categories = ["contract", "infra", "invariant"]

        mgr = get_storage()
        records = mgr.get_repo_contracts(
            repo=cleaned_repo,
            categories=categories,
            limit=limit,
        )

        results: list[RepoContractChunk] = []
        for rec in records:
            file_path = str(rec.get("file_path", ""))
            breadcrumb = str(rec.get("breadcrumb", ""))
            anchor = (
                f"[{cleaned_repo}] {file_path} > {breadcrumb}"
                if breadcrumb
                else f"[{cleaned_repo}] {file_path}"
            )
            raw_tags = rec.get("tags")
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, Sequence) else []
            results.append(
                RepoContractChunk(
                    anchor=anchor,
                    repo=cleaned_repo,
                    file_path=file_path,
                    category=str(rec.get("category", "contract")),
                    breadcrumb=breadcrumb,
                    tags=tags,
                    content=str(rec.get("content", "")),
                )
            )
        return results

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
        mgr = get_storage()
        records = mgr.get_technologies(repo=repo)

        repo_map: dict[str, set[str]] = defaultdict(set)
        count_map: dict[str, int] = defaultdict(int)

        filter_tech = tech_name.strip().lower() if tech_name and tech_name.strip() else None

        for rec in records:
            r_repo = str(rec.get("repo", "")).strip()
            raw_tags = rec.get("tags")
            if not isinstance(raw_tags, Sequence):
                continue

            for tag in raw_tags:
                clean_tag = str(tag).strip()
                if not clean_tag:
                    continue

                if filter_tech and filter_tech not in clean_tag.lower():
                    continue

                repo_map[clean_tag].add(r_repo)
                count_map[clean_tag] += 1

        tech_items: list[TechUsage] = []
        # Sort by occurrence count descending, then alphabetically
        sorted_keys = sorted(count_map.keys(), key=lambda k: (-count_map[k], k.lower()))

        for t in sorted_keys:
            tech_items.append(
                TechUsage(
                    technology=t,
                    repositories=sorted(repo_map[t]),
                    chunk_count=count_map[t],
                )
            )

        return TechSummary(
            total_technologies=len(tech_items),
            technologies=tech_items,
        )

    return server


# Global default server instance
server: MCPServer = create_cortex_mcp_server()


def main() -> None:
    """Main entrypoint for cortex-mcp."""
    server.run("stdio")


if __name__ == "__main__":
    main()
