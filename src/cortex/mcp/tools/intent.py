"""Contract change intent simulation and patch generation MCP tool registry."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cortex.models.intent import (
    ChangeIntentAction,
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    PortfolioChangePlan,
    RepoMigrationPatch,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from cortex.mcp.context import ServerContext


def register_intent_tools(server: MCPServer, ctx: ServerContext) -> None:
    """Register change intent simulation and patch generation tools on MCPServer."""

    @server.tool(
        name="cortex_simulate_change_intent",
        description=(
            "Simulate intended cross-repository architectural contract changes, "
            "identifying affected downstream call sites, violations, blast radius, "
            "and generating automated migration patches."
        ),
    )
    def cortex_simulate_change_intent(
        repo: str = "",
        symbol: str = "",
        action: str = "RENAME_SYMBOL",
        new_symbol: str | None = None,
        file_path: str | None = None,
        max_depth: int = 5,
        generate_patches: bool = True,
        plan_json: str | None = None,
    ) -> ChangeIntentSimulationReport:
        """Simulate change intent and evaluate portfolio blast radius."""
        plan: PortfolioChangePlan
        if plan_json:
            raw = json.loads(plan_json)
            if "intents" in raw:
                plan = PortfolioChangePlan.model_validate(raw)
            else:
                intent = ContractChangeIntent.model_validate(raw)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_from_mcp",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        else:
            act_enum = ChangeIntentAction.RENAME_SYMBOL
            act_upper = action.strip().upper()
            for m in ChangeIntentAction:
                if m.value == act_upper or m.name == act_upper:
                    act_enum = m
                    break
            intent = ContractChangeIntent(
                repo=repo.strip(),
                target_symbol=symbol.strip(),
                action=act_enum,
                new_symbol=new_symbol.strip() if new_symbol else None,
                file_path=file_path.strip() if file_path else None,
            )
            plan = PortfolioChangePlan(
                plan_id=intent.intent_id,
                title=f"Intent: {intent.action.value} {intent.target_symbol}",
                intents=[intent],
            )

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.simulate_change_intent(
                plan=plan,
                max_depth=max_depth,
                generate_patches=generate_patches,
            )

        client = ctx.create_in_process_client()
        return client.simulate_change_intent(
            plan=plan,
            max_depth=max_depth,
            generate_patches=generate_patches,
        )

    @server.tool(
        name="cortex_generate_contract_patches",
        description=(
            "Synthesize automated unified diff migration patches (diff -u) "
            "across downstream repositories for declared contract mutations."
        ),
    )
    def cortex_generate_contract_patches(
        repo: str = "",
        symbol: str = "",
        action: str = "RENAME_SYMBOL",
        new_symbol: str | None = None,
        file_path: str | None = None,
        plan_json: str | None = None,
    ) -> list[RepoMigrationPatch]:
        """Generate unified diff migration patches across downstream consumers."""
        plan: PortfolioChangePlan
        if plan_json:
            raw = json.loads(plan_json)
            if "intents" in raw:
                plan = PortfolioChangePlan.model_validate(raw)
            else:
                intent = ContractChangeIntent.model_validate(raw)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_from_mcp",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        else:
            act_enum = ChangeIntentAction.RENAME_SYMBOL
            act_upper = action.strip().upper()
            for m in ChangeIntentAction:
                if m.value == act_upper or m.name == act_upper:
                    act_enum = m
                    break
            intent = ContractChangeIntent(
                repo=repo.strip(),
                target_symbol=symbol.strip(),
                action=act_enum,
                new_symbol=new_symbol.strip() if new_symbol else None,
                file_path=file_path.strip() if file_path else None,
            )
            plan = PortfolioChangePlan(
                plan_id=intent.intent_id,
                title=f"Intent: {intent.action.value} {intent.target_symbol}",
                intents=[intent],
            )

        remote_client = ctx.get_remote_client()
        if remote_client is not None:
            return remote_client.generate_contract_patches(plan=plan)

        client = ctx.create_in_process_client()
        return client.generate_contract_patches(plan=plan)
