"""Hermetic tests for server /sync endpoint and client sync integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.loader import CortexConfig, RepositorySourceConfig
from cortex.ingestion.models import SyncResult
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_server_sync_endpoint_auth_required() -> None:
    """Verify /sync requires valid Bearer token when api_key is configured."""
    cfg = CortexConfig()
    app = create_app(config=cfg, api_key="secret-token-123")
    client = TestClient(app)

    # 1. Missing header
    res_no_auth = client.post("/sync", json={"all": True})
    assert res_no_auth.status_code == 401

    # 2. Invalid token
    res_bad_auth = client.post(
        "/sync",
        headers={"Authorization": "Bearer wrong-token"},
        json={"all": True},
    )
    assert res_bad_auth.status_code == 401


def test_server_sync_endpoint_execution(tmp_path: Path) -> None:
    """Verify /sync executes IngestionEngine.sync_all and returns result payload."""
    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir()

    cfg = CortexConfig()
    cfg.sources.repositories = [RepositorySourceConfig(path=repo_dir, name="repo1")]

    app = create_app(config=cfg, api_key="test-key")
    client = TestClient(app)

    dummy_result = SyncResult(
        repo="repo1",
        base_commit="c1",
        target_commit="c2",
        added_chunks=3,
        updated_chunks=1,
        deleted_chunks=0,
        processed_files=2,
        duration_seconds=0.45,
    )

    with patch("cortex.server.IngestionEngine.from_config") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.sync_all.return_value = [dummy_result]
        mock_engine_factory.return_value = mock_engine

        res = client.post(
            "/sync",
            headers={"Authorization": "Bearer test-key"},
            json={"all": True},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["total_synced"] == 1
        assert len(data["synced"]) == 1
        assert data["synced"][0]["repo"] == "repo1"
        assert data["synced"][0]["added_chunks"] == 3


def test_server_sync_endpoint_repo_not_found() -> None:
    """Verify /sync returns 404 when requested repo is not discovered or configured."""
    cfg = CortexConfig()
    app = create_app(config=cfg, api_key="test-key")
    client = TestClient(app)

    res = client.post(
        "/sync",
        headers={"Authorization": "Bearer test-key"},
        json={"repo": "unknown-repo"},
    )
    assert res.status_code == 404
    assert res.json()["status"] == "not_found"


def test_server_health_includes_watcher_status(tmp_path: Path) -> None:
    """Verify /health reflects active watcher status when watch=True."""
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.count_chunks.return_value = 10

    cfg = CortexConfig()
    cfg.storage.data_dir = tmp_path / "data"

    app = create_app(
        config=cfg,
        storage=mock_storage,
        watch=True,
        watch_interval=60.0,
    )

    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert "watcher" in data
        assert data["watcher"]["is_running"] is True
        assert data["watcher"]["interval_seconds"] == 60.0


def test_client_sync_remote_mode() -> None:
    """Verify CortexClient.sync sends POST /sync in remote hub mode."""
    cfg = CortexConfig()
    cfg.remote.hub_url = "http://homelab:8000"
    cfg.remote.api_key = "remote-key"

    client = CortexClient(mode="remote", config=cfg)

    dummy_payload = {
        "status": "ok",
        "total_synced": 1,
        "synced": [{"repo": "remote-repo", "added_chunks": 5}],
    }

    with patch.object(client._http_client, "post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dummy_payload
        mock_post.return_value = mock_resp

        res = client.sync(repo="remote-repo", all_repos=False)

        assert res["status"] == "ok"
        assert res["total_synced"] == 1
        mock_post.assert_called_once_with(
            "http://homelab:8000/sync",
            json={"repo": "remote-repo", "all": False, "force_full": False},
        )
