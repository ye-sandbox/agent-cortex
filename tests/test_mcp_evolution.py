"""Hermetic tests for MCP contract evolution and changelog tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.drift import ChangeKind, ContractType, DriftSeverity
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ChangelogRelease,
    ContractEvolutionEvent,
    ContractEvolutionTimeline,
)
from cortex.storage.manager import StorageManager


@pytest.mark.anyio
async def test_mcp_evolution_tools_registration() -> None:
    """Verify evolution tools are properly registered in MCP server."""
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_get_contract_timeline" in tool_names
    assert "cortex_synthesize_changelog" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_get_contract_timeline_invocation() -> None:
    """Verify tool execution returning structured contract evolution timeline."""
    mock_storage = MagicMock(spec=StorageManager)
    server = create_cortex_mcp_server(storage=mock_storage)

    event = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "sentinel", "c1", ContractType.OPENAPI, ChangeKind.REMOVED, "GET /deals"
        ),
        repo="sentinel",
        commit_sha="c1",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="GET /deals",
        file_path="openapi.json",
        summary="Removed deals route",
    )
    timeline = ContractEvolutionTimeline.from_events([event], repo="sentinel")

    with patch("cortex.mcp_server.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_contract_timeline.return_value = timeline

        result = await server.call_tool(
            "cortex_get_contract_timeline",
            {"repo": "sentinel", "breaking_only": True},
        )
        assert result is not None
        assert not result.is_error


@pytest.mark.anyio
async def test_mcp_cortex_synthesize_changelog_invocation() -> None:
    """Verify tool execution returning structured architectural changelog."""
    mock_storage = MagicMock(spec=StorageManager)
    server = create_cortex_mcp_server(storage=mock_storage)

    changelog = ArchitecturalChangelog(
        title="Portfolio Changelog",
        repo="sentinel",
        releases=[
            ChangelogRelease(
                tag_or_period="v1.0.0",
                date="2026-10-20",
                repo="sentinel",
                breaking_count=0,
                total_changes=1,
            )
        ],
        total_breaking=0,
        total_changes=1,
    )

    with patch("cortex.mcp_server.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.synthesize_changelog.return_value = changelog

        result = await server.call_tool(
            "cortex_synthesize_changelog",
            {"repo": "sentinel", "group_by": "release"},
        )
        assert result is not None
        assert not result.is_error
