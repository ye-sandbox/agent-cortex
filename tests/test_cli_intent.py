"""Hermetic tests for cortex intent CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.graph import DependencyEdgeType
from cortex.models.impact import BlastRadiusSeverity
from cortex.models.intent import (
    ChangeIntentSimulationReport,
    DownstreamCallSite,
    PatchHunk,
    RepoMigrationPatch,
    SimulationViolation,
)

runner = CliRunner()


def _build_mock_simulation_report() -> ChangeIntentSimulationReport:
    """Build mock simulation report for CLI testing."""
    site = DownstreamCallSite(
        repo="dashboard-ui",
        file_path="src/api.ts",
        line_number=10,
        source_symbol="renderDashboard",
        raw_statement="import { fetch_deals } from 'sentinel';",
        matched_symbol="fetch_deals",
        edge_type=DependencyEdgeType.IMPORT,
    )
    viol = SimulationViolation(
        severity=BlastRadiusSeverity.HIGH,
        category="signature_divergence",
        message="Parameter mismatch in caller",
        call_site=site,
    )
    patch = RepoMigrationPatch(
        repo="dashboard-ui",
        total_files=1,
        hunks=[
            PatchHunk(
                file_path="src/api.ts",
                old_line_start=10,
                old_line_count=1,
                new_line_start=10,
                new_line_count=1,
                diff_text="@@ -10,1 +10,1 @@\n-import { fetch_deals }\n+import { get_deals }",
                original_text="import { fetch_deals }",
                replacement_text="import { get_deals }",
                explanation="Renamed symbol",
            )
        ],
        unified_diff=(
            "--- a/src/api.ts\n"
            "+++ b/src/api.ts\n"
            "@@ -10,1 +10,1 @@\n"
            "-import { fetch_deals }\n"
            "+import { get_deals }"
        ),
        breaking_changes_resolved=1,
    )
    return ChangeIntentSimulationReport(
        plan_id="intent_sentinel_fetch_deals_rename_symbol",
        total_intents=1,
        affected_repos=["dashboard-ui"],
        total_call_sites=1,
        call_sites=[site],
        violations=[viol],
        overall_risk_level=BlastRadiusSeverity.HIGH,
        overall_risk_score=55.0,
        patches_available=True,
        migration_patches=[patch],
        execution_order=["dashboard-ui", "sentinel"],
    )


def test_cli_intent_simulate_human_output() -> None:
    """Test cortex intent simulate rendering rich panels, violations and call sites."""
    report = _build_mock_simulation_report()

    with patch("cortex.cli.CortexClient") as mock_cls:
        client = MagicMock()
        mock_cls.return_value.__enter__.return_value = client
        mock_cls.return_value.simulate_change_intent.return_value = report

        result = runner.invoke(
            app,
            [
                "intent",
                "simulate",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--new-symbol",
                "get_deals",
            ],
        )

        assert result.exit_code == 0
        assert "Portfolio Change Intent Simulation" in result.output
        assert "HIGH" in result.output
        assert "dashboard-ui" in result.output
        assert "Automated Migration Patches Available" in result.output


def test_cli_intent_simulate_json() -> None:
    """Test cortex intent simulate with --json flag."""
    report = _build_mock_simulation_report()

    with patch("cortex.cli.CortexClient") as mock_cls:
        client = MagicMock()
        mock_cls.return_value.__enter__.return_value = client
        mock_cls.return_value.simulate_change_intent.return_value = report

        result = runner.invoke(
            app,
            [
                "intent",
                "simulate",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--new-symbol",
                "get_deals",
                "--json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["plan_id"] == "intent_sentinel_fetch_deals_rename_symbol"
        assert data["total_call_sites"] == 1
        assert data["affected_repos"] == ["dashboard-ui"]


def test_cli_intent_simulate_plan_file(tmp_path: Path) -> None:
    """Test cortex intent simulate loading a PortfolioChangePlan from JSON file."""
    plan_file = tmp_path / "plan.json"
    plan_data = {
        "plan_id": "plan_test_multi",
        "title": "Multi intent test",
        "intents": [
            {
                "repo": "sentinel",
                "target_symbol": "fetch_deals",
                "action": "RENAME_SYMBOL",
                "new_symbol": "get_deals",
            }
        ],
    }
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    report = _build_mock_simulation_report()

    with patch("cortex.cli.CortexClient") as mock_cls:
        client = MagicMock()
        mock_cls.return_value.__enter__.return_value = client
        mock_cls.return_value.simulate_change_intent.return_value = report

        result = runner.invoke(
            app,
            [
                "intent",
                "simulate",
                "--plan",
                str(plan_file),
                "--json",
            ],
        )

        assert result.exit_code == 0
        mock_cls.return_value.simulate_change_intent.assert_called_once()


def test_cli_intent_gates() -> None:
    """Test --fail-on-risk and --fail-on-violations error exit codes."""
    report = _build_mock_simulation_report()

    with patch("cortex.cli.CortexClient") as mock_cls:
        client = MagicMock()
        mock_cls.return_value.__enter__.return_value = client
        mock_cls.return_value.simulate_change_intent.return_value = report

        # fail on risk
        res_risk = runner.invoke(
            app,
            [
                "intent",
                "simulate",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--fail-on-risk",
            ],
        )
        assert res_risk.exit_code == 1

        # fail on violations
        res_viol = runner.invoke(
            app,
            [
                "intent",
                "simulate",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--fail-on-violations",
            ],
        )
        assert res_viol.exit_code == 1


def test_cli_intent_patch_output_and_file_export(tmp_path: Path) -> None:
    """Test cortex intent patch with stdout display and --output-dir file writing."""
    report = _build_mock_simulation_report()
    patches = report.migration_patches

    with patch("cortex.cli.CortexClient") as mock_cls:
        client = MagicMock()
        mock_cls.return_value.__enter__.return_value = client
        mock_cls.return_value.generate_contract_patches.return_value = patches

        # 1. Output to terminal
        result = runner.invoke(
            app,
            [
                "intent",
                "patch",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--new-symbol",
                "get_deals",
            ],
        )
        assert result.exit_code == 0
        assert "Patch: dashboard-ui" in result.output

        # 2. Export to output dir
        out_dir = tmp_path / "patches"
        res_export = runner.invoke(
            app,
            [
                "intent",
                "patch",
                "sentinel",
                "--symbol",
                "fetch_deals",
                "--new-symbol",
                "get_deals",
                "--output-dir",
                str(out_dir),
            ],
        )
        assert res_export.exit_code == 0
        saved_file = out_dir / "dashboard-ui.patch"
        assert saved_file.is_file()
        assert "--- a/src/api.ts" in saved_file.read_text(encoding="utf-8")
