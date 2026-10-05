# ServiceIQ

AI-Powered Enterprise Service Intelligence Platform.

## Architecture

Frontend
   ↓
Backend API
   ↓
AI Gateway
   ↓
Langflow
   ↓
LLM

Backend
   ↓
Enterprise Database
==========================
    Langflow
        │
        │ HTTPS
        ▼
    AI Gateway
        │
    JWT / API Key
        │
        ▼
Enterprise API
        │
Authorization
        │
        ▼
    DB / Views

## AI Capabilities

- Customer Service Assistant
- Service Order Assistant
- SLA Risk Detection
- Laboratory Intelligence
- Standard & Compliance Assistant

## Technology

- Frontend: React
- Backend: ...
- Database: ...
- AI Orchestration: Langflow
- AI Coding Assistant: IBM Bob
- LLM: ...

# Task 003 — Service Order AI API

## Objective

Create a read-only API that allows Langflow
to retrieve authorized service order information.

## Data Source

ai_service_order_summary

## Endpoint

GET /api/ai/service-orders/{order_number}

## Authorization

Customer:
- Can only access own service orders.

Staff:
- Can access assigned/authorized orders.

Manager:
- Can access authorized organizational scope.

## Response

Must include:

- order_number
- customer
- service_type
- laboratory
- order_status
- inspection_status
- sla_status

## Security

- No raw SQL from request
- No direct DB access from Langflow
- Validate order_number
- Enforce authorization server-side

## Testing

Create tests for:

1. Authorized customer
2. Unauthorized customer
3. Staff
4. Manager
5. Non-existent order
6. Invalid order number