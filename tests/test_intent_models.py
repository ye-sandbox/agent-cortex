"""Unit tests for change intent and automated contract patch models."""

from __future__ import annotations

from cortex.models.graph import DependencyEdgeType
from cortex.models.impact import BlastRadiusSeverity
from cortex.models.intent import (
    ChangeIntentAction,
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    DownstreamCallSite,
    PatchHunk,
    PortfolioChangePlan,
    RepoMigrationPatch,
    SimulationViolation,
)


def test_change_intent_action_properties() -> None:
    """Test action enum properties and breaking classification."""
    assert ChangeIntentAction.RENAME_SYMBOL.is_breaking is True
    assert ChangeIntentAction.MODIFY_SIGNATURE.is_breaking is True
    assert ChangeIntentAction.REMOVE_CONTRACT.is_breaking is True
    assert ChangeIntentAction.CHANGE_ENDPOINT.is_breaking is True
    assert ChangeIntentAction.REPLACE_CONTRACT.is_breaking is True
    assert ChangeIntentAction.DEPRECATE_CONTRACT.is_breaking is False


def test_contract_change_intent_deterministic_id() -> None:
    """Test deterministic ID generation if intent_id omitted."""
    intent = ContractChangeIntent(
        repo="sentinel-backend",
        target_symbol="fetch_deals",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="get_deals",
    )
    assert intent.intent_id == "intent_sentinel_backend_fetch_deals_rename_symbol"
    assert intent.repo == "sentinel-backend"
    assert intent.target_symbol == "fetch_deals"
    assert intent.new_symbol == "get_deals"


def test_portfolio_change_plan_validation() -> None:
    """Test grouping multiple intents into a PortfolioChangePlan."""
    intent1 = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_jwt",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="validate_jwt",
    )
    intent2 = ContractChangeIntent(
        repo="auth-service",
        target_symbol="POST /auth/token",
        action=ChangeIntentAction.CHANGE_ENDPOINT,
        new_symbol="POST /v2/token",
    )
    plan = PortfolioChangePlan(
        plan_id="plan_auth_v2",
        title="Auth V2 Migration",
        intents=[intent1, intent2],
        author="agent-planner",
    )
    assert len(plan.intents) == 2
    assert plan.plan_id == "plan_auth_v2"
    assert plan.author == "agent-planner"


def test_repo_migration_patch_totals_calculation() -> None:
    """Test file count and hunk aggregation in RepoMigrationPatch."""
    hunk1 = PatchHunk(
        file_path="src/client.py",
        old_line_start=12,
        old_line_count=1,
        new_line_start=12,
        new_line_count=1,
        diff_text="@@ -12,1 +12,1 @@\n-from auth import verify_jwt\n+from auth import validate_jwt",
        original_text="from auth import verify_jwt",
        replacement_text="from auth import validate_jwt",
        explanation="Renamed symbol",
    )
    hunk2 = PatchHunk(
        file_path="src/client.py",
        old_line_start=45,
        old_line_count=1,
        new_line_start=45,
        new_line_count=1,
        diff_text="@@ -45,1 +45,1 @@\n-verify_jwt(token)\n+validate_jwt(token)",
        original_text="verify_jwt(token)",
        replacement_text="validate_jwt(token)",
        explanation="Renamed call",
    )
    patch = RepoMigrationPatch(
        repo="clipflow-frontend",
        hunks=[hunk1, hunk2],
        breaking_changes_resolved=2,
    )
    assert patch.total_files == 1
    assert len(patch.hunks) == 2
    assert patch.breaking_changes_resolved == 2


def test_change_intent_simulation_report_summary_and_counts() -> None:
    """Test count derivation and markdown summary rendering for simulation report."""
    site = DownstreamCallSite(
        repo="dashboard-ui",
        file_path="src/api.ts",
        line_number=22,
        source_symbol="renderDashboard",
        raw_statement="import { fetch_deals } from 'sentinel';",
        matched_symbol="fetch_deals",
        edge_type=DependencyEdgeType.IMPORT,
    )
    violation = SimulationViolation(
        severity=BlastRadiusSeverity.HIGH,
        category="signature_divergence",
        message="Parameter renamed",
        call_site=site,
    )
    patch = RepoMigrationPatch(
        repo="dashboard-ui",
        total_files=1,
        breaking_changes_resolved=1,
    )

    report = ChangeIntentSimulationReport(
        plan_id="plan_deal_migration",
        total_intents=1,
        call_sites=[site],
        violations=[violation],
        migration_patches=[patch],
        overall_risk_level=BlastRadiusSeverity.HIGH,
        overall_risk_score=52.5,
        execution_order=["dashboard-ui", "sentinel-backend"],
    )

    assert report.total_call_sites == 1
    assert report.affected_repos == ["dashboard-ui"]
    assert report.patches_available is True

    summary = report.to_markdown_summary()
    assert "Portfolio Change Intent Simulation: `plan_deal_migration`" in summary
    assert "**Overall Risk Level:** `HIGH`" in summary
    assert "dashboard-ui" in summary
    assert "Automated Migration Patches" in summary
    assert "Recommended Staging Order" in summary
