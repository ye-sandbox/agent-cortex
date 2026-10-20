"""Repository synchronization client mixin."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError

logger = logging.getLogger(__name__)


class SyncClientMixin(CortexBaseClient):
    """Domain mixin providing local and remote repository synchronization."""

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
