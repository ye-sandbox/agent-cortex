"""Dependency graph and AST code signature MCP tool registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cortex.models.graph import (
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.retrieval.graph import DependencyGraphEngine

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_graph_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register dependency graph and AST code signature query tools on MCPServer."""

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

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependencies(
                repo=cleaned_repo,
                file_path=file_path,
                symbol=symbol,
                cross_repo_only=cross_repo_only,
                limit=limit,
            )

        engine = DependencyGraphEngine(ctx.get_storage())
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

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_dependents(
                symbol=cleaned_sym,
                module=module,
                limit=limit,
            )

        engine = DependencyGraphEngine(ctx.get_storage())
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

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.get_signatures(
                query=cleaned_query,
                repo=repo,
                kind=kind,
                language=language,
                limit=limit,
            )

        engine = DependencyGraphEngine(ctx.get_storage())
        return engine.get_signatures(
            query=cleaned_query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )
