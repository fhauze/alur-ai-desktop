"""
langflow/components/service-order-tool/get_service_order_status.py
-------------------------------------------------------------------
Langflow custom component: get_service_order_status

Tool name:   get_service_order_status
Description: Retrieve the authorised status of a service order.

Security contract
─────────────────
This component is the ONLY permitted path for Langflow to interact with
service order data. It enforces the following invariants:

  1. Authentication  — a Bearer token is fetched from the Langflow secret
                       store (SecretStrInput). The token is never logged,
                       never embedded in flow JSON, and never passed as a
                       plain-text input.

  2. No direct DB    — the component calls the ServiceIQ AI API HTTP endpoint.
                       It has no database credentials and no knowledge of the
                       underlying schema.

  3. Input-only      — the only value taken from LLM/flow context is
                       order_number. The API URL and credentials are
                       configured by an operator, not by the LLM.

  4. Authorization   — access control is enforced server-side by the backend.
                       This component never bypasses or re-implements auth.

  5. Error isolation — all HTTP error codes (400, 401, 403, 404, 500+) are
                       caught and returned as structured error Data objects.
                       Exceptions never surface raw stack traces to the LLM.

  6. No SQL          — this component constructs zero SQL. The order_number
                       is passed as a URL path segment to the backend, which
                       uses parameterised queries exclusively.

Langflow version: 1.12.4+
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from langflow.custom import Component
from langflow.io import MessageTextInput, Output, SecretStrInput, StrInput
from langflow.schema import Data

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Must match the server-side regex in backend/api/service_orders.py:
#   r"^[\x20-\x7E]{1,100}$"
# Validated here too so malformed inputs are rejected before an HTTP call
# is made — defence in depth, not a replacement for server-side validation.
_ORDER_NUMBER_RE = re.compile(r"^[\x20-\x7E]{1,100}$")

# Timeout for the outbound HTTP request (seconds).
_REQUEST_TIMEOUT = 10


def _validate_order_number(order_number: str) -> str | None:
    """Return None if valid, or an error message if invalid."""
    if not order_number or not order_number.strip():
        return "order_number must not be empty."
    if len(order_number) > 100:
        return "order_number must not exceed 100 characters."
    if not _ORDER_NUMBER_RE.match(order_number):
        return "order_number contains invalid characters. Printable ASCII only (1–100 chars)."
    return None


def _error_data(code: int, detail: str, order_number: str) -> Data:
    """Build a structured error Data object returned on non-200 responses."""
    return Data(
        data={
            "success": False,
            "error_code": code,
            "error": detail,
            "order_number": order_number,
        }
    )


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


class GetServiceOrderStatusComponent(Component):
    """Retrieve the authorised status of a service order from ServiceIQ.

    Calls GET /api/ai/service-orders/{order_number} on the ServiceIQ AI
    API and returns a structured Data object containing the order status,
    inspection status, SLA status, customer, laboratory, and service type.

    The component authenticates with a Bearer token stored in the Langflow
    secret store. It never accesses the database directly and never bypasses
    server-side authorization.
    """

    # ── Component metadata ────────────────────────────────────────────────────

    display_name = "Get Service Order Status"
    description = "Retrieve the authorised status of a service order from ServiceIQ."
    icon = "ClipboardList"
    name = "GetServiceOrderStatus"
    documentation = "https://github.com/your-org/serviceiq/blob/main/docs/langflow/service-order-tool.md"

    # ── Inputs ────────────────────────────────────────────────────────────────

    inputs = [
        # Primary input — provided by the LLM or flow context.
        MessageTextInput(
            name="order_number",
            display_name="Order Number",
            info=(
                "The human-readable service order number to look up. "
                "Example: ORD-2024-001. "
                "Must be 1–100 printable ASCII characters."
            ),
            tool_mode=True,   # exposes this field to LLM tool-call routing
            required=True,
        ),

        # Operator-configured inputs — set once by the platform team,
        # never supplied by the LLM or by untrusted flow input.
        StrInput(
            name="api_base_url",
            display_name="API Base URL",
            info=(
                "Base URL of the ServiceIQ AI API. "
                "Example: https://api.serviceiq.example.com"
            ),
            value="https://api.serviceiq.example.com",
            advanced=True,
            required=True,
        ),
        SecretStrInput(
            name="bearer_token",
            display_name="Bearer Token",
            info=(
                "JWT Bearer token for the ServiceIQ AI API. "
                "Store this in the Langflow secret store — never enter it "
                "as a plain-text flow value. "
                "The token must carry role and scope claims as documented in "
                "docs/api/openapi.yaml §BearerAuth."
            ),
            required=True,
            # 'value' intentionally omitted — must be set via secret store.
        ),
    ]

    # ── Outputs ───────────────────────────────────────────────────────────────

    outputs = [
        Output(
            display_name="Service Order",
            name="service_order",
            method="get_service_order_status",
        ),
    ]

    # ── Build method ──────────────────────────────────────────────────────────

    async def get_service_order_status(self) -> Data:
        """Fetch the service order status from the ServiceIQ AI API.

        Pipeline:
          1. Validate order_number input (client-side defence-in-depth).
          2. Construct the request URL (no user input in query/headers).
          3. Issue authenticated GET request with timeout.
          4. Map HTTP status codes to structured Data objects.
          5. Return typed Data — never a raw exception or stack trace.

        Returns:
            Data with ``success=True`` and order fields on HTTP 200.
            Data with ``success=False``, ``error_code``, and ``error``
            on any error condition.
        """
        order_number: str = self.order_number

        # ── Step 1: validate order_number ─────────────────────────────────────
        validation_error = _validate_order_number(order_number)
        if validation_error:
            result = _error_data(400, validation_error, order_number)
            self.status = f"Validation error: {validation_error}"
            return result

        # ── Step 2: build URL ─────────────────────────────────────────────────
        # The order_number is URL-path-encoded by httpx; no manual interpolation.
        # api_base_url is operator-configured, never LLM-supplied.
        base = self.api_base_url.rstrip("/")
        url = f"{base}/api/ai/service-orders/{order_number}"

        # ── Step 3: issue authenticated request ───────────────────────────────
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException:
            result = _error_data(
                504,
                f"Request to ServiceIQ API timed out after {_REQUEST_TIMEOUT}s.",
                order_number,
            )
            self.status = "Timeout"
            return result
        except httpx.RequestError as exc:
            result = _error_data(
                503,
                f"Could not reach ServiceIQ API: {type(exc).__name__}.",
                order_number,
            )
            self.status = f"Connection error: {type(exc).__name__}"
            return result

        # ── Step 4: map HTTP status codes ──────────────────────────────────────
        status_code = response.status_code

        if status_code == 200:
            try:
                body: dict[str, Any] = response.json()
            except json.JSONDecodeError:
                result = _error_data(
                    502,
                    "ServiceIQ API returned a non-JSON 200 response.",
                    order_number,
                )
                self.status = "Invalid JSON response"
                return result

            result = Data(
                data={
                    "success": True,
                    "order_number":      body.get("order_number"),
                    "customer":          body.get("customer"),
                    "service_type":      body.get("service_type"),
                    "laboratory":        body.get("laboratory"),
                    "order_status":      body.get("order_status"),
                    "inspection_status": body.get("inspection_status"),
                    "sla_status":        body.get("sla_status"),
                }
            )
            self.status = f"OK — {body.get('order_status', 'unknown')}"
            return result

        if status_code == 400:
            result = _error_data(
                400,
                "The order number format was rejected by the server.",
                order_number,
            )
            self.status = "400 Bad Request"
            return result

        if status_code == 401:
            result = _error_data(
                401,
                (
                    "Authentication failed. The Bearer token is missing, "
                    "expired, or invalid. Check the bearer_token secret."
                ),
                order_number,
            )
            self.status = "401 Unauthorized"
            return result

        if status_code == 403:
            result = _error_data(
                403,
                (
                    "Access denied. The token does not have permission to "
                    "view this order, or the order does not exist."
                ),
                order_number,
            )
            self.status = "403 Forbidden"
            return result

        if status_code == 404:
            result = _error_data(
                404,
                (
                    "Order not found. The order number may be incorrect, "
                    "or access was denied (403 and 404 return the same "
                    "message server-side to prevent enumeration)."
                ),
                order_number,
            )
            self.status = "404 Not Found"
            return result

        # 500 and all other unexpected codes
        result = _error_data(
            status_code,
            f"Unexpected response from ServiceIQ API (HTTP {status_code}).",
            order_number,
        )
        self.status = f"HTTP {status_code}"
        return result
