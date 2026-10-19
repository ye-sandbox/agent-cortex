"""Authentication and security middleware for agent-cortex server."""

from __future__ import annotations

import hmac
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from cortex.config.dynamic import DynamicConfigManager


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
