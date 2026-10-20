"""Runtime context and resource lifecycle management for cortex MCP server."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from cortex.config.loader import CortexConfig, load_config
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

if TYPE_CHECKING:
    from cortex.client import CortexClient


class ServerContext:
    """Manages lazy initialization, caching, and dual-mode client lifecycle for MCP tools."""

    def __init__(
        self,
        config: CortexConfig | None = None,
        pipeline: HybridRetrievalPipeline | None = None,
        storage: StorageManager | None = None,
        client: CortexClient | None = None,
    ) -> None:
        self._lazy_config = config
        self._lazy_pipeline = pipeline
        self._lazy_storage = storage
        self._lazy_client = client

    def get_config(self) -> CortexConfig:
        """Resolve or load active Cortex configuration."""
        if self._lazy_config is None:
            self._lazy_config = load_config()
        return self._lazy_config

    def _resolve_client_cls(self) -> type[CortexClient]:
        """Resolve CortexClient class dynamically supporting monkeypatches on mcp_server."""
        from cortex.client import CortexClient

        client_attr = "CortexClient"
        mcp_mod = sys.modules.get("cortex.mcp_server")
        if mcp_mod is not None and hasattr(mcp_mod, client_attr):
            cls_candidate = getattr(mcp_mod, client_attr)
            if isinstance(cls_candidate, type):
                return cls_candidate
            return cls_candidate  # type: ignore[no-any-return]
        return CortexClient

    def get_remote_client(self) -> CortexClient | None:
        """Return explicit remote client if injected or configured in remote hub mode."""
        if self._lazy_client is not None:
            return self._lazy_client
        if self._lazy_pipeline is not None or self._lazy_storage is not None:
            return None
        cfg = self.get_config()
        if cfg.remote.hub_url:
            client_cls = self._resolve_client_cls()
            self._lazy_client = client_cls(mode="remote", config=cfg)
            return self._lazy_client
        return None

    def create_in_process_client(self) -> CortexClient:
        """Instantiate an in-process CortexClient sharing the server storage and config."""
        client_cls = self._resolve_client_cls()
        return client_cls(config=self.get_config(), mode="in_process", storage=self.get_storage())

    def get_pipeline(self) -> HybridRetrievalPipeline:
        """Resolve or construct hybrid retrieval pipeline."""
        if self._lazy_pipeline is None:
            cfg = self.get_config()
            self._lazy_pipeline = HybridRetrievalPipeline.from_config(cfg)
        return self._lazy_pipeline

    def get_storage(self) -> StorageManager:
        """Resolve or construct local storage manager."""
        if self._lazy_storage is None:
            cfg = self.get_config()
            self._lazy_storage = StorageManager(cfg.storage.data_dir)
        return self._lazy_storage
