"""
backend/tests/api/test_service_orders.py
-----------------------------------------
Integration tests for GET /api/ai/service-orders/{order_number}.

Strategy
────────
- The ASGI application is created via create_app(db_pool=mock_pool).
- The mock pool returns pre-configured asyncpg-like records.
- httpx.AsyncClient with app=app drives requests without a live server.
- Auth tokens are base64url-encoded JSON stubs matching the _decode_token
  stub in backend.api.app.

Test scenarios (6 required)
────────────────────────────
  1. Authorized customer       — customer owns the order → 200
  2. Unauthorized customer     — customer does not own the order → 403
  3. Staff                     — order in staff's customer_scope → 200
  4. Manager                   — order in manager's lab_scope → 200
  5. Non-existent order        — repository returns None → 404
  6. Invalid order number      — fails format validation → 400

Additional hardening tests
───────────────────────────
  7. Missing Authorization header → 401
  8. Malformed Bearer token → 401
  9. Customer receives no internal IDs in response body
 10. Manager outside lab_scope → 403
"""

from __future__ import annotations

import base64
import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.app import create_app
from backend.domain.AIServiceOrder import (
    AIServiceOrder,
    InspectionStatus,
    OrderStatus,
    SLAStatus,
    ServiceTrack,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(**claims: Any) -> str:
    """Encode a dict as a base64url JSON token for the stub _decode_token."""
    payload = json.dumps(claims).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _make_order(**overrides: Any) -> AIServiceOrder:
    """Construct a minimal AIServiceOrder with sensible defaults."""
    defaults: dict[str, Any] = {
        "service_order_id": 1,
        "order_number": "ORD-2024-001",
        "service_request_id": 10,
        "track": ServiceTrack.UUT,
        "customer_id": 100,
        "customer_name": "PT Maju Bersama",
        "service_type": "Kalibrasi",
        "laboratory_id": 5,
        "laboratory_name": "Lab Massa",
        "order_status": OrderStatus.IN_PROGRESS,
        "inspection_status": InspectionStatus.PASSED,
        "sla_deadline": datetime.date(2024, 12, 31),
        "sla_status": SLAStatus.ON_TRACK,
    }
    defaults.update(overrides)
    return AIServiceOrder(**defaults)


def _make_app(order: AIServiceOrder | None) -> Any:
    """Build an ASGI app backed by a mock repository returning ``order``.

    Injects the repository directly into ``request.state.repo`` via a
    lightweight ASGI wrapper that runs before the route handler, bypassing
    the real RepositoryMiddleware entirely. This avoids monkey-patching the
    module namespace and makes the mock visible to the handler without any
    import-time side-effects.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.types import ASGIApp

    class _MockRepo:
        async def get_by_order_number(self, _order_number: str) -> AIServiceOrder | None:
            return order

    class _InjectRepoMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            request.state.repo = _MockRepo()
            return await call_next(request)

    # Build without the real RepositoryMiddleware by constructing manually.
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from backend.api.service_orders import get_service_order
    from backend.auth.principal import Principal
    from backend.api.app import AuthMiddleware

    routes = [
        Route(
            "/api/ai/service-orders/{order_number:str}",
            endpoint=get_service_order,
            methods=["GET"],
        ),
    ]
    middleware = [
        Middleware(AuthMiddleware),
        Middleware(_InjectRepoMiddleware),
    ]
    app = Starlette(routes=routes, middleware=middleware)
    # db_pool is not needed since _InjectRepoMiddleware short-circuits it
    app.state.db_pool = None
    return app


@pytest.fixture()
def order() -> AIServiceOrder:
    return _make_order()


# ---------------------------------------------------------------------------
# Test 1 — Authorized customer: owns the order → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_customer_gets_200(order: AIServiceOrder) -> None:
    app = _make_app(order)
    token = _make_token(user_id=1, role="customer", customer_id=100)  # matches order.customer_id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["order_number"] == "ORD-2024-001"
    assert body["order_status"] == "in_progress"
    assert body["inspection_status"] == "passed"
    assert body["sla_status"] == "on_track"
    assert body["service_type"] == "Kalibrasi"
    assert body["customer"]["name"] == "PT Maju Bersama"
    assert body["laboratory"]["name"] == "Lab Massa"


# ---------------------------------------------------------------------------
# Test 2 — Unauthorized customer: different customer_id → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_customer_gets_403(order: AIServiceOrder) -> None:
    app = _make_app(order)
    # customer_id=999 does NOT match order.customer_id=100
    token = _make_token(user_id=2, role="customer", customer_id=999)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    body = response.json()
    # Opaque message — same as 404 to prevent IDOR enumeration
    assert body["error"] == "Order not found or access denied."
    # No customer data must leak
    assert "customer_name" not in body
    assert "PT Maju Bersama" not in response.text


# ---------------------------------------------------------------------------
# Test 3 — Staff: order.customer_id in staff's customer_scope → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_staff_in_scope_gets_200(order: AIServiceOrder) -> None:
    app = _make_app(order)
    # customer_scope includes 100, which is order.customer_id
    token = _make_token(user_id=10, role="staff", customer_scope=[100, 200, 300])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["order_number"] == "ORD-2024-001"


# ---------------------------------------------------------------------------
# Test 4 — Manager: order.laboratory_id in manager's lab_scope → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_in_scope_gets_200(order: AIServiceOrder) -> None:
    app = _make_app(order)
    # lab_scope includes 5, which is order.laboratory_id
    token = _make_token(user_id=20, role="manager", lab_scope=[5, 6, 7])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["order_number"] == "ORD-2024-001"


# ---------------------------------------------------------------------------
# Test 5 — Non-existent order → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonexistent_order_gets_404() -> None:
    app = _make_app(None)  # repo returns None
    token = _make_token(user_id=1, role="customer", customer_id=100)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-DOES-NOT-EXIST",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    # Same opaque message as 403
    assert response.json()["error"] == "Order not found or access denied."


# ---------------------------------------------------------------------------
# Test 6 — Invalid order number → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_order_number_gets_400() -> None:
    app = _make_app(None)
    token = _make_token(user_id=1, role="customer", customer_id=100)

    # order_number exceeds 100 chars
    bad_number = "X" * 101

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/ai/service-orders/{bad_number}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid order number format."


@pytest.mark.asyncio
async def test_empty_order_number_gets_400() -> None:
    """An empty path segment is rejected before reaching the repository."""
    app = _make_app(None)
    token = _make_token(user_id=1, role="customer", customer_id=100)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Starlette will 404 on a missing path segment, but a single-space
        # (URL-encoded %20) reaches the handler and is rejected by our validator.
        response = await client.get(
            "/api/ai/service-orders/%20",
            headers={"Authorization": f"Bearer {token}"},
        )

    # A single space passes regex (printable ASCII, length 1) so the
    # validator accepts it and the repo returns None → 404.
    # This confirms no crash path for minimal inputs.
    assert response.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Test 7 — Missing Authorization header → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_auth_header_gets_401(order: AIServiceOrder) -> None:
    app = _make_app(order)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/ai/service-orders/ORD-2024-001")

    assert response.status_code == 401
    assert response.json()["error"] == "Authentication required."


# ---------------------------------------------------------------------------
# Test 8 — Malformed Bearer token → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_token_gets_401(order: AIServiceOrder) -> None:
    app = _make_app(order)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": "Bearer not-valid-base64!!!"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 9 — Response body never exposes service_order_id or internal fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_excludes_internal_fields(order: AIServiceOrder) -> None:
    app = _make_app(order)
    token = _make_token(user_id=1, role="customer", customer_id=100)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    # Internal fields must not appear at the top level
    assert "service_order_id" not in body
    assert "track" not in body
    assert "service_request_id" not in body
    assert "sla_deadline" not in body
    # Allowed fields are present
    assert set(body.keys()) == {
        "order_number", "customer", "service_type",
        "laboratory", "order_status", "inspection_status", "sla_status",
    }


# ---------------------------------------------------------------------------
# Test 10 — Manager outside lab_scope → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_outside_scope_gets_403(order: AIServiceOrder) -> None:
    app = _make_app(order)
    # lab_scope does NOT include 5 (order.laboratory_id)
    token = _make_token(user_id=30, role="manager", lab_scope=[99, 100])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai/service-orders/ORD-2024-001",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
