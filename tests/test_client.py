"""Hermetic tests for CortexClient dual-mode architecture and fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from cortex.client import (
    CortexAuthError,
    CortexClient,
    CortexRemoteError,
)
from cortex.config.loader import CortexConfig, RemoteConfig
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    SearchResultChunk,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager


def _make_dummy_chunk() -> SearchResultChunk:
    return SearchResultChunk(
        id="sample-repo:README.md:c0",
        repo="sample-repo",
        file_path="README.md",
        category=ChunkCategory.DOC,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="Overview",
        score=0.88,
        content="Sample documentation content",
        snippet="Sample documentation content",
        tags=["python"],
    )


def test_client_in_process_mode() -> None:
    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    dummy_chunk = _make_dummy_chunk()
    mock_pipeline.search.return_value = [dummy_chunk]

    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.count_chunks.return_value = 15
    mock_storage.get_repo_contracts.return_value = [
        {
            "file_path": "openapi.json",
            "breadcrumb": "POST /items",
            "category": "contract",
            "tags": ["openapi"],
            "content": "create items",
        }
    ]
    mock_storage.get_technologies.return_value = [{"repo": "sample-repo", "tags": ["python"]}]

    cfg = CortexConfig()
    client = CortexClient(
        mode="in_process",
        config=cfg,
        pipeline=mock_pipeline,
        storage=mock_storage,
    )

    # Health
    health = client.health()
    assert health["status"] == "ok"
    assert health["total_chunks"] == 15
    assert health["mode"] == "in_process"

    # Search
    results = client.search("test query", limit=5)
    assert len(results) == 1
    assert results[0].repo == "sample-repo"
    assert results[0].score == 0.88

    # Search stream
    stream_results = list(client.search_stream("test query"))
    assert len(stream_results) == 1
    assert stream_results[0].id == dummy_chunk.id

    # Contracts
    contracts = client.get_repo_contracts("sample-repo")
    assert len(contracts) == 1
    assert contracts[0].anchor == "[sample-repo] openapi.json > POST /items"

    # Technologies
    tech = client.list_technologies()
    assert tech.total_technologies == 1
    assert tech.technologies[0].technology == "python"

    client.close()


def test_client_remote_mode_with_server() -> None:
    mock_chunk = _make_dummy_chunk()
    api_key = "test-token"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Verify Authorization header
        auth = request.headers.get("authorization")
        if auth != f"Bearer {api_key}":
            return httpx.Response(401, json={"error": "Unauthorized"})

        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "total_chunks": 50})
        elif path == "/search":
            accept = request.headers.get("accept", "")
            if "application/x-ndjson" in accept:
                content = json.dumps(mock_chunk.model_dump(mode="json")) + "\n"
                return httpx.Response(
                    200,
                    content=content.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
            return httpx.Response(200, json=[mock_chunk.model_dump(mode="json")])
        elif path == "/contracts":
            return httpx.Response(
                200,
                json=[
                    {
                        "anchor": "[sample-repo] compose.yaml > worker",
                        "repo": "sample-repo",
                        "file_path": "compose.yaml",
                        "category": "infra",
                        "breadcrumb": "worker",
                        "tags": ["docker"],
                        "content": "image: redis",
                    }
                ],
            )
        elif path == "/technologies":
            return httpx.Response(
                200,
                json={
                    "total_technologies": 1,
                    "technologies": [
                        {
                            "technology": "docker",
                            "repositories": ["sample-repo"],
                            "chunk_count": 1,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    client = CortexClient(
        mode="remote",
        hub_url="http://testserver",
        api_key=api_key,
    )
    client._http_client = httpx.Client(
        transport=httpx.MockTransport(mock_handler),
        headers={"Authorization": f"Bearer {api_key}"},
        base_url="http://testserver",
    )

    # Health
    health = client.health()
    assert health["status"] == "ok"
    assert health["total_chunks"] == 50

    # Search
    results = client.search("overview")
    assert len(results) == 1
    assert results[0].repo == "sample-repo"

    # Streaming Search (NDJSON)
    stream_results = list(client.search_stream("overview"))
    assert len(stream_results) == 1
    assert stream_results[0].id == mock_chunk.id

    # Contracts
    contracts = client.get_repo_contracts("sample-repo")
    assert len(contracts) == 1
    assert contracts[0].file_path == "compose.yaml"

    # Technologies
    tech = client.list_technologies()
    assert tech.total_technologies == 1
    assert tech.technologies[0].technology == "docker"

    client.close()


def test_client_remote_auth_failure() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    client = CortexClient(
        mode="remote",
        hub_url="http://testserver",
        api_key="wrong-secret",
    )
    client._http_client = httpx.Client(
        transport=httpx.MockTransport(mock_handler),
        headers={"Authorization": "Bearer wrong-secret"},
        base_url="http://testserver",
    )

    with pytest.raises(CortexAuthError):
        client.search("test")

    with pytest.raises(CortexAuthError):
        list(client.search_stream("test"))

    with pytest.raises(CortexAuthError):
        client.get_repo_contracts("test-repo")

    with pytest.raises(CortexAuthError):
        client.list_technologies()

    client.close()


def test_client_auto_fallback_when_remote_down() -> None:
    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    dummy_chunk = _make_dummy_chunk()
    mock_pipeline.search.return_value = [dummy_chunk]

    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.count_chunks.return_value = 25
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_technologies.return_value = []

    cfg = CortexConfig(remote=RemoteConfig(hub_url="http://offline-hub:8000"))

    # Transport that always raises ConnectError
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by test mock")

    client = CortexClient(
        mode="auto",
        config=cfg,
        pipeline=mock_pipeline,
        storage=mock_storage,
    )
    client._http_client = httpx.Client(
        transport=httpx.MockTransport(mock_handler),
        base_url="http://offline-hub:8000",
    )

    # Health check falls back to local
    health = client.health()
    assert health["status"] == "ok"
    assert health["total_chunks"] == 25
    assert health["mode"] == "in_process"

    # Search falls back to local
    results = client.search("query")
    assert len(results) == 1
    assert results[0].repo == "sample-repo"

    # Streaming search falls back to local
    stream_results = list(client.search_stream("query"))
    assert len(stream_results) == 1

    # Contracts falls back to local
    contracts = client.get_repo_contracts("sample-repo")
    assert contracts == []

    # Technologies falls back to local
    tech = client.list_technologies()
    assert tech.total_technologies == 0

    client.close()


def test_client_remote_mode_without_hub_url_raises() -> None:
    cfg = CortexConfig(remote=RemoteConfig(hub_url=None))
    with pytest.raises(ValueError, match="Remote mode requested but no hub_url"):
        CortexClient(mode="remote", config=cfg)


def test_client_context_manager() -> None:
    cfg = CortexConfig()
    with CortexClient(mode="in_process", config=cfg) as client:
        assert client.mode == "in_process"
    # Verify client closed cleanly


def test_client_remote_mode_connection_error_raises() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to connect")

    client = CortexClient(mode="remote", hub_url="http://bad-hub:8000")
    client._http_client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    with pytest.raises(CortexRemoteError, match="Remote health check failed"):
        client.health()

    with pytest.raises(CortexRemoteError, match="Remote search failed"):
        client.search("test")

    with pytest.raises(CortexRemoteError, match="Remote streaming search failed"):
        list(client.search_stream("test"))

    with pytest.raises(CortexRemoteError, match="Remote get_repo_contracts failed"):
        client.get_repo_contracts("repo")

    with pytest.raises(CortexRemoteError, match="Remote list_technologies failed"):
        client.list_technologies()

    client.close()
