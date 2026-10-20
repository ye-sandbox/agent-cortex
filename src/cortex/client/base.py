"""Base dual-mode client foundation for agent-cortex.

Defines client modes, base exceptions, session lifecycle, and common storage/pipeline accessors.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Self

import httpx

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)

ClientMode = Literal["in_process", "remote", "auto"]


class CortexClientError(Exception):
    """Base exception for cortex client errors."""


class CortexRemoteError(CortexClientError):
    """Exception raised when remote cortex hub request fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        hub_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.hub_url = hub_url


class CortexAuthError(CortexRemoteError):
    """Exception raised when remote authentication fails (401 Unauthorized)."""

    def __init__(self, message: str = "Invalid or missing Bearer token") -> None:
        super().__init__(message, status_code=401)


class CortexBaseClient:
    """Core base client managing configuration, HTTP session, and local storage instances."""

    def __init__(
        self,
        mode: ClientMode = "auto",
        hub_url: str | None = None,
        api_key: str | None = None,
        tenant_id: str | None = None,
        timeout: float = 30.0,
        config: CortexConfig | None = None,
        pipeline: HybridRetrievalPipeline | None = None,
        storage: StorageManager | None = None,
        dynamic_config: DynamicConfigManager | None = None,
    ) -> None:
        self.config = config or load_config()
        self.mode = mode
        self.timeout = timeout

        # Resolve tenant ID (from param, env, or default)
        env_tenant = os.environ.get("CORTEX_TENANT_ID")
        self.tenant_id = (
            tenant_id.strip()
            if tenant_id and tenant_id.strip()
            else (env_tenant.strip() if env_tenant and env_tenant.strip() else "default")
        )

        # Resolve hub URL and API key from args, then config
        self.hub_url = (
            hub_url.rstrip("/")
            if hub_url and hub_url.strip()
            else (self.config.remote.hub_url.rstrip("/") if self.config.remote.hub_url else None)
        )
        self.api_key = (
            api_key.strip()
            if api_key and api_key.strip()
            else (self.config.remote.api_key.strip() if self.config.remote.api_key else None)
        )

        if self.mode == "remote" and not self.hub_url:
            msg = "Remote mode requested but no hub_url provided or configured."
            raise ValueError(msg)

        # Lazy local pipeline, storage, and dynamic config instances
        self._pipeline = pipeline
        self._storage = storage
        self._dynamic_config = dynamic_config

        # HTTP client for remote communications
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.tenant_id:
            headers["X-Tenant-ID"] = self.tenant_id

        self._http_client = httpx.Client(
            headers=headers,
            timeout=self.timeout,
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    def _get_pipeline(self) -> HybridRetrievalPipeline:
        if self._pipeline is None:
            self._pipeline = HybridRetrievalPipeline.from_config(self.config)
        return self._pipeline

    def _get_storage(self) -> StorageManager:
        if self._storage is None:
            self._storage = StorageManager(self.config.storage.data_dir)
        return self._storage

    def _get_dynamic_config(self) -> DynamicConfigManager:
        if self._dynamic_config is None:
            self._dynamic_config = DynamicConfigManager(data_dir=self.config.storage.data_dir)
        return self._dynamic_config

    def _should_use_remote(self) -> bool:
        if self.mode == "remote":
            return True
        if self.mode == "in_process":
            return False
        # mode == "auto": use remote if hub_url is declared
        return bool(self.hub_url)

    def health(self) -> dict[str, Any]:
        """Check health and vitals of the active hub or local engine."""
        if self._should_use_remote() and self.hub_url:
            try:
                resp = self._http_client.get(f"{self.hub_url}/health")
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
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                msg = f"Remote health check returned HTTP {status}: {exc.response.text}"
                raise CortexRemoteError(
                    msg,
                    status_code=exc.response.status_code,
                    hub_url=self.hub_url,
                ) from exc

        # Local in-process fallback / direct execution
        from cortex import __version__

        mgr = self._get_storage()
        total_chunks = mgr.count_chunks()
        profile = self.config.get_active_profile()

        return {
            "status": "ok",
            "version": __version__,
            "profile": profile.name,
            "total_chunks": total_chunks,
            "storage_dir": str(self.config.storage.data_dir),
            "mode": "in_process",
        }
