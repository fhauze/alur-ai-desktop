You are the lead engineer responsible for making this entire project work end-to-end.

PROJECT:
alur-ai-desktop

OBJECTIVE:
Fix and complete the entire backend + Langflow integration so that the system is actually runnable and testable.

FINAL ACCEPTANCE CRITERIA:

1. Backend starts successfully without errors.
2. Backend can connect to the configured PostgreSQL database.
3. Backend exposes the required API endpoints for ServiceIQ.
4. Langflow is running at:
   http://localhost:7860
5. Langflow has a working ServiceIQ Agent.
6. Langflow Agent can call the ServiceIQ backend tools.
7. Agent can receive an order number from the user's natural-language question.
8. The order number is passed to the correct backend tool.
9. Backend authenticates/authorizes the request correctly.
10. Backend queries the database correctly.
11. Backend returns structured data.
12. Langflow receives the tool result.
13. Gemini Agent converts the result into a natural-language answer.
14. A user can ask for a specific order, for example:

   "Bagaimana status order ORD-2026-00125?"

   and Langflow must return a meaningful answer based on the actual database/backend result.

IMPORTANT:
Do not stop after fixing one error.
Continue debugging until the complete flow works.

Do not claim success unless you actually execute and verify the required tests.

==================================================
PHASE 1 — PROJECT RECONNAISSANCE
==================================================

First inspect the entire repository.

Do NOT modify anything during this phase.

Inspect:

- backend/
- backend/api/
- backend/db/
- all configuration files
- requirements.txt / pyproject.toml
- .env.example
- .env files if present
- Langflow integration code
- custom Langflow tools
- prompts
- MCP configuration
- database-related code
- API routes
- tests
- README
- Docker files if present

Determine:

1. Python version
2. virtual environment
3. backend framework
4. database driver
5. PostgreSQL configuration
6. required environment variables
7. backend port
8. Langflow port
9. existing ServiceIQ tools
10. existing Langflow flow
11. how Langflow currently communicates with backend
12. whether MCP is available
13. whether the existing custom tools are HTTP tools, Python tools, MCP tools, or another implementation

Do not guess.

Create:

docs/debug/end-to-end-analysis.md

Document:

- current architecture
- current errors
- missing configuration
- missing dependencies
- backend startup flow
- Langflow integration flow
- database dependencies
- required fixes
- expected final architecture

==================================================
PHASE 2 — FIX PYTHON ENVIRONMENT
==================================================

Make the Python backend reproducible.

Check:

- Python version
- virtualenv
- dependency files
- installed packages

The current known error was:

ModuleNotFoundError: No module named 'starlette'

Verify that all runtime dependencies are declared properly.

Do NOT simply install random packages manually.

If FastAPI/Starlette/Uvicorn are required, ensure they are declared in the project's dependency file.

Then install dependencies into the project's virtual environment.

Verify:

python --version
which python
which uvicorn
python -c "import starlette"
python -c "import uvicorn"

Do not continue until the environment is reproducible.

==================================================
PHASE 3 — FIX DATABASE CONFIGURATION
==================================================

The current backend startup error is:

OSError: Missing required database environment variables:
DB_NAME, DB_USER

Inspect:

backend/db/connection.py

Determine ALL required database environment variables from the actual implementation.

Do not guess variable names.

Check:

- DB_HOST
- DB_PORT
- DB_NAME
- DB_USER
- DB_PASSWORD
- SSL configuration if required
- pool configuration

Create/update:

.env.example

with all required variables.

Never commit real credentials.

If .env is missing, create the local development configuration required by this project.

If credentials cannot be determined safely from the repository, DO NOT invent production credentials.

Instead:

1. document the required variables
2. use an appropriate local development configuration if the local PostgreSQL instance is available
3. validate connectivity

Test database connectivity independently before starting the backend.

For example, use the project's existing database driver or PostgreSQL client.

The database connection must actually succeed.

==================================================
PHASE 4 — VERIFY DATABASE SCHEMA
==================================================

Inspect the database schema used by ServiceIQ.

Identify the actual tables/views needed for:

- service orders
- service requests
- customers
- inspections
- SLA
- laboratories
- standards

Do not invent table names.

Use the existing schema and existing project analysis.

Identify the real relationship:

customer
    ↓
service_request
    ↓
service_order
    ↓
inspection
    ↓
SLA
    ↓
laboratory / standard

If semantic AI views already exist, inspect and reuse them.

If they do not exist, create the minimum required read-only semantic view for:

AI Service Order Status

The view should expose only fields needed by the AI.

At minimum determine whether the system can return:

- order_id
- order_number
- customer
- service type
- laboratory
- order status
- inspection status
- SLA status
- SLA deadline

Do NOT use SELECT *.

Do NOT expose passwords, tokens, internal secrets, or unnecessary PII.

Do NOT modify production transaction data.

==================================================
PHASE 5 — BACKEND SERVICE ORDER API
==================================================

Find the existing ServiceIQ API implementation.

If incomplete, implement it.

Required capability:

GET service order by order number.

Conceptually:

GET /api/ai/service-orders/{order_number}

The exact route may differ if the project already has an established API convention.

Follow the existing architecture instead of creating a duplicate implementation.

Required layers:

API/Controller
    ↓
Service
    ↓
Repository
    ↓
Database

The API must:

1. validate order_number
2. authenticate request
3. authorize access
4. query database using parameterized queries
5. return structured JSON
6. handle not-found
7. handle database errors safely
8. never expose database credentials
9. never expose SQL errors to the user
10. never allow arbitrary SQL from Langflow

Example successful response:

{
  "success": true,
  "data": {
    "order_number": "ORD-2026-00125",
    "status": "...",
    "customer": "...",
    "laboratory": "...",
    "inspection_status": "...",
    "sla_status": "...",
    "sla_deadline": "..."
  }
}

Use the project's actual database fields and values.

Do not fabricate data.

==================================================
PHASE 6 — BACKEND AUTHENTICATION
==================================================

Inspect the current authentication design.

Determine how Langflow is supposed to authenticate to the backend.

IMPORTANT SECURITY REQUIREMENT:

The LLM must NOT receive database credentials.

The LLM must NOT generate bearer tokens.

The LLM must NOT receive a tool argument called "Bearer Token".

Authentication should be handled by the backend/tool integration layer.

If the existing architecture uses an internal service token/API key:

Langflow Tool
    ↓
secure server-side credential
    ↓
Backend API

Do not expose the secret as an LLM-generated argument.

If the current custom Langflow components have:

Bearer Token *
as a required tool input,

refactor them so that the token is resolved securely by the integration layer.

The tool interface exposed to the Agent should be something like:

get_service_order_status(
    order_number: string
)

NOT:

get_service_order_status(
    order_number: string,
    bearer_token: string
)

==================================================
PHASE 7 — CREATE/FIX ALL REQUIRED SERVICEIQ TOOLS
==================================================

Verify these existing tools:

- get_service_order_status
- get_service_order
- get_customer_requests
- get_inspection_status
- get_sla_status
- get_applicable_standard
- get_laboratory

For each tool verify:

1. input schema
2. output schema
3. authentication
4. backend endpoint
5. error handling
6. timeout
7. validation
8. Langflow Tool Mode compatibility

The MOST IMPORTANT tool is:

get_service_order_status

Its Agent-facing schema must allow:

order_number: string

Example:

{
  "order_number": "ORD-2026-00125"
}

The tool must actually call the backend.

Do not mock the result.

==================================================
PHASE 8 — LANGFLOW
==================================================

Use the existing Langflow installation.

Langflow URL:

http://localhost:7860

If an MCP server is already configured in this project, use the MCP integration rather than manually rebuilding everything.

Inspect the existing Langflow flow through the available MCP/API.

Do not create a second duplicate flow if an existing ServiceIQ flow already exists.

Fix the existing flow.

Expected architecture:

Chat Input
    ↓
ServiceIQ Agent
    ↓
Agent Tools
    ↓
ServiceIQ backend tools
    ↓
Backend API
    ↓
PostgreSQL
    ↓
Tool result
    ↓
Agent
    ↓
Chat Output

The Agent must have:

Language Model:
Gemini Flash / existing configured Gemini model

Tools:
- get_service_order_status
- get_service_order
- get_customer_requests
- get_inspection_status
- get_sla_status
- get_applicable_standard
- get_laboratory

==================================================
PHASE 9 — FIX LANGFLOW TOOL CONNECTIONS
==================================================

Inspect the existing custom tool components.

The previous flow had tool nodes that were not correctly connected to Agent.Tools.

Fix this.

Every tool must expose a valid Tool/Toolset output.

Enable Tool Mode where required.

Connect:

get_service_order_status
        ┐
get_service_order
        ├──> Agent.Tools
get_customer_requests
        │
get_inspection_status
        │
get_sla_status
        │
get_applicable_standard
        │
get_laboratory
        ┘

Chat Input:

Chat Input
    ↓
Agent Input

Agent:

Agent
    ↓
Chat Output

Do NOT leave the Ollama node disconnected if it is supposed to be used.

The project must have ONE intentional language-model configuration.

If Gemini is the intended production/demo model:

use Gemini.

Remove or disconnect unused Ollama configuration.

Do not maintain two confusing model paths.

==================================================
PHASE 10 — AGENT INSTRUCTIONS
==================================================

Create/fix the Agent instructions.

The Agent must understand:

You are ServiceIQ, an enterprise service intelligence assistant.

You answer questions using authorized enterprise service data.

For questions about a specific service order:

1. Extract the order number.
2. Call get_service_order_status.
3. Use the returned data.
4. Never invent status.
5. If the order does not exist, clearly say that the order could not be found.
6. If the user asks for details, call get_service_order.
7. If the user asks about inspection, call get_inspection_status.
8. If the user asks about SLA, call get_sla_status.
9. If the user asks about standards, call get_applicable_standard.
10. If the user asks about laboratory information, call get_laboratory.

Never ask the user for a bearer token.

Never expose internal API credentials.

Never generate SQL.

Never claim data that is not returned by a tool.

For a specific order question, prefer structured tool data over general knowledge.

Example:

User:
"Bagaimana status order ORD-2026-00125?"

Agent:
1. Extract:
   order_number = ORD-2026-00125

2. Call:
   get_service_order_status(
       order_number="ORD-2026-00125"
   )

3. Answer based on returned data.

==================================================
PHASE 11 — LANGFLOW TEST
==================================================

Do NOT consider the task complete just because Langflow opens.

Actually execute the flow.

Test:

"Bagaimana status order ORD-2026-00125?"

Verify the following chain:

Chat Input
    ↓
Agent
    ↓
Tool selection
    ↓
get_service_order_status
    ↓
order_number = ORD-2026-00125
    ↓
backend request
    ↓
database query
    ↓
JSON response
    ↓
Agent
    ↓
Chat Output

Inspect Langflow logs/tool traces.

Confirm there is NO:

"missing Order Number"

and NO:

"missing Bearer Token"

and NO:

tool not connected

and NO:

401

and NO:

403

and NO:

404 caused by incorrect route

and NO:

500

and NO:

database connection error

==================================================
PHASE 12 — TEST BACKEND DIRECTLY
==================================================

Before testing Langflow, test the backend independently.

Use curl or the appropriate project command.

Test:

1. health endpoint
2. service order endpoint
3. known existing order
4. non-existing order
5. invalid order number
6. unauthorized request

Do not use fake success responses.

If the order:

ORD-2026-00125

does not exist in the database, discover an actual existing order number from the development database and use that for the integration test.

Document the real test order number.

==================================================
PHASE 13 — AUTOMATED TESTS
==================================================

Add tests for:

Backend:

- health
- database connection
- existing order
- missing order
- invalid order
- unauthorized access
- database failure

Tool:

- correct order_number passed
- missing order_number
- backend 401
- backend 403
- backend 404
- backend 500
- timeout

Langflow integration:

- order question
- tool invocation
- tool result
- final answer

==================================================
PHASE 14 — END-TO-END TEST
==================================================

This is the most important test.

Start all required services.

Backend:

http://127.0.0.1:8000

Langflow:

http://localhost:7860

Then execute:

User:

"Bagaimana status order ORD-2026-00125?"

Expected:

Langflow Agent recognizes the order number.

It calls:

get_service_order_status

Backend receives:

ORD-2026-00125

Backend queries PostgreSQL.

Backend returns structured data.

Langflow Agent receives structured data.

Agent produces a natural-language response.

The response must be based on actual database data.

If the exact order does not exist, use a real existing order from the database and document it.

==================================================
PHASE 15 — ERROR RECOVERY
==================================================

If any test fails:

DO NOT STOP.

Trace the failure backwards.

For example:

Langflow
  ↓
Tool
  ↓
HTTP
  ↓
Backend
  ↓
Service
  ↓
Repository
  ↓
DB

Fix the root cause.

Then rerun the test.

Repeat until the complete flow succeeds.

==================================================
PHASE 16 — CLEANUP
==================================================

Remove:

- unused Ollama configuration if Gemini is selected
- dead code
- duplicate API implementations
- hardcoded credentials
- debug secrets
- fake/mock production responses
- unnecessary database access
- arbitrary SQL execution endpoints
- unused Langflow nodes
- broken tool definitions

Keep:

- clear architecture
- typed schemas
- error handling
- tests
- documentation
- secure configuration

==================================================
PHASE 17 — FINAL VERIFICATION
==================================================

At the end, execute the actual startup commands.

Backend:

cd backend/api
source ../../.venv/bin/activate
uvicorn app:app --reload

Verify it stays running.

Then verify:

curl http://127.0.0.1:8000/health

or the project's actual health endpoint.

Verify Langflow:

http://localhost:7860

Then execute the ServiceIQ flow.

Finally test:

"Bagaimana status order ORD-2026-00125?"

If that order does not exist, use an actual order number from the development database.

==================================================
IMPORTANT RULES
==================================================

1. Do not fabricate database records.
2. Do not fabricate successful API responses.
3. Do not claim something works without executing it.
4. Do not stop after fixing the first error.
5. Do not expose database credentials to Langflow Agent.
6. Do not expose bearer tokens as LLM-generated tool arguments.
7. Do not give Langflow direct unrestricted database access.
8. Do not create arbitrary SQL execution tools.
9. Do not modify production data.
10. Prefer existing project architecture.
11. Do not create duplicate Langflow flows if the existing one can be repaired.
12. Use the existing MCP integration if available.
13. If an MCP operation fails, inspect the error and fix the underlying configuration.
14. Run actual tests after every major fix.
15. Continue until the complete end-to-end flow is verified.

FINAL REPORT:

After everything is working, provide:

1. Files changed
2. Database changes
3. Environment variables required
4. Backend startup command
5. Backend health endpoint
6. Backend API endpoint
7. Langflow flow name
8. Langflow URL
9. Tools connected to Agent
10. Authentication mechanism
11. Actual test order number
12. Backend test result
13. Langflow test result
14. Exact example question
15. Exact resulting answer
16. Remaining limitations
17. Commands required to restart the entire system

Do not say "completed" unless the end-to-end test has actually passed.