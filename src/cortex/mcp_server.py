"""Model Context Protocol (MCP) server implementation for agent-cortex."""

from __future__ import annotations

from typing import Literal

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
from cortex.models.drift import ContractDriftReport
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ContractEvolutionTimeline,
)
from cortex.models.graph import (
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.models.impact import (
    BlastRadiusSimulationReport,
    ImpactTraceResult,
)
from cortex.models.intent import (
    ChangeIntentAction,
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    PortfolioChangePlan,
    RepoMigrationPatch,
)
from cortex.models.topology import (
    PortfolioDependencyMatrix,
    PortfolioTopologyGraph,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

__all__ = [
    "ChangeIntentSimulationReport",
    "CompactSearchResult",
    "RepoContractChunk",
    "RepoMigrationPatch",
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

    @server.tool(
        name="cortex_get_dependencies",
        description=(
            "Trace outgoing imports, function/method calls, class extensions, and cross-repo "
            "architectural bridges for a given repository, file, or symbol."
        ),
    )
    def cortex_get_dependencies(
        repo: str,
        file_path: str | None = None,
        symbol: str | None = None,
        cross_repo_only: bool = False,
        limit: int = 100,
    ) -> DependencyQueryResult:
        """Trace outgoing dependencies and cross-repo architectural bridges."""
        cleaned_repo = repo.strip()
        if not cleaned_repo:
            return DependencyQueryResult(
                repo=repo,
                file_path=file_path,
                symbol=symbol,
                total_dependencies=0,
                dependencies=[],
                cross_repo_links=[],
            )

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependencies(
                repo=cleaned_repo,
                file_path=file_path,
                symbol=symbol,
                cross_repo_only=cross_repo_only,
                limit=limit,
            )

        engine = DependencyGraphEngine(get_storage())
        return engine.get_dependencies(
            repo=cleaned_repo,
            file_path=file_path,
            symbol=symbol,
            cross_repo_only=cross_repo_only,
            limit=limit,
        )

    @server.tool(
        name="cortex_get_dependents",
        description=(
            "Find incoming callers, importers, and dependents across portfolio repositories "
            "for a target symbol or module."
        ),
    )
    def cortex_get_dependents(
        symbol: str,
        module: str | None = None,
        limit: int = 100,
    ) -> DependentsQueryResult:
        """Find incoming callers, importers, and dependents across repositories."""
        cleaned_sym = symbol.strip()
        if not cleaned_sym:
            return DependentsQueryResult(
                symbol=symbol,
                module=module,
                total_dependents=0,
                dependents=[],
                cross_repo_links=[],
            )

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependents(
                symbol=cleaned_sym,
                module=module,
                limit=limit,
            )

        engine = DependencyGraphEngine(get_storage())
        return engine.get_dependents(
            symbol=cleaned_sym,
            module=module,
            limit=limit,
        )

    @server.tool(
        name="cortex_get_code_signatures",
        description=(
            "Lookup AST code contracts and signatures by query substring, repo, kind, or language."
        ),
    )
    def cortex_get_code_signatures(
        query: str,
        repo: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> SignaturesQueryResult:
        """Query AST code signatures by query substring, repo, kind, or language."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return SignaturesQueryResult(
                query=query,
                total_signatures=0,
                signatures=[],
            )

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_signatures(
                query=cleaned_query,
                repo=repo,
                kind=kind,
                language=language,
                limit=limit,
            )

        engine = DependencyGraphEngine(get_storage())
        return engine.get_signatures(
            query=cleaned_query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )

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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_contract_drift(
                repo=repo,
                breaking_only=breaking_only,
                cross_repo_only=cross_repo_only,
            )

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
        return client.get_contract_drift(
            repo=repo,
            breaking_only=breaking_only,
            cross_repo_only=cross_repo_only,
        )

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
        remote_client = get_remote_client()
        if remote_client is not None:
            res = remote_client.get_portfolio_topology(
                format=format,
                direction=direction,
                include_internal=include_internal,
                min_weight=min_weight,
            )
        else:
            client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
            res = client.get_portfolio_topology(
                format=format,
                direction=direction,
                include_internal=include_internal,
                min_weight=min_weight,
            )

        if isinstance(res, PortfolioTopologyGraph):
            import json

            return json.dumps(res.model_dump(mode="json"), indent=2)
        if isinstance(res, dict):
            import json

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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependency_matrix(min_weight=min_weight)

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
        return client.get_dependency_matrix(min_weight=min_weight)

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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.simulate_blast_radius(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                change_kind=change_kind,
                max_depth=max_depth,
            )

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
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
        remote_client = get_remote_client()
        if remote_client is not None:
            chains, nodes, cycles = remote_client.trace_impact(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                max_depth=max_depth,
            )
        else:
            client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.get_contract_timeline(
                repo=repo,
                contract_type=contract_type,
                change_kind=change_kind,
                breaking_only=breaking_only,
                limit=limit,
            )

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
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
        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.synthesize_changelog(
                repo=repo,
                group_by=group_key,
                breaking_only=breaking_only,
                limit=limit,
            )

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
        return client.synthesize_changelog(
            repo=repo,
            group_by=group_key,
            breaking_only=breaking_only,
            limit=limit,
        )

    @server.tool(
        name="cortex_simulate_change_intent",
        description=(
            "Simulate intended cross-repository architectural contract changes, "
            "identifying affected downstream call sites, violations, blast radius, "
            "and generating automated migration patches."
        ),
    )
    def cortex_simulate_change_intent(
        repo: str = "",
        symbol: str = "",
        action: str = "RENAME_SYMBOL",
        new_symbol: str | None = None,
        file_path: str | None = None,
        max_depth: int = 5,
        generate_patches: bool = True,
        plan_json: str | None = None,
    ) -> ChangeIntentSimulationReport:
        """Simulate change intent and evaluate portfolio blast radius."""
        import json

        plan: PortfolioChangePlan
        if plan_json:
            raw = json.loads(plan_json)
            if "intents" in raw:
                plan = PortfolioChangePlan.model_validate(raw)
            else:
                intent = ContractChangeIntent.model_validate(raw)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_from_mcp",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        else:
            act_enum = ChangeIntentAction.RENAME_SYMBOL
            act_upper = action.strip().upper()
            for m in ChangeIntentAction:
                if m.value == act_upper or m.name == act_upper:
                    act_enum = m
                    break
            intent = ContractChangeIntent(
                repo=repo.strip(),
                target_symbol=symbol.strip(),
                action=act_enum,
                new_symbol=new_symbol.strip() if new_symbol else None,
                file_path=file_path.strip() if file_path else None,
            )
            plan = PortfolioChangePlan(
                plan_id=intent.intent_id,
                title=f"Intent: {intent.action.value} {intent.target_symbol}",
                intents=[intent],
            )

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.simulate_change_intent(
                plan=plan,
                max_depth=max_depth,
                generate_patches=generate_patches,
            )

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
        return client.simulate_change_intent(
            plan=plan,
            max_depth=max_depth,
            generate_patches=generate_patches,
        )

    @server.tool(
        name="cortex_generate_contract_patches",
        description=(
            "Synthesize automated unified diff migration patches (diff -u) "
            "across downstream repositories for declared contract mutations."
        ),
    )
    def cortex_generate_contract_patches(
        repo: str = "",
        symbol: str = "",
        action: str = "RENAME_SYMBOL",
        new_symbol: str | None = None,
        file_path: str | None = None,
        plan_json: str | None = None,
    ) -> list[RepoMigrationPatch]:
        """Generate unified diff migration patches across downstream consumers."""
        import json

        plan: PortfolioChangePlan
        if plan_json:
            raw = json.loads(plan_json)
            if "intents" in raw:
                plan = PortfolioChangePlan.model_validate(raw)
            else:
                intent = ContractChangeIntent.model_validate(raw)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_from_mcp",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        else:
            act_enum = ChangeIntentAction.RENAME_SYMBOL
            act_upper = action.strip().upper()
            for m in ChangeIntentAction:
                if m.value == act_upper or m.name == act_upper:
                    act_enum = m
                    break
            intent = ContractChangeIntent(
                repo=repo.strip(),
                target_symbol=symbol.strip(),
                action=act_enum,
                new_symbol=new_symbol.strip() if new_symbol else None,
                file_path=file_path.strip() if file_path else None,
            )
            plan = PortfolioChangePlan(
                plan_id=intent.intent_id,
                title=f"Intent: {intent.action.value} {intent.target_symbol}",
                intents=[intent],
            )

        remote_client = get_remote_client()
        if remote_client is not None:
            return remote_client.generate_contract_patches(plan=plan)

        client = CortexClient(config=get_config(), mode="in_process", storage=get_storage())
        return client.generate_contract_patches(plan=plan)

    return server


# Global default server instance
server: MCPServer = create_cortex_mcp_server()


def main() -> None:
    """Main entrypoint for cortex-mcp."""
    server.run("stdio")


if __name__ == "__main__":
    main()
