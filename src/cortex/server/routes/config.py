"""Dynamic configuration and multi-tenant management routes for agent-cortex server."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cortex.server.context import ServerContext


def create_config_routes(ctx: ServerContext) -> list[Route]:
    async def get_config_endpoint(request: Request) -> JSONResponse:
        isolation_err = ctx.check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = ctx.resolve_tenant(request)
        dyn_mgr = ctx.get_dynamic_config()
        effective_cfg = dyn_mgr.get_tenant_config(tenant_id, fallback=ctx.get_config())
        return JSONResponse(effective_cfg.model_dump(mode="json"))

    async def get_raw_config_endpoint(request: Request) -> JSONResponse:
        isolation_err = ctx.check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = ctx.resolve_tenant(request)
        dyn_mgr = ctx.get_dynamic_config()
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

        isolation_err = ctx.check_tenant_isolation(request, body)
        if isolation_err is not None:
            return isolation_err

        tenant_id = ctx.resolve_tenant(request, body)
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

        dyn_mgr = ctx.get_dynamic_config()
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
        isolation_err = ctx.check_tenant_isolation(request)
        if isolation_err is not None:
            return isolation_err
        tenant_id = ctx.resolve_tenant(request)
        dyn_mgr = ctx.get_dynamic_config()
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
        dyn_mgr = ctx.get_dynamic_config()
        tenants = dyn_mgr.list_tenants()
        if auth_tenant:
            tenants = [t for t in tenants if str(t.get("tenant_id", "")).strip() == auth_tenant]
        return JSONResponse({"total_tenants": len(tenants), "tenants": tenants})

    return [
        Route("/config", get_config_endpoint, methods=["GET"]),
        Route("/config", set_config_endpoint, methods=["POST", "PUT"]),
        Route("/config", delete_config_endpoint, methods=["DELETE"]),
        Route("/config/raw", get_raw_config_endpoint, methods=["GET"]),
        Route("/tenants", list_tenants_endpoint, methods=["GET"]),
    ]
