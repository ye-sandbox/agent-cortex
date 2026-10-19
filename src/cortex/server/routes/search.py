"""Search, contracts, and technology discovery routes for agent-cortex server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from cortex.models.chunk import (
    ChunkCategory,
    ChunkScope,
    SearchResultChunk,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)
from cortex.server.context import ServerContext


def create_search_routes(ctx: ServerContext) -> list[Route]:
    async def search_endpoint(request: Request) -> Response:
        body: dict[str, Any] = {}
        if request.method == "POST":
            try:
                raw_body = await request.json()
                if isinstance(raw_body, dict):
                    body = raw_body
                else:
                    return JSONResponse(
                        {"error": "Bad Request", "detail": "JSON body must be an object"},
                        status_code=400,
                    )
            except Exception:
                return JSONResponse(
                    {"error": "Bad Request", "detail": "Invalid JSON body"},
                    status_code=400,
                )

        isolation_err = ctx.check_tenant_isolation(request, body)
        if isolation_err is not None:
            return isolation_err

        # Resolve tenant & tenant-specific configuration
        tenant_id = ctx.resolve_tenant(request, body)
        dyn_mgr = ctx.get_dynamic_config()
        tenant_cfg = dyn_mgr.get_tenant_config(tenant_id, fallback=ctx.get_config())

        query = str(body.get("query", request.query_params.get("query", ""))).strip()
        if not query:
            return JSONResponse([])

        # Limit (falls back to tenant-specific default_limit)
        limit_val = body.get("limit", request.query_params.get("limit"))
        limit: int = tenant_cfg.retrieval.default_limit
        if limit_val is not None:
            try:
                limit = int(limit_val)
            except ValueError, TypeError:
                limit = tenant_cfg.retrieval.default_limit

        # Scopes
        scope_val = body.get("scope", body.get("scopes", request.query_params.get("scope")))
        scopes: list[ChunkScope] | None = None
        if scope_val:
            raw_scopes: list[str] = (
                [s.strip() for s in scope_val.split(",")]
                if isinstance(scope_val, str)
                else [str(s).strip() for s in scope_val]
            )
            scopes = []
            for s in raw_scopes:
                if s:
                    try:
                        scopes.append(ChunkScope(s.lower()))
                    except ValueError:
                        return JSONResponse(
                            {"error": "Bad Request", "detail": f"Invalid scope '{s}'"},
                            status_code=400,
                        )

        # Category
        cat_val = body.get("category", request.query_params.get("category"))
        category: ChunkCategory | None = None
        if cat_val:
            try:
                category = ChunkCategory(str(cat_val).strip().lower())
            except ValueError:
                return JSONResponse(
                    {"error": "Bad Request", "detail": f"Invalid category '{cat_val}'"},
                    status_code=400,
                )

        # Repository filter
        repo_val = body.get("repo", request.query_params.get("repo"))
        repo: str | None = str(repo_val).strip() if repo_val else None

        # Rerank flag
        rerank_raw = body.get("rerank", request.query_params.get("rerank", "true"))
        rerank = str(rerank_raw).lower() not in ("false", "0", "no")

        # Include archived
        archived_raw = body.get(
            "include_archived", request.query_params.get("include_archived", "false")
        )
        include_archived = str(archived_raw).lower() in ("true", "1", "yes")

        # Streaming format flag
        stream_raw = body.get("stream", request.query_params.get("stream", "false"))
        stream_flag = str(stream_raw).lower() in ("true", "1", "yes")

        accept_header = request.headers.get("accept", "").lower()
        wants_ndjson = ("application/x-ndjson" in accept_header) or stream_flag

        pipe = ctx.get_pipeline_for_tenant(tenant_id, tenant_cfg)
        results: list[SearchResultChunk] = pipe.search(
            query=query,
            limit=limit,
            scopes=scopes,
            include_archived=include_archived,
            category=category,
            repo=repo,
            rerank=rerank,
        )

        if wants_ndjson:

            async def ndjson_stream() -> AsyncIterator[str]:
                for r in results:
                    item = r.model_dump(mode="json")
                    item["anchor"] = r.format_anchor()
                    yield json.dumps(item) + "\n"

            return StreamingResponse(
                ndjson_stream(),
                media_type="application/x-ndjson",
            )

        output: list[dict[str, Any]] = []
        for r in results:
            item = r.model_dump(mode="json")
            item["anchor"] = r.format_anchor()
            output.append(item)

        return JSONResponse(output)

    async def contracts_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip()
        if not repo:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Missing required 'repo' parameter"},
                status_code=400,
            )

        contract_type = request.query_params.get("contract_type")
        limit_str = request.query_params.get("limit", "50")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 50

        categories = resolve_contract_categories(contract_type)
        mgr = ctx.get_storage()
        records = mgr.get_repo_contracts(repo=repo, categories=categories, limit=limit)
        chunks = format_contract_chunks(repo, records)
        return JSONResponse([c.model_dump(mode="json") for c in chunks])

    async def technologies_endpoint(request: Request) -> JSONResponse:
        tech_name = request.query_params.get("tech_name")
        repo = request.query_params.get("repo")

        mgr = ctx.get_storage()
        records = mgr.get_technologies(repo=repo)
        summary = aggregate_tech_summary(records, tech_name=tech_name)
        return JSONResponse(summary.model_dump(mode="json"))

    return [
        Route("/search", search_endpoint, methods=["GET", "POST"]),
        Route("/contracts", contracts_endpoint, methods=["GET"]),
        Route("/technologies", technologies_endpoint, methods=["GET"]),
    ]
