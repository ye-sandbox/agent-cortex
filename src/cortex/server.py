"""Lightweight HTTP daemon server for agent-cortex.

Provides streaming JSON and NDJSON endpoints for semantic search, repository contract
inspection, technology discovery, dynamic configuration management, and health probes
with multi-tenant resolution and Bearer token authentication.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
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
from cortex.models.chunk import ChunkCategory, ChunkScope, SearchResultChunk
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

        # 1. Global API key match
        if self.api_key and token == self.api_key:
            return await call_next(request)

        # 2. Check tenant-specific API keys if dynamic config is available
        if self.dynamic_config is not None:
            for tenant in self.dynamic_config.list_tenants():
                t_id = str(tenant.get("tenant_id", "")).strip()
                if not t_id:
                    continue
                raw_cfg = self.dynamic_config.get_raw_config(t_id)
                if not raw_cfg:
                    continue
                tenant_remote = raw_cfg.get("remote")
                t_key: str | None = None
                if isinstance(tenant_remote, dict):
                    raw_val = tenant_remote.get("api_key")
                    if raw_val:
                        t_key = str(raw_val).strip()
                if not t_key and "api_key" in raw_cfg:
                    t_key = str(raw_cfg["api_key"]).strip()

                if t_key and t_key == token:
                    request.state.tenant_id = t_id
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

    def resolve_tenant(request: Request, body: dict[str, Any] | None = None) -> str:
        """Resolve active tenant identifier from request state, header, query, or body."""
        if hasattr(request.state, "tenant_id") and request.state.tenant_id:
            return str(request.state.tenant_id).strip()

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

        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "profile": profile.name,
                "total_chunks": total_chunks,
                "storage_dir": str(current_cfg.storage.data_dir),
                "tenants_count": len(tenants),
            }
        )

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

        categories: list[str]
        if contract_type:
            ct = contract_type.strip().lower()
            if ct in ("openapi", "api", "contract"):
                categories = ["contract"]
            elif ct in ("compose", "docker", "infra"):
                categories = ["infra"]
            elif ct in ("invariant", "rule", "invariants"):
                categories = ["invariant"]
            elif ct == "all":
                categories = ["contract", "infra", "invariant"]
            else:
                categories = [ct]
        else:
            categories = ["contract", "infra", "invariant"]

        mgr = get_storage()
        records = mgr.get_repo_contracts(repo=repo, categories=categories, limit=limit)

        results: list[dict[str, Any]] = []
        for rec in records:
            file_path = str(rec.get("file_path", ""))
            breadcrumb = str(rec.get("breadcrumb", ""))
            anchor = (
                f"[{repo}] {file_path} > {breadcrumb}" if breadcrumb else f"[{repo}] {file_path}"
            )
            raw_tags = rec.get("tags")
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, Sequence) else []
            results.append(
                {
                    "anchor": anchor,
                    "repo": repo,
                    "file_path": file_path,
                    "category": str(rec.get("category", "contract")),
                    "breadcrumb": breadcrumb,
                    "tags": tags,
                    "content": str(rec.get("content", "")),
                }
            )

        return JSONResponse(results)

    async def technologies_endpoint(request: Request) -> JSONResponse:
        tech_name = request.query_params.get("tech_name")
        repo = request.query_params.get("repo")

        mgr = get_storage()
        records = mgr.get_technologies(repo=repo)

        repo_map: dict[str, set[str]] = defaultdict(set)
        count_map: dict[str, int] = defaultdict(int)

        filter_tech = tech_name.strip().lower() if tech_name and tech_name.strip() else None

        for rec in records:
            r_repo = str(rec.get("repo", "")).strip()
            raw_tags = rec.get("tags")
            if not isinstance(raw_tags, Sequence):
                continue

            for tag in raw_tags:
                clean_tag = str(tag).strip()
                if not clean_tag:
                    continue

                if filter_tech and filter_tech not in clean_tag.lower():
                    continue

                repo_map[clean_tag].add(r_repo)
                count_map[clean_tag] += 1

        sorted_keys = sorted(count_map.keys(), key=lambda k: (-count_map[k], k.lower()))
        tech_items = [
            {
                "technology": t,
                "repositories": sorted(repo_map[t]),
                "chunk_count": count_map[t],
            }
            for t in sorted_keys
        ]

        return JSONResponse(
            {
                "total_technologies": len(tech_items),
                "technologies": tech_items,
            }
        )

    # Dynamic Configuration Endpoints
    async def get_config_endpoint(request: Request) -> JSONResponse:
        tenant_id = resolve_tenant(request)
        dyn_mgr = get_dynamic_config()
        effective_cfg = dyn_mgr.get_tenant_config(tenant_id, fallback=get_config())
        return JSONResponse(effective_cfg.model_dump(mode="json"))

    async def get_raw_config_endpoint(request: Request) -> JSONResponse:
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
        dyn_mgr = get_dynamic_config()
        tenants = dyn_mgr.list_tenants()
        return JSONResponse({"total_tenants": len(tenants), "tenants": tenants})

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/healthz", health_endpoint, methods=["GET"]),
        Route("/search", search_endpoint, methods=["GET", "POST"]),
        Route("/contracts", contracts_endpoint, methods=["GET"]),
        Route("/technologies", technologies_endpoint, methods=["GET"]),
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

    return Starlette(routes=routes, middleware=middleware)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    api_key: str | None = None,
    config: CortexConfig | None = None,
    log_level: str = "info",
    dynamic_config: DynamicConfigManager | None = None,
) -> None:
    """Launch uvicorn server running agent-cortex daemon."""
    app = create_app(config=config, api_key=api_key, dynamic_config=dynamic_config)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
