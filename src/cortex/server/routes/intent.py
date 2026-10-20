"""Change intent simulation and contract patch routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from cortex.models.intent import (
    ContractChangeIntent,
    PortfolioChangePlan,
)
from cortex.retrieval.intent import ChangeIntentEngine
from cortex.server.context import ServerContext


def create_intent_routes(ctx: ServerContext) -> list[Route]:
    """Create Starlette routes for portfolio change intent simulation and patch synthesis."""

    async def simulate_intent_endpoint(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        try:
            if "intents" in body:
                plan = PortfolioChangePlan.model_validate(body)
            else:
                intent = ContractChangeIntent.model_validate(body)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_single_intent",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        except Exception as exc:
            return JSONResponse({"error": f"Invalid request payload: {exc}"}, status_code=422)

        max_depth_str = request.query_params.get("max_depth", "5")
        try:
            max_depth = max(1, min(20, int(max_depth_str)))
        except ValueError:
            max_depth = 5

        generate_patches = request.query_params.get("generate_patches", "true").lower() in (
            "true",
            "1",
            "yes",
        )

        engine = ChangeIntentEngine(ctx.get_storage())
        report = engine.simulate_intent(
            plan,
            max_depth=max_depth,
            generate_patches=generate_patches,
        )
        return JSONResponse(report.model_dump(mode="json"))

    async def generate_patches_endpoint(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        try:
            if "intents" in body:
                plan = PortfolioChangePlan.model_validate(body)
            else:
                intent = ContractChangeIntent.model_validate(body)
                plan = PortfolioChangePlan(
                    plan_id=intent.intent_id or "plan_single_intent",
                    title=f"Intent: {intent.action.value} {intent.target_symbol}",
                    intents=[intent],
                )
        except Exception as exc:
            return JSONResponse({"error": f"Invalid request payload: {exc}"}, status_code=422)

        engine = ChangeIntentEngine(ctx.get_storage())
        report = engine.simulate_intent(plan, generate_patches=True)
        return JSONResponse([p.model_dump(mode="json") for p in report.migration_patches])

    return [
        Route("/intent/simulate", simulate_intent_endpoint, methods=["POST"]),
        Route("/intent/patch", generate_patches_endpoint, methods=["POST"]),
    ]
