"""Hermetic tests for MCP contract drift tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)
from cortex.storage.manager import StorageManager


@pytest.mark.anyio
async def test_mcp_drift_tool_registration() -> None:
    """Verify cortex_get_contract_drift is properly registered in MCP server."""
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_get_contract_drift" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_get_contract_drift_invocation() -> None:
    """Verify tool execution returning structured contract drift report."""
    mock_storage = MagicMock(spec=StorageManager)
    server = create_cortex_mcp_server(storage=mock_storage)

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
        summary="OpenAPI endpoint removed",
    )
    report = ContractDriftReport.from_alerts([alert], repo="sentinel")

    with patch("cortex.mcp_server.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_contract_drift.return_value = report

        res = await server.call_tool(
            "cortex_get_contract_drift",
            {"repo": "sentinel", "breaking_only": True},
        )

        assert not res.is_error
        assert len(res.content) == 1
        assert "GET /deals" in res.content[0].text
