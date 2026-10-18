"""Hermetic tests for multi-tenant dynamic configuration resolution on cortex server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig
from cortex.models.profile import HardwareProfileName
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_server_dynamic_config_crud_endpoints(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    app = create_app(
        config=base_cfg,
        storage=storage_mgr,
        dynamic_config=dyn_mgr,
    )
    client = TestClient(app)

    # 1. Health endpoint includes tenant count
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["tenants_count"] == 0

    # 2. GET /config defaults to fallback
    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json()["profile"] == "balanced"

    # 3. POST /config for default tenant
    resp = client.post(
        "/config",
        json={
            "tenant_id": "default",
            "config": {"profile": "high", "retrieval": {"default_limit": 25}},
            "description": "Global default high-precision profile",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify GET /config reflects updated default
    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json()["profile"] == "high"
    assert resp.json()["retrieval"]["default_limit"] == 25

    # 4. POST /config for specific tenant via X-Tenant-ID header
    resp = client.post(
        "/config",
        headers={"X-Tenant-ID": "team-fast"},
        json={
            "config": {"profile": "low", "retrieval": {"default_limit": 5}},
            "description": "Low-latency profile for fast agents",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "team-fast"

    # 5. GET /config with X-Tenant-ID
    resp = client.get("/config", headers={"X-Tenant-ID": "team-fast"})
    assert resp.status_code == 200
    assert resp.json()["profile"] == "low"
    assert resp.json()["retrieval"]["default_limit"] == 5

    # 6. GET /config/raw
    resp = client.get("/config/raw", headers={"X-Tenant-ID": "team-fast"})
    assert resp.status_code == 200
    assert resp.json()["configured"] is True
    assert resp.json()["config"]["profile"] == "low"

    # 7. GET /tenants
    resp = client.get("/tenants")
    assert resp.status_code == 200
    tenant_ids = [t["tenant_id"] for t in resp.json()["tenants"]]
    assert "default" in tenant_ids
    assert "team-fast" in tenant_ids

    # 8. DELETE /config
    resp = client.delete("/config", headers={"X-Tenant-ID": "team-fast"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # After deletion, team-fast falls back to default DB config
    resp = client.get("/config", headers={"X-Tenant-ID": "team-fast"})
    assert resp.status_code == 200
    assert resp.json()["profile"] == "high"


def test_server_multi_tenant_search_resolution(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    # Configure custom limit for tenant-a
    dyn_mgr.set_tenant_config("tenant-a", {"retrieval": {"default_limit": 3}})
    # Configure custom limit for tenant-b
    dyn_mgr.set_tenant_config("tenant-b", {"retrieval": {"default_limit": 12}})

    mock_pipeline = MagicMock()
    mock_pipeline.search.return_value = []

    app = create_app(
        config=base_cfg,
        pipeline=mock_pipeline,
        storage=storage_mgr,
        dynamic_config=dyn_mgr,
    )
    client = TestClient(app)

    # Search with tenant-a (no explicit limit passed)
    resp = client.post(
        "/search",
        headers={"X-Tenant-ID": "tenant-a"},
        json={"query": "deals contract"},
    )
    assert resp.status_code == 200
    # Ensure default_limit=3 from tenant-a was used
    mock_pipeline.search.assert_called_with(
        query="deals contract",
        limit=3,
        scopes=None,
        include_archived=False,
        category=None,
        repo=None,
        rerank=True,
    )

    # Search with tenant-b in body param
    resp = client.post(
        "/search",
        json={"query": "worker docker", "tenant_id": "tenant-b"},
    )
    assert resp.status_code == 200
    mock_pipeline.search.assert_called_with(
        query="worker docker",
        limit=12,
        scopes=None,
        include_archived=False,
        category=None,
        repo=None,
        rerank=True,
    )


def test_server_tenant_bearer_token_authentication(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    # Configure tenant with its own API key
    dyn_mgr.set_tenant_config(
        "tenant-secret",
        {
            "profile": "high",
            "remote": {"api_key": "secret-token-123"},
        },
    )

    mock_pipeline = MagicMock()
    mock_pipeline.search.return_value = []

    app = create_app(
        config=base_cfg,
        pipeline=mock_pipeline,
        storage=storage_mgr,
        api_key="global-admin-key",
        dynamic_config=dyn_mgr,
    )
    client = TestClient(app)

    # 1. Unauthenticated request gets 401
    resp = client.get("/config")
    assert resp.status_code == 401

    # 2. Invalid token gets 401
    resp = client.get("/config", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401

    # 3. Global admin token succeeds
    resp = client.get("/config", headers={"Authorization": "Bearer global-admin-key"})
    assert resp.status_code == 200

    # 4. Tenant secret token automatically authenticates and resolves to tenant-secret
    resp = client.get("/config", headers={"Authorization": "Bearer secret-token-123"})
    assert resp.status_code == 200
    assert resp.json()["profile"] == "high"

    # 5. Tenant token attempting to read or mutate another tenant gets 403 Forbidden
    resp = client.get(
        "/config",
        headers={
            "Authorization": "Bearer secret-token-123",
            "X-Tenant-ID": "other-tenant",
        },
    )
    assert resp.status_code == 403

    resp = client.post(
        "/config",
        headers={"Authorization": "Bearer secret-token-123"},
        json={"tenant_id": "other-tenant", "config": {"profile": "low"}},
    )
    assert resp.status_code == 403

    resp = client.delete(
        "/config",
        headers={
            "Authorization": "Bearer secret-token-123",
            "X-Tenant-ID": "other-tenant",
        },
    )
    assert resp.status_code == 403

    # 6. Tenant token attempting /search with another tenant gets 403 Forbidden
    resp = client.post(
        "/search",
        headers={
            "Authorization": "Bearer secret-token-123",
            "X-Tenant-ID": "other-tenant",
        },
        json={"query": "test"},
    )
    assert resp.status_code == 403

    # 7. Tenant token calling /tenants only sees its own tenant record
    dyn_mgr.set_tenant_config("other-tenant", {"profile": "low"})
    resp = client.get("/tenants", headers={"Authorization": "Bearer secret-token-123"})
    assert resp.status_code == 200
    assert resp.json()["total_tenants"] == 1
    assert resp.json()["tenants"][0]["tenant_id"] == "tenant-secret"
