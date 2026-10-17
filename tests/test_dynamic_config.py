"""Hermetic tests for dynamic configuration manager and static migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortex.config.dynamic import DynamicConfigManager, deep_merge
from cortex.config.loader import CortexConfig
from cortex.config.migration import migrate_static_to_db
from cortex.models.profile import HardwareProfileName


def test_deep_merge_basic_and_nested() -> None:
    base = {"a": 1, "nested": {"x": 10, "y": 20}, "list": [1, 2]}
    override = {"nested": {"y": 99, "z": 30}, "b": 2}
    merged = deep_merge(base, override)

    assert merged["a"] == 1
    assert merged["b"] == 2
    assert merged["nested"]["x"] == 10
    assert merged["nested"]["y"] == 99
    assert merged["nested"]["z"] == 30
    assert merged["list"] == [1, 2]


def test_dynamic_config_manager_lifecycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    mgr = DynamicConfigManager(data_dir=data_dir)

    # Initial state
    assert mgr.list_tenants() == []
    assert mgr.get_raw_config("default") is None

    # Base config fallback
    base_cfg = CortexConfig(profile=HardwareProfileName.BALANCED)
    resolved = mgr.get_tenant_config("default", fallback=base_cfg)
    assert resolved.profile == HardwareProfileName.BALANCED

    # Set default tenant config
    mgr.set_tenant_config("default", {"profile": "high", "retrieval": {"default_limit": 42}})
    assert mgr.get_raw_config("default") == {
        "profile": "high",
        "retrieval": {"default_limit": 42},
    }

    resolved_default = mgr.get_tenant_config("default", fallback=base_cfg)
    assert resolved_default.profile == HardwareProfileName.HIGH
    assert resolved_default.retrieval.default_limit == 42
    # Verify unoverridden fields inherit from fallback
    assert resolved_default.retrieval.k == 60

    # Set specific tenant config ("fast-agent")
    mgr.set_tenant_config(
        "fast-agent",
        {"profile": "low", "retrieval": {"default_limit": 5}},
        description="Low-latency tier for fast agents",
    )

    resolved_fast = mgr.get_tenant_config("fast-agent", fallback=base_cfg)
    assert resolved_fast.profile == HardwareProfileName.LOW
    assert resolved_fast.retrieval.default_limit == 5

    # List tenants
    tenants = mgr.list_tenants()
    tenant_ids = {t["tenant_id"] for t in tenants}
    assert "default" in tenant_ids
    assert "fast-agent" in tenant_ids

    # Delete tenant
    assert mgr.delete_tenant_config("fast-agent") is True
    assert mgr.delete_tenant_config("fast-agent") is False
    assert mgr.get_raw_config("fast-agent") is None

    # Deleted tenant falls back to default DB config
    resolved_after_delete = mgr.get_tenant_config("fast-agent", fallback=base_cfg)
    assert resolved_after_delete.profile == HardwareProfileName.HIGH
    assert resolved_after_delete.retrieval.default_limit == 42


def test_dynamic_config_validation_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    mgr = DynamicConfigManager(data_dir=data_dir)

    with pytest.raises(ValueError, match="tenant_id cannot be empty"):
        mgr.set_tenant_config("", {"profile": "low"})

    with pytest.raises(ValueError):
        # Invalid profile name should fail Pydantic validation
        mgr.set_tenant_config("tenant1", {"profile": "invalid-profile-xyz"})


def test_migrate_static_to_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "cortex_data"
    mgr = DynamicConfigManager(data_dir=data_dir)

    static_cfg = CortexConfig(profile=HardwareProfileName.HIGH)
    static_cfg.retrieval.default_limit = 15

    # First migration succeeds
    migrated = migrate_static_to_db(config=static_cfg, manager=mgr, tenant_id="default")
    assert migrated is True

    raw = mgr.get_raw_config("default")
    assert raw is not None
    assert raw["profile"] == "high"
    assert raw["retrieval"]["default_limit"] == 15

    # Second migration without overwrite skips
    migrated_again = migrate_static_to_db(
        config=static_cfg, manager=mgr, tenant_id="default", overwrite=False
    )
    assert migrated_again is False

    # Second migration with overwrite succeeds
    static_cfg.retrieval.default_limit = 30
    migrated_overwrite = migrate_static_to_db(
        config=static_cfg, manager=mgr, tenant_id="default", overwrite=True
    )
    assert migrated_overwrite is True
    raw_updated = mgr.get_raw_config("default")
    assert raw_updated is not None
    assert raw_updated["retrieval"]["default_limit"] == 30
