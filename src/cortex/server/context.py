"""Application runtime context and resource lifecycle management for agent-cortex server."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager


class ServerContext:
    """Manages lazy initialization, caching, and tenant resolution for the HTTP server."""

    def __init__(
        self,
        config: CortexConfig | None = None,
        pipeline: HybridRetrievalPipeline | None = None,
        storage: StorageManager | None = None,
        dynamic_config: DynamicConfigManager | None = None,
    ) -> None:
        self._lazy_config = config
        self._lazy_pipeline = pipeline
        self._lazy_storage = storage
        self._lazy_dynamic_config = dynamic_config
        self._pipeline_cache: dict[str, HybridRetrievalPipeline] = {}

    def get_config(self) -> CortexConfig:
        if self._lazy_config is None:
            self._lazy_config = load_config()
        return self._lazy_config

    def get_dynamic_config(self) -> DynamicConfigManager:
        if self._lazy_dynamic_config is None:
            cfg = self.get_config()
            self._lazy_dynamic_config = DynamicConfigManager(data_dir=cfg.storage.data_dir)
        return self._lazy_dynamic_config

    def get_storage(self) -> StorageManager:
        if self._lazy_storage is None:
            cfg = self.get_config()
            self._lazy_storage = StorageManager(cfg.storage.data_dir)
        return self._lazy_storage

    def get_explicit_requested_tenant(
        self, request: Request, body: dict[str, Any] | None = None
    ) -> str | None:
        """Extract explicitly requested tenant ID from header, query param, or JSON body."""
        header_tenant = request.headers.get("X-Tenant-ID", "").strip()
        if header_tenant:
            return header_tenant

        query_tenant = request.query_params.get(
            "tenant_id", request.query_params.get("tenant", "")
        ).strip()
        if query_tenant:
            return query_tenant

        if body and isinstance(body, dict):
            body_tenant = str(body.get("tenant_id", body.get("tenant", ""))).strip()
            if body_tenant:
                return body_tenant

        return None

    def check_tenant_isolation(
        self, request: Request, body: dict[str, Any] | None = None
    ) -> JSONResponse | None:
        """Verify that a tenant-scoped token does not access another tenant's resources."""
        auth_tenant = getattr(request.state, "authenticated_tenant_id", None)
        if not auth_tenant:
            return None
        requested = self.get_explicit_requested_tenant(request, body)
        if requested and requested != auth_tenant:
            return JSONResponse(
                {
                    "error": "Forbidden",
                    "detail": (
                        f"Tenant token for '{auth_tenant}' is not authorized "
                        f"to access tenant '{requested}'"
                    ),
                },
                status_code=403,
            )
        return None

    def resolve_tenant(self, request: Request, body: dict[str, Any] | None = None) -> str:
        """Resolve active tenant identifier from request state, header, query, or body."""
        if hasattr(request.state, "tenant_id") and request.state.tenant_id:
            return str(request.state.tenant_id).strip()

        explicit = self.get_explicit_requested_tenant(request, body)
        if explicit:
            return explicit

        return "default"

    def get_pipeline_for_tenant(
        self, tenant_id: str, tenant_cfg: CortexConfig
    ) -> HybridRetrievalPipeline:
        """Resolve or instantiate cached retrieval pipeline for tenant configuration."""
        if self._lazy_pipeline is not None:
            return self._lazy_pipeline

        cache_key = (
            f"{tenant_cfg.profile.value}:{tenant_cfg.storage.data_dir}:"
            f"{tenant_cfg.retrieval.k}:{tenant_cfg.retrieval.weight_dense}:"
            f"{tenant_cfg.retrieval.weight_sparse}"
        )
        if cache_key in self._pipeline_cache:
            return self._pipeline_cache[cache_key]

        pipe = HybridRetrievalPipeline.from_config(tenant_cfg)
        self._pipeline_cache[cache_key] = pipe
        return pipe
