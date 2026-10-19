"""Hermetic tests for MCP graph query tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
)
from cortex.storage.manager import StorageManager


@pytest.mark.anyio
async def test_mcp_graph_tools_registration() -> None:
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_get_dependencies" in tool_names
    assert "cortex_get_dependents" in tool_names
    assert "cortex_get_code_signatures" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_get_dependencies() -> None:
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
    mock_storage.table_names.return_value = ["code_dependencies"]
    mock_storage.get_signatures.return_value = []

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool("cortex_get_dependencies", {"repo": "cortex"})

    assert not res.is_error
    assert len(res.content) == 1
    assert "fastembed" in res.content[0].text


@pytest.mark.anyio
async def test_mcp_cortex_get_dependents() -> None:
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

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool("cortex_get_dependents", {"symbol": "sync"})

    assert not res.is_error
    assert len(res.content) == 1
    assert "maestri" in res.content[0].text


@pytest.mark.anyio
async def test_mcp_cortex_get_code_signatures() -> None:
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

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool("cortex_get_code_signatures", {"query": "trace"})

    assert not res.is_error
    assert len(res.content) == 1
    assert "trace" in res.content[0].text
