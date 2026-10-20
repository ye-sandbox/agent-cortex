"""Contract evolution timeline and changelog synthesis routes for agent-cortex server."""

from __future__ import annotations

from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from cortex.models.drift import ChangeKind, ContractType
from cortex.retrieval.evolution import ContractEvolutionEngine
from cortex.server.context import ServerContext


def create_evolution_routes(ctx: ServerContext) -> list[Route]:
    """Create HTTP routes for contract evolution timeline and changelogs."""

    async def timeline_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip() or None
        c_type_raw = request.query_params.get("contract_type", "").strip()
        c_kind_raw = request.query_params.get("change_kind", "").strip()
        breaking_str = request.query_params.get("breaking_only", "false").lower()
        breaking_only = breaking_str in ("1", "true", "yes")
        since_date = request.query_params.get("since_date", "").strip() or None
        until_date = request.query_params.get("until_date", "").strip() or None
        limit_str = request.query_params.get("limit", "100")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 100

        c_type = ContractType(c_type_raw) if c_type_raw else None
        c_kind = ChangeKind(c_kind_raw) if c_kind_raw else None

        cfg = ctx.get_config()
        evolution_engine = ContractEvolutionEngine.from_config(cfg)
        timeline = evolution_engine.get_timeline(
            repo=repo,
            contract_type=c_type,
            change_kind=c_kind,
            breaking_only=breaking_only,
            since_date=since_date,
            until_date=until_date,
            limit=limit,
        )
        return JSONResponse(timeline.model_dump(mode="json"))

    async def changelog_endpoint(request: Request) -> Response:
        repo = request.query_params.get("repo", "").strip() or None
        group_by_raw = request.query_params.get("group_by", "release").lower().strip()
        group_by: Literal["release", "date", "repo"] = (
            "date" if group_by_raw == "date" else ("repo" if group_by_raw == "repo" else "release")
        )
        breaking_str = request.query_params.get("breaking_only", "false").lower()
        breaking_only = breaking_str in ("1", "true", "yes")
        format_param = request.query_params.get("format", "json").lower().strip()
        limit_str = request.query_params.get("limit", "200")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 200

        cfg = ctx.get_config()
        evolution_engine = ContractEvolutionEngine.from_config(cfg)
        changelog = evolution_engine.synthesize_changelog(
            repo=repo,
            group_by=group_by,
            breaking_only=breaking_only,
            limit=limit,
        )

        if format_param in ("markdown", "md"):
            return PlainTextResponse(changelog.to_markdown(), media_type="text/markdown")
        return JSONResponse(changelog.model_dump(mode="json"))

    async def history_scan_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip() or None
        max_commits_str = request.query_params.get("max_commits", "20")
        since_commit = request.query_params.get("since_commit", "").strip() or None
        try:
            max_commits = int(max_commits_str)
        except ValueError:
            max_commits = 20

        cfg = ctx.get_config()
        import cortex.server

        sources = cortex.server.resolve_sync_sources(
            config=cfg,
            repo_filter=repo,
            all_flag=(repo is None),
        )

        evolution_engine = ContractEvolutionEngine.from_config(cfg)
        total_discovered = 0

        for src in sources:
            if not src.enabled:
                continue
            evts = evolution_engine.scan_git_history(
                repo_path=src.path,
                repo_name=src.get_repo_name(),
                max_commits=max_commits,
                since_commit=since_commit,
            )
            total_discovered += len(evts)

        return JSONResponse(
            {
                "status": "ok",
                "discovered_events": total_discovered,
                "scanned_repositories": len(sources),
            }
        )

    return [
        Route("/timeline", timeline_endpoint, methods=["GET"]),
        Route("/changelog", changelog_endpoint, methods=["GET"]),
        Route("/history/scan", history_scan_endpoint, methods=["POST"]),
    ]
