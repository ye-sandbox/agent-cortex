"""Tests for server /drift/alerts endpoint and CortexClient remote drift routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_server_drift_alerts_endpoint() -> None:
    """Verify /drift/alerts endpoint returns structured ContractDriftReport."""
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
        summary="Endpoint removed",
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.table_names.return_value = []

    app = create_app(config=CortexConfig(), storage=mock_storage)

    with patch("cortex.server.ContractDriftEngine") as mock_engine_cls:
        mock_engine = MagicMock()
        mock_engine_cls.from_config.return_value = mock_engine
        mock_engine.analyze_repo_drift.return_value = report
        mock_engine.analyze_portfolio_drift.return_value = report

        with patch("cortex.server.resolve_sync_sources") as mock_sources:
            mock_src = MagicMock()
            mock_src.get_repo_name.return_value = "sentinel"
            mock_src.path = "/mock/sentinel"
            mock_sources.return_value = [mock_src]

            client = TestClient(app)

            # Query with repo filter
            res = client.get("/drift/alerts?repo=sentinel")
            assert res.status_code == 200
            data = res.json()
            assert data["total_alerts"] == 1
            assert data["breaking_count"] == 1
            assert data["alerts"][0]["identifier"] == "GET /deals"

            # Query with breaking_only filter
            res_breaking = client.get("/drift/alerts?repo=sentinel&breaking_only=true")
            assert res_breaking.status_code == 200
            data_breaking = res_breaking.json()
            assert data_breaking["breaking_count"] == 1


def test_client_remote_drift_routing() -> None:
    """Verify CortexClient.get_contract_drift queries remote hub when in remote mode."""
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
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    client = CortexClient(mode="remote", hub_url="http://mock-hub:8000")
    with patch.object(client._http_client, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = report.model_dump(mode="json")
        mock_get.return_value = mock_resp

        res = client.get_contract_drift(repo="sentinel", breaking_only=True)
        assert res.total_alerts == 1
        assert res.breaking_count == 1
        assert res.alerts[0].identifier == "DELETE /item"
        mock_get.assert_called_once()
