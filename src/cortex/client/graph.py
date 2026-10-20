"""Dependency graph and AST signatures client mixin."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.graph import (
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.retrieval.graph import DependencyGraphEngine

logger = logging.getLogger(__name__)


class GraphClientMixin(CortexBaseClient):
    """Domain mixin providing AST dependency tracing, callers, and code signatures."""

    def get_dependencies(
        self,
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

        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {
                    "repo": cleaned_repo,
                    "cross_repo_only": "true" if cross_repo_only else "false",
                    "limit": limit,
                }
                if file_path:
                    params["file_path"] = file_path.strip()
                if symbol:
                    params["symbol"] = symbol.strip()

                resp = self._http_client.get(
                    f"{self.hub_url}/graph/dependencies",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return DependencyQueryResult.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        # Local execution
        engine = DependencyGraphEngine(self._get_storage())
        return engine.get_dependencies(
            repo=cleaned_repo,
            file_path=file_path,
            symbol=symbol,
            cross_repo_only=cross_repo_only,
            limit=limit,
        )

    def get_dependents(
        self,
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

        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {
                    "symbol": cleaned_sym,
                    "limit": limit,
                }
                if module:
                    params["module"] = module.strip()

                resp = self._http_client.get(
                    f"{self.hub_url}/graph/dependents",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return DependentsQueryResult.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        # Local execution
        engine = DependencyGraphEngine(self._get_storage())
        return engine.get_dependents(
            symbol=cleaned_sym,
            module=module,
            limit=limit,
        )

    def get_signatures(
        self,
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

        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {
                    "query": cleaned_query,
                    "limit": limit,
                }
                if repo:
                    params["repo"] = repo.strip()
                if kind:
                    params["kind"] = kind.strip()
                if language:
                    params["language"] = language.strip()

                resp = self._http_client.get(
                    f"{self.hub_url}/graph/signatures",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return SignaturesQueryResult.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        # Local execution
        engine = DependencyGraphEngine(self._get_storage())
        return engine.get_signatures(
            query=cleaned_query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )
