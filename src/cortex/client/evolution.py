"""Contract evolution timeline and changelog synthesis client mixin."""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ContractEvolutionTimeline,
)

logger = logging.getLogger(__name__)


class EvolutionClientMixin(CortexBaseClient):
    """Domain mixin providing contract evolution event querying and changelog synthesis."""

    def get_contract_timeline(
        self,
        repo: str | None = None,
        contract_type: str | None = None,
        change_kind: str | None = None,
        breaking_only: bool = False,
        since_date: str | None = None,
        until_date: str | None = None,
        limit: int = 100,
    ) -> ContractEvolutionTimeline:
        """Query contract evolution timeline in local or remote mode."""
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {"limit": limit}
                if repo:
                    params["repo"] = repo
                if contract_type:
                    params["contract_type"] = contract_type
                if change_kind:
                    params["change_kind"] = change_kind
                if breaking_only:
                    params["breaking_only"] = "true"
                if since_date:
                    params["since_date"] = since_date
                if until_date:
                    params["until_date"] = until_date
                resp = self._http_client.get(
                    f"{self.hub_url}/timeline",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return ContractEvolutionTimeline.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote timeline query failed: {exc}") from exc
                logger.warning("Remote hub timeline query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.evolution import ContractEvolutionEngine

        evo_engine = ContractEvolutionEngine(self._get_storage())
        return evo_engine.get_timeline(
            repo=repo,
            contract_type=contract_type,
            change_kind=change_kind,
            breaking_only=breaking_only,
            since_date=since_date,
            until_date=until_date,
            limit=limit,
        )

    def synthesize_changelog(
        self,
        repo: str | None = None,
        group_by: Literal["release", "date", "repo"] = "release",
        breaking_only: bool = False,
        limit: int = 200,
    ) -> ArchitecturalChangelog:
        """Synthesize architectural changelog in local or remote mode."""
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {
                    "group_by": group_by,
                    "limit": limit,
                    "format": "json",
                }
                if repo:
                    params["repo"] = repo
                if breaking_only:
                    params["breaking_only"] = "true"
                resp = self._http_client.get(
                    f"{self.hub_url}/changelog",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return ArchitecturalChangelog.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote changelog query failed: {exc}") from exc
                logger.warning("Remote hub changelog query failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.evolution import ContractEvolutionEngine

        evo_engine = ContractEvolutionEngine(self._get_storage())
        return evo_engine.synthesize_changelog(
            repo=repo,
            group_by=group_by,
            breaking_only=breaking_only,
            limit=limit,
        )
