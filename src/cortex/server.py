"""Lightweight HTTP daemon server for agent-cortex.

Provides streaming JSON and NDJSON endpoints for semantic search, repository contract
inspection, technology discovery, dynamic configuration management, and health probes
with multi-tenant resolution and Bearer token authentication.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from cortex.config.dynamic import DynamicConfigManager
from cortex.config.loader import CortexConfig, load_config
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.models import SyncResult
from cortex.ingestion.watcher import RepoWatcher, WatcherConfig
from cortex.models.chunk import (
    ChunkCategory,
    ChunkScope,
    SearchResultChunk,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)
from cortex.models.drift import ContractDriftReport
from cortex.retrieval.drift import ContractDriftEngine
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing Bearer token authentication supporting server and tenant tokens."""

    def __init__(
        self,
        app: Any,
        api_key: str | None = None,
        dynamic_config: DynamicConfigManager | None = None,
    ) -> None:
        super().__init__(app)
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.dynamic_config = dynamic_config

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always permit health endpoints without authentication for liveness probes
        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)

        raw_auth = request.headers.get("Authorization", "").strip()

        # If no server-wide API key is configured and no dynamic config manager is active
        if not self.api_key and self.dynamic_config is None:
            return await call_next(request)

        # If authorization header is missing
        if not raw_auth:
            if self.api_key:
                return JSONResponse(
                    {"error": "Unauthorized", "detail": "Missing Authorization header"},
                    status_code=401,
                )
            # Permitted if no global api_key was enforced
            return await call_next(request)

        if not raw_auth.startswith("Bearer "):
            return JSONResponse(
                {
                    "error": "Unauthorized",
                    "detail": "Invalid Authorization scheme, must be Bearer token",
                },
                status_code=401,
            )

        token = raw_auth[7:].strip()

        # 1. Global API key match (constant-time comparison)
        if self.api_key and hmac.compare_digest(
            self.api_key.encode("utf-8"), token.encode("utf-8")
        ):
            request.state.is_admin = True
            return await call_next(request)

        # 2. Check tenant-specific API keys in a single query if dynamic config is available
        if self.dynamic_config is not None:
            matched_tenant = self.dynamic_config.resolve_tenant_by_api_key(token)
            if matched_tenant:
                request.state.tenant_id = matched_tenant
                request.state.authenticated_tenant_id = matched_tenant
                request.state.is_admin = False
                return await call_next(request)

        return JSONResponse(
            {"error": "Unauthorized", "detail": "Invalid Bearer token"},
            status_code=401,
        )


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
    lazy_config = config
    lazy_pipeline = pipeline
    lazy_storage = storage
    lazy_dynamic_config = dynamic_config

    pipeline_cache: dict[str, HybridRetrievalPipeline] = {}

    def get_config() -> CortexConfig:
        nonlocal lazy_config
        if lazy_config is None:
            lazy_config = load_config()
        return lazy_config

    def get_dynamic_config() -> DynamicConfigManager:
        nonlocal lazy_dynamic_config
        if lazy_dynamic_config is None:
            cfg = get_config()
            lazy_dynamic_config = DynamicConfigManager(data_dir=cfg.storage.data_dir)
        return lazy_dynamic_config

    def get_storage() -> StorageManager:
        nonlocal lazy_storage
        if lazy_storage is None:
            cfg = get_config()
            lazy_storage = StorageManager(cfg.storage.data_dir)
        return lazy_storage

    def get_explicit_requested_tenant(
        request: Request, body: dict[str, Any] | None = None
    ) -> str | None:
        """Extract explicitly requested tenant ID from header, query param, or JSON body."""
        header_tenant = request.headers.get("X-Tenant-ID", "").strip()
        if header_tenant:
            return header_tenant

        query_tenant = request.query_params.get(
            "tenant_id", request.query_params.get("tenant", "")
        ).strip()
        if query_tenant:
            return query_tenant

        if body and isinstance(body, dict):
            body_tenant = str(body.get("tenant_id", body.get("tenant", ""))).strip()
            if body_tenant:
                return body_tenant

        return None

    def check_tenant_isolation(
        request: Request, body: dict[str, Any] | None = None
    ) -> JSONResponse | None:
        """Verify that a tenant-scoped token does not access another tenant's resources."""
        auth_tenant = getattr(request.state, "authenticated_tenant_id", None)
        if not auth_tenant:
            return None
        requested = get_explicit_requested_tenant(request, body)
        if requested and requested != auth_tenant:
            return JSONResponse(
                {
                    "error": "Forbidden",
                    "detail": (
                        f"Tenant token for '{auth_tenant}' is not authorized "
                        f"to access tenant '{requested}'"
                    ),
                },
                status_code=403,
            )
        return None

    def resolve_tenant(request: Request, body: dict[str, Any] | None = None) -> str:
        """Resolve active tenant identifier from request state, header, query, or body."""
        if hasattr(request.state, "tenant_id") and request.state.tenant_id:
            return str(request.state.tenant_id).strip()

        explicit = get_explicit_requested_tenant(request, body)
        if explicit:
            return explicit

        return "default"

    def get_pipeline_for_tenant(
        tenant_id: str, tenant_cfg: CortexConfig
    ) -> HybridRetrievalPipeline:
        """Resolve or instantiate cached retrieval pipeline for tenant configuration."""
        if lazy_pipeline is not None:
            return lazy_pipeline

        cache_key = (
            f"{tenant_cfg.profile.value}:{tenant_cfg.storage.data_dir}:"
            f"{tenant_cfg.retrieval.k}:{tenant_cfg.retrieval.weight_dense}:"
            f"{tenant_cfg.retrieval.weight_sparse}"
        )
        if cache_key in pipeline_cache:
            return pipeline_cache[cache_key]

        pipe = HybridRetrievalPipeline.from_config(tenant_cfg)
        pipeline_cache[cache_key] = pipe
        return pipe

    cfg = get_config()
    effective_api_key = api_key if api_key is not None else cfg.remote.api_key

    async def health_endpoint(request: Request) -> JSONResponse:
        from cortex import __version__

        mgr = get_storage()
        total_chunks = mgr.count_chunks()
        current_cfg = get_config()
        profile = current_cfg.get_active_profile()
        dyn_mgr = get_dynamic_config()
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

        isolation_err = check_tenant_isolation(request, body)
        if isolation_err is not None:
            return isolation_err

        # Resolve tenant & tenant-specific configuration
        tenant_id = resolve_tenant(request, body)
        dyn_mgr = get_dynamic_config()
        tenant_cfg = dyn_mgr.get_tenant_config(tenant_id, fallback=get_config())

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

        pipe = get_pipeline_for_tenant(tenant_id, tenant_cfg)
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
        mgr = get_storage()
        records = mgr.get_repo_contracts(repo=repo, categories=categories, limit=limit)
        chunks = format_contract_chunks(repo, records)
        return JSONResponse([c.model_dump(mode="json") for c in chunks])

    async def technologies_endpoint(request: Request) -> JSONResponse:
        tech_name = request.query_params.get("tech_name")
        repo = request.query_params.get("repo")

        mgr = get_storage()
        records = mgr.get_technologies(repo=repo)
        summary = aggregate_tech_summary(records, tech_name=tech_name)
        return JSONResponse(summary.model_dump(mode="json"))

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

        engine = DependencyGraphEngine(get_storage())
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

        engine = DependencyGraphEngine(get_storage())
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

        engine = DependencyGraphEngine(get_storage())
        res = engine.get_signatures(
            query=query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )
        return JSONResponse(res.model_dump(mode="json"))

    async def drift_alerts_endpoint(request: Request) -> JSONResponse:
        repo = request.query_params.get("repo", "").strip() or None
        breaking_str = request.query_params.get("breaking_only", "false").lower()
        breaking_only = breaking_str in ("1", "true", "yes")
        cross_repo_str = request.query_params.get("cross_repo_only", "false").lower()
        cross_repo_only = cross_repo_str in ("1", "true", "yes")

        cfg = get_config()
        drift_engine = ContractDriftEngine.from_config(cfg)
        sources = resolve_sync_sources(
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

    # Dynamic Configuration Endpoints
    async def get_config_endpoint(request: Request) -> JSONResponse:
        isolation_err = check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = resolve_tenant(request)
        dyn_mgr = get_dynamic_config()
        effective_cfg = dyn_mgr.get_tenant_config(tenant_id, fallback=get_config())
        return JSONResponse(effective_cfg.model_dump(mode="json"))

    async def get_raw_config_endpoint(request: Request) -> JSONResponse:
        isolation_err = check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = resolve_tenant(request)
        dyn_mgr = get_dynamic_config()
        raw = dyn_mgr.get_raw_config(tenant_id)
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "configured": raw is not None,
                "config": raw if raw is not None else {},
            }
        )

    async def set_config_endpoint(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "Bad Request", "detail": "JSON body must be an object"},
                    status_code=400,
                )
        except Exception:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Invalid JSON body"},
                status_code=400,
            )

        isolation_err = check_tenant_isolation(request, body)
        if isolation_err is not None:
            return isolation_err

        tenant_id = resolve_tenant(request, body)
        raw_config_data = body.get("config", body)
        if not isinstance(raw_config_data, dict):
            return JSONResponse(
                {"error": "Bad Request", "detail": "Configuration must be a JSON object"},
                status_code=400,
            )

        # Exclude metadata envelope keys if body passed directly
        cleaned_config = {
            k: v
            for k, v in raw_config_data.items()
            if k not in ("tenant_id", "tenant", "description")
        }
        description = str(body.get("description", "")).strip()

        dyn_mgr = get_dynamic_config()
        try:
            saved = dyn_mgr.set_tenant_config(
                tenant_id=tenant_id,
                config_data=cleaned_config,
                description=description,
            )
            return JSONResponse(
                {
                    "status": "ok",
                    "tenant_id": tenant_id,
                    "config": saved,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": "Bad Request", "detail": str(exc)},
                status_code=400,
            )

    async def delete_config_endpoint(request: Request) -> JSONResponse:
        isolation_err = check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = resolve_tenant(request)
        dyn_mgr = get_dynamic_config()
        deleted = dyn_mgr.delete_tenant_config(tenant_id)
        return JSONResponse(
            {
                "status": "ok" if deleted else "not_found",
                "tenant_id": tenant_id,
                "deleted": deleted,
            }
        )

    async def list_tenants_endpoint(request: Request) -> JSONResponse:
        auth_tenant = getattr(request.state, "authenticated_tenant_id", None)
        dyn_mgr = get_dynamic_config()
        tenants = dyn_mgr.list_tenants()
        if auth_tenant:
            tenants = [t for t in tenants if str(t.get("tenant_id", "")).strip() == auth_tenant]
        return JSONResponse({"total_tenants": len(tenants), "tenants": tenants})

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

        current_cfg = get_config()
        effective_repo = (
            str(repo_filter).strip() if repo_filter and str(repo_filter).strip() else None
        )
        sources = resolve_sync_sources(
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
            eng = IngestionEngine.from_config(current_cfg)
            return eng.sync_all(sources=sources, force_full=force_full)

        results = await asyncio.to_thread(_do_sync)
        return JSONResponse(
            {
                "status": "ok",
                "total_synced": len(results),
                "synced": [r.model_dump() for r in results],
            }
        )

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/healthz", health_endpoint, methods=["GET"]),
        Route("/search", search_endpoint, methods=["GET", "POST"]),
        Route("/contracts", contracts_endpoint, methods=["GET"]),
        Route("/technologies", technologies_endpoint, methods=["GET"]),
        Route("/graph/dependencies", graph_dependencies_endpoint, methods=["GET"]),
        Route("/graph/dependents", graph_dependents_endpoint, methods=["GET"]),
        Route("/graph/signatures", graph_signatures_endpoint, methods=["GET"]),
        Route("/drift/alerts", drift_alerts_endpoint, methods=["GET"]),
        Route("/sync", sync_endpoint, methods=["POST"]),
        Route("/config", get_config_endpoint, methods=["GET"]),
        Route("/config", set_config_endpoint, methods=["POST", "PUT"]),
        Route("/config", delete_config_endpoint, methods=["DELETE"]),
        Route("/config/raw", get_raw_config_endpoint, methods=["GET"]),
        Route("/tenants", list_tenants_endpoint, methods=["GET"]),
    ]

    middleware: list[Middleware] = []
    dyn_for_middleware = dynamic_config or (lazy_dynamic_config if lazy_dynamic_config else None)
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
        should_watch = watch or get_config().sync.auto_watch
        if should_watch:
            cfg = get_config()
            interval = watch_interval if watch_interval is not None else cfg.sync.interval
            watcher = RepoWatcher(
                config=cfg,
                watcher_config=WatcherConfig(
                    interval=interval,
                    debounce=cfg.sync.debounce,
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
