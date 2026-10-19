"""Unit tests for contract drift domain models."""

import pytest

from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)


def test_drift_severity_is_breaking() -> None:
    """Verify breaking change property on severities."""
    assert DriftSeverity.CRITICAL.is_breaking is True
    assert DriftSeverity.HIGH.is_breaking is True
    assert DriftSeverity.MEDIUM.is_breaking is False
    assert DriftSeverity.LOW.is_breaking is False
    assert DriftSeverity.INFO.is_breaking is False


def test_contract_drift_alert_build_id() -> None:
    """Verify deterministic alert ID generation and consistency."""
    alert_id = ContractDriftAlert.build_id(
        repo="sentinel",
        file_path="specs/openapi.json",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        identifier="DELETE /deals/{id}",
    )
    assert alert_id == "sentinel:specs/openapi.json:openapi:removed:DELETE_deals_id"

    alert = ContractDriftAlert(
        id=alert_id,
        repo="sentinel",
        file_path="specs/openapi.json",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.HIGH,
        identifier="DELETE /deals/{id}",
        summary="Endpoint 'DELETE /deals/{id}' was removed",
        details="Route deleted from OpenAPI paths",
        impacted_repos=["ia-maestri"],
        impacted_callers=["ia-maestri:src/client.ts:45"],
    )

    assert alert.repo == "sentinel"
    assert alert.severity == DriftSeverity.HIGH
    assert alert.impacted_repos == ["ia-maestri"]


def test_contract_drift_alert_invalid_id() -> None:
    """Ensure validator raises error when alert ID does not match repo/file prefix."""
    with pytest.raises(ValueError, match="does not start with expected prefix"):
        ContractDriftAlert(
            id="other_repo:file.json:openapi:removed:test",
            repo="my_repo",
            file_path="file.json",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.REMOVED,
            severity=DriftSeverity.HIGH,
            identifier="test",
            summary="test summary",
        )


def test_contract_drift_report_aggregation() -> None:
    """Test aggregated report generation and counting."""
    alert1 = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "r1", "f1.py", ContractType.CODE_SIGNATURE, ChangeKind.REMOVED, "f1"
        ),
        repo="r1",
        file_path="f1.py",
        contract_type=ContractType.CODE_SIGNATURE,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="f1",
        summary="Removed function f1",
        impacted_repos=["r2"],
    )
    alert2 = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "r1", "f1.py", ContractType.CODE_SIGNATURE, ChangeKind.MODIFIED, "f2"
        ),
        repo="r1",
        file_path="f1.py",
        contract_type=ContractType.CODE_SIGNATURE,
        change_kind=ChangeKind.MODIFIED,
        severity=DriftSeverity.HIGH,
        identifier="f2",
        summary="Modified signature f2",
    )
    alert3 = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "r1", "f1.py", ContractType.CODE_SIGNATURE, ChangeKind.MODIFIED, "f3"
        ),
        repo="r1",
        file_path="f1.py",
        contract_type=ContractType.CODE_SIGNATURE,
        change_kind=ChangeKind.MODIFIED,
        severity=DriftSeverity.MEDIUM,
        identifier="f3",
        summary="Docstring changed f3",
    )
    alert4 = ContractDriftAlert(
        id=ContractDriftAlert.build_id(
            "r1", "f1.py", ContractType.CODE_SIGNATURE, ChangeKind.ADDED, "f4"
        ),
        repo="r1",
        file_path="f1.py",
        contract_type=ContractType.CODE_SIGNATURE,
        change_kind=ChangeKind.ADDED,
        severity=DriftSeverity.INFO,
        identifier="f4",
        summary="Added function f4",
    )

    report = ContractDriftReport.from_alerts([alert1, alert2, alert3, alert4], repo="r1")
    assert report.total_alerts == 4
    assert report.breaking_count == 2  # CRITICAL + HIGH
    assert report.warning_count == 1  # MEDIUM
    assert report.info_count == 1  # INFO
