"""Integration tests for server change intent simulation and patch routes."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.config.loader import CortexConfig
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def _setup_mock_storage() -> MagicMock:
    mock_storage = MagicMock(spec=StorageManager)
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-ui",
            "src/client.ts",
            DependencyEdgeType.IMPORT,
            "backend-service",
            "getUser",
            3,
        ),
        source_repo="frontend-ui",
        source_file="src/client.ts",
        source_symbol="fetchData",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="backend-service",
        target_symbol="getUser",
        target_repo="backend-service",
        line_number=3,
        raw_statement="import { getUser } from 'backend-service';",
    )
    mock_storage.get_dependencies.return_value = [dep1]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_technologies.return_value = []
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_indexed_repos.return_value = ["backend-service", "frontend-ui"]
    return mock_storage


def test_server_intent_simulate_post() -> None:
    """Test POST /intent/simulate endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    payload = {
        "repo": "backend-service",
        "target_symbol": "getUser",
        "action": "RENAME_SYMBOL",
        "new_symbol": "fetchUser",
    }
    resp = client.post("/intent/simulate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "plan_id" in data
    assert data["total_intents"] == 1
    assert data["total_call_sites"] == 1
    assert data["affected_repos"] == ["frontend-ui"]
    assert data["patches_available"] is True
    assert len(data["migration_patches"]) == 1


def test_server_intent_patch_post() -> None:
    """Test POST /intent/patch endpoint."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    payload = {
        "repo": "backend-service",
        "target_symbol": "getUser",
        "action": "RENAME_SYMBOL",
        "new_symbol": "fetchUser",
    }
    resp = client.post("/intent/patch", json=payload)
    assert resp.status_code == 200
    patches = resp.json()
    assert isinstance(patches, list)
    assert len(patches) == 1
    assert patches[0]["repo"] == "frontend-ui"
    assert "fetchUser" in patches[0]["unified_diff"]


def test_server_intent_errors() -> None:
    """Test 400 and 422 error handling for invalid payloads."""
    storage = _setup_mock_storage()
    app = create_app(config=CortexConfig(), storage=storage)
    client = TestClient(app)

    # Invalid JSON
    resp = client.post(
        "/intent/simulate",
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400

    # Unprocessable entity (missing target_symbol)
    resp_invalid = client.post("/intent/simulate", json={"repo": "backend-service"})
    assert resp_invalid.status_code == 422
