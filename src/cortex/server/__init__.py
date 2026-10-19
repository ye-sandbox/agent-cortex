"""Lightweight HTTP daemon server for agent-cortex.

Provides streaming JSON and NDJSON endpoints for semantic search, repository contract
inspection, technology discovery, dynamic configuration management, and health probes
with multi-tenant resolution and Bearer token authentication.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.watcher import RepoWatcher, WatcherConfig
from cortex.retrieval.drift import ContractDriftEngine
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.server.context import ServerContext
from cortex.server.middleware import BearerAuthMiddleware
from cortex.server.routes.config import create_config_routes
from cortex.server.routes.drift import create_drift_routes
from cortex.server.routes.graph import create_graph_routes
from cortex.server.routes.health import create_health_routes
from cortex.server.routes.impact import create_impact_routes
from cortex.server.routes.search import create_search_routes
from cortex.server.routes.sync import create_sync_routes
from cortex.server.routes.topology import create_topology_routes
from cortex.storage.manager import StorageManager

# Re-exported for backwards compatibility and test mock patching
__all__ = [
    "BearerAuthMiddleware",
    "ContractDriftEngine",
    "IngestionEngine",
    "RepoWatcher",
    "ServerContext",
    "WatcherConfig",
    "create_app",
    "resolve_sync_sources",
    "run_server",
]


def create_app(
    config: CortexConfig | None = None,
    pipeline: HybridRetrievalPipeline | None = None,
    storage: StorageManager | None = None,
    api_key: str | None = None,
    dynamic_config: DynamicConfigManager | None = None,
    watch: bool = False,
    watch_interval: float | None = None,
) -> Starlette:
    """Create and configure Starlette ASGI application for agent-cortex daemon."""
    ctx = ServerContext(
        config=config,
        pipeline=pipeline,
        storage=storage,
        dynamic_config=dynamic_config,
    )

    routes = [
        *create_health_routes(ctx),
        *create_search_routes(ctx),
        *create_graph_routes(ctx),
        *create_drift_routes(ctx),
        *create_impact_routes(ctx),
        *create_topology_routes(ctx),
        *create_sync_routes(ctx),
        *create_config_routes(ctx),
    ]

    cfg = ctx.get_config()
    effective_api_key = api_key if api_key is not None else cfg.remote.api_key

    middleware: list[Middleware] = []
    dyn_for_middleware = dynamic_config or (
        ctx.get_dynamic_config() if cfg.storage.data_dir.exists() else None
    )
    if effective_api_key or dyn_for_middleware is not None:
        middleware.append(
            Middleware(
                BearerAuthMiddleware,
                api_key=effective_api_key,
                dynamic_config=dyn_for_middleware,
            )
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        watcher_task: asyncio.Task[None] | None = None
        should_watch = watch or ctx.get_config().sync.auto_watch
        if should_watch:
            current_cfg = ctx.get_config()
            interval = watch_interval if watch_interval is not None else current_cfg.sync.interval
            watcher = RepoWatcher(
                config=current_cfg,
                watcher_config=WatcherConfig(
                    interval=interval,
                    debounce=current_cfg.sync.debounce,
                    all_repos=True,
                ),
            )
            app.state.watcher = watcher
            watcher_task = asyncio.create_task(watcher.run_loop_async())

        try:
            yield
        finally:
            if watcher_task is not None:
                watcher_inst = getattr(app.state, "watcher", None)
                if watcher_inst is not None and isinstance(watcher_inst, RepoWatcher):
                    watcher_inst.stop()
                try:
                    await asyncio.wait_for(watcher_task, timeout=5.0)
                except TimeoutError, asyncio.CancelledError:
                    watcher_task.cancel()

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    api_key: str | None = None,
    config: CortexConfig | None = None,
    log_level: str = "info",
    dynamic_config: DynamicConfigManager | None = None,
    watch: bool = False,
    watch_interval: float | None = None,
) -> None:
    """Launch uvicorn server running agent-cortex daemon."""
    app = create_app(
        config=config,
        api_key=api_key,
        dynamic_config=dynamic_config,
        watch=watch,
        watch_interval=watch_interval,
    )
    uvicorn.run(app, host=host, port=port, log_level=log_level)
