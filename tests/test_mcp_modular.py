"""Hermetic tests for modular MCP server registries and ServerContext."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

import cortex.mcp_server as mcp_facade
from cortex.config.loader import CortexConfig
from cortex.mcp import (
    ServerContext,
    cortex_version,
    create_cortex_mcp_server,
    main,
    server,
)
from cortex.mcp.tools import (
    register_drift_tools,
    register_evolution_tools,
    register_graph_tools,
    register_impact_tools,
    register_intent_tools,
    register_retrieval_tools,
    register_topology_tools,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

EXPECTED_MCP_TOOLS = {
    "cortex_version",
    "cortex_search",
    "cortex_get_repo_contracts",
    "cortex_list_technologies",
    "cortex_get_dependencies",
    "cortex_get_dependents",
    "cortex_get_code_signatures",
    "cortex_get_contract_drift",
    "cortex_get_portfolio_topology",
    "cortex_get_dependency_matrix",
    "cortex_simulate_blast_radius",
    "cortex_trace_impact",
    "cortex_get_contract_timeline",
    "cortex_synthesize_changelog",
    "cortex_simulate_change_intent",
    "cortex_generate_contract_patches",
}


@pytest.mark.anyio
async def test_mcp_modular_complete_tool_registration() -> None:
    """Verify create_cortex_mcp_server registers all domain tools."""
    srv = create_cortex_mcp_server()
    tools = await srv.list_tools()
    tool_names = {t.name for t in tools}

    assert tool_names == EXPECTED_MCP_TOOLS


@pytest.mark.anyio
async def test_mcp_domain_registries_isolation() -> None:
    """Verify each domain tool registry can register tools onto a blank MCPServer."""
    ctx = ServerContext()

    # 1. Retrieval
    s_retrieval = MCPServer(name="test_retrieval")
    register_retrieval_tools(s_retrieval, ctx)
    t_retrieval = {t.name for t in await s_retrieval.list_tools()}
    assert t_retrieval == {
        "cortex_version",
        "cortex_search",
        "cortex_get_repo_contracts",
        "cortex_list_technologies",
    }

    # 2. Graph
    s_graph = MCPServer(name="test_graph")
    register_graph_tools(s_graph, ctx)
    t_graph = {t.name for t in await s_graph.list_tools()}
    assert t_graph == {
        "cortex_get_dependencies",
        "cortex_get_dependents",
        "cortex_get_code_signatures",
    }

    # 3. Drift
    s_drift = MCPServer(name="test_drift")
    register_drift_tools(s_drift, ctx)
    t_drift = {t.name for t in await s_drift.list_tools()}
    assert t_drift == {"cortex_get_contract_drift"}

    # 4. Topology
    s_topology = MCPServer(name="test_topology")
    register_topology_tools(s_topology, ctx)
    t_topology = {t.name for t in await s_topology.list_tools()}
    assert t_topology == {
        "cortex_get_portfolio_topology",
        "cortex_get_dependency_matrix",
    }

    # 5. Impact
    s_impact = MCPServer(name="test_impact")
    register_impact_tools(s_impact, ctx)
    t_impact = {t.name for t in await s_impact.list_tools()}
    assert t_impact == {
        "cortex_simulate_blast_radius",
        "cortex_trace_impact",
    }

    # 6. Evolution
    s_evolution = MCPServer(name="test_evolution")
    register_evolution_tools(s_evolution, ctx)
    t_evolution = {t.name for t in await s_evolution.list_tools()}
    assert t_evolution == {
        "cortex_get_contract_timeline",
        "cortex_synthesize_changelog",
    }

    # 7. Intent
    s_intent = MCPServer(name="test_intent")
    register_intent_tools(s_intent, ctx)
    t_intent = {t.name for t in await s_intent.list_tools()}
    assert t_intent == {
        "cortex_simulate_change_intent",
        "cortex_generate_contract_patches",
    }


def test_server_context_lazy_resolution() -> None:
    """Verify ServerContext caches and provides access to injected components."""
    mock_storage = MagicMock(spec=StorageManager)
    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    cfg = CortexConfig()

    ctx = ServerContext(
        config=cfg,
        pipeline=mock_pipeline,
        storage=mock_storage,
    )

    assert ctx.get_config() is cfg
    assert ctx.get_pipeline() is mock_pipeline
    assert ctx.get_storage() is mock_storage
    # When storage or pipeline is injected, remote client should not be used
    assert ctx.get_remote_client() is None


def test_server_context_remote_resolution() -> None:
    """Verify ServerContext instantiates remote client when hub_url is declared."""
    cfg = CortexConfig()
    cfg.remote.hub_url = "http://localhost:8000"

    ctx = ServerContext(config=cfg)
    client = ctx.get_remote_client()
    assert client is not None
    assert client.mode == "remote"
    # Calling get_remote_client again returns cached instance
    assert ctx.get_remote_client() is client


def test_mcp_facade_reexports() -> None:
    """Verify mcp_server backwards-compatibility façade exports identity symbols."""
    assert mcp_facade.server is server
    assert mcp_facade.create_cortex_mcp_server is create_cortex_mcp_server
    assert mcp_facade.cortex_version is cortex_version
    assert mcp_facade.main is main
    assert hasattr(mcp_facade, "CortexClient")
    assert hasattr(mcp_facade, "ServerContext")
