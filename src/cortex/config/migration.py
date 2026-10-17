"""Migration utilities for transitioning static file configurations to LanceDB tables."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config

logger = logging.getLogger(__name__)


def migrate_static_to_db(
    config: CortexConfig | None = None,
    manager: DynamicConfigManager | None = None,
    tenant_id: str = "default",
    overwrite: bool = False,
) -> bool:
    """Migrate static YAML/file configuration into the DB-backed runtime configuration table.

    Returns True if migration was performed, or False if skipped because configuration
    already exists and overwrite was not requested.
    """
    effective_cfg = config if config is not None else load_config()
    effective_mgr = (
        manager
        if manager is not None
        else DynamicConfigManager(data_dir=effective_cfg.storage.data_dir)
    )

    cleaned_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else "default"
    existing = effective_mgr.get_raw_config(cleaned_tenant)

    if existing is not None and not overwrite:
        logger.info(
            "Runtime config for tenant '%s' already exists in LanceDB table; skipping migration.",
            cleaned_tenant,
        )
        return False

    now_iso = datetime.now(UTC).isoformat()
    description = f"Migrated from static configuration on {now_iso}"
    effective_mgr.set_tenant_config(
        tenant_id=cleaned_tenant,
        config_data=effective_cfg,
        description=description,
    )
    logger.info("Successfully migrated static configuration for tenant '%s' to DB.", cleaned_tenant)
    return True
