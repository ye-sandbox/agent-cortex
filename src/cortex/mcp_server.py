"""Model Context Protocol (MCP) server backwards-compatibility façade for agent-cortex."""

from __future__ import annotations

from cortex.client import CortexClient
from cortex.mcp import (
    ChangeIntentSimulationReport,
    CompactSearchResult,
    RepoContractChunk,
    RepoMigrationPatch,
    ServerContext,
    TechSummary,
    TechUsage,
    cortex_version,
    create_cortex_mcp_server,
    main,
    server,
)

__all__ = [
    "ChangeIntentSimulationReport",
    "CompactSearchResult",
    "CortexClient",
    "RepoContractChunk",
    "RepoMigrationPatch",
    "ServerContext",
    "TechSummary",
    "TechUsage",
    "cortex_version",
    "create_cortex_mcp_server",
    "main",
    "server",
]

if __name__ == "__main__":
    main()
