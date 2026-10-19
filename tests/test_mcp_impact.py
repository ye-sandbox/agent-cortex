"""Hermetic tests for MCP blast-radius simulation and impact tracing tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSimulationReport,
    ImpactTraceResult,
)
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


@pytest.mark.anyio
async def test_mcp_impact_tools_registration() -> None:
    """Verify registration of blast radius and impact trace MCP tools."""
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_simulate_blast_radius" in tool_names
    assert "cortex_trace_impact" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_simulate_blast_radius() -> None:
    """Test cortex_simulate_blast_radius tool execution."""
    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    result = await server.call_tool(
        "cortex_simulate_blast_radius",
        {
            "repo": "backend-service",
            "symbol": "get_deals",
            "change_kind": "REMOVED",
            "max_depth": 3,
        },
    )
    assert not result.is_error
    assert len(result.content) == 1
    content_text = result.content[0].text  # type: ignore[union-attr]
    report = BlastRadiusSimulationReport.model_validate_json(content_text)
    assert report.target_repo == "backend-service"
    assert report.target_symbol == "get_deals"
    assert "frontend-app" in report.impacted_repos


@pytest.mark.anyio
async def test_mcp_cortex_trace_impact() -> None:
    """Test cortex_trace_impact tool execution."""
    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    result = await server.call_tool(
        "cortex_trace_impact",
        {
            "repo": "backend-service",
            "symbol": "get_deals",
            "max_depth": 3,
        },
    )
    assert not result.is_error
    assert len(result.content) == 1
    content_text = result.content[0].text  # type: ignore[union-attr]
    trace_res = ImpactTraceResult.model_validate_json(content_text)
    assert trace_res.target_repo == "backend-service"
    assert trace_res.symbol == "get_deals"
    assert trace_res.total_chains >= 1
    assert trace_res.caller_chains[0].hops[0].repo == "frontend-app"
