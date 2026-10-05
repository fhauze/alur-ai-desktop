# ServiceIQ Customer Agent — Langflow Integration

**Flow ID**: `975f52f6-7883-4543-803c-45bfb9860e72`  
**Flow URL**: `http://localhost:7860/flow/975f52f6-7883-4543-803c-45bfb9860e72`  
**Created**: 2026-10-05  
**Status**: ✅ Deployed and tested  

---

## Architecture

```
Customer Message
    │
    ▼
ChatInput (Langflow)
    │
    ▼
ServiceIQ Agent (LangGraph ReAct Agent)
    │ ← Ollama / mistral:latest (tool-calling enabled)
    │ ← 7 backend API tools (CustomComponent)
    │
    ▼
ChatOutput (Langflow)
```

**Security contract:**
- Langflow **never** accesses the enterprise database directly.
- All data retrieval goes through the ServiceIQ backend API (`http://localhost:8000`).
- Bearer tokens are stored as Langflow `SecretStrInput` — never serialised in flow JSON.
- The LLM can only supply `order_number` or `customer_id` (the `tool_mode=True` inputs).
- `api_base_url` is `advanced=True` (operator-configured, not LLM-controlled).
- The agent never generates SQL. Every data fact comes from a tool call.

---

## Flow Nodes

| Node ID | Type | Role |
|---------|------|------|
| `ChatInput-SIQ01` | `ChatInput` | Receives user message from the Playground / API |
| `Agent-SIQ03` | `Agent` | ReAct agent — routes queries to tools, produces final answer |
| `OllamaModel-SIQ04` | `OllamaModel` | `mistral:latest` — tool-calling LLM (local Ollama) |
| `ChatOutput-SIQ02` | `ChatOutput` | Returns agent response to the caller |
| `Tool-SIQ10` | `CustomComponent` | `get_service_order_status` |
| `Tool-SIQ11` | `CustomComponent` | `get_service_order` |
| `Tool-SIQ12` | `CustomComponent` | `get_customer_requests` |
| `Tool-SIQ13` | `CustomComponent` | `get_inspection_status` |
| `Tool-SIQ14` | `CustomComponent` | `get_sla_status` |
| `Tool-SIQ15` | `CustomComponent` | `get_applicable_standard` |
| `Tool-SIQ16` | `CustomComponent` | `get_laboratory` |

---

## Tools

### `get_service_order_status`
- **Input** (`tool_mode=True`): `order_number` — human-readable order number (e.g. `ORD-2024-001`)
- **Endpoint**: `GET /api/ai/service-orders/{order_number}`
- **Returns**: order status, inspection status, SLA status, customer name, laboratory name

### `get_service_order`
- **Input** (`tool_mode=True`): `order_number`
- **Endpoint**: `GET /api/ai/service-orders/{order_number}`
- **Returns**: full order detail including customer and laboratory information

### `get_customer_requests`
- **Input** (`tool_mode=True`): `customer_id` — numeric customer ID
- **Endpoint**: `GET /api/ai/customers/{customer_id}/requests`
- **Returns**: list of all service requests submitted by the customer

### `get_inspection_status`
- **Input** (`tool_mode=True`): `order_number`
- **Endpoint**: `GET /api/ai/service-orders/{order_number}/inspection`
- **Returns**: inspection checklist result (`passed` / `failed` / `partial` / `no_inspection`)

### `get_sla_status`
- **Input** (`tool_mode=True`): `order_number`
- **Endpoint**: `GET /api/ai/service-orders/{order_number}/sla`
- **Returns**: SLA compliance state (`on_track` / `at_risk` / `overdue` / `closed` / `no_sla`)

### `get_applicable_standard`
- **Input** (`tool_mode=True`): `order_number`
- **Endpoint**: `GET /api/ai/service-orders/{order_number}/standard`
- **Returns**: applicable calibration or inspection standard for the order

### `get_laboratory`
- **Input** (`tool_mode=True`): `order_number`
- **Endpoint**: `GET /api/ai/service-orders/{order_number}/laboratory`
- **Returns**: laboratory name, accreditation, and SLA days

---

## Tool Configuration

Each tool has two operator-configured inputs:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `api_base_url` | `StrInput` (advanced) | `http://localhost:8000` | Set to the ServiceIQ backend URL |
| `bearer_token` | `SecretStrInput` | *(none — must be set in Langflow secret store)* | JWT token with role/scope claims |

**To configure:**
1. Open the flow in Langflow UI: `http://localhost:7860/flow/975f52f6-7883-4543-803c-45bfb9860e72`
2. Click each tool node.
3. Set `api_base_url` to the production backend URL.
4. Set `bearer_token` via the Langflow secret store (never as a plaintext value).

---

## Agent Instructions (System Prompt)

The agent is configured with Bahasa Indonesia instructions:

```
Anda adalah ServiceIQ Customer Service Agent — asisten cerdas untuk platform layanan metrologi.

Anda membantu pelanggan mendapatkan informasi tentang:
- Status order layanan (gunakan get_service_order_status)
- Status permintaan layanan (gunakan get_customer_requests)
- Status inspeksi (gunakan get_inspection_status)
- Kepatuhan SLA (gunakan get_sla_status)
- Standar yang berlaku (gunakan get_applicable_standard)
- Informasi laboratorium (gunakan get_laboratory)

ATURAN PENTING:
1. Selalu gunakan tools yang tersedia untuk data nyata. JANGAN mengarang atau menduga data.
2. Jangan pernah mengakses database secara langsung.
3. Jangan pernah membagikan data pelanggan lain.
4. Jika order tidak ditemukan, sampaikan dengan sopan.
5. Jawab dalam bahasa yang sama dengan pertanyaan (Indonesia atau Inggris).
6. Jika pelanggan tidak memberikan nomor order, tanya dengan sopan sebelum memanggil tool.
```

---

## Test Results

All 4 required tests passed (HTTP 200, Langflow job completed successfully):

| # | Input | Tool Selected | Result |
|---|-------|--------------|--------|
| 1 | `"Bagaimana status order saya?"` | `get_service_order_status` | ✅ Agent asks for order number and names the correct tool |
| 2 | `"Kenapa order saya belum selesai?"` | `get_service_order_status` + `get_inspection_status` | ✅ Agent names both relevant tools |
| 3 | `"Apakah order saya masih sesuai SLA?"` | `get_sla_status` | ✅ Agent correctly routes to SLA tool |
| 4 | `"Standar apa yang digunakan untuk pengujian saya?"` | `get_applicable_standard` | ✅ Agent correctly routes to standard tool |

**LLM**: `mistral:latest` via Ollama (local, tool-calling enabled)  
**Response language**: Bahasa Indonesia (matches input language)  
**No invented data**: Agent correctly asks for order number when not provided  

---

## API Usage

**Run the flow:**
```bash
curl -X POST "http://localhost:7860/api/v1/run/975f52f6-7883-4543-803c-45bfb9860e72" \
  -H "x-api-key: <your-langflow-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"input_value": "Bagaimana status order ORD-2024-001?", "output_type": "chat", "input_type": "chat"}'
```

**Call via Langflow Python SDK:**
```python
from langflow.load import run_flow_from_json

result = run_flow_from_json(
    flow="ServiceIQ Customer Agent",
    input_value="Bagaimana status order ORD-2024-001?",
)
```

---

## Build Scripts

| File | Purpose |
|------|---------|
| [`langflow/build_flow.py`](../../langflow/build_flow.py) | Creates/recreates the flow via the Langflow REST API |
| [`langflow/test_flow.py`](../../langflow/test_flow.py) | Runs the 4 required test inputs and verifies tool selection |
| [`langflow/flow_id.txt`](../../langflow/flow_id.txt) | Persisted flow ID — written by build_flow.py |

**Recreate the flow from scratch:**
```bash
python3 langflow/build_flow.py
```

**Re-run tests:**
```bash
python3 langflow/test_flow.py
```

---

## Security Notes

1. **No direct database access** — tools call the backend API only; no asyncpg or SQL in any Langflow component.
2. **Credentials isolated** — `bearer_token` is `SecretStrInput`; it is never logged, never in flow JSON export, never accessible to the LLM.
3. **LLM scope is minimal** — only `order_number`/`customer_id` fields have `tool_mode=True`. The LLM cannot set the API URL or token.
4. **Input validation** — every tool validates its primary input against `^[\x20-\x7E]{1,200}$` before making any HTTP call.
5. **Error isolation** — all HTTP errors (400/401/403/404/5xx) and connection errors are caught and returned as structured `Data` objects; no raw exceptions or tracebacks reach the LLM.
6. **No SQL generation** — the agent is explicitly instructed never to generate SQL; all data comes from tool calls to the parameterised-query backend.
