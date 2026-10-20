"""Transitive blast radius simulation and impact tracing client mixin."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.impact import (
    BlastRadiusSimulationReport,
    BlastRadiusSimulationRequest,
    CallerChain,
    ImpactedNode,
)

logger = logging.getLogger(__name__)


class ImpactClientMixin(CortexBaseClient):
    """Domain mixin providing blast-radius simulation and transitive caller impact tracing."""

    def simulate_blast_radius(
        self,
        repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        change_kind: str = "MODIFIED",
        max_depth: int = 5,
    ) -> BlastRadiusSimulationReport:
        """Simulate change blast radius and synthesize AI agent planning advisories."""
        req = BlastRadiusSimulationRequest(
            repo=repo,
            symbol=symbol,
            file_path=file_path,
            change_kind=change_kind,
            max_depth=max_depth,
        )

        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.post(
                    f"{self.hub_url}/impact/simulate",
                    json=req.model_dump(mode="json"),
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return BlastRadiusSimulationReport.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    msg = f"Remote blast radius simulation failed: {exc}"
                    raise CortexRemoteError(msg) from exc
                logger.warning(
                    "Remote hub blast radius simulation failed (%s); falling back to local", exc
                )

        # Local mode
        from cortex.retrieval.impact import ImpactAnalysisEngine

        engine = ImpactAnalysisEngine(self._get_storage())
        return engine.simulate_blast_radius(req)

    def trace_impact(
        self,
        repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        max_depth: int = 5,
    ) -> tuple[list[CallerChain], list[ImpactedNode], list[list[str]]]:
        """Trace incoming transitive caller chains and cycle paths across portfolio repositories."""
        if self._should_use_remote() and self.hub_url:
            try:
                params: dict[str, Any] = {"repo": repo, "max_depth": max_depth}
                if symbol:
                    params["symbol"] = symbol
                if file_path:
                    params["file_path"] = file_path

                resp = self._http_client.get(
                    f"{self.hub_url}/impact/trace",
                    params=params,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                payload = resp.json()
                raw_chains = payload.get("caller_chains", [])
                raw_nodes = payload.get("impacted_nodes", [])
                raw_cycles = payload.get("cycles_detected", [])
                chains = [CallerChain.model_validate(c) for c in raw_chains]
                nodes = [ImpactedNode.model_validate(n) for n in raw_nodes]
                cycles = [list(c) for c in raw_cycles]
                return chains, nodes, cycles
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote impact trace failed: {exc}") from exc
                logger.warning("Remote hub impact trace failed (%s); falling back to local", exc)

        # Local mode
        from cortex.retrieval.impact import ImpactAnalysisEngine

        engine = ImpactAnalysisEngine(self._get_storage())
        return engine.trace_transitive_callers(
            target_repo=repo,
            symbol=symbol,
            file_path=file_path,
            max_depth=max_depth,
        )
