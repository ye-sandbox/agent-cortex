"""Integration tests for server topology endpoints and dual-mode remote CortexClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.topology import (
    PortfolioDependencyMatrix,
    PortfolioTopologyGraph,
)
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def _setup_mock_storage() -> MagicMock:
    mock_storage = MagicMock(spec=StorageManager)
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/api.py",
            DependencyEdgeType.IMPORT,
            "backend-service",
            "run",
            5,
        ),
        source_repo="frontend-app",
        source_file="src/api.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="backend-service",
        target_symbol="run",
        target_repo="backend-service",
        line_number=5,
    )
    mock_storage.get_dependencies.return_value = [dep1]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_technologies.return_value = []
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_indexed_repos.return_value = ["backend-service", "frontend-app"]
    return mock_storage


def test_server_topology_graph_json() -> None:
    """Test GET /topology/graph endpoint with JSON serialization."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/topology/graph?format=json")
    assert res.status_code == 200
    data = res.json()
    graph = PortfolioTopologyGraph.model_validate(data)
    assert graph.total_repos == 2
    assert graph.total_cross_repo_edges == 1
    assert graph.edges[0].source_repo == "frontend-app"
    assert graph.edges[0].target_repo == "backend-service"


def test_server_topology_graph_mermaid_and_dot() -> None:
    """Test GET /topology/graph endpoint with Mermaid and DOT formats."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    # Mermaid
    res_mmd = client.get("/topology/graph?format=mermaid")
    assert res_mmd.status_code == 200
    assert "flowchart LR" in res_mmd.text
    assert "frontend_app" in res_mmd.text
    assert "backend_service" in res_mmd.text

    # DOT
    res_dot = client.get("/topology/graph?format=dot")
    assert res_dot.status_code == 200
    assert "digraph PortfolioTopology {" in res_dot.text
    assert '"frontend-app" -> "backend-service"' in res_dot.text


def test_server_topology_graph_cytoscape() -> None:
    """Test GET /topology/graph endpoint with Cytoscape JSON output."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/topology/graph?format=cytoscape")
    assert res.status_code == 200
    data = res.json()
    assert "elements" in data
    assert len(data["elements"]["nodes"]) == 2
    assert len(data["elements"]["edges"]) == 1


def test_server_topology_matrix() -> None:
    """Test GET /topology/matrix endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/topology/matrix")
    assert res.status_code == 200
    data = res.json()
    matrix = PortfolioDependencyMatrix.model_validate(data)
    assert "backend-service" in matrix.repos
    assert "frontend-app" in matrix.repos
    assert len(matrix.rows) == 2


def test_server_topology_cycles() -> None:
    """Test GET /topology/cycles endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    res = client.get("/topology/cycles")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_client_remote_topology_integration() -> None:
    """Test CortexClient methods operating through remote HTTP transport."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)

    with TestClient(app) as test_client, patch("httpx.Client", return_value=test_client):
        client = CortexClient(mode="remote", hub_url="http://testserver")

        # 1. get_portfolio_topology (JSON)
        graph = client.get_portfolio_topology(format="json")
        assert isinstance(graph, PortfolioTopologyGraph)
        assert graph.total_repos == 2

        # 2. get_portfolio_topology (Mermaid)
        mermaid = client.get_portfolio_topology(format="mermaid")
        assert isinstance(mermaid, str)
        assert "flowchart LR" in mermaid

        # 3. get_dependency_matrix
        matrix = client.get_dependency_matrix()
        assert isinstance(matrix, PortfolioDependencyMatrix)
        assert len(matrix.repos) == 2

        # 4. get_topology_cycles
        cycles = client.get_topology_cycles()
        assert isinstance(cycles, list)
        assert len(cycles) == 0
