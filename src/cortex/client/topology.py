"""Portfolio topology, coupling metrics, and cycle analysis client mixin."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyMatrix,
    PortfolioTopologyGraph,
    TopologyExportFormat,
)

logger = logging.getLogger(__name__)


class TopologyClientMixin(CortexBaseClient):
    """Domain mixin providing portfolio topology graphs, coupling matrix, and cycles."""

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
