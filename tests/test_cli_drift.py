"""Hermetic tests for cortex drift CLI commands."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)

runner = CliRunner()


def test_cli_drift_help() -> None:
    """Verify drift CLI help documentation."""
    result = runner.invoke(app, ["drift", "--help"])
    assert result.exit_code == 0
    assert "audit" in result.output
    assert "alerts" in result.output


def test_cli_drift_audit_clean() -> None:
    """Verify clean audit output when no contract drift is detected."""
    empty_report = ContractDriftReport.from_alerts([], repo="test-repo")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_drift.return_value = empty_report

        res = runner.invoke(app, ["drift", "audit", "test-repo"])
        assert res.exit_code == 0
        assert "No architectural contract drift detected" in res.output


def test_cli_drift_audit_json() -> None:
    """Verify JSON output formatting on drift audit."""
    alert = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "sentinel", "openapi.json", ContractType.OPENAPI, ChangeKind.REMOVED, "GET /deals"
        ),
        repo="sentinel",
        file_path="openapi.json",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.HIGH,
        identifier="GET /deals",
        summary="Endpoint 'GET /deals' was removed",
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_drift.return_value = report

        res = runner.invoke(app, ["drift", "audit", "sentinel", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["total_alerts"] == 1
        assert data["breaking_count"] == 1
        assert data["alerts"][0]["identifier"] == "GET /deals"


def test_cli_drift_audit_table() -> None:
    """Verify table rendering on drift audit."""
    alert = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "sentinel", "openapi.json", ContractType.OPENAPI, ChangeKind.REMOVED, "DELETE /item"
        ),
        repo="sentinel",
        file_path="openapi.json",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="DELETE /item",
        summary="[BREAKING CROSS-REPO] Endpoint removed",
        impacted_repos=["consumer-app"],
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_drift.return_value = report

        res = runner.invoke(app, ["drift", "audit", "sentinel"], env={"COLUMNS": "200"})
        assert res.exit_code == 0
        assert "DELETE /item" in res.output
        assert "CRITICAL" in res.output
        assert "consumer-app" in res.output


def test_cli_drift_audit_fail_on_breaking() -> None:
    """Verify --fail-on-breaking exits with code 1 when breaking changes exist."""
    alert = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "sentinel", "openapi.json", ContractType.OPENAPI, ChangeKind.REMOVED, "POST /deals"
        ),
        repo="sentinel",
        file_path="openapi.json",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.HIGH,
        identifier="POST /deals",
        summary="Endpoint removed",
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_drift.return_value = report

        res = runner.invoke(app, ["drift", "audit", "sentinel", "--fail-on-breaking"])
        assert res.exit_code == 1
        assert "breaking architectural contract change(s) detected" in res.output


def test_cli_drift_alerts_command() -> None:
    """Verify drift alerts command invocation."""
    report = ContractDriftReport.from_alerts([])

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_drift.return_value = report

        res = runner.invoke(app, ["drift", "alerts", "--repo", "sentinel"])
        assert res.exit_code == 0
