"""Integration tests for server impact routes and dual-mode remote CortexClient."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationReport,
)
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def _setup_mock_storage() -> MagicMock:
    mock_storage = MagicMock(spec=StorageManager)
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/api.py",
            DependencyEdgeType.CALL,
            "backend-service",
            "get_deals",
            10,
        ),
        source_repo="frontend-app",
        source_file="src/api.py",
        source_symbol="fetch_deals",
        edge_type=DependencyEdgeType.CALL,
        target_module="backend-service",
        target_symbol="get_deals",
        target_repo="backend-service",
        line_number=10,
    )
    mock_storage.get_dependencies.return_value = [dep1]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_technologies.return_value = []
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_indexed_repos.return_value = ["backend-service", "frontend-app"]
    return mock_storage


def test_server_impact_simulate_post() -> None:
    """Test POST /impact/simulate endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    payload = {
        "repo": "backend-service",
        "symbol": "get_deals",
        "change_kind": "REMOVED",
        "max_depth": 3,
    }
    res = client.post("/impact/simulate", json=payload)
    assert res.status_code == 200
    report = BlastRadiusSimulationReport.model_validate(res.json())
    assert report.target_repo == "backend-service"
    assert report.target_symbol == "get_deals"
    assert report.change_kind == "REMOVED"
    assert "frontend-app" in report.impacted_repos


def test_server_impact_simulate_get() -> None:
    """Test GET /impact/simulate endpoint with query parameters."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/impact/simulate?repo=backend-service&symbol=get_deals&change_kind=MODIFIED")
    assert res.status_code == 200
    report = BlastRadiusSimulationReport.model_validate(res.json())
    assert report.target_repo == "backend-service"
    assert report.target_symbol == "get_deals"


def test_server_impact_trace() -> None:
    """Test GET /impact/trace endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/impact/trace?repo=backend-service&symbol=get_deals")
    assert res.status_code == 200
    data = res.json()
    assert data["target_repo"] == "backend-service"
    assert len(data["caller_chains"]) >= 1
    assert data["caller_chains"][0]["hops"][0]["repo"] == "frontend-app"


def test_server_impact_validation_errors() -> None:
    """Test missing or invalid parameters return 400 or 422."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    # Missing repo parameter in GET /impact/simulate
    res_get = client.get("/impact/simulate")
    assert res_get.status_code == 400

    # Missing repo parameter in GET /impact/trace
    res_trace = client.get("/impact/trace")
    assert res_trace.status_code == 400

    # Invalid max_depth in POST /impact/simulate
    res_post = client.post("/impact/simulate", json={"repo": "backend-service", "max_depth": 0})
    assert res_post.status_code == 422


def test_client_remote_impact_methods() -> None:
    """Test CortexClient simulate_blast_radius and trace_impact over HTTP."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    test_http = TestClient(app)

    client = CortexClient(mode="remote", hub_url="http://testserver")
    client._http_client = test_http

    report = client.simulate_blast_radius(
        repo="backend-service",
        symbol="get_deals",
        change_kind="REMOVED",
    )
    assert report.target_repo == "backend-service"
    assert report.risk_level in (BlastRadiusSeverity.CRITICAL, BlastRadiusSeverity.HIGH)

    chains, nodes, cycles = client.trace_impact(
        repo="backend-service",
        symbol="get_deals",
    )
    assert len(chains) == 1
    assert chains[0].hops[0].repo == "frontend-app"
    assert len(nodes) == 1
