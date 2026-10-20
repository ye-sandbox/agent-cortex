"""Architectural contract drift and breaking change detection client mixin."""

from __future__ import annotations

import logging
from typing import Any

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.drift import ContractDriftReport

logger = logging.getLogger(__name__)


class DriftClientMixin(CortexBaseClient):
    """Domain mixin providing contract drift and breaking change alerting."""

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
