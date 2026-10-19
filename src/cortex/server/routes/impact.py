"""Blast-radius simulation and transitive impact tracing routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from cortex.models.impact import BlastRadiusSimulationRequest
from cortex.retrieval.impact import ImpactAnalysisEngine
from cortex.server.context import ServerContext


def create_impact_routes(ctx: ServerContext) -> list[Route]:
    """Create Starlette routes for transitive caller tracing and blast-radius simulation."""

    async def simulate_impact_post_endpoint(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        try:
            req = BlastRadiusSimulationRequest.model_validate(body)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid request payload: {exc}"}, status_code=422)

        engine = ImpactAnalysisEngine(ctx.get_storage())
        report = engine.simulate_blast_radius(req)
        return JSONResponse(report.model_dump(mode="json"))

    async def simulate_impact_get_endpoint(request: Request) -> Response:
        repo = request.query_params.get("repo")
        if not repo or not repo.strip():
            return JSONResponse({"error": "Query parameter 'repo' is required"}, status_code=400)

        symbol = request.query_params.get("symbol")
        file_path = request.query_params.get("file_path")
        change_kind = request.query_params.get("change_kind", "MODIFIED")
        max_depth_str = request.query_params.get("max_depth", "5")
        try:
            max_depth = max(1, min(20, int(max_depth_str)))
        except ValueError:
            max_depth = 5

        req = BlastRadiusSimulationRequest(
            repo=repo.strip(),
            symbol=symbol.strip() if symbol else None,
            file_path=file_path.strip() if file_path else None,
            change_kind=change_kind,
            max_depth=max_depth,
        )
        engine = ImpactAnalysisEngine(ctx.get_storage())
        report = engine.simulate_blast_radius(req)
        return JSONResponse(report.model_dump(mode="json"))

    async def trace_impact_endpoint(request: Request) -> Response:
        repo = request.query_params.get("repo")
        if not repo or not repo.strip():
            return JSONResponse({"error": "Query parameter 'repo' is required"}, status_code=400)

        symbol = request.query_params.get("symbol")
        file_path = request.query_params.get("file_path")
        max_depth_str = request.query_params.get("max_depth", "5")
        try:
            max_depth = max(1, min(20, int(max_depth_str)))
        except ValueError:
            max_depth = 5

        engine = ImpactAnalysisEngine(ctx.get_storage())
        chains, nodes, cycles = engine.trace_transitive_callers(
            target_repo=repo.strip(),
            symbol=symbol.strip() if symbol else None,
            file_path=file_path.strip() if file_path else None,
            max_depth=max_depth,
        )
        return JSONResponse(
            {
                "target_repo": repo.strip(),
                "symbol": symbol.strip() if symbol else None,
                "file_path": file_path.strip() if file_path else None,
                "caller_chains": [c.model_dump(mode="json") for c in chains],
                "impacted_nodes": [n.model_dump(mode="json") for n in nodes],
                "cycles_detected": cycles,
            }
        )

    return [
        Route("/impact/simulate", simulate_impact_post_endpoint, methods=["POST"]),
        Route("/impact/simulate", simulate_impact_get_endpoint, methods=["GET"]),
        Route("/impact/trace", trace_impact_endpoint, methods=["GET"]),
    ]
