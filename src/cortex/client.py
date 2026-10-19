"""Dual-mode client for agent-cortex.

Provides seamless switching and fallback between local in-process retrieval (Stage 1 & 2
LanceDB + FastEmbed) and remote homelab daemon querying via HTTP/NDJSON streaming.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Sequence
from typing import Any, Literal

import httpx

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config
from cortex.models.chunk import (
    ChunkCategory,
    ChunkScope,
    RepoContractChunk,
    SearchResultChunk,
    TechSummary,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)
from cortex.models.drift import ContractDriftReport
from cortex.models.graph import (
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyMatrix,
    PortfolioTopologyGraph,
    TopologyExportFormat,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)

ClientMode = Literal["in_process", "remote", "auto"]


class CortexClientError(Exception):
    """Base exception for cortex client errors."""


class CortexRemoteError(CortexClientError):
    """Exception raised when remote cortex hub request fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        hub_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.hub_url = hub_url


class CortexAuthError(CortexRemoteError):
    """Exception raised when remote authentication fails (401 Unauthorized)."""

    def __init__(self, message: str = "Invalid or missing Bearer token") -> None:
        super().__init__(message, status_code=401)


class CortexClient:
    """Unified dual-mode client for querying agent-cortex knowledge bases."""

    def __init__(
        self,
        mode: ClientMode = "auto",
        hub_url: str | None = None,
        api_key: str | None = None,
        tenant_id: str | None = None,
        timeout: float = 30.0,
        config: CortexConfig | None = None,
        pipeline: HybridRetrievalPipeline | None = None,
        storage: StorageManager | None = None,
        dynamic_config: DynamicConfigManager | None = None,
    ) -> None:
        self.config = config or load_config()
        self.mode = mode
        self.timeout = timeout

        # Resolve tenant ID (from param, env, or default)
        env_tenant = os.environ.get("CORTEX_TENANT_ID")
        self.tenant_id = (
            tenant_id.strip()
            if tenant_id and tenant_id.strip()
            else (env_tenant.strip() if env_tenant and env_tenant.strip() else "default")
        )

        # Resolve hub URL and API key from args, then config
        self.hub_url = (
            hub_url.rstrip("/")
            if hub_url and hub_url.strip()
            else (self.config.remote.hub_url.rstrip("/") if self.config.remote.hub_url else None)
        )
        self.api_key = (
            api_key.strip()
            if api_key and api_key.strip()
            else (self.config.remote.api_key.strip() if self.config.remote.api_key else None)
        )

        if self.mode == "remote" and not self.hub_url:
            msg = "Remote mode requested but no hub_url provided or configured."
            raise ValueError(msg)

        # Lazy local pipeline, storage, and dynamic config instances
        self._pipeline = pipeline
        self._storage = storage
        self._dynamic_config = dynamic_config

        # HTTP client for remote communications
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.tenant_id:
            headers["X-Tenant-ID"] = self.tenant_id

        self._http_client = httpx.Client(
            headers=headers,
            timeout=self.timeout,
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._http_client.close()

    def __enter__(self) -> CortexClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    def _get_pipeline(self) -> HybridRetrievalPipeline:
        if self._pipeline is None:
            self._pipeline = HybridRetrievalPipeline.from_config(self.config)
        return self._pipeline

    def _get_storage(self) -> StorageManager:
        if self._storage is None:
            self._storage = StorageManager(self.config.storage.data_dir)
        return self._storage

    def _get_dynamic_config(self) -> DynamicConfigManager:
        if self._dynamic_config is None:
            self._dynamic_config = DynamicConfigManager(data_dir=self.config.storage.data_dir)
        return self._dynamic_config

    def _should_use_remote(self) -> bool:
        if self.mode == "remote":
            return True
        if self.mode == "in_process":
            return False
        # mode == "auto": use remote if hub_url is declared
        return bool(self.hub_url)

    def health(self) -> dict[str, Any]:
        """Check health and vitals of the active hub or local engine."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(f"{self.hub_url}/health")
                resp.raise_for_status()
                res_json: dict[str, Any] = resp.json()
                return res_json
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
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                msg = f"Remote health check returned HTTP {status}: {exc.response.text}"
                raise CortexRemoteError(
                    msg,
                    status_code=exc.response.status_code,
                    hub_url=self.hub_url,
                ) from exc

        # Local in-process fallback / direct execution
        from cortex import __version__

        mgr = self._get_storage()
        total_chunks = mgr.count_chunks()
        profile = self.config.get_active_profile()

        return {
            "status": "ok",
            "version": __version__,
            "profile": profile.name,
            "total_chunks": total_chunks,
            "storage_dir": str(self.config.storage.data_dir),
            "mode": "in_process",
        }

    def search(
        self,
        query: str,
        limit: int | None = None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None = None,
        category: ChunkCategory | str | None = None,
        repo: str | None = None,
        rerank: bool = True,
        include_archived: bool = False,
    ) -> list[SearchResultChunk]:
        """Search portfolio documentation, contracts, and invariants."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        if self._should_use_remote() and self.hub_url:
            try:
                return self._remote_search(
                    query=cleaned_query,
                    limit=limit,
                    scopes=scopes,
                    category=category,
                    repo=repo,
                    rerank=rerank,
                    include_archived=include_archived,
                )
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

        # Local in-process search
        return self._local_search(
            query=cleaned_query,
            limit=limit,
            scopes=scopes,
            category=category,
            repo=repo,
            rerank=rerank,
            include_archived=include_archived,
        )

    def search_stream(
        self,
        query: str,
        limit: int | None = None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None = None,
        category: ChunkCategory | str | None = None,
        repo: str | None = None,
        rerank: bool = True,
        include_archived: bool = False,
    ) -> Iterator[SearchResultChunk]:
        """Stream search results chunk-by-chunk using NDJSON streaming over HTTP or generator."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return

        if self._should_use_remote() and self.hub_url:
            try:
                yield from self._remote_search_stream(
                    query=cleaned_query,
                    limit=limit,
                    scopes=scopes,
                    category=category,
                    repo=repo,
                    rerank=rerank,
                    include_archived=include_archived,
                )
                return
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

        # Local in-process streaming fallback
        results = self._local_search(
            query=cleaned_query,
            limit=limit,
            scopes=scopes,
            category=category,
            repo=repo,
            rerank=rerank,
            include_archived=include_archived,
        )
        yield from results

    def _remote_search(
        self,
        query: str,
        limit: int | None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None,
        category: ChunkCategory | str | None,
        repo: str | None,
        rerank: bool,
        include_archived: bool,
    ) -> list[SearchResultChunk]:
        payload = self._build_search_payload(
            query=query,
            limit=limit,
            scopes=scopes,
            category=category,
            repo=repo,
            rerank=rerank,
            include_archived=include_archived,
            stream=False,
        )
        resp = self._http_client.post(
            f"{self.hub_url}/search",
            json=payload,
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 401:
            raise CortexAuthError()
        resp.raise_for_status()

        raw_list = resp.json()
        if not isinstance(raw_list, list):
            return []

        return [SearchResultChunk.model_validate(item) for item in raw_list]

    def _remote_search_stream(
        self,
        query: str,
        limit: int | None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None,
        category: ChunkCategory | str | None,
        repo: str | None,
        rerank: bool,
        include_archived: bool,
    ) -> Iterator[SearchResultChunk]:
        payload = self._build_search_payload(
            query=query,
            limit=limit,
            scopes=scopes,
            category=category,
            repo=repo,
            rerank=rerank,
            include_archived=include_archived,
            stream=True,
        )
        with self._http_client.stream(
            "POST",
            f"{self.hub_url}/search",
            json=payload,
            headers={"Accept": "application/x-ndjson"},
        ) as resp:
            if resp.status_code == 401:
                raise CortexAuthError()
            resp.raise_for_status()
            for line in resp.iter_lines():
                clean_line = line.strip()
                if clean_line:
                    item = json.loads(clean_line)
                    yield SearchResultChunk.model_validate(item)

    def _local_search(
        self,
        query: str,
        limit: int | None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None,
        category: ChunkCategory | str | None,
        repo: str | None,
        rerank: bool,
        include_archived: bool,
    ) -> list[SearchResultChunk]:
        pipe = self._get_pipeline()
        resolved_scopes: list[ChunkScope] | None = None
        if scopes is not None:
            resolved_scopes = []
            for s in scopes:
                if isinstance(s, ChunkScope):
                    resolved_scopes.append(s)
                else:
                    resolved_scopes.append(ChunkScope(str(s).lower()))

        resolved_cat: ChunkCategory | None = None
        if category is not None:
            resolved_cat = (
                category
                if isinstance(category, ChunkCategory)
                else ChunkCategory(str(category).lower())
            )

        effective_limit = limit
        if effective_limit is None:
            dyn_cfg = self._get_dynamic_config().get_tenant_config(
                self.tenant_id, fallback=self.config
            )
            effective_limit = dyn_cfg.retrieval.default_limit

        return pipe.search(
            query=query,
            limit=effective_limit,
            scopes=resolved_scopes,
            include_archived=include_archived,
            category=resolved_cat,
            repo=repo,
            rerank=rerank,
        )

    def get_repo_contracts(
        self,
        repo: str,
        contract_type: str | None = None,
        limit: int = 50,
    ) -> list[RepoContractChunk]:
        """Inspect OpenAPI contracts, Docker compose services, and architectural invariants."""
        cleaned_repo = repo.strip()
        if not cleaned_repo:
            return []

        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {"repo": cleaned_repo, "limit": limit}
                if contract_type:
                    params["contract_type"] = contract_type
                resp = self._http_client.get(f"{self.hub_url}/contracts", params=params)
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                raw_list = resp.json()
                return [RepoContractChunk.model_validate(item) for item in raw_list]
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
        categories = resolve_contract_categories(contract_type)
        mgr = self._get_storage()
        records = mgr.get_repo_contracts(
            repo=cleaned_repo,
            categories=categories,
            limit=limit,
        )
        return format_contract_chunks(cleaned_repo, records)

    def list_technologies(
        self,
        tech_name: str | None = None,
        repo: str | None = None,
    ) -> TechSummary:
        """Discover and aggregate technology stacks across portfolio repositories."""
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {}
                if tech_name:
                    params["tech_name"] = tech_name
                if repo:
                    params["repo"] = repo
                resp = self._http_client.get(f"{self.hub_url}/technologies", params=params)
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return TechSummary.model_validate(resp.json())
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
        mgr = self._get_storage()
        records = mgr.get_technologies(repo=repo)
        return aggregate_tech_summary(records, tech_name=tech_name)

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

    def _build_search_payload(
        self,
        query: str,
        limit: int | None,
        scopes: Sequence[ChunkScope] | Sequence[str] | None,
        category: ChunkCategory | str | None,
        repo: str | None,
        rerank: bool,
        include_archived: bool,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "rerank": rerank,
            "include_archived": include_archived,
            "stream": stream,
        }
        if limit is not None:
            payload["limit"] = limit
        if scopes is not None:
            payload["scopes"] = [s.value if isinstance(s, ChunkScope) else str(s) for s in scopes]
        if category is not None:
            payload["category"] = (
                category.value if isinstance(category, ChunkCategory) else str(category)
            )
        if repo:
            payload["repo"] = repo
        if self.tenant_id and self.tenant_id != "default":
            payload["tenant_id"] = self.tenant_id
        return payload

    def get_config(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Retrieve effective configuration for a tenant (remote or local DB-backed)."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                resp = self._http_client.get(
                    f"{self.hub_url}/config",
                    headers=headers,
                    params={"tenant_id": target_tenant},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_json: dict[str, Any] = resp.json()
                return res_json
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

        dyn_mgr = self._get_dynamic_config()
        cfg = dyn_mgr.get_tenant_config(target_tenant, fallback=self.config)
        return cfg.model_dump(mode="json")

    def set_config(
        self,
        config_data: dict[str, Any] | CortexConfig,
        tenant_id: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Upsert runtime configuration for a tenant in remote hub or local LanceDB table."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id
        dict_data = (
            config_data.model_dump(mode="json")
            if isinstance(config_data, CortexConfig)
            else dict(config_data)
        )

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                payload = {
                    "tenant_id": target_tenant,
                    "config": dict_data,
                    "description": description,
                }
                resp = self._http_client.post(
                    f"{self.hub_url}/config",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_json: dict[str, Any] = resp.json()
                return res_json
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

        dyn_mgr = self._get_dynamic_config()
        saved = dyn_mgr.set_tenant_config(target_tenant, dict_data, description=description)
        return {"status": "ok", "tenant_id": target_tenant, "config": saved}

    def delete_config(self, tenant_id: str | None = None) -> bool:
        """Delete dynamic configuration overrides for a tenant."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                resp = self._http_client.delete(
                    f"{self.hub_url}/config",
                    headers=headers,
                    params={"tenant_id": target_tenant},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_data = resp.json()
                return bool(isinstance(res_data, dict) and res_data.get("deleted", False))
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

        dyn_mgr = self._get_dynamic_config()
        return dyn_mgr.delete_tenant_config(target_tenant)

    def list_tenants(self) -> list[dict[str, Any]]:
        """List configured tenants from remote hub or local LanceDB table."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(f"{self.hub_url}/tenants")
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_data = resp.json()
                if isinstance(res_data, dict):
                    raw_tenants = res_data.get("tenants", [])
                    if isinstance(raw_tenants, list):
                        return [t for t in raw_tenants if isinstance(t, dict)]
                return []
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

        dyn_mgr = self._get_dynamic_config()
        return dyn_mgr.list_tenants()

    def sync(
        self,
        repo: str | None = None,
        all_repos: bool = False,
        force_full: bool = False,
    ) -> dict[str, Any]:
        """Trigger repository synchronization locally or via remote hub."""
        if self._should_use_remote() and self.hub_url:
            payload: dict[str, Any] = {
                "repo": repo,
                "all": all_repos,
                "force_full": force_full,
            }
            try:
                resp = self._http_client.post(f"{self.hub_url}/sync", json=payload)
                if resp.status_code == 401:
                    raise CortexAuthError("Invalid or missing Bearer token for remote sync")
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"status": "ok", "raw": data}
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error("Remote hub at '%s' unreachable: %s", self.hub_url, exc)
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}.",
                    hub_url=self.hub_url,
                ) from exc

        # Local mode
        from cortex.ingestion.discovery import resolve_sync_sources
        from cortex.ingestion.engine import IngestionEngine

        sources = resolve_sync_sources(
            config=self.config,
            repo_filter=repo,
            all_flag=all_repos,
        )
        if not sources:
            return {
                "status": "not_found" if repo else "ok",
                "total_synced": 0,
                "synced": [],
            }

        engine = IngestionEngine.from_config(self.config)
        results = engine.sync_all(sources=sources, force_full=force_full)
        return {
            "status": "ok",
            "total_synced": len(results),
            "synced": [r.model_dump() for r in results],
        }

    def get_contract_drift(
        self,
        repo: str | None = None,
        breaking_only: bool = False,
        cross_repo_only: bool = False,
    ) -> ContractDriftReport:
        """Query architectural contract drift and breaking changes in local or remote mode."""
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {}
                if repo and repo.strip():
                    params["repo"] = repo.strip()
                if breaking_only:
                    params["breaking_only"] = "true"
                if cross_repo_only:
                    params["cross_repo_only"] = "true"

                resp = self._http_client.get(
                    f"{self.hub_url}/drift/alerts",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 401:
                    raise CortexAuthError("Authentication failed: invalid Bearer token")
                resp.raise_for_status()
                data = resp.json()
                return ContractDriftReport.model_validate(data)
            except CortexAuthError:
                raise
            except Exception as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote drift query failed: {exc}") from exc
                logger.warning("Remote hub drift query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.ingestion.discovery import resolve_sync_sources
        from cortex.retrieval.drift import ContractDriftEngine

        drift_engine = ContractDriftEngine.from_config(self.config)
        sources = resolve_sync_sources(
            config=self.config,
            repo_filter=repo,
            all_flag=(repo is None),
        )

        if repo and repo.strip():
            target_src = next((s for s in sources if s.get_repo_name() == repo.strip()), None)
            if target_src:
                raw_report = drift_engine.analyze_repo_drift(
                    repo_path=target_src.path,
                    repo_name=target_src.get_repo_name(),
                )
            else:
                raw_report = ContractDriftReport(repo=repo)
        else:
            raw_report = drift_engine.analyze_portfolio_drift(sources=sources)

        filtered_alerts = raw_report.alerts
        if breaking_only:
            filtered_alerts = [a for a in filtered_alerts if a.severity.is_breaking]
        if cross_repo_only:
            filtered_alerts = [a for a in filtered_alerts if len(a.impacted_repos) > 0]

        return ContractDriftReport.from_alerts(
            filtered_alerts,
            repo=raw_report.repo,
            base_commit=raw_report.base_commit,
            target_commit=raw_report.target_commit,
        )

    def get_portfolio_topology(
        self,
        format: TopologyExportFormat | str = "json",
        direction: str = "LR",
        include_internal: bool = False,
        min_weight: int = 1,
    ) -> PortfolioTopologyGraph | str | dict[str, Any]:
        """Query portfolio architecture topology graph and metrics."""
        fmt_val = format.value if isinstance(format, TopologyExportFormat) else str(format).lower()
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {
                    "format": fmt_val,
                    "direction": direction,
                    "include_internal": "true" if include_internal else "false",
                    "min_weight": min_weight,
                }
                headers: dict[str, str] = {}
                if fmt_val in ("mermaid", "dot"):
                    headers["Accept"] = "text/plain"
                else:
                    headers["Accept"] = "application/json"

                resp = self._http_client.get(
                    f"{self.hub_url}/topology/graph",
                    params=params,
                    headers=headers,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()

                if fmt_val == "json":
                    return PortfolioTopologyGraph.model_validate(resp.json())
                if fmt_val == "cytoscape":
                    res_json: dict[str, Any] = resp.json()
                    return res_json
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = resp.json()
                    if isinstance(data, dict) and "content" in data:
                        return str(data["content"])
                return resp.text
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote topology query failed: {exc}") from exc
                logger.warning("Remote hub topology query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.topology import PortfolioTopologyEngine

        engine = PortfolioTopologyEngine(self._get_storage())
        if fmt_val == "json":
            return engine.build_topology(
                include_internal=include_internal,
                min_weight=min_weight,
            )
        return engine.export(
            format_type=fmt_val,
            direction=direction,
            include_internal=include_internal,
            min_weight=min_weight,
        )

    def get_dependency_matrix(
        self,
        min_weight: int = 0,
    ) -> PortfolioDependencyMatrix:
        """Query cross-repository dependency NxN matrix and coupling metrics."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(
                    f"{self.hub_url}/topology/matrix",
                    params={"min_weight": min_weight},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return PortfolioDependencyMatrix.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote matrix query failed: {exc}") from exc
                logger.warning("Remote hub matrix query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.topology import PortfolioTopologyEngine

        engine = PortfolioTopologyEngine(self._get_storage())
        return engine.build_matrix(min_weight=min_weight)

    def get_topology_cycles(
        self,
        min_weight: int = 1,
    ) -> list[DependencyCycle]:
        """Query circular dependency paths across portfolio repositories."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(
                    f"{self.hub_url}/topology/cycles",
                    params={"min_weight": min_weight},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                raw_list = resp.json()
                if isinstance(raw_list, list):
                    return [DependencyCycle.model_validate(c) for c in raw_list]
                return []
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote cycles query failed: {exc}") from exc
                logger.warning("Remote hub cycles query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.topology import PortfolioTopologyEngine

        engine = PortfolioTopologyEngine(self._get_storage())
        graph = engine.build_topology(min_weight=min_weight)
        return graph.cycles
