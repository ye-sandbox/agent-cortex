"""Dynamic configuration and multi-tenant management client mixin."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from cortex.client.base import CortexAuthError, CortexBaseClient, CortexRemoteError
from cortex.config.loader import CortexConfig

logger = logging.getLogger(__name__)


class ConfigClientMixin(CortexBaseClient):
    """Domain mixin providing dynamic configuration and multi-tenant management."""

    def get_config(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Retrieve effective configuration for a tenant (remote or local DB-backed)."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                resp = self._http_client.get(
                    f"{self.hub_url}/config",
                    headers=headers,
                    params={"tenant_id": target_tenant},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_json: dict[str, Any] = resp.json()
                return res_json
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        dyn_mgr = self._get_dynamic_config()
        cfg = dyn_mgr.get_tenant_config(target_tenant, fallback=self.config)
        return cfg.model_dump(mode="json")

    def set_config(
        self,
        config_data: dict[str, Any] | CortexConfig,
        tenant_id: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Upsert runtime configuration for a tenant in remote hub or local LanceDB table."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id
        dict_data = (
            config_data.model_dump(mode="json")
            if isinstance(config_data, CortexConfig)
            else dict(config_data)
        )

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                payload = {
                    "tenant_id": target_tenant,
                    "config": dict_data,
                    "description": description,
                }
                resp = self._http_client.post(
                    f"{self.hub_url}/config",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_json: dict[str, Any] = resp.json()
                return res_json
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        dyn_mgr = self._get_dynamic_config()
        saved = dyn_mgr.set_tenant_config(target_tenant, dict_data, description=description)
        return {"status": "ok", "tenant_id": target_tenant, "config": saved}

    def delete_config(self, tenant_id: str | None = None) -> bool:
        """Delete dynamic configuration overrides for a tenant."""
        target_tenant = tenant_id.strip() if tenant_id and tenant_id.strip() else self.tenant_id

        if self._should_use_remote() and self.hub_url:
            try:
                headers = {"X-Tenant-ID": target_tenant}
                resp = self._http_client.delete(
                    f"{self.hub_url}/config",
                    headers=headers,
                    params={"tenant_id": target_tenant},
                )
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_data = resp.json()
                return bool(isinstance(res_data, dict) and res_data.get("deleted", False))
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        dyn_mgr = self._get_dynamic_config()
        return dyn_mgr.delete_tenant_config(target_tenant)

    def list_tenants(self) -> list[dict[str, Any]]:
        """List configured tenants from remote hub or local LanceDB table."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(f"{self.hub_url}/tenants")
                if resp.status_code == 401:
                    raise CortexAuthError()
                resp.raise_for_status()
                res_data = resp.json()
                if isinstance(res_data, dict):
                    raw_tenants = res_data.get("tenants", [])
                    if isinstance(raw_tenants, list):
                        return [t for t in raw_tenants if isinstance(t, dict)]
                return []
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(
                    "Remote hub at '%s' unreachable: %s. Aborting request.",
                    self.hub_url,
                    exc,
                )
                raise CortexRemoteError(
                    f"Remote hub at '{self.hub_url}' is unreachable: {exc}. "
                    "Aborting request as remote hub is configured.",
                    hub_url=self.hub_url,
                ) from exc

        dyn_mgr = self._get_dynamic_config()
        return dyn_mgr.list_tenants()
