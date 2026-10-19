"""Repository ingestion and synchronization routes for agent-cortex server."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cortex.ingestion.models import SyncResult
from cortex.server.context import ServerContext


def create_sync_routes(ctx: ServerContext) -> list[Route]:
    async def sync_endpoint(request: Request) -> JSONResponse:
        body: dict[str, Any] = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                raw_body = await request.json()
                if isinstance(raw_body, dict):
                    body = raw_body
            except Exception:
                return JSONResponse(
                    {"error": "Bad Request", "detail": "Invalid JSON body"},
                    status_code=400,
                )

        repo_filter = body.get("repo")
        all_flag = bool(body.get("all", False))
        force_full = bool(body.get("force_full", False))

        current_cfg = ctx.get_config()
        effective_repo = (
            str(repo_filter).strip() if repo_filter and str(repo_filter).strip() else None
        )

        import cortex.server

        sources = cortex.server.resolve_sync_sources(
            config=current_cfg,
            repo_filter=effective_repo,
            all_flag=all_flag,
        )

        if not sources:
            return JSONResponse(
                {
                    "status": "not_found" if effective_repo else "ok",
                    "detail": (
                        f"Repository '{effective_repo}' not found"
                        if effective_repo
                        else "No repositories configured"
                    ),
                    "total_synced": 0,
                    "synced": [],
                },
                status_code=404 if effective_repo else 200,
            )

        def _do_sync() -> list[SyncResult]:
            eng = cortex.server.IngestionEngine.from_config(current_cfg)
            return eng.sync_all(sources=sources, force_full=force_full)

        results = await asyncio.to_thread(_do_sync)
        return JSONResponse(
            {
                "status": "ok",
                "total_synced": len(results),
                "synced": [r.model_dump() for r in results],
            }
        )

    return [
        Route("/sync", sync_endpoint, methods=["POST"]),
    ]
