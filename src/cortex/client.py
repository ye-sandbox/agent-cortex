"""Dual-mode client for agent-cortex.

Provides seamless switching and fallback between local in-process retrieval (Stage 1 & 2
LanceDB + FastEmbed) and remote homelab daemon querying via HTTP/NDJSON streaming.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Any, Literal

import httpx

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config
from cortex.mcp_server import RepoContractChunk, TechSummary, TechUsage
from cortex.models.chunk import ChunkCategory, ChunkScope, SearchResultChunk
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
        categories: list[str]
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

        mgr = self._get_storage()
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
