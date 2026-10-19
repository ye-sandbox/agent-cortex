"""Tests for server graph endpoints and dual-mode CortexClient graph queries."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig
from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_server_graph_dependencies_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    dep = CodeDependency(
        id="cortex:src/lib.py:IMPORT:fastembed::5",
        source_repo="cortex",
        source_file="src/lib.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="fastembed",
        line_number=5,
    )
    mock_storage.get_dependencies.return_value = [dep]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures"]
    mock_storage.get_signatures.return_value = []

    app = create_app(config=CortexConfig(), storage=mock_storage)
    client = TestClient(app)

    # Missing repo -> 400
    res_err = client.get("/graph/dependencies")
    assert res_err.status_code == 400

    # Successful query
    res = client.get("/graph/dependencies?repo=cortex")
    assert res.status_code == 200
    data = res.json()
    assert data["repo"] == "cortex"
    assert data["total_dependencies"] == 1
    assert data["dependencies"][0]["target_module"] == "fastembed"


def test_server_graph_dependents_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    dep = CodeDependency(
        id="maestri:src/app.ts:CALL:cortex:sync:10",
        source_repo="maestri",
        source_file="src/app.ts",
        source_symbol="start",
        edge_type=DependencyEdgeType.CALL,
        target_module="cortex",
        target_symbol="sync",
        line_number=10,
    )
    mock_storage.get_dependencies.return_value = [dep]
    mock_storage.table_names.return_value = ["code_dependencies"]
    mock_storage.get_signatures.return_value = []

    app = create_app(config=CortexConfig(), storage=mock_storage)
    client = TestClient(app)

    # Missing symbol -> 400
    res_err = client.get("/graph/dependents")
    assert res_err.status_code == 400

    # Successful query
    res = client.get("/graph/dependents?symbol=sync")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "sync"
    assert data["total_dependents"] == 1


def test_server_graph_signatures_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    sig = CodeSignature(
        id="cortex:src/cli.py:function:trace",
        repo="cortex",
        file_path="src/cli.py",
        language="python",
        kind="function",
        identifier="trace",
        signature="def trace() -> None",
        line_start=1,
        line_end=10,
    )
    mock_storage.get_signatures.return_value = [sig]
    mock_storage.table_names.return_value = ["code_signatures"]

    app = create_app(config=CortexConfig(), storage=mock_storage)
    client = TestClient(app)

    # Missing query -> 400
    res_err = client.get("/graph/signatures")
    assert res_err.status_code == 400

    # Successful query
    res = client.get("/graph/signatures?query=trace&repo=cortex")
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "trace"
    assert data["total_signatures"] == 1
    assert data["signatures"][0]["identifier"] == "trace"


def test_cortex_client_dual_mode_graph() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    dep = CodeDependency(
        id="cortex:src/lib.py:IMPORT:fastembed::5",
        source_repo="cortex",
        source_file="src/lib.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="fastembed",
        line_number=5,
    )
    sig = CodeSignature(
        id="cortex:src/cli.py:function:trace",
        repo="cortex",
        file_path="src/cli.py",
        language="python",
        kind="function",
        identifier="trace",
        signature="def trace() -> None",
        line_start=1,
        line_end=10,
    )
    mock_storage.get_dependencies.return_value = [dep]
    mock_storage.get_signatures.return_value = [sig]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures"]

    # Local in-process client
    client = CortexClient(mode="in_process", storage=mock_storage)

    deps_res = client.get_dependencies(repo="cortex")
    assert isinstance(deps_res, DependencyQueryResult)
    assert deps_res.total_dependencies == 1

    dependents_res = client.get_dependents(symbol="fastembed")
    assert isinstance(dependents_res, DependentsQueryResult)

    sigs_res = client.get_signatures(query="trace")
    assert isinstance(sigs_res, SignaturesQueryResult)
    assert sigs_res.total_signatures == 1
