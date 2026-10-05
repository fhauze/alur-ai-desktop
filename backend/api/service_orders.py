"""
backend/api/service_orders.py
------------------------------
Route handler for:

    GET /api/ai/service-orders/{order_number}

Responsibilities of this module
────────────────────────────────
1. Validate the ``order_number`` path parameter (format guard — no raw DB
   values are constructed from request input).
2. Resolve the authenticated Principal from request state (set by middleware).
3. Call the repository — only the semantic view is queried; no direct table
   access from this layer.
4. Enforce server-side authorisation via the authorization guard (IDOR
   prevention: the check is against the *fetched* record's customer_id, not
   the URL parameter).
5. Return a filtered response that exposes only the required fields.
6. Map all error conditions to appropriate HTTP status codes with opaque
   messages that do not reveal whether an order exists to an unauthorised
   caller.

What this module does NOT do
─────────────────────────────
- Does not construct SQL from request data.
- Does not access the database directly.
- Does not perform access control based solely on the URL parameter.
- Does not expose fields beyond the required response schema.
- Does not reveal customer data to unauthorised callers.

Response shape
──────────────
{
  "order_number":      str | null,
  "customer":          { "id": int, "name": str | null } | null,
  "service_type":      str | null,
  "laboratory":        { "id": int, "name": str | null } | null,
  "order_status":      str,
  "inspection_status": str,
  "sla_status":        str
}

HTTP status codes
─────────────────
  200 — order found and caller is authorised
  400 — order_number fails format validation
  401 — no authenticated principal on the request
  403 — principal exists but is not authorised for this order
        (same shape as 404 — does not reveal order existence)
  404 — order not found
        (same message as 403 to prevent enumeration)
"""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.auth.authorization import AccessDeniedError, require_order_access
from backend.auth.principal import Principal
from backend.repositories.AIServiceOrderRepository import AIServiceOrderRepository

# ---------------------------------------------------------------------------
# order_number validation
#
# order_number comes from a URL path segment and must be validated before use.
# The repository only queries the view with it as a parameterised value, but
# we still reject obviously malformed inputs early to fail fast and cleanly.
#
# Accepted format: printable ASCII, 1–100 characters, no control characters.
# This is deliberately broad — actual order number patterns (e.g. ORD-2024-001)
# are a business concern; the API rejects only structurally invalid input.
# ---------------------------------------------------------------------------
_ORDER_NUMBER_RE = re.compile(r"^[\x20-\x7E]{1,100}$")


def _validate_order_number(order_number: str) -> bool:
    """Return True if order_number passes format validation."""
    return bool(_ORDER_NUMBER_RE.match(order_number))


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"error": detail}, status_code=status)


def _order_response(order: Any) -> JSONResponse:
    """Build the restricted API response from an AIServiceOrder domain object.

    Only the fields listed in the response schema are included.
    Internal fields (service_order_id, track, service_request_id, sla_deadline,
    laboratory_id, customer_id) are deliberately excluded.
    """
    customer = (
        {"id": order.customer_id, "name": order.customer_name}
        if order.customer_id is not None
        else None
    )
    laboratory = (
        {"id": order.laboratory_id, "name": order.laboratory_name}
        if order.laboratory_id is not None
        else None
    )
    body = {
        "order_number":      order.order_number,
        "customer":          customer,
        "service_type":      order.service_type,
        "laboratory":        laboratory,
        "order_status":      order.order_status.value,
        "inspection_status": order.inspection_status.value,
        "sla_status":        order.sla_status.value,
    }
    return JSONResponse(body, status_code=200)


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


async def get_service_order(request: Request) -> Response:
    """Handle GET /api/ai/service-orders/{order_number}.

    Pipeline:
      1. Extract and validate path parameter.
      2. Resolve Principal from request state.
      3. Query repository by order_number (parameterised).
      4. 404 if not found.
      5. Authorise principal against fetched record.
      6. 403 (opaque) if denied.
      7. Return filtered response.
    """
    # ── Step 1: validate path parameter ─────────────────────────────────────
    order_number: str = request.path_params["order_number"]
    if not _validate_order_number(order_number):
        return _error(400, "Invalid order number format.")

    # ── Step 2: resolve authenticated principal ──────────────────────────────
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        return _error(401, "Authentication required.")

    # ── Step 3: query the repository ─────────────────────────────────────────
    repo: AIServiceOrderRepository = request.state.repo
    orders = await repo.get_by_order_number(order_number)

    # ── Step 4: not found ────────────────────────────────────────────────────
    if orders is None:
        # Use the same message as 403 — prevents order-existence enumeration.
        return _error(404, "Order not found or access denied.")

    # ── Step 5 & 6: authorise ────────────────────────────────────────────────
    try:
        require_order_access(principal, orders)
    except AccessDeniedError:
        # 403 has identical message to 404 — an unauthenticated guesser cannot
        # distinguish "exists but denied" from "does not exist".
        return _error(403, "Order not found or access denied.")

    # ── Step 7: return filtered response ────────────────────────────────────
    return _order_response(orders)
