"""Portfolio topology, matrix, and cycle detection routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from cortex.models.topology import TopologyExportFormat
from cortex.retrieval.topology import PortfolioTopologyEngine
from cortex.server.context import ServerContext


def create_topology_routes(ctx: ServerContext) -> list[Route]:
    async def topology_graph_endpoint(request: Request) -> Response:
        fmt_str = request.query_params.get("format", "json").lower()
        direction = request.query_params.get("direction", "LR").upper()
        if direction not in ("LR", "TD", "RL", "BT"):
            direction = "LR"
        include_internal_str = request.query_params.get("include_internal", "false").lower()
        include_internal = include_internal_str in ("1", "true", "yes")
        min_weight_str = request.query_params.get("min_weight", "1")
        try:
            min_weight = max(1, int(min_weight_str))
        except ValueError:
            min_weight = 1

        engine = PortfolioTopologyEngine(ctx.get_storage())
        try:
            export_fmt = TopologyExportFormat(fmt_str)
        except ValueError:
            export_fmt = TopologyExportFormat.JSON

        if export_fmt == TopologyExportFormat.JSON:
            graph = engine.build_topology(
                include_internal=include_internal,
                min_weight=min_weight,
            )
            return JSONResponse(graph.model_dump(mode="json"))

        exported = engine.export(
            format_type=export_fmt,
            direction=direction,
            include_internal=include_internal,
            min_weight=min_weight,
        )

        if isinstance(exported, dict):
            return JSONResponse(exported)

        accept = request.headers.get("accept", "")
        if "application/json" in accept and "text/plain" not in accept:
            return JSONResponse({"format": export_fmt.value, "content": exported})
        return PlainTextResponse(exported, media_type="text/plain; charset=utf-8")

    async def topology_matrix_endpoint(request: Request) -> JSONResponse:
        min_weight_str = request.query_params.get("min_weight", "0")
        try:
            min_weight = max(0, int(min_weight_str))
        except ValueError:
            min_weight = 0

        engine = PortfolioTopologyEngine(ctx.get_storage())
        matrix = engine.build_matrix(min_weight=min_weight)
        return JSONResponse(matrix.model_dump(mode="json"))

    async def topology_cycles_endpoint(request: Request) -> JSONResponse:
        min_weight_str = request.query_params.get("min_weight", "1")
        try:
            min_weight = max(1, int(min_weight_str))
        except ValueError:
            min_weight = 1

        engine = PortfolioTopologyEngine(ctx.get_storage())
        graph = engine.build_topology(min_weight=min_weight)
        return JSONResponse([c.model_dump(mode="json") for c in graph.cycles])

    return [
        Route("/topology/graph", topology_graph_endpoint, methods=["GET"]),
        Route("/topology/matrix", topology_matrix_endpoint, methods=["GET"]),
        Route("/topology/cycles", topology_cycles_endpoint, methods=["GET"]),
    ]
