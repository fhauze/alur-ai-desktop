# `get_service_order_status` — Langflow Tool Integration

> **Project:** ServiceIQ — AI-Powered Enterprise Service Intelligence Platform  
> **Component file:** [`langflow/components/service-order-tool/get_service_order_status.py`](../../langflow/components/service-order-tool/get_service_order_status.py)  
> **Manifest:** [`langflow/components/service-order-tool/component.json`](../../langflow/components/service-order-tool/component.json)  
> **API spec:** [`docs/api/openapi.yaml`](../api/openapi.yaml)  
> **Backend handler:** [`backend/api/service_orders.py`](../../backend/api/service_orders.py)  
> **Langflow version:** 1.12.0+

---

## Purpose

`get_service_order_status` is a Langflow custom component that gives the AI layer read-only access to ServiceIQ service order data. It calls the `GET /api/ai/service-orders/{order_number}` endpoint and returns a structured `Data` object the LLM can reason over.

The component enforces a strict security contract: it is the **only** permitted path for Langflow to interact with service order data. It never accesses the database, never constructs SQL, and never bypasses server-side authorization.

---

## Installation

### Option A — Custom components directory

1. Copy the `langflow/components/service-order-tool/` directory into your Langflow custom components path:

   ```bash
   cp -r langflow/components/service-order-tool/ \
     ~/.langflow/custom_components/service-order-tool/
   ```

2. Restart Langflow. The component appears in the sidebar under **ServiceIQ → Get Service Order Status**.

### Option B — Environment variable path

Set `LANGFLOW_COMPONENTS_PATH` to include the directory containing the component:

```bash
export LANGFLOW_COMPONENTS_PATH=/path/to/serviceiq/langflow/components
```

---

## Inputs

| Field | Type | Required | Configured by | Description |
|-------|------|----------|--------------|-------------|
| `order_number` | `MessageTextInput` | ✅ | LLM / flow | Human-readable order number (e.g. `ORD-2024-001`). The only value the LLM provides. 1–100 printable ASCII characters. |
| `api_base_url` | `StrInput` | ✅ | Operator | Base URL of the ServiceIQ AI API. Default: `https://api.serviceiq.example.com`. Set once; marked `advanced=True` so it is not exposed to LLM tool calls. |
| `bearer_token` | `SecretStrInput` | ✅ | Operator (secret store) | JWT Bearer token. **Must be stored in the Langflow secret store, not entered as a plain-text flow value.** See §Authentication below. |

> **LLM input boundary:** `order_number` is the only field marked `tool_mode=True`. `api_base_url` and `bearer_token` are operator-configured and invisible to the LLM.

---

## Output

A single `Data` output named `service_order` is returned by the `get_service_order_status` method.

### Success (`HTTP 200`)

```json
{
  "success": true,
  "order_number": "ORD-2024-001",
  "customer": {
    "id": 100,
    "name": "PT Maju Bersama"
  },
  "service_type": "Kalibrasi",
  "laboratory": {
    "id": 5,
    "name": "Lab Massa dan Volume"
  },
  "order_status": "in_progress",
  "inspection_status": "passed",
  "sla_status": "on_track"
}
```

### Error

All error conditions return the same `Data` envelope shape:

```json
{
  "success": false,
  "error_code": 403,
  "error": "Access denied. The token does not have permission to view this order, or the order does not exist.",
  "order_number": "ORD-2024-001"
}
```

### Field reference

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `success` | `boolean` | no | `true` on HTTP 200, `false` on all errors |
| `order_number` | `string` | yes | Human-readable order number |
| `customer` | `object\|null` | yes | `{id, name}` — null if customer lookup fails |
| `service_type` | `string\|null` | yes | Service type label (e.g. `Kalibrasi`) |
| `laboratory` | `object\|null` | yes | `{id, name}` — null if unassigned |
| `order_status` | `string` | no | One of: `new`, `in_progress`, `pending`, `certified`, `completed`, `cancelled` |
| `inspection_status` | `string` | no | One of: `no_inspection`, `passed`, `failed`, `partial` |
| `sla_status` | `string` | no | One of: `no_sla`, `on_track`, `at_risk`, `overdue`, `closed` |
| `error_code` | `integer` | — | Present only on error |
| `error` | `string` | — | Present only on error |

---

## Authentication

### How it works

The `bearer_token` field uses Langflow's `SecretStrInput` type. This means:

- The token value is **never stored in the flow JSON**.
- The token is **never logged** by Langflow.
- The token is **never passed as a plain-text field** that an LLM prompt can read.
- The value is only injected at execution time from the Langflow secret store.

### Token format

The JWT must carry the claims documented in [`docs/api/openapi.yaml §BearerAuth`](../api/openapi.yaml).

| Claim | Type | Role | Required |
|-------|------|------|---------|
| `sub` | string | all | yes |
| `role` | string | all | yes — one of `customer`, `staff`, `manager` |
| `customer_id` | integer | `customer` | required for customer role |
| `customer_scope` | integer[] | `staff` | required for staff role |
| `lab_scope` | integer[] | `manager` | required for manager role |
| `exp` | integer | all | yes |
| `iss` | string | all | yes |

### Setting the token in Langflow

1. In Langflow UI: **Settings → Variables → New Variable**
2. Name: `SERVICEIQ_BEARER_TOKEN`
3. Type: `Credential`
4. Paste the JWT value.
5. In the component's `bearer_token` field: enter `SERVICEIQ_BEARER_TOKEN` as the variable reference.

> **Do not** paste the raw JWT directly into the `bearer_token` field in the flow canvas. Use the variable reference only.

---

## Authorization Behaviour

Authorization is enforced **entirely server-side** by the ServiceIQ backend. The component passes the Bearer token and the order number — the backend performs all access control decisions.

| Role | Access granted when |
|------|---------------------|
| `customer` | Token's `customer_id` matches the order's customer |
| `staff` | Order's customer ID is within token's `customer_scope` |
| `manager` | Order's laboratory ID is within token's `lab_scope` |

### IDOR protection

The backend compares the token claims against the **fetched database record**, not against the URL parameter. A customer cannot access another customer's order by guessing a valid `order_number` — the check is against what the database returns, not what was requested.

### Opaque 403/404

The backend intentionally returns the **same error message** for `403` (denied) and `404` (not found):

```
"Order not found or access denied."
```

This prevents an attacker from confirming whether an `order_number` exists by comparing response messages. The Langflow component preserves this opacity — it reports slightly different `error` strings locally (to help operators debug) but **does not expose which condition occurred to the LLM prompt**.

---

## Error Handling

The component handles all documented error conditions and returns a structured `Data` object in every case. Raw exceptions are never surfaced to the LLM.

| HTTP status | `error_code` | `error` message |
|-------------|-------------|-----------------|
| `400` | 400 | `"The order number format was rejected by the server."` |
| `401` | 401 | `"Authentication failed. The Bearer token is missing, expired, or invalid."` |
| `403` | 403 | `"Access denied. The token does not have permission to view this order, or the order does not exist."` |
| `404` | 404 | `"Order not found. The order number may be incorrect, or access was denied."` |
| `5xx` | actual code | `"Unexpected response from ServiceIQ API (HTTP <N>)."` |
| Timeout | 504 | `"Request to ServiceIQ API timed out after 10s."` |
| Network error | 503 | `"Could not reach ServiceIQ API: <ExceptionType>."` |

### Client-side validation

Before any HTTP request is made, the component validates `order_number` against the same pattern used by the backend (`[\x20-\x7E]{1,100}`). Invalid inputs return a `400` error Data immediately without contacting the API. This is defence in depth — the backend performs its own independent validation.

---

## Security Rules

The following rules are permanent constraints on this component. They must not be modified without a security review.

| Rule | Implementation |
|------|---------------|
| **No direct database access** | Component has no database imports, no credentials, no asyncpg dependency |
| **No SQL construction** | No `SELECT`, `INSERT`, or any query string appears in this file |
| **Credentials in secret store only** | `bearer_token` uses `SecretStrInput`; value never in flow JSON |
| **LLM controls only `order_number`** | Only `order_number` has `tool_mode=True`; `api_base_url` and `bearer_token` are `advanced=True` |
| **No authorization bypass** | Backend enforces auth; component passes token as-is and accepts the result |
| **Structured error output** | All exceptions caught; `Data` returned with `success=False`; no stack traces |
| **Input validation** | `order_number` validated client-side before HTTP call |
| **Fixed timeout** | 10s request timeout; prevents indefinite hang |

---

## Flow Integration Example

### Minimal agent flow

```
[Chat Input]
     │
     ▼
[OpenAI Agent]
     │  tool: get_service_order_status(order_number)
     ▼
[Get Service Order Status]  ←── bearer_token: SERVICEIQ_BEARER_TOKEN (secret)
     │                      ←── api_base_url: https://api.serviceiq.example.com
     │ Data
     ▼
[Chat Output]
```

The LLM calls the tool when a user asks a question like:

> *"What is the status of order ORD-2024-001?"*
> *"Is my service order VER-2025-0042 overdue?"*
> *"Did order KAL-2023-0988 pass inspection?"*

The component returns a `Data` object the agent can include in its response.

### Example LLM prompt suggested response format

When writing a system prompt for an agent using this tool, include:

```
When a user asks about a service order:
1. Call get_service_order_status with the order_number the user provided.
2. If success is true, report: order_status, inspection_status, sla_status,
   and the laboratory name if available.
3. If success is false and error_code is 401, tell the user their session
   has expired and they should re-authenticate.
4. If success is false and error_code is 403 or 404, tell the user the
   order was not found or they do not have access to it.
5. Do not invent order details. Only report what the tool returned.
```

---

## Data Flow Diagram

```
User prompt
    │
    ▼
LLM Agent
    │  tool_call: get_service_order_status
    │    arg: order_number = "ORD-2024-001"
    ▼
GetServiceOrderStatusComponent
    │
    ├── validate order_number (client-side)
    │
    ├── GET https://api.serviceiq.example.com
    │       /api/ai/service-orders/ORD-2024-001
    │   Headers:
    │     Authorization: Bearer <token from secret store>
    │     Accept: application/json
    │
    │   [ServiceIQ Backend]
    │     │ AuthMiddleware → decode JWT → Principal
    │     │ RepositoryMiddleware → AIServiceOrderRepository
    │     │ get_by_order_number("ORD-2024-001")
    │     │   → SELECT ... FROM public.ai_service_order_summary
    │     │       WHERE order_number = $1   ← parameterised
    │     │ require_order_access(principal, order)
    │     └── JSON response
    │
    └── Data { success, order_number, order_status, ... }
         │
         ▼
    LLM Agent response to user
```

---

## Versioning

| Version | Langflow | Change |
|---------|----------|--------|
| 1.0.0 | 1.12.0+ | Initial release |

When the ServiceIQ API response schema changes (new fields, renamed fields, new enum values), update:

1. [`backend/domain/AIServiceOrder.py`](../../backend/domain/AIServiceOrder.py) — add enum value
2. [`database/views/ai_service_order_summary.sql`](../../database/views/ai_service_order_summary.sql) — update view
3. [`docs/api/openapi.yaml`](../api/openapi.yaml) — add to schema
4. This component's `get_service_order_status` method — add field to success `Data`
5. Bump `version` in [`component.json`](../../langflow/components/service-order-tool/component.json)
