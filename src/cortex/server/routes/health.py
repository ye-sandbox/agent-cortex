"""Health and status inspection routes for agent-cortex server."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cortex.ingestion.watcher import RepoWatcher
from cortex.server.context import ServerContext


def create_health_routes(ctx: ServerContext) -> list[Route]:
    async def health_endpoint(request: Request) -> JSONResponse:
        from cortex import __version__

        mgr = ctx.get_storage()
        total_chunks = mgr.count_chunks()
        current_cfg = ctx.get_config()
        profile = current_cfg.get_active_profile()
        dyn_mgr = ctx.get_dynamic_config()
        tenants = dyn_mgr.list_tenants()

        resp_payload: dict[str, Any] = {
            "status": "ok",
            "version": __version__,
            "profile": profile.name,
            "total_chunks": total_chunks,
            "storage_dir": str(current_cfg.storage.data_dir),
            "tenants_count": len(tenants),
        }

        watcher_inst = getattr(request.app.state, "watcher", None)
        if watcher_inst is not None and isinstance(watcher_inst, RepoWatcher):
            resp_payload["watcher"] = watcher_inst.get_status().model_dump()

        return JSONResponse(resp_payload)

    return [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/healthz", health_endpoint, methods=["GET"]),
    ]
