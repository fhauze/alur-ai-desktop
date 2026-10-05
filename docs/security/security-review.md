# ServiceIQ — Security Review

**Scope**: All source files in the ServiceIQ AI data layer  
**Review date**: 2026-10-03  
**Reviewer**: Bob (AI-Assisted Security Review)  
**Status**: Complete — 1 critical finding, 2 medium findings, 4 informational notes  

---

## Files Reviewed

| File | Lines | Result |
|------|-------|--------|
| `database/views/ai_service_order_summary.sql` | 143 | ✅ No issues |
| `backend/domain/AIServiceOrder.py` | ~130 | ✅ No issues |
| `backend/repositories/AIServiceOrderRepository.py` | ~250 | ✅ No issues |
| `backend/auth/principal.py` | ~60 | ✅ No issues |
| `backend/auth/authorization.py` | 114 | ✅ No issues |
| `backend/api/service_orders.py` | 170 | ✅ No issues |
| `backend/api/app.py` | 180 | ⚠️ CRITICAL — stub token decoder |
| `backend/db/connection.py` | 109 | ✅ No issues |
| `docs/api/openapi.yaml` | 684 | ℹ️ Informational |
| `langflow/components/service-order-tool/get_service_order_status.py` | 311 | ℹ️ Informational |
| `backend/tests/repositories/AIServiceOrderRepository_test.py` | 581 | ✅ Good coverage |
| `backend/tests/api/test_service_orders.py` | 398 | ✅ Good coverage |

---

## Summary

The codebase demonstrates **sound security architecture** throughout. IDOR is correctly prevented, SQL injection is not possible, sensitive field suppression is enforced at the response layer, and the Langflow component correctly isolates operator credentials from LLM-supplied input. The single critical finding is a **known and documented stub** — the token decoder is not production-safe — and it requires a drop-in replacement before deployment, not a structural change.

```
CRITICAL  1   _decode_token is a base64url stub — not JWT-verified
MEDIUM    2   CORS not configured; app.state.db_pool may be None at runtime
INFO      4   On_event deprecation; single space URL path note; httpx SSL; no rate-limiting
```

---

## Findings

---

### [CRITICAL] F-01 — Token decoder is a stub; tokens are not cryptographically verified

**File**: [`backend/api/app.py`](../../backend/api/app.py) — `_decode_token`, line 55  
**CVSS v3**: 9.8 (AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H)

#### Problem

`_decode_token` decodes the Bearer token by **base64url-decoding** it and parsing the JSON claims directly. No signature verification is performed. Any attacker who understands the format can craft a token claiming any role, any `customer_id`, or any `lab_scope` without a secret key:

```python
# Current — STUB, line 55–87 of backend/api/app.py
padded = token + "=" * (-len(token) % 4)
claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
role = Role(claims["role"])
return Principal(user_id=int(claims["user_id"]), role=role, ...)
```

A malicious caller can encode `{"user_id":1,"role":"manager","lab_scope":[1,2,3,4,5,6,7,8,9]}` and access every order in every laboratory.

#### Context

The stub is **explicitly documented** in the file and in `docs/api/openapi.yaml`. It was built as the correct injection point with the correct `Principal` shape so that the rest of the auth layer (authorization.py, service_orders.py) does not need to change. This is a pre-wired socket waiting for a real plug.

#### Required fix (before production)

Replace the body of `_decode_token` with a real JWT verification library. The function contract is already correct — return `Principal` on success, `None` on failure, never raise.

**Recommended implementation using PyJWT** (add `PyJWT[crypto]` to `pyproject.toml`):

```python
import jwt  # PyJWT

_JWT_ALGORITHM = "RS256"  # or "HS256" for shared-secret
_JWT_PUBLIC_KEY = os.environ["JWT_PUBLIC_KEY"]  # PEM string from env var

def _decode_token(token: str) -> Principal | None:
    try:
        claims = jwt.decode(
            token,
            _JWT_PUBLIC_KEY,
            algorithms=[_JWT_ALGORITHM],
            options={"verify_exp": True, "verify_aud": False},
        )
        role = Role(claims["role"])
        return Principal(
            user_id=int(claims["sub"]),
            role=role,
            customer_id=claims.get("customer_id"),
            customer_scope=frozenset(claims.get("customer_scope", [])),
            lab_scope=frozenset(claims.get("lab_scope", [])),
        )
    except Exception:
        return None
```

Additional required environment variable: `JWT_PUBLIC_KEY` (RSA public key PEM).

**Regression test to add**: A test that presents a forged base64url JSON token and confirms the response is `401`, not `200`. This test will pass today (stub accepts it) and must fail after the fix is in place — i.e., write it as a **known-failing** test now and flip it when the fix lands.

---

### [MEDIUM] F-02 — No CORS policy configured

**File**: [`backend/api/app.py`](../../backend/api/app.py) — `create_app`, line 139  
**CVSS v3**: 5.4 (AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:L/A:N)

#### Problem

The Starlette application has no `CORSMiddleware`. If this API is ever called from a browser context (e.g., a Langflow UI embedded in a web page, or a future web dashboard), the absence of CORS headers means:

- **Overly-permissive**: some reverse proxies add `Access-Control-Allow-Origin: *` by default, allowing any origin to read the response.
- **Overly-restrictive**: browsers may block legitimate cross-origin calls from the Langflow UI.

The Langflow component uses `httpx` (a server-side HTTP client), so this does not affect the current Langflow path. However, it becomes relevant the moment any browser-side code is added.

#### Required fix

Add `CORSMiddleware` to `create_app` with an explicit allowlist. Do not use `allow_origins=["*"]` for an authenticated API.

```python
from starlette.middleware.cors import CORSMiddleware

_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _ALLOWED_ORIGINS if o.strip()],
        allow_methods=["GET"],
        allow_headers=["Authorization", "Content-Type"],
    ),
    Middleware(AuthMiddleware),
    Middleware(RepositoryMiddleware),
]
```

New environment variable: `CORS_ALLOWED_ORIGINS` (comma-separated list, e.g. `https://langflow.serviceiq.example.com`).

---

### [MEDIUM] F-03 — `app.state.db_pool = None` in test helper bypasses pool guard

**File**: [`backend/tests/api/test_service_orders.py`](../../backend/tests/api/test_service_orders.py) — `_make_app`, line 126  
**Severity**: Medium (test isolation, not production)

#### Problem

The test helper sets `app.state.db_pool = None` explicitly:

```python
app.state.db_pool = None  # line 126
```

`RepositoryMiddleware` reads `request.app.state.db_pool` and passes it directly to `AIServiceOrderRepository(pool)`. If, in a future test, the mock `_InjectRepoMiddleware` is not used (e.g., a test added incorrectly), `RepositoryMiddleware` will construct a repository with `pool=None`. The repository will then attempt `async with pool.acquire()` and raise `AttributeError: 'NoneType' object has no attribute 'acquire'` — which, because it's inside an `async` route handler with no global exception handler, could produce an unhandled 500 with a raw traceback.

This is not currently exploitable because:
1. The test always uses `_InjectRepoMiddleware` which short-circuits before `RepositoryMiddleware` runs.
2. `create_app` is not called without a `db_pool` in tests.

#### Required fix (production guard, not test change)

Add a null guard in `RepositoryMiddleware.dispatch` so a misconfigured startup fails loudly at the middleware level:

```python
async def dispatch(self, request: Request, call_next: Callable) -> Response:
    pool = request.app.state.db_pool
    if pool is None:
        return JSONResponse({"error": "Service unavailable."}, status_code=503)
    request.state.repo = AIServiceOrderRepository(pool)
    return await call_next(request)
```

---

### [INFO] F-04 — `app.on_event` is deprecated in Starlette 0.37+

**File**: [`backend/api/app.py`](../../backend/api/app.py) — lines 169–177  
**Severity**: Informational (no security impact)

#### Observation

```python
@app.on_event("startup")
async def _startup() -> None: ...

@app.on_event("shutdown")
async def _shutdown() -> None: ...
```

`on_event` is deprecated in Starlette ≥ 0.37. The recommended replacement is `lifespan` context managers. This has no security impact but will produce deprecation warnings in newer Starlette versions and should be addressed before the next Starlette upgrade.

#### Recommended fix

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: Starlette):
    from backend.db.connection import init_pool, close_pool
    app.state.db_pool = await init_pool()
    yield
    await close_pool()

app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
```

---

### [INFO] F-05 — Single-space `%20` path accepted by `order_number` validator

**File**: [`backend/api/service_orders.py`](../../backend/api/service_orders.py) — `_ORDER_NUMBER_RE`, line 78  
**Severity**: Informational (no security impact)

#### Observation

The regex `^[\x20-\x7E]{1,100}$` accepts a single space (`%20`). The test file [`test_service_orders.py`](../../backend/tests/api/test_service_orders.py) line 301 explicitly covers this and confirms it results in a `404` (repo returns None for a space-only order number). There is no exploit path — it reaches the repository as a parameterised value, returns no row, and the handler returns 404.

If the business requirement is that order numbers must not be blank or whitespace-only, update the regex to `^[\x21-\x7E][\x20-\x7E]{0,99}$` (first character must be non-space).

---

### [INFO] F-06 — Langflow component does not verify TLS certificate for self-signed/custom CAs

**File**: [`langflow/components/service-order-tool/get_service_order_status.py`](../../langflow/components/service-order-tool/get_service_order_status.py) — line 208  
**Severity**: Informational (deployment concern)

#### Observation

```python
async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
    response = await client.get(url, headers=headers)
```

`httpx.AsyncClient()` defaults to verifying TLS certificates via the system CA store. This is correct for production deployments with a public CA certificate on the ServiceIQ API. However, if the API is deployed with a self-signed certificate or an internal CA, the call will fail with an SSL error.

**Do not** add `verify=False` — that would disable certificate verification entirely and expose the Bearer token to MITM.

If the API uses an internal CA, add the CA bundle path as an operator input:

```python
StrInput(
    name="ssl_ca_bundle",
    display_name="SSL CA Bundle Path",
    info="Path to a CA bundle file for custom CAs. Leave empty for system default.",
    advanced=True,
    required=False,
    value="",
)
```

```python
verify = self.ssl_ca_bundle.strip() or True
async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, verify=verify) as client: ...
```

---

### [INFO] F-07 — No rate limiting on the API

**File**: [`backend/api/app.py`](../../backend/api/app.py)  
**Severity**: Informational (infrastructure concern)

#### Observation

The API has no request rate limiting. A valid (but low-privileged) token could enumerate order numbers rapidly. The authorisation layer correctly returns identical 403/404 responses, so no information is leaked per-request, but a burst of requests could put load on the database.

Rate limiting belongs at the infrastructure layer (nginx, API gateway, cloud load balancer) and is out of scope for this Python application. Note it for the deployment runbook.

---

## What was reviewed and found sound

The following security properties were **verified correct** and require no changes:

| Property | Evidence |
|----------|----------|
| **No SQL injection** | All queries use asyncpg `$N` positional placeholders. `test_get_by_id_uses_parameterized_query` and `test_list_by_customer_uses_parameterized_query` assert `"42" not in sql` and `"77" not in sql`. |
| **IDOR prevention** | `require_order_access` compares `order.customer_id` (fetched from DB) not the URL parameter. Covered by `test_unauthorized_customer_gets_403`. |
| **403/404 indistinguishable** | Both return `"Order not found or access denied."`. Covered by `test_unauthorized_customer_gets_403` and `test_nonexistent_order_gets_404`. |
| **Sensitive field suppression** | `_order_response` explicitly excludes `service_order_id`, `track`, `service_request_id`, `sla_deadline`, `customer_id`, `laboratory_id`. Covered by `test_response_excludes_internal_fields`. |
| **No credentials in code** | `connection.py` reads only from env vars; missing vars raise `EnvironmentError` immediately. No secrets in any source file. |
| **Unknown roles denied** | `authorization.py` line 67–69 raises `AccessDeniedError` for any role not in the enum — defensive default-deny. |
| **Langflow token never in flow JSON** | `bearer_token` uses `SecretStrInput` with no `value` default — cannot be embedded in exported flow files. |
| **LLM cannot control auth** | Only `order_number` has `tool_mode=True`; `api_base_url` and `bearer_token` are `advanced=True` / `SecretStrInput` — operator-only. |
| **No direct DB from Langflow** | The component uses `httpx` to call the API. It has no asyncpg dependency, no DSN, no connection pool. |
| **Input validation at multiple layers** | `order_number` is validated by the same regex in both the API handler and the Langflow component (defence in depth). |
| **Manager None-lab denial** | `_check_manager` raises if `order.laboratory_id is None` — no manager can access unassigned orders. Covered by `test_manager_outside_scope_gets_403`. |
| **Auth middleware never raises** | `_decode_token` catches all exceptions and returns `None`; middleware sets `principal = None`; route returns `401`. |
| **Pool credential redaction** | asyncpg redacts the DSN (including password) from tracebacks. Documented in `connection.py`. |

---

## Pre-production checklist

Before going live, the following **must** be completed:

- [ ] **[F-01 CRITICAL]** Replace `_decode_token` stub with real JWT verification (PyJWT RS256 or equivalent). Add `JWT_PUBLIC_KEY` to environment. Add regression test asserting forged tokens return 401.
- [ ] **[F-02 MEDIUM]** Add `CORSMiddleware` with explicit origin allowlist. Add `CORS_ALLOWED_ORIGINS` to environment.
- [ ] **[F-03 MEDIUM]** Add null-pool guard to `RepositoryMiddleware.dispatch` to return 503 rather than 500 on misconfigured startup.
- [ ] **[F-04 INFO]** Migrate `on_event` to `lifespan` before next Starlette upgrade.
- [ ] **[F-05 INFO]** Decide whether space-only order numbers should be explicitly rejected at the validator level; update regex if so.
- [ ] **[F-06 INFO]** Document TLS CA bundle requirement in deployment runbook; add `ssl_ca_bundle` input to Langflow component if internal CA is used.
- [ ] **[F-07 INFO]** Configure rate limiting at the infrastructure layer (nginx, API gateway, or cloud load balancer).

---

## Test coverage summary

**35 tests, 35 passing, 0 failing, 0 warnings.**

| Area | Test count | Key security assertions |
|------|-----------|------------------------|
| Repository unit tests | 24 | Parameterised query asserted, no SQL interpolation, limit/offset forwarding |
| API integration tests | 11 | 200/400/401/403/404 paths, IDOR, response field exclusion, scope checks |
| **Total** | **35** | |

Missing test (to be added with F-01 fix):  
- `test_forged_token_gets_401` — present a hand-crafted base64url JSON token with `role=manager, lab_scope=[1..999]`; assert `401` after real JWT verification is in place.

---

*Review completed. All files in the ServiceIQ AI data layer have been read in full.*
