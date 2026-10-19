"""Cross-repository code dependency and signature graph retrieval engine."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from cortex.models.graph import (
    CodeDependency,
    CrossRepoLink,
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def _sanitize_sql_str(val: str) -> str:
    """Escape single quotes for LanceDB SQL filter clauses."""
    return val.replace("'", "''")


class DependencyGraphEngine:
    """Retrieval engine for code dependencies, callers, and AST symbol signatures."""

    def __init__(self, storage_manager: StorageManager) -> None:
        """Initialize with storage manager."""
        self.storage = storage_manager

    def get_known_repos(self) -> list[str]:
        """Discover known repository identifiers across indexed signatures and chunks."""
        repos: set[str] = set()
        if "code_signatures" in self.storage.table_names():
            sigs = self.storage.get_signatures(limit=1000)
            for s in sigs:
                if s.repo:
                    repos.add(s.repo)
        if not repos and "chunks" in self.storage.table_names():
            techs = self.storage.get_technologies()
            for t in techs:
                repo_name = t.get("repo")
                if repo_name and isinstance(repo_name, str):
                    repos.add(repo_name)
        return sorted(repos)

    def resolve_cross_repo_links(
        self,
        dependencies: Sequence[CodeDependency],
        known_repos: Sequence[str] | None = None,
    ) -> list[CrossRepoLink]:
        """Detect and resolve architectural bridges across repository boundaries."""
        repos = list(known_repos) if known_repos is not None else self.get_known_repos()
        links: list[CrossRepoLink] = []

        for dep in dependencies:
            target_repo: str | None = dep.target_repo

            if not target_repo:
                target_mod = dep.target_module.lower().strip()
                # Check for direct repo name match or package prefix match
                for repo in repos:
                    r_clean = repo.lower().strip()
                    # Skip self-links
                    if r_clean == dep.source_repo.lower().strip():
                        continue
                    # Match module or package naming patterns (e.g. repo name or package prefix)
                    if (
                        target_mod == r_clean
                        or target_mod.startswith(f"{r_clean}.")
                        or target_mod.startswith(f"{r_clean}/")
                        or f"/{r_clean}/" in target_mod
                        or f"/{r_clean}" in target_mod
                        or target_mod.replace("-", "_") == r_clean.replace("-", "_")
                    ):
                        target_repo = repo
                        break

            if target_repo and target_repo.lower() != dep.source_repo.lower():
                symbol_display = dep.target_symbol or dep.target_module
                detail = f"{dep.edge_type.value} {dep.target_module}"
                if dep.target_symbol:
                    detail += f"::{dep.target_symbol}"
                links.append(
                    CrossRepoLink(
                        source_repo=dep.source_repo,
                        source_file=dep.source_file,
                        target_repo=target_repo,
                        edge_type=dep.edge_type,
                        symbol=symbol_display,
                        detail=detail,
                    )
                )

        return links

    def get_dependencies(
        self,
        repo: str,
        file_path: str | None = None,
        symbol: str | None = None,
        cross_repo_only: bool = False,
        limit: int = 200,
    ) -> DependencyQueryResult:
        """Query outgoing code dependencies for a repo, file, or symbol."""
        clauses: list[str] = [f"source_repo = '{_sanitize_sql_str(repo)}'"]
        if file_path and file_path.strip():
            clauses.append(f"source_file = '{_sanitize_sql_str(file_path.strip())}'")

        where = " AND ".join(clauses)
        deps = self.storage.get_dependencies(where=where, limit=limit * 2)

        if symbol and symbol.strip():
            sym_clean = symbol.strip().lower()
            deps = [
                d
                for d in deps
                if sym_clean in d.source_symbol.lower()
                or sym_clean in d.target_symbol.lower()
                or sym_clean in d.target_module.lower()
            ]

        cross_links = self.resolve_cross_repo_links(deps)

        if cross_repo_only:
            deps = [
                d
                for d in deps
                if (d.target_repo and d.target_repo != repo)
                or any(
                    link.source_file == d.source_file
                    and (link.symbol == d.target_symbol or link.symbol == d.target_module)
                    for link in cross_links
                )
            ]

        final_deps = deps[:limit]
        return DependencyQueryResult(
            repo=repo,
            file_path=file_path,
            symbol=symbol,
            total_dependencies=len(final_deps),
            dependencies=final_deps,
            cross_repo_links=cross_links,
        )

    def get_dependents(
        self,
        symbol: str,
        module: str | None = None,
        limit: int = 200,
    ) -> DependentsQueryResult:
        """Query incoming callers and importers for a symbol or module."""
        clauses: list[str] = []
        if symbol and symbol.strip():
            safe_sym = _sanitize_sql_str(symbol.strip())
            clauses.append(f"(target_symbol = '{safe_sym}' OR target_module = '{safe_sym}')")
        if module and module.strip():
            safe_mod = _sanitize_sql_str(module.strip())
            clauses.append(f"target_module = '{safe_mod}'")

        where = " AND ".join(clauses) if clauses else None
        dependents = self.storage.get_dependencies(where=where, limit=limit)

        # Fallback in-memory search if SQL equality missed qualified or case variations
        if not dependents and symbol and symbol.strip():
            all_deps = self.storage.get_dependencies(limit=limit * 5)
            s_lower = symbol.strip().lower()
            dependents = [
                d
                for d in all_deps
                if s_lower == d.target_symbol.lower()
                or s_lower == d.target_module.lower()
                or d.target_symbol.lower().endswith(f".{s_lower}")
            ][:limit]

        cross_links = self.resolve_cross_repo_links(dependents)

        return DependentsQueryResult(
            symbol=symbol,
            module=module,
            total_dependents=len(dependents),
            dependents=dependents,
            cross_repo_links=cross_links,
        )

    def get_signatures(
        self,
        query: str,
        repo: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        limit: int = 50,
    ) -> SignaturesQueryResult:
        """Query code signatures by identifier substring, language, and kind."""
        clauses: list[str] = []
        if repo and repo.strip():
            clauses.append(f"repo = '{_sanitize_sql_str(repo.strip())}'")
        if kind and kind.strip():
            clauses.append(f"kind = '{_sanitize_sql_str(kind.strip().lower())}'")
        if language and language.strip():
            clauses.append(f"language = '{_sanitize_sql_str(language.strip().lower())}'")

        where = " AND ".join(clauses) if clauses else None
        signatures = self.storage.get_signatures(where=where, limit=limit * 5)

        q_clean = query.strip().lower()
        if q_clean and q_clean != "*":
            signatures = [
                s
                for s in signatures
                if q_clean in s.identifier.lower()
                or q_clean in s.signature.lower()
                or q_clean in s.docstring.lower()
            ]

        final_sigs = signatures[:limit]
        return SignaturesQueryResult(
            query=query,
            total_signatures=len(final_sigs),
            signatures=final_sigs,
        )
