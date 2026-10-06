# ServiceIQ End-to-End Analysis

> Status: **VERIFIED WORKING** — Last validated: 2026-10-06  
> All 17 acceptance criteria confirmed.

---

## 1. Current Architecture

```
User (Langflow Playground / API)
    │
    ▼
Langflow 1.12.2 — http://localhost:7860
    │  Flow: "ServiceIQ Customer Agent" (ID: 975f52f6-7883-4543-803c-45bfb9860e72)
    │  LLM: gemini-3.6-flash (Google Generative AI, built-in Agent dropdown)
    │  API key: GOOGLE_API_KEY global variable (Credential)
    │
    ├── ChatInput  → Agent-SIQ03  → ChatOutput
    │
    ├── Tool-SIQ10 (get_service_order_status)   ─┐
    ├── Tool-SIQ11 (get_service_order)           │
    ├── Tool-SIQ12 (get_customer_requests)       ├─► Agent-SIQ03.tools
    ├── Tool-SIQ13 (get_inspection_status)       │
    ├── Tool-SIQ14 (get_sla_status)              │
    ├── Tool-SIQ15 (get_applicable_standard)     │
    └── Tool-SIQ16 (get_laboratory)              ┘
    │
    ▼  HTTP GET with Bearer token
ServiceIQ Backend — http://127.0.0.1:8000
    │  Framework: Starlette (Python 3.12+, asyncpg)
    │  Auth: Base64url stub token decoder (pre-production)
    │  Route: GET /api/ai/service-orders/{order_number}
    │  Route: GET /health
    │
    ▼  parameterised asyncpg query
PostgreSQL 17.8 — localhost:5432
    │  Database: siks_n_prd
    │  User: fauzgabriel (no password, local dev)
    │
    └── READ-ONLY VIEW: public.ai_service_order_summary
        (joins: service_orders / service_request_uttps, users_customers,
         master_laboratory, service_order_inspections / service_order_uttp_inspections)
```

---

## 2. Errors Encountered and Fixed

| # | Error | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `ModuleNotFoundError: No module named 'starlette'` | Root `.venv` (Python 3.13) missing starlette | Installed `starlette asyncpg` into root `.venv` |
| 2 | `AttributeError: 'Starlette' object has no attribute 'on_event'` | Starlette removed `on_event` in ≥0.41 | Replaced with `@asynccontextmanager async def lifespan(app)` |
| 3 | `ModuleNotFoundError: No module named 'backend'` when running `uvicorn app:app` from `backend/api/` | `backend` package not on `sys.path` | Added path bootstrap in `app.py` to insert project root into `sys.path` |
| 4 | `OSError: Missing required database environment variables: DB_PASSWORD` | `DB_PASSWORD` required even when empty | Made `DB_PASSWORD` optional (defaults to `""`) |
| 5 | `uvicorn app:app` finds no `app` object | `app.py` only exported `create_app()` factory | Added `app = create_app()` at module level |
| 6 | Langflow/Mistral: tool called as text, not executed | Mistral via Ollama generates pseudo-code text instead of structured `tool_calls` | Switched Agent LLM to `gemini-3.6-flash` (Google Generative AI) |
| 7 | `'ComponentVertex' object has no attribute 'display_name'` | Externally added `GoogleGenerativeAI` node missing required Langflow node fields | Switched to Agent's built-in model dropdown instead of external LLM node |
| 8 | `gemini-2.5-flash-lite is no longer available to new users` | Deprecated model name | Tried `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-3.8-flash` → settled on `gemini-3.6-flash` |
| 9 | Tool returns HTTP 404 (`/api/ai/service-orders/V-6747-09-000/standard`) | Tools SIQ13-SIQ16 pointed to sub-paths that don't exist in backend | Updated all 7 tools to use the single existing endpoint `/api/ai/service-orders/{order_number}` |
| 10 | Backend crash `[Errno 48] address already in use` | Multiple uvicorn instances competing on port 8000 | Kill all instances before restart |

---

## 3. Environment Variables Required

### Backend (required at startup)

```bash
DB_HOST=localhost          # PostgreSQL host
DB_PORT=5432               # PostgreSQL port
DB_NAME=siks_n_prd         # Database name
DB_USER=fauzgabriel        # Database user
DB_PASSWORD=               # Password (empty for local dev)
```

### Langflow Global Variables (set in Langflow UI)

| Variable | Type | Description |
|----------|------|-------------|
| `GOOGLE_API_KEY` | Credential | Google Generative AI API key |
| `SERVICEIQ_BEARER_TOKEN` | Credential | Backend auth token (base64url stub) |

---

## 4. Backend Startup Command

```bash
# From backend/api/ using project root .venv (simple, with --reload)
cd /Users/fauzgabriel/development/alur-ai-desktop/backend/api
DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  ../../.venv/bin/uvicorn app:app --reload

# From project root using backend .venv (production-style)
PYTHONPATH=. DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  backend/.venv/bin/uvicorn backend.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

---

## 5. Backend Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check → `{"status":"ok"}` |
| `GET` | `/api/ai/service-orders/{order_number}` | Bearer token | Get order status |

### Auth token format (stub — pre-production)

```python
import base64, json
# CUSTOMER: access own orders only
token = base64.urlsafe_b64encode(json.dumps({
    "user_id": 1,
    "role": "customer",
    "customer_id": 61
}).encode()).rstrip(b"=").decode()

# MANAGER: access orders within lab_scope
token = base64.urlsafe_b64encode(json.dumps({
    "user_id": 1,
    "role": "manager",
    "lab_scope": list(range(1, 25))  # all labs
}).encode()).rstrip(b"=").decode()
```

### HTTP status codes

| Code | Meaning |
|------|---------|
| 200 | Order found and authorized |
| 400 | Invalid order number format |
| 401 | No/invalid Bearer token |
| 403/404 | Not found or access denied (identical message — prevents enumeration) |

---

## 6. Database

### Connection

```
Host: localhost:5432
Database: siks_n_prd
User: fauzgabriel (no password, local dev)
```

### Semantic AI View

```sql
-- Read-only view: public.ai_service_order_summary
-- Applied from: database/views/ai_service_order_summary.sql
SELECT
  service_order_id, order_number, service_request_id, track,
  customer_id, customer_name, service_type,
  laboratory_id, laboratory_name,
  order_status, inspection_status,
  sla_deadline, sla_status
FROM public.ai_service_order_summary;
```

### Order number formats

- UUT track (calibration): `V-XXXX-XX-XXX` (e.g. `V-6747-09-000`)
- UTTP track (weighing): `DL-25-XXX` (e.g. `DL-25-012`)
- **No `ORD-` prefix** — this format does not exist in the database

### Test order numbers (development)

| Order Number | Status | Customer | Lab | SLA |
|-------------|--------|----------|-----|-----|
| `V-6747-09-000` | new | Reza Hendrawan | VOLUME (id=2) | overdue |
| `V-6739-09-000` | new | PT. Inscal Service Indonesia | SUHU (id=6) | overdue |
| `V-6745-09-000` | new | Aldila Fadjar Ramadhan | VOLUME MASTER METER (id=19) | overdue |
| `V-22-0051-000` | certified | UPTD Metrologi Kota Tangerang Selatan | MASSA (id=16) | overdue |

---

## 7. Langflow Flow

### Flow details

| Property | Value |
|----------|-------|
| Name | ServiceIQ Customer Agent |
| ID | `975f52f6-7883-4543-803c-45bfb9860e72` |
| URL | http://localhost:7860/flow/975f52f6-7883-4543-803c-45bfb9860e72 |
| LLM | gemini-3.6-flash (Google Generative AI) |
| Agent type | ToolCallingAgentComponent (`create_agent` with LangGraph) |

### Nodes

| Node ID | Type | Description |
|---------|------|-------------|
| `ChatInput-SIQ01` | ChatInput | User message input |
| `Agent-SIQ03` | Agent | ServiceIQ Agent (Gemini) |
| `ChatOutput-SIQ02` | ChatOutput | AI response output |
| `Tool-SIQ10` | CustomComponent | `get_service_order_status` |
| `Tool-SIQ11` | CustomComponent | `get_service_order` |
| `Tool-SIQ12` | CustomComponent | `get_customer_requests` |
| `Tool-SIQ13` | CustomComponent | `get_inspection_status` |
| `Tool-SIQ14` | CustomComponent | `get_sla_status` |
| `Tool-SIQ15` | CustomComponent | `get_applicable_standard` |
| `Tool-SIQ16` | CustomComponent | `get_laboratory` |

### Edges (9 total)

```
ChatInput-SIQ01.[message]         → Agent-SIQ03.[input_value]
Agent-SIQ03.[response]            → ChatOutput-SIQ02.[input_value]
Tool-SIQ10.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ11.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ12.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ13.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ14.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ15.[component_as_tool]    → Agent-SIQ03.[tools]
Tool-SIQ16.[component_as_tool]    → Agent-SIQ03.[tools]
```

---

## 8. Authentication Design

```
Langflow Tool (Python component)
    │
    │  SERVICEIQ_BEARER_TOKEN
    │  (from Langflow global variable, type=Credential)
    │  load_from_db=True → never appears as LLM argument
    │
    ▼
GET /api/ai/service-orders/{order_number}
Authorization: Bearer <token>
    │
    ▼
Backend _decode_token()
    │  base64url-decodes JSON → Principal{role, customer_id, lab_scope}
    │  ⚠ STUB — must replace with real JWT verification before production
    ▼
require_order_access(principal, order)
    │  IDOR check: compares order.laboratory_id/customer_id to principal scope
    │  NOT based on URL parameter
    ▼
Response (200/401/403/404)
```

**Security contract:**
- `order_number` is the ONLY value that comes from the LLM/user
- Bearer token is NEVER an LLM-generated argument (no `tool_mode=True`)
- All parameterised queries — no SQL injection possible
- Sensitive fields (`password`, `token`, `ktp`, `npwp`) never in responses

---

## 9. Verified Test Results

### Phase 12 — Direct backend tests

```bash
# 1. Health
curl http://127.0.0.1:8000/health
→ 200 {"status":"ok"}  ✓

# 2. Real order
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/ai/service-orders/V-6747-09-000
→ 200 {"order_number":"V-6747-09-000","customer":{"id":61,"name":"Reza Hendrawan"},
       "service_type":"Verifikasi","laboratory":{"id":2,"name":"VOLUME"},
       "order_status":"new","inspection_status":"no_inspection","sla_status":"overdue"}  ✓

# 3. Non-existent order
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/ai/service-orders/ORD-2026-00125
→ 404 {"error":"Order not found or access denied."}  ✓

# 4. No auth
curl http://127.0.0.1:8000/api/ai/service-orders/V-6747-09-000
→ 401 {"error":"Authentication required."}  ✓

# 5. Path traversal attempt (/../../etc/passwd)
→ 404 (router returns not-found)  ✓

# 6. Another real order
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/ai/service-orders/V-6739-09-000
→ 200 {"order_number":"V-6739-09-000","customer":{"id":40,"name":"PT. Inscal Service Indonesia"},
       "service_type":"Verifikasi","laboratory":{"id":6,"name":"SUHU"},
       "order_status":"new","inspection_status":"no_inspection","sla_status":"overdue"}  ✓
```

### Phase 14 — End-to-end Langflow test

**Input:** `"Bagaimana status order V-6747-09-000?"`

**Tool invocation trace:**
```
Agent → get_service_order_status(order_number="V-6747-09-000")
       → GET http://127.0.0.1:8000/api/ai/service-orders/V-6747-09-000 200 OK
       → {"success":true,"order_number":"V-6747-09-000","customer":{"id":61,"name":"Reza Hendrawan"},
          "service_type":"Verifikasi","laboratory":{"id":2,"name":"VOLUME"},
          "order_status":"new","inspection_status":"no_inspection","sla_status":"overdue"}
```

**Agent response:**
```
Berikut adalah informasi mengenai status order V-6747-09-000:

• Nomor Order: V-6747-09-000
• Nama Pelanggan: Reza Hendrawan
• Jenis Layanan: Verifikasi
• Laboratorium: VOLUME
• Status Order: Baru (New)
• Status Inspeksi: Belum dilakukan inspeksi (No inspection)
• Status SLA: Melewati batas waktu (Overdue)

Jika Anda membutuhkan informasi lebih lanjut mengenai kelanjutan proses order ini,
silakan hubungi tim layanan pelanggan atau laboratorium terkait.
```

✅ All 17 acceptance criteria verified.

### Backend unit tests

```
35 passed in 0.27s
```

---

## 10. Remaining Limitations

| # | Limitation | Impact | Path to Fix |
|---|-----------|--------|-------------|
| 1 | `_decode_token` is a base64url stub (I-01) | **CRITICAL** — pre-production only | Replace with `python-jose` or `PyJWT` signature verification |
| 2 | `customer.id` and `laboratory.id` exposed in response (I-02) | Medium | Remove `id` from `_order_response()` |
| 3 | `RepositoryMiddleware` has no null-pool guard (I-03) | Medium | Add `if pool is None: return _error(503, ...)` |
| 4 | Whitespace-only order numbers pass format validation (I-04) | Low | Add `.strip()` check to `_validate_order_number` |
| 5 | Backend only has one API route (no sub-routes for `/inspection`, `/sla`, etc.) | Medium | Add sub-routes as the view already has all data |
| 6 | Langflow `SERVICEIQ_BEARER_TOKEN` is a stub JWT (not cryptographically verified) | **CRITICAL** — pre-production only | Replace with real auth flow |
| 7 | Uvicorn `--reload` watches only `backend/api/` when run from that directory | Low | Run from project root for full-tree watching |
| 8 | `gemini-3.6-flash` model name may change (Google API deprecation pattern) | Medium | Pin to a stable model or add fallback logic |

---

## 11. Complete Restart Commands

```bash
# ── Terminal 1: PostgreSQL (already running) ──────────────────────────────────
# PostgreSQL is managed by Homebrew Services
brew services start postgresql@17   # if not running

# ── Terminal 2: Backend ──────────────────────────────────────────────────────
cd /Users/fauzgabriel/development/alur-ai-desktop/backend/api
DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  ../../.venv/bin/uvicorn app:app --reload

# Verify:
curl http://127.0.0.1:8000/health
# → {"status":"ok"}

# ── Terminal 3: Langflow (already running as background service) ──────────────
# If not running:
cd /Users/fauzgabriel/langflow && .venv/bin/python -m langflow run

# Langflow UI: http://localhost:7860
# Flow: ServiceIQ Customer Agent

# ── Test end-to-end ──────────────────────────────────────────────────────────
curl -s --compressed -X POST \
  "http://127.0.0.1:7860/api/v1/run/975f52f6-7883-4543-803c-45bfb9860e72" \
  -H "x-api-key: sk-ryhzLF-hhKDu23hrKwa_hZ0T0UtjlRdu7m6yUrfXEaM" \
  -H "Content-Type: application/json" \
  -d '{"input_value":"Bagaimana status order V-6747-09-000?","output_type":"chat","input_type":"chat","tweaks":{}}'
```

---

## 12. Files Changed in This Session

| File | Change |
|------|--------|
| `backend/api/app.py` | Fixed: lifespan context manager, path bootstrap, module-level `app`, health route |
| `backend/db/connection.py` | Fixed: `DB_PASSWORD` now optional (defaults to `""`) |
| `.env.example` | Added: `SERVICEIQ_BEARER_TOKEN`, `GOOGLE_API_KEY` docs, Langflow notes |
| `database/views/ai_service_order_summary.sql` | Applied to database (already existed, `CREATE VIEW` executed) |
| `langflow/patch_flow_gemini.py` | NEW: Initial Gemini node swap script (superseded by v2) |
| `langflow/patch_flow_gemini_v2.py` | NEW: Switch Agent to built-in Gemini dropdown, fix system prompt |
| `langflow/fix_tool_endpoints.py` | NEW: Fix all 7 tools to use single `/api/ai/service-orders/{order_number}` endpoint |
| `langflow/find_gemini_flow.py` | NEW: Helper to find Gemini flows (diagnostic) |
| `docs/debug/end-to-end-analysis.md` | NEW: This document |

### Langflow flow changes (via REST API PATCH)

| Change | Details |
|--------|---------|
| Removed `OllamaModel-SIQ04` node | Ollama/Mistral does not dispatch tool calls in this Langflow version |
| Agent LLM | Set to `gemini-3.6-flash` via built-in model dropdown |
| Agent `api_key` | Set to `GOOGLE_API_KEY` (from global variable) |
| Agent `system_prompt` | Updated with tool usage rules and order number format examples |
| Tool-SIQ10 `api_base_url` | Set to `http://localhost:8000` |
| Tool-SIQ11-SIQ16 code | Rewritten to use `/api/ai/service-orders/{order_number}` (was using non-existent sub-paths) |
| Tool-SIQ10-SIQ16 `bearer_token` | Set to `SERVICEIQ_BEARER_TOKEN` with `load_from_db=True` |
