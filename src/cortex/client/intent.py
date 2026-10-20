"""Change intent simulation and contract patch generation client mixin."""

from __future__ import annotations

import logging

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.models.intent import (
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    PortfolioChangePlan,
    RepoMigrationPatch,
)

logger = logging.getLogger(__name__)


class IntentClientMixin(CortexBaseClient):
    """Domain mixin providing change intent simulation and automated contract patch synthesis."""

    def simulate_change_intent(
        self,
        plan: PortfolioChangePlan | ContractChangeIntent,
        max_depth: int = 5,
        generate_patches: bool = True,
    ) -> ChangeIntentSimulationReport:
        """Simulate change intent or portfolio change plan in local or remote mode."""
        plan_obj = (
            PortfolioChangePlan(
                plan_id=plan.intent_id or "plan_single_intent",
                title=f"Intent: {plan.action.value} {plan.target_symbol}",
                intents=[plan],
            )
            if isinstance(plan, ContractChangeIntent)
            else plan
        )

        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.post(
                    f"{self.hub_url}/intent/simulate",
                    json=plan_obj.model_dump(mode="json"),
                    params={
                        "max_depth": max_depth,
                        "generate_patches": str(generate_patches).lower(),
                    },
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                return ChangeIntentSimulationReport.model_validate(resp.json())
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(
                        f"Remote change intent simulation failed: {exc}"
                    ) from exc
                logger.warning(
                    "Remote hub change intent simulation failed (%s); falling back to local", exc
                )

        # Local mode
        from cortex.retrieval.intent import ChangeIntentEngine

        engine = ChangeIntentEngine(self._get_storage())
        return engine.simulate_intent(
            plan_obj,
            max_depth=max_depth,
            generate_patches=generate_patches,
        )

    def generate_contract_patches(
        self,
        plan: PortfolioChangePlan | ContractChangeIntent,
    ) -> list[RepoMigrationPatch]:
        """Generate migration patches for change intent or plan in local or remote mode."""
        plan_obj = (
            PortfolioChangePlan(
                plan_id=plan.intent_id or "plan_single_intent",
                title=f"Intent: {plan.action.value} {plan.target_symbol}",
                intents=[plan],
            )
            if isinstance(plan, ContractChangeIntent)
            else plan
        )

        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.post(
                    f"{self.hub_url}/intent/patch",
                    json=plan_obj.model_dump(mode="json"),
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                raw_list = resp.json()
                if isinstance(raw_list, list):
                    return [RepoMigrationPatch.model_validate(p) for p in raw_list]
                return []
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.mode == "remote":
                    raise CortexRemoteError(f"Remote patch generation failed: {exc}") from exc
                logger.warning(
                    "Remote hub patch generation failed (%s); falling back to local", exc
                )

        # Local mode
        from cortex.retrieval.intent import ChangeIntentEngine

        engine = ChangeIntentEngine(self._get_storage())
        report = engine.simulate_intent(plan_obj, generate_patches=True)
        return report.migration_patches
