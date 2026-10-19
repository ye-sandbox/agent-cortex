"""Hermetic tests for MCP portfolio topology and dependency matrix tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.graph import CodeDependency, DependencyEdgeType
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


@pytest.mark.anyio
async def test_mcp_topology_tools_registration() -> None:
    """Verify registration of topology and dependency matrix MCP tools."""
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_get_portfolio_topology" in tool_names
    assert "cortex_get_dependency_matrix" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_get_portfolio_topology() -> None:
    """Test cortex_get_portfolio_topology MCP tool execution."""
    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    # 1. Mermaid (default)
    res_mmd = await server.call_tool("cortex_get_portfolio_topology", {"format": "mermaid"})
    assert not res_mmd.is_error
    assert len(res_mmd.content) == 1
    assert "flowchart LR" in res_mmd.content[0].text

    # 2. JSON
    res_json = await server.call_tool("cortex_get_portfolio_topology", {"format": "json"})
    assert not res_json.is_error
    data = json.loads(res_json.content[0].text)
    assert data["total_repos"] == 2
    assert len(data["edges"]) == 1


@pytest.mark.anyio
async def test_mcp_cortex_get_dependency_matrix() -> None:
    """Test cortex_get_dependency_matrix MCP tool execution."""
    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    res = await server.call_tool("cortex_get_dependency_matrix", {"min_weight": 0})
    assert not res.is_error
    assert len(res.content) == 1
    # Check JSON or string content
    text = res.content[0].text
    assert "backend-service" in text
    assert "frontend-app" in text
