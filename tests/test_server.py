"""Hermetic tests for agent-cortex daemon server."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.config.loader import CortexConfig
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    SearchResultChunk,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def _make_dummy_chunk() -> SearchResultChunk:
    return SearchResultChunk(
        id="test-repo:docs/guide.md:c1",
        repo="test-repo",
        file_path="docs/guide.md",
        category=ChunkCategory.DOC,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="Getting Started",
        score=0.92,
        content="# Getting Started\nThis is a test guide.",
        snippet="This is a test guide.",
        tags=["python", "fastapi"],
    )


def test_server_health_unauthenticated() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.count_chunks.return_value = 42

    cfg = CortexConfig()
    app = create_app(config=cfg, storage=mock_storage, api_key=None)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["total_chunks"] == 42
    assert "version" in data
    assert "profile" in data


def test_server_auth_enforcement() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.count_chunks.return_value = 10
    mock_storage.get_repo_contracts.return_value = []
    mock_storage.get_technologies.return_value = []

    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    mock_pipeline.search.return_value = []

    cfg = CortexConfig()
    api_key = "super-secret-token"
    app = create_app(
        config=cfg,
        pipeline=mock_pipeline,
        storage=mock_storage,
        api_key=api_key,
    )
    client = TestClient(app)

    # /health is always permitted without auth
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    # /search without auth header -> 401
    search_resp = client.get("/search?query=hello")
    assert search_resp.status_code == 401
    assert search_resp.json()["error"] == "Unauthorized"

    # /search with wrong auth token -> 401
    bad_auth = client.get("/search?query=hello", headers={"Authorization": "Bearer wrong-token"})
    assert bad_auth.status_code == 401

    # /search with invalid scheme -> 401
    bad_scheme = client.get("/search?query=hello", headers={"Authorization": "Basic 12345"})
    assert bad_scheme.status_code == 401

    # /search with valid token -> 200
    good_auth = client.get(
        "/search?query=hello",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert good_auth.status_code == 200


def test_server_search_json_and_ndjson() -> None:
    mock_chunk = _make_dummy_chunk()
    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    mock_pipeline.search.return_value = [mock_chunk]

    mock_storage = MagicMock(spec=StorageManager)

    cfg = CortexConfig()
    app = create_app(config=cfg, pipeline=mock_pipeline, storage=mock_storage, api_key=None)
    client = TestClient(app)

    # Empty query -> empty list
    empty_resp = client.get("/search?query=")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []

    # GET /search standard JSON
    resp = client.get("/search?query=guide&limit=5&scope=internal&category=doc&rerank=true")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    results = resp.json()
    assert len(results) == 1
    assert results[0]["repo"] == "test-repo"
    assert results[0]["anchor"] == "[test-repo] docs/guide.md > Getting Started"
    assert results[0]["score"] == 0.92

    # POST /search JSON body
    post_resp = client.post(
        "/search",
        json={"query": "guide", "limit": 5, "scopes": ["internal"], "category": "doc"},
    )
    assert post_resp.status_code == 200
    assert len(post_resp.json()) == 1

    # NDJSON streaming via Accept header
    ndjson_resp = client.get(
        "/search?query=guide",
        headers={"Accept": "application/x-ndjson"},
    )
    assert ndjson_resp.status_code == 200
    assert "application/x-ndjson" in ndjson_resp.headers["content-type"]
    lines = [line for line in ndjson_resp.text.strip().split("\n") if line.strip()]
    assert len(lines) == 1
    item = json.loads(lines[0])
    assert item["id"] == "test-repo:docs/guide.md:c1"
    assert item["anchor"] == "[test-repo] docs/guide.md > Getting Started"

    # NDJSON streaming via ?stream=true parameter
    stream_resp = client.get("/search?query=guide&stream=true")
    assert stream_resp.status_code == 200
    assert "application/x-ndjson" in stream_resp.headers["content-type"]


def test_server_search_validation_errors() -> None:
    mock_pipeline = MagicMock(spec=HybridRetrievalPipeline)
    mock_storage = MagicMock(spec=StorageManager)

    app = create_app(pipeline=mock_pipeline, storage=mock_storage, api_key=None)
    client = TestClient(app)

    # Invalid scope
    resp_scope = client.get("/search?query=test&scope=unknown_scope")
    assert resp_scope.status_code == 400
    assert "Invalid scope" in resp_scope.json()["detail"]

    # Invalid category
    resp_cat = client.get("/search?query=test&category=invalid_category")
    assert resp_cat.status_code == 400
    assert "Invalid category" in resp_cat.json()["detail"]


def test_server_contracts_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.get_repo_contracts.return_value = [
        {
            "file_path": "specs/openapi.json",
            "breadcrumb": "GET /deals",
            "category": "contract",
            "tags": ["openapi", "deals"],
            "content": "Operation: GET /deals",
        }
    ]

    app = create_app(storage=mock_storage, api_key=None)
    client = TestClient(app)

    # Missing repo parameter -> 400
    bad_resp = client.get("/contracts")
    assert bad_resp.status_code == 400

    # Valid repo
    resp = client.get("/contracts?repo=sentinel&contract_type=openapi&limit=10")
    assert resp.status_code == 200
    contracts = resp.json()
    assert len(contracts) == 1
    assert contracts[0]["anchor"] == "[sentinel] specs/openapi.json > GET /deals"
    assert contracts[0]["category"] == "contract"
    assert contracts[0]["tags"] == ["openapi", "deals"]


def test_server_technologies_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.get_technologies.return_value = [
        {"repo": "repo-a", "tags": ["fastapi", "docker"]},
        {"repo": "repo-b", "tags": ["fastapi", "lancedb"]},
    ]

    app = create_app(storage=mock_storage, api_key=None)
    client = TestClient(app)

    resp = client.get("/technologies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_technologies"] == 3
    tech_map = {t["technology"]: t for t in data["technologies"]}
    assert "fastapi" in tech_map
    assert tech_map["fastapi"]["chunk_count"] == 2
    assert sorted(tech_map["fastapi"]["repositories"]) == ["repo-a", "repo-b"]
