"""Contract drift and breaking change detection routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cortex.models.drift import ContractDriftReport
from cortex.server.context import ServerContext


def create_drift_routes(ctx: ServerContext) -> list[Route]:
    async def drift_alerts_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip() or None
        breaking_str = request.query_params.get("breaking_only", "false").lower()
        breaking_only = breaking_str in ("1", "true", "yes")
        cross_repo_str = request.query_params.get("cross_repo_only", "false").lower()
        cross_repo_only = cross_repo_str in ("1", "true", "yes")

        cfg = ctx.get_config()
        import cortex.server

        drift_engine = cortex.server.ContractDriftEngine.from_config(cfg)
        sources = cortex.server.resolve_sync_sources(
            config=cfg,
            repo_filter=repo,
            all_flag=(repo is None),
        )

        if repo:
            target_src = next((s for s in sources if s.get_repo_name() == repo), None)
            if target_src:
                raw_report = drift_engine.analyze_repo_drift(
                    repo_path=target_src.path,
                    repo_name=target_src.get_repo_name(),
                )
            else:
                raw_report = ContractDriftReport(repo=repo)
        else:
            raw_report = drift_engine.analyze_portfolio_drift(sources=sources)

        filtered_alerts = raw_report.alerts
        if breaking_only:
            filtered_alerts = [a for a in filtered_alerts if a.severity.is_breaking]
        if cross_repo_only:
            filtered_alerts = [a for a in filtered_alerts if len(a.impacted_repos) > 0]

        report = ContractDriftReport.from_alerts(
            filtered_alerts,
            repo=raw_report.repo,
            base_commit=raw_report.base_commit,
            target_commit=raw_report.target_commit,
        )
        return JSONResponse(report.model_dump(mode="json"))

    return [
        Route("/drift/alerts", drift_alerts_endpoint, methods=["GET"]),
    ]
