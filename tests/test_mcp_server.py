"""Hermetic tests for Model Context Protocol (MCP) server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cortex.mcp_server import create_cortex_mcp_server
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
    SearchResultChunk,
)
from cortex.storage.manager import StorageManager


@pytest.mark.anyio
async def test_mcp_tool_registration() -> None:
    server = create_cortex_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "cortex_version" in tool_names
    assert "cortex_search" in tool_names
    assert "cortex_get_repo_contracts" in tool_names
    assert "cortex_list_technologies" in tool_names


@pytest.mark.anyio
async def test_mcp_cortex_version() -> None:
    from cortex import __version__

    server = create_cortex_mcp_server()
    res = await server.call_tool("cortex_version", {})

    assert not res.is_error
    assert f"agent-cortex v{__version__}" in str(res.content)


@pytest.mark.anyio
async def test_mcp_search_empty_query() -> None:
    server = create_cortex_mcp_server()
    res = await server.call_tool("cortex_search", {"query": "   "})

    assert not res.is_error
    assert res.structured_content == {"result": []}


@pytest.mark.anyio
async def test_mcp_search_with_mock_pipeline() -> None:
    mock_pipeline = MagicMock()
    chunk = SearchResultChunk(
        id="sentinel:specs/openapi.json:get_deals",
        repo="sentinel",
        file_path="specs/openapi.json",
        category=ChunkCategory.CONTRACT,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="GET /deals",
        score=0.9412,
        content="GET /deals retrieves all active deals from the datastore.",
        snippet="GET /deals retrieves all active deals",
        tags=["deals", "GET"],
    )
    mock_pipeline.search.return_value = [chunk]

    server = create_cortex_mcp_server(pipeline=mock_pipeline)
    res = await server.call_tool(
        "cortex_search",
        {
            "query": "deals endpoint",
            "limit": 5,
            "scope": "internal,public",
            "category": "contract",
            "repo": "sentinel",
            "rerank": True,
        },
    )

    assert not res.is_error
    mock_pipeline.search.assert_called_once_with(
        query="deals endpoint",
        limit=5,
        scopes=[ChunkScope.INTERNAL, ChunkScope.PUBLIC],
        category=ChunkCategory.CONTRACT,
        repo="sentinel",
        rerank=True,
    )

    structured = res.structured_content
    assert structured is not None
    assert len(structured["result"]) == 1
    item = structured["result"][0]
    assert item["anchor"] == "[sentinel] specs/openapi.json > GET /deals"
    assert item["repo"] == "sentinel"
    assert item["file_path"] == "specs/openapi.json"
    assert item["category"] == "contract"
    assert item["scope"] == "internal"
    assert item["score"] == 0.9412
    assert "GET /deals retrieves all active deals" in item["snippet"]
    assert item["tags"] == ["deals", "GET"]


@pytest.mark.anyio
async def test_mcp_get_repo_contracts_empty_repo() -> None:
    server = create_cortex_mcp_server()
    res = await server.call_tool("cortex_get_repo_contracts", {"repo": "  "})

    assert not res.is_error
    assert res.structured_content == {"result": []}


@pytest.mark.anyio
async def test_mcp_get_repo_contracts_with_mock_storage() -> None:
    mock_storage = MagicMock()
    mock_storage.get_repo_contracts.return_value = [
        {
            "repo": "clipflow",
            "file_path": "compose.yaml",
            "category": "infra",
            "breadcrumb": "services > worker",
            "tags": ["infra", "docker-compose", "worker"],
            "content": "### Service: worker\n- **Image:** `worker:latest`",
        },
        {
            "repo": "clipflow",
            "file_path": "specs/openapi.json",
            "category": "contract",
            "breadcrumb": "POST /render",
            "tags": ["POST", "render"],
            "content": "### POST /render\n**Summary:** Render video job",
        },
    ]

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool(
        "cortex_get_repo_contracts",
        {"repo": "clipflow", "contract_type": "all", "limit": 20},
    )

    assert not res.is_error
    mock_storage.get_repo_contracts.assert_called_once_with(
        repo="clipflow",
        categories=["contract", "infra", "invariant"],
        limit=20,
    )

    structured = res.structured_content
    assert structured is not None
    items = structured["result"]
    assert len(items) == 2
    assert items[0]["anchor"] == "[clipflow] compose.yaml > services > worker"
    assert items[0]["category"] == "infra"
    assert items[1]["anchor"] == "[clipflow] specs/openapi.json > POST /render"
    assert items[1]["category"] == "contract"


@pytest.mark.anyio
async def test_mcp_get_repo_contracts_types() -> None:
    mock_storage = MagicMock()
    mock_storage.get_repo_contracts.return_value = []

    server = create_cortex_mcp_server(storage=mock_storage)

    # openapi
    await server.call_tool(
        "cortex_get_repo_contracts",
        {"repo": "sentinel", "contract_type": "openapi"},
    )
    mock_storage.get_repo_contracts.assert_called_with(
        repo="sentinel", categories=["contract"], limit=50
    )

    # compose
    await server.call_tool(
        "cortex_get_repo_contracts",
        {"repo": "sentinel", "contract_type": "compose"},
    )
    mock_storage.get_repo_contracts.assert_called_with(
        repo="sentinel", categories=["infra"], limit=50
    )

    # invariant
    await server.call_tool(
        "cortex_get_repo_contracts",
        {"repo": "sentinel", "contract_type": "invariant"},
    )
    mock_storage.get_repo_contracts.assert_called_with(
        repo="sentinel", categories=["invariant"], limit=50
    )


@pytest.mark.anyio
async def test_mcp_list_technologies_all() -> None:
    mock_storage = MagicMock()
    mock_storage.get_technologies.return_value = [
        {"repo": "backend-a", "tags": ["fastapi", "postgres", "redis"]},
        {"repo": "backend-b", "tags": ["fastapi", "sqlite"]},
        {"repo": "worker-c", "tags": ["celery", "redis"]},
    ]

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool("cortex_list_technologies", {})

    assert not res.is_error
    structured = res.structured_content
    assert structured is not None
    summary = structured
    assert summary["total_technologies"] == 5

    tech_dict = {t["technology"]: t for t in summary["technologies"]}
    assert tech_dict["fastapi"]["chunk_count"] == 2
    assert tech_dict["fastapi"]["repositories"] == ["backend-a", "backend-b"]
    assert tech_dict["redis"]["chunk_count"] == 2
    assert tech_dict["redis"]["repositories"] == ["backend-a", "worker-c"]
    assert tech_dict["postgres"]["chunk_count"] == 1


@pytest.mark.anyio
async def test_mcp_list_technologies_filtered_by_name() -> None:
    mock_storage = MagicMock()
    mock_storage.get_technologies.return_value = [
        {"repo": "sentinel", "tags": ["fastapi", "lancedb"]},
        {"repo": "maestri", "tags": ["fastapi", "electron"]},
        {"repo": "clipflow", "tags": ["ffmpeg", "redis"]},
    ]

    server = create_cortex_mcp_server(storage=mock_storage)
    res = await server.call_tool("cortex_list_technologies", {"tech_name": "fastapi"})

    assert not res.is_error
    structured = res.structured_content
    assert structured is not None
    assert structured["total_technologies"] == 1
    tech = structured["technologies"][0]
    assert tech["technology"] == "fastapi"
    assert tech["repositories"] == ["maestri", "sentinel"]
    assert tech["chunk_count"] == 2


@pytest.mark.anyio
async def test_mcp_live_storage_integration(tmp_path: Path) -> None:
    """Test MCP tools against live LanceDB instance with real upserted DocumentChunks."""
    storage = StorageManager(data_dir=tmp_path / "data")
    chunks = [
        DocumentChunk(
            id="test-repo:specs/openapi.json:get_items",
            repo="test-repo",
            file_path="specs/openapi.json",
            category=ChunkCategory.CONTRACT,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
            breadcrumb="GET /items",
            commit_sha="abcdef123456",
            tags=["items", "GET", "fastapi"],
            content="### GET /items\nList all items.",
            vector=[0.1, 0.2, 0.3, 0.4],
        ),
        DocumentChunk(
            id="test-repo:compose.yaml:service_redis",
            repo="test-repo",
            file_path="compose.yaml",
            category=ChunkCategory.INFRA,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
            breadcrumb="services > redis",
            commit_sha="abcdef123456",
            tags=["infra", "docker-compose", "redis"],
            content="### Service: redis\n- Image: redis:7-alpine",
            vector=[0.2, 0.1, 0.4, 0.3],
        ),
        DocumentChunk(
            id="other-repo:README.md:main",
            repo="other-repo",
            file_path="README.md",
            category=ChunkCategory.DOC,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.PUBLIC,
            breadcrumb="Overview",
            commit_sha="fedcba654321",
            tags=["documentation", "fastapi"],
            content="# Other Repo\nBuilt with FastAPI.",
            vector=[0.4, 0.3, 0.2, 0.1],
        ),
    ]
    storage.upsert_chunks(chunks, dim=4)

    server = create_cortex_mcp_server(storage=storage)

    # Test cortex_get_repo_contracts via MCP protocol
    res_contracts = await server.call_tool("cortex_get_repo_contracts", {"repo": "test-repo"})
    assert not res_contracts.is_error
    structured_contracts = res_contracts.structured_content
    assert structured_contracts is not None
    assert len(structured_contracts["result"]) == 2
    paths = {c["file_path"] for c in structured_contracts["result"]}
    assert paths == {"specs/openapi.json", "compose.yaml"}

    # Test cortex_list_technologies across repos via MCP protocol
    res_tech = await server.call_tool("cortex_list_technologies", {})
    assert not res_tech.is_error
    structured_tech = res_tech.structured_content
    assert structured_tech is not None
    tech_map = {t["technology"]: t for t in structured_tech["technologies"]}
    assert "fastapi" in tech_map
    assert set(tech_map["fastapi"]["repositories"]) == {"test-repo", "other-repo"}
    assert "redis" in tech_map
    assert tech_map["redis"]["repositories"] == ["test-repo"]


@pytest.mark.anyio
async def test_mcp_dual_mode_remote_client() -> None:
    """Verify MCP tools delegate to CortexClient when configured in Dual-Mode."""
    from cortex.models.chunk import RepoContractChunk, TechSummary, TechUsage

    mock_client = MagicMock()
    mock_client.search.return_value = [
        SearchResultChunk(
            id="remote-repo:README.md:c0",
            repo="remote-repo",
            file_path="README.md",
            category=ChunkCategory.DOC,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
            breadcrumb="Architecture",
            score=0.88,
            content="Remote hub architecture overview.",
            snippet="Remote hub architecture",
            tags=["architecture"],
        )
    ]
    mock_client.get_repo_contracts.return_value = [
        RepoContractChunk(
            anchor="[remote-repo] specs/openapi.json > GET /status",
            repo="remote-repo",
            file_path="specs/openapi.json",
            category="contract",
            breadcrumb="GET /status",
            tags=["GET", "status"],
            content="### GET /status\nHealth status.",
        )
    ]
    mock_client.list_technologies.return_value = TechSummary(
        total_technologies=1,
        technologies=[
            TechUsage(
                technology="fastapi",
                repositories=["remote-repo"],
                chunk_count=3,
            )
        ],
    )

    server = create_cortex_mcp_server(client=mock_client)

    # 1. cortex_search
    res = await server.call_tool("cortex_search", {"query": "hub architecture", "limit": 3})
    assert not res.is_error
    mock_client.search.assert_called_once_with(
        query="hub architecture",
        limit=3,
        scopes=None,
        category=None,
        repo=None,
        rerank=True,
    )
    structured = res.structured_content
    assert structured is not None
    assert structured["result"][0]["repo"] == "remote-repo"

    # 2. cortex_get_repo_contracts
    res_contracts = await server.call_tool(
        "cortex_get_repo_contracts",
        {"repo": "remote-repo", "contract_type": "openapi", "limit": 10},
    )
    assert not res_contracts.is_error
    mock_client.get_repo_contracts.assert_called_once_with(
        repo="remote-repo",
        contract_type="openapi",
        limit=10,
    )
    structured_contracts = res_contracts.structured_content
    assert structured_contracts is not None
    assert structured_contracts["result"][0]["anchor"] == (
        "[remote-repo] specs/openapi.json > GET /status"
    )

    # 3. cortex_list_technologies
    res_tech = await server.call_tool(
        "cortex_list_technologies",
        {"tech_name": "fastapi", "repo": "remote-repo"},
    )
    assert not res_tech.is_error
    mock_client.list_technologies.assert_called_once_with(
        tech_name="fastapi",
        repo="remote-repo",
    )
    structured_tech = res_tech.structured_content
    assert structured_tech is not None
    assert structured_tech["total_technologies"] == 1
    assert structured_tech["technologies"][0]["technology"] == "fastapi"
