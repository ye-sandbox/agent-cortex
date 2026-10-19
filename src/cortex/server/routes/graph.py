"""Code dependency graph and signature inspection routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cortex.retrieval.graph import DependencyGraphEngine
from cortex.server.context import ServerContext


def create_graph_routes(ctx: ServerContext) -> list[Route]:
    async def graph_dependencies_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip()
        if not repo:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Missing required 'repo' parameter"},
                status_code=400,
            )
        file_path = request.query_params.get("file") or request.query_params.get("file_path")
        symbol = request.query_params.get("symbol")
        cross_repo_str = request.query_params.get("cross_repo_only", "false").lower()
        cross_repo_only = cross_repo_str in ("1", "true", "yes")
        limit_str = request.query_params.get("limit", "100")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 100

        engine = DependencyGraphEngine(ctx.get_storage())
        res = engine.get_dependencies(
            repo=repo,
            file_path=file_path,
            symbol=symbol,
            cross_repo_only=cross_repo_only,
            limit=limit,
        )
        return JSONResponse(res.model_dump(mode="json"))

    async def graph_dependents_endpoint(request: Request) -> JSONResponse:
        symbol = request.query_params.get("symbol", "").strip()
        if not symbol:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Missing required 'symbol' parameter"},
                status_code=400,
            )
        module = request.query_params.get("module")
        limit_str = request.query_params.get("limit", "100")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 100

        engine = DependencyGraphEngine(ctx.get_storage())
        res = engine.get_dependents(
            symbol=symbol,
            module=module,
            limit=limit,
        )
        return JSONResponse(res.model_dump(mode="json"))

    async def graph_signatures_endpoint(request: Request) -> JSONResponse:
        query = request.query_params.get("query", "").strip()
        if not query:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Missing required 'query' parameter"},
                status_code=400,
            )
        repo = request.query_params.get("repo")
        kind = request.query_params.get("kind")
        language = request.query_params.get("language")
        limit_str = request.query_params.get("limit", "50")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 50

        engine = DependencyGraphEngine(ctx.get_storage())
        res = engine.get_signatures(
            query=query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )
        return JSONResponse(res.model_dump(mode="json"))

    return [
        Route("/graph/dependencies", graph_dependencies_endpoint, methods=["GET"]),
        Route("/graph/dependents", graph_dependents_endpoint, methods=["GET"]),
        Route("/graph/signatures", graph_signatures_endpoint, methods=["GET"]),
    ]
