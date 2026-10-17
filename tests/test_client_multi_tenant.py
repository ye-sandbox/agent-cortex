"""Hermetic tests for dual-mode CortexClient multi-tenant resolution and dynamic configuration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from cortex.client import CortexClient
from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig
from cortex.models.profile import HardwareProfileName
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_client_local_dynamic_config_lifecycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    with CortexClient(
        mode="in_process",
        tenant_id="alpha-tenant",
        config=base_cfg,
        storage=storage_mgr,
        dynamic_config=dyn_mgr,
    ) as client:
        # Default resolved config matches base fallback
        initial_cfg = client.get_config()
        assert initial_cfg["profile"] == "balanced"

        # Update dynamic config for this tenant
        res = client.set_config(
            {"profile": "low", "retrieval": {"default_limit": 7}},
            description="Alpha low-latency tier",
        )
        assert res["status"] == "ok"
        assert res["tenant_id"] == "alpha-tenant"

        # Read back config
        updated_cfg = client.get_config()
        assert updated_cfg["profile"] == "low"
        assert updated_cfg["retrieval"]["default_limit"] == 7

        # List tenants
        tenants = client.list_tenants()
        assert any(t["tenant_id"] == "alpha-tenant" for t in tenants)

        # Delete config
        assert client.delete_config() is True

        # Reverts to base fallback
        reverted_cfg = client.get_config()
        assert reverted_cfg["profile"] == "balanced"


def test_client_remote_dynamic_config_lifecycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    app = create_app(
        config=base_cfg,
        storage=storage_mgr,
        dynamic_config=dyn_mgr,
    )

    # Use Starlette TestClient transport for httpx inside CortexClient
    starlette_test_client = TestClient(app)

    with CortexClient(
        mode="remote",
        hub_url="http://mock-hub:8000",
        tenant_id="remote-tenant-1",
        config=base_cfg,
    ) as client:
        # Route internal httpx client through Starlette TestClient transport
        client._http_client = starlette_test_client

        # Initial config
        cfg = client.get_config()
        assert cfg["profile"] == "balanced"

        # Upsert dynamic config
        res = client.set_config({"profile": "high", "retrieval": {"default_limit": 22}})
        assert res["status"] == "ok"
        assert res["tenant_id"] == "remote-tenant-1"

        # Verify updated
        updated = client.get_config()
        assert updated["profile"] == "high"
        assert updated["retrieval"]["default_limit"] == 22

        # List tenants
        tenants = client.list_tenants()
        assert any(t["tenant_id"] == "remote-tenant-1" for t in tenants)

        # Delete tenant
        assert client.delete_config() is True
        assert client.delete_config() is False


def test_client_local_search_tenant_default_limit(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    dyn_mgr = DynamicConfigManager(data_dir=data_dir)
    storage_mgr = StorageManager(data_dir=data_dir)
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)

    # Set custom default_limit for tenant
    dyn_mgr.set_tenant_config("tenant-fast", {"retrieval": {"default_limit": 4}})

    mock_pipeline = MagicMock()
    mock_pipeline.search.return_value = []

    with CortexClient(
        mode="in_process",
        tenant_id="tenant-fast",
        config=base_cfg,
        pipeline=mock_pipeline,
        storage=storage_mgr,
        dynamic_config=dyn_mgr,
    ) as client:
        # When limit=None, client should resolve tenant-fast's default_limit (4)
        client.search(query="auth pattern")
        mock_pipeline.search.assert_called_with(
            query="auth pattern",
            limit=4,
            scopes=None,
            include_archived=False,
            category=None,
            repo=None,
            rerank=True,
        )
