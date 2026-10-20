"""Search, contract inspection, and tech stack discovery client mixin."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
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

logger = logging.getLogger(__name__)


class SearchClientMixin(CortexBaseClient):
    """Domain mixin providing hybrid search, contract discovery, and technology summary."""

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
