"""Dynamic configuration manager backed by LanceDB tables.

Provides multi-tenant runtime configuration storage, retrieval, deep-merging, and lifecycle
management without requiring static configuration restarts.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lancedb
from lancedb.db import DBConnection
from lancedb.pydantic import LanceModel
from lancedb.table import Table

from cortex.config.loader import CortexConfig, load_config
from cortex.storage.manager import validate_storage_path

logger = logging.getLogger(__name__)


class DynamicConfigRecord(LanceModel):
    """Database schema for a runtime tenant configuration entry."""

    tenant_id: str
    config_json: str
    updated_at: str
    description: str = ""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override dictionary into base dictionary."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


class DynamicConfigManager:
    """Manages dynamic runtime configuration tables in LanceDB."""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        db: DBConnection | None = None,
        table_name: str = "runtime_configs",
    ) -> None:
        self.table_name = table_name

        if db is not None:
            self._db = db
            self.data_dir: Path | None = None
        else:
            if data_dir is not None:
                resolved_path = Path(data_dir)
            else:
                env_override = os.environ.get("AGENT_CORTEX_DATA_DIR")
                if env_override:
                    resolved_path = Path(env_override)
                else:
                    resolved_path = Path("~/.local/share/agent-cortex/data")

            self.data_dir = validate_storage_path(resolved_path)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(self.data_dir))

    @property
    def db(self) -> DBConnection:
        """Return the underlying LanceDB connection."""
        return self._db

    def table_names(self) -> list[str]:
        """Return list of existing table names in the database."""
        res = self._db.list_tables()
        return list(res.tables)

    def get_or_create_table(self) -> Table:
        """Retrieve existing runtime config table or create a new one."""
        if self.table_name in self.table_names():
            return self._db.open_table(self.table_name)
        return self._db.create_table(self.table_name, schema=DynamicConfigRecord)

    def list_tenants(self) -> list[dict[str, Any]]:
        """List all configured tenant IDs, timestamps, and descriptions."""
        if self.table_name not in self.table_names():
            return []
        tbl = self._db.open_table(self.table_name)
        try:
            results: list[dict[str, Any]] = (
                tbl.search().select(["tenant_id", "updated_at", "description"]).to_list()
            )
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to list tenants from '%s': %s", self.table_name, exc)
            return []

    def resolve_tenant_by_api_key(self, token: str) -> str | None:
        """Resolve tenant_id matching a Bearer token in a single table scan."""
        cleaned_token = token.strip()
        if not cleaned_token or self.table_name not in self.table_names():
            return None
        tbl = self._db.open_table(self.table_name)
        try:
            rows: list[dict[str, Any]] = tbl.search().select(["tenant_id", "config_json"]).to_list()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to scan tenant API keys from '%s': %s", self.table_name, exc)
            return None

        for row in rows:
            t_id = str(row.get("tenant_id", "")).strip()
            if not t_id:
                continue
            try:
                raw_cfg = json.loads(str(row.get("config_json", "{}")))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(raw_cfg, dict):
                continue

            t_key: str | None = None
            tenant_remote = raw_cfg.get("remote")
            if isinstance(tenant_remote, dict):
                raw_val = tenant_remote.get("api_key")
                if raw_val:
                    t_key = str(raw_val).strip()
            if not t_key and "api_key" in raw_cfg and raw_cfg["api_key"]:
                t_key = str(raw_cfg["api_key"]).strip()

            if t_key and hmac.compare_digest(t_key.encode("utf-8"), cleaned_token.encode("utf-8")):
                return t_id

        return None

    def get_raw_config(self, tenant_id: str) -> dict[str, Any] | None:
        """Retrieve the unmerged raw JSON dictionary for a tenant if configured."""
        if self.table_name not in self.table_names():
            return None
        tbl = self._db.open_table(self.table_name)
        safe_tenant = tenant_id.strip().replace("'", "''")
        try:
            results = tbl.search().where(f"tenant_id = '{safe_tenant}'").limit(1).to_list()
            if not results:
                return None
            raw_json = str(results[0].get("config_json", "{}"))
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error reading config for tenant '%s': %s", tenant_id, exc)
            return None

    def get_tenant_config(
        self,
        tenant_id: str = "default",
        fallback: CortexConfig | None = None,
    ) -> CortexConfig:
        """Resolve effective configuration for a tenant with fallback inheritance.

        Resolution order:
        1. Base: `fallback` (or `load_config()`)
        2. Default DB override: if "default" tenant config exists in DB, deep-merge onto base.
        3. Tenant DB override: if `tenant_id != "default"` and tenant config exists, deep-merge.
        """
        base_cfg = fallback if fallback is not None else load_config()
        effective_dict: dict[str, Any] = base_cfg.model_dump(mode="json")

        cleaned_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else "default"

        # Apply default DB overrides if present
        default_db_raw = self.get_raw_config("default")
        if default_db_raw:
            effective_dict = deep_merge(effective_dict, default_db_raw)

        # Apply specific tenant DB overrides if different from default
        if cleaned_tenant != "default":
            tenant_db_raw = self.get_raw_config(cleaned_tenant)
            if tenant_db_raw:
                effective_dict = deep_merge(effective_dict, tenant_db_raw)

        return CortexConfig.model_validate(effective_dict)

    def set_tenant_config(
        self,
        tenant_id: str,
        config_data: dict[str, Any] | CortexConfig,
        description: str = "",
    ) -> dict[str, Any]:
        """Upsert dynamic configuration for a tenant in the runtime configuration table."""
        cleaned_tenant = tenant_id.strip()
        if not cleaned_tenant:
            msg = "tenant_id cannot be empty"
            raise ValueError(msg)

        if isinstance(config_data, CortexConfig):
            dict_data = config_data.model_dump(mode="json")
        else:
            dict_data = dict(config_data)

        # Validate that the dictionary can be validated as a valid partial/full config
        # We test validating against default config base
        test_merged = deep_merge(load_config().model_dump(mode="json"), dict_data)
        CortexConfig.model_validate(test_merged)

        tbl = self.get_or_create_table()
        now_iso = datetime.now(UTC).isoformat()
        json_str = json.dumps(dict_data)

        record = {
            "tenant_id": cleaned_tenant,
            "config_json": json_str,
            "updated_at": now_iso,
            "description": description.strip(),
        }

        (
            tbl.merge_insert("tenant_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute([record])
        )

        return dict_data

    def delete_tenant_config(self, tenant_id: str) -> bool:
        """Delete dynamic configuration overrides for a tenant.

        Returns True if the tenant entry existed and was deleted.
        """
        cleaned_tenant = tenant_id.strip()
        if not cleaned_tenant or self.table_name not in self.table_names():
            return False

        if self.get_raw_config(cleaned_tenant) is None:
            return False

        tbl = self._db.open_table(self.table_name)
        safe_tenant = cleaned_tenant.replace("'", "''")
        tbl.delete(f"tenant_id = '{safe_tenant}'")
        return True
