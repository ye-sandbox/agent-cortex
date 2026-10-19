"""Hermetic tests for cortex impact CLI commands."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.graph import DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationReport,
    CallerChain,
    CallerChainHop,
    ImpactAdvisory,
    ImpactedNode,
)

runner = CliRunner()


def _build_mock_report() -> BlastRadiusSimulationReport:
    node1 = ImpactedNode(
        repo="consumer-app",
        file_path="src/main.py",
        symbol="run",
        depth=1,
        direct=True,
        caller_count=2,
    )
    adv = ImpactAdvisory(
        severity=BlastRadiusSeverity.HIGH,
        category="migration_order",
        message="Update callers before target",
        recommended_action="Stage leaf changes first",
    )
    return BlastRadiusSimulationReport(
        target_repo="core-service",
        target_symbol="calc_metrics",
        target_file="src/core.py",
        change_kind="REMOVED",
        max_depth=3,
        risk_score=82.5,
        risk_level=BlastRadiusSeverity.CRITICAL,
        total_impacted_repos=1,
        impacted_repos=["consumer-app"],
        total_impacted_files=1,
        impacted_files=["consumer-app:src/main.py"],
        total_impacted_symbols=1,
        impacted_nodes=[node1],
        advisories=[adv],
        recommended_update_order=[
            "[Hop 1] consumer-app:src/main.py::run",
            "[Root Target] core-service:src/core.py::calc_metrics",
        ],
        suggested_test_suites=["core-service: tests/", "consumer-app: tests/"],
    )


def test_cli_impact_simulate_table() -> None:
    """Test cortex impact simulate rendering Rich tables and panels."""
    report = _build_mock_report()

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.simulate_blast_radius.return_value = report

        res = runner.invoke(app, ["impact", "simulate", "core-service", "--symbol", "calc_metrics"])
        assert res.exit_code == 0
        assert "Blast-Radius Simulation" in res.output
        assert "core-service" in res.output
        assert "Impacted Downstream Components" in res.output
        assert "consumer-app" in res.output
        assert "AI Agent Planning Advisories" in res.output
        assert "Recommended Staging Sequence" in res.output


def test_cli_impact_simulate_json() -> None:
    """Test cortex impact simulate --json output."""
    report = _build_mock_report()

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.simulate_blast_radius.return_value = report

        res = runner.invoke(app, ["impact", "simulate", "core-service", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["target_repo"] == "core-service"
        assert data["risk_score"] == 82.5
        assert data["risk_level"] == "CRITICAL"


def test_cli_impact_simulate_fail_on_risk() -> None:
    """Test cortex impact simulate --fail-on-risk exits with code 1 when breaking."""
    report = _build_mock_report()

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.simulate_blast_radius.return_value = report

        res = runner.invoke(app, ["impact", "simulate", "core-service", "--fail-on-risk"])
        assert res.exit_code == 1
        assert "exceeding risk threshold" in res.output


def test_cli_impact_trace_tree_and_json() -> None:
    """Test cortex impact trace with tree rendering and JSON."""
    hop1 = CallerChainHop(
        repo="consumer-app",
        file_path="src/main.py",
        symbol="run",
        depth=1,
        edge_type=DependencyEdgeType.CALL,
    )
    chain = CallerChain(
        hops=[hop1],
        path_str="consumer-app:src/main.py:run",
        depth=1,
        cross_repo=True,
        repos_involved=["consumer-app"],
    )
    node1 = ImpactedNode(
        repo="consumer-app",
        file_path="src/main.py",
        symbol="run",
        depth=1,
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.trace_impact.return_value = ([chain], [node1], [])

        # 1. Tree output
        res_tree = runner.invoke(
            app, ["impact", "trace", "core-service", "--symbol", "calc_metrics"]
        )
        assert res_tree.exit_code == 0
        assert "core-service" in res_tree.output
        assert "consumer-app" in res_tree.output
        assert "Impact Trace Summary" in res_tree.output

        # 2. JSON output
        res_json = runner.invoke(app, ["impact", "trace", "core-service", "--json"])
        assert res_json.exit_code == 0
        data = json.loads(res_json.output)
        assert data["target_repo"] == "core-service"
        assert len(data["caller_chains"]) == 1
