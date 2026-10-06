"""
backend/api/app.py
-------------------
ASGI application factory for the ServiceIQ AI API.

Wires together:
  - Starlette routing
  - Auth middleware (reads Bearer token → Principal)
  - Repository injection (via request.state)

Authentication middleware
─────────────────────────
In production, replace ``_decode_token`` with a real JWT verification call
(e.g. python-jose, PyJWT, or an introspection endpoint). The Principal shape
and injection point remain identical regardless of the token implementation.

The middleware never reveals token validation details in the response body.

Database pool injection
───────────────────────
The pool is initialised once at startup and stored on app.state. The
middleware injects the repository into request.state so that route handlers
receive it without importing the pool directly. Credentials live only in
environment variables (backend.db.connection).
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
# When this file is loaded directly (e.g. ``uvicorn app:app`` from backend/api/)
# the project root is not on sys.path and ``from backend.api...`` would fail.
# Inserting the project root (two levels up from this file) fixes that without
# requiring the caller to set PYTHONPATH manually.
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))          # .../backend/api
_project_root = os.path.dirname(os.path.dirname(_here))     # project root
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from backend.api.service_orders import get_service_order
from backend.auth.principal import Principal, Role
from backend.repositories.AIServiceOrderRepository import AIServiceOrderRepository


# ---------------------------------------------------------------------------
# Token → Principal decoder
#
# Replace the body of _decode_token with real JWT verification.
# The function must return a Principal on success or None on failure.
# It must never raise — authentication failures must produce None so that
# the middleware can return a uniform 401 without leaking internals.
# ---------------------------------------------------------------------------


def _decode_token(token: str) -> Principal | None:
    """Decode a Bearer token into a Principal.

    STUB IMPLEMENTATION — replace with real JWT verification before production.

    Expected token format (for testing and development):
      A JSON string base64url-encoded, e.g.:
        {"user_id": 1, "role": "customer", "customer_id": 100}
        {"user_id": 2, "role": "staff",    "customer_scope": [100, 200]}
        {"user_id": 3, "role": "manager",  "lab_scope": [5, 6]}

    In production this function would:
      1. Verify the JWT signature against the public key.
      2. Validate exp/iat/iss claims.
      3. Extract the claims and build a Principal.
    """
    import base64

    try:
        # Pad base64url to a multiple of 4
        padded = token + "=" * (-len(token) % 4)
        claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))

        role = Role(claims["role"])
        return Principal(
            user_id=int(claims["user_id"]),
            role=role,
            customer_id=claims.get("customer_id"),
            customer_scope=frozenset(claims.get("customer_scope", [])),
            lab_scope=frozenset(claims.get("lab_scope", [])),
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract and decode the Bearer token; attach Principal to request.state.

    Requests without a valid token proceed with principal = None.
    The route handler is responsible for enforcing authentication (returning
    401 if principal is None). This separation means non-auth routes (e.g.
    health checks) can exist without tokens.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        principal: Principal | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            principal = _decode_token(token)
        request.state.principal = principal
        return await call_next(request)


# ---------------------------------------------------------------------------
# Repository injection middleware
# ---------------------------------------------------------------------------


class RepositoryMiddleware(BaseHTTPMiddleware):
    """Attach a fresh AIServiceOrderRepository to each request.

    The repository wraps the application-level connection pool. No connection
    is acquired until the repository method is called. Credentials are never
    visible here — the pool is initialised from environment variables at
    startup in create_app().
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        pool = request.app.state.db_pool
        request.state.repo = AIServiceOrderRepository(pool)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(db_pool: Any = None) -> Starlette:
    """Create and return the configured Starlette ASGI application.

    Args:
        db_pool: An asyncpg Pool. If None, the pool is initialised from
                 environment variables at startup (production path).
                 Pass a mock pool in tests.

    Returns:
        A Starlette application ready to be served by uvicorn.
    """
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route(
            "/api/ai/service-orders/{order_number:str}",
            endpoint=get_service_order,
            methods=["GET"],
        ),
    ]

    middleware = [
        Middleware(AuthMiddleware),
        Middleware(RepositoryMiddleware),
    ]

    if db_pool is not None:
        # Test path: pool provided by caller, no lifespan needed.
        app = Starlette(routes=routes, middleware=middleware)
        app.state.db_pool = db_pool
    else:
        # Production path: manage pool via lifespan context manager.
        @asynccontextmanager
        async def lifespan(app: Starlette):  # type: ignore[type-arg]
            from backend.db.connection import close_pool, init_pool
            app.state.db_pool = await init_pool()
            yield
            await close_pool()

        app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)

    return app


# ---------------------------------------------------------------------------
# Module-level application instance
# ---------------------------------------------------------------------------
# Exposes a pre-built ``app`` object so uvicorn can be pointed at this module
# in two equivalent ways:
#
#   From the project root (recommended):
#     PYTHONPATH=. uvicorn backend.api.app:create_app --factory
#
#   From backend/api/ (simple, no PYTHONPATH needed):
#     uvicorn app:app --reload
#
# The factory path is preferred in production (pool initialised via lifespan).
# The module-level ``app`` uses the same production path.
# ---------------------------------------------------------------------------
app = create_app()
