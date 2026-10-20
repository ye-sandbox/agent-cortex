"""Hermetic tests for MCP change intent simulation and patch generation tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.intent import (
    ChangeIntentSimulationReport,
    RepoMigrationPatch,
)
from cortex.storage.manager import StorageManager


def _setup_mock_storage() -> MagicMock:
    mock_storage = MagicMock(spec=StorageManager)
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/index.ts",
            DependencyEdgeType.IMPORT,
            "auth-backend",
            "verifyToken",
            2,
        ),
        source_repo="frontend-app",
        source_file="src/index.ts",
        source_symbol="render",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="auth-backend",
        target_symbol="verifyToken",
        target_repo="auth-backend",
        line_number=2,
        raw_statement="import { verifyToken } from 'auth-backend';",
    )
    mock_storage.get_dependencies.return_value = [dep1]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_technologies.return_value = []
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_indexed_repos.return_value = ["auth-backend", "frontend-app"]
    return mock_storage


@pytest.mark.anyio
async def test_mcp_intent_tools_registration() -> None:
    """Verify registration of change intent simulation and patch tools in MCP server."""
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_simulate_change_intent" in tool_names
    assert "cortex_generate_contract_patches" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_simulate_change_intent() -> None:
    """Test cortex_simulate_change_intent tool execution."""
    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    result = await server.call_tool(
        "cortex_simulate_change_intent",
        {
            "repo": "auth-backend",
            "symbol": "verifyToken",
            "action": "RENAME_SYMBOL",
            "new_symbol": "validateToken",
        },
    )
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    content_text = result.content[0].text  # type: ignore[union-attr]
    report = ChangeIntentSimulationReport.model_validate_json(content_text)
    assert report.total_intents == 1
    assert report.total_call_sites == 1
    assert report.affected_repos == ["frontend-app"]
    assert report.patches_available is True


@pytest.mark.anyio
async def test_mcp_cortex_generate_contract_patches() -> None:
    """Test cortex_generate_contract_patches tool execution."""

    storage = _setup_mock_storage()
    server = create_cortex_mcp_server(storage=storage)

    result = await server.call_tool(
        "cortex_generate_contract_patches",
        {
            "repo": "auth-backend",
            "symbol": "verifyToken",
            "action": "RENAME_SYMBOL",
            "new_symbol": "validateToken",
        },
    )
    assert result is not None
    assert not result.is_error
    assert len(result.content) == 1
    content_text = result.content[0].text  # type: ignore[union-attr]
    patch = RepoMigrationPatch.model_validate_json(content_text)
    assert patch.repo == "frontend-app"
    assert "validateToken" in patch.unified_diff
