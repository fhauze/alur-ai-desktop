"""
backend/auth/authorization.py
------------------------------
Server-side authorisation guard for service-order access.

This module is the **single authoritative location** for all access-control
decisions. Route handlers call ``require_order_access`` and catch
``AccessDeniedError`` — they never perform role checks themselves.

IDOR prevention
───────────────
  The guard compares the order's customer_id (from the database-fetched domain
  object) against the caller's identity. A CUSTOMER can never access another
  customer's order even if they guess a valid order_number, because the check
  is against the fetched record's customer_id field, not the URL parameter.

Authorisation matrix
────────────────────
  Role      │ Condition for access
  ──────────┼───────────────────────────────────────────────────────────────
  CUSTOMER  │ order.customer_id == principal.customer_id
  STAFF     │ order.customer_id in principal.customer_scope
            │   OR principal.customer_id == order.customer_id (if STAFF
            │   also has a direct customer association)
  MANAGER   │ order.laboratory_id in principal.lab_scope
            │   (None laboratory_id → denied; manager scope must be explicit)

Errors
──────
  AccessDeniedError — raised when the principal does not satisfy any
                      condition for the requested order.
"""

from __future__ import annotations

from backend.auth.principal import Principal, Role
from backend.domain.AIServiceOrder import AIServiceOrder


class AccessDeniedError(Exception):
    """Raised when a principal is not authorised to access an order.

    The message is intentionally generic to avoid leaking order existence
    to unauthorised callers (same response shape as not-found).
    """


def require_order_access(principal: Principal, order: AIServiceOrder) -> None:
    """Assert that ``principal`` is authorised to read ``order``.

    This function either returns None (access granted) or raises
    AccessDeniedError (access denied). It never returns a boolean.

    Args:
        principal: The authenticated caller, produced by auth middleware.
        order:     The fetched AIServiceOrder domain object.

    Raises:
        AccessDeniedError: if the principal is not permitted to view the order.
    """
    if principal.role == Role.CUSTOMER:
        _check_customer(principal, order)
    elif principal.role == Role.STAFF:
        _check_staff(principal, order)
    elif principal.role == Role.MANAGER:
        _check_manager(principal, order)
    else:
        # Defensive: unknown future roles are denied by default.
        raise AccessDeniedError("Unknown role.")


# ---------------------------------------------------------------------------
# Role-specific checks (private)
# ---------------------------------------------------------------------------


def _check_customer(principal: Principal, order: AIServiceOrder) -> None:
    """CUSTOMER: may only see orders they own.

    Compares principal.customer_id (from auth token) against
    order.customer_id (from the database view). This prevents IDOR:
    a customer cannot access another customer's order by guessing an
    order_number, because the guard checks the fetched record, not the URL.
    """
    if order.customer_id is None:
        # Order has no customer association — deny rather than leak.
        raise AccessDeniedError("Access denied.")
    if principal.customer_id != order.customer_id:
        raise AccessDeniedError("Access denied.")


def _check_staff(principal: Principal, order: AIServiceOrder) -> None:
    """STAFF: may see orders within their customer scope.

    customer_scope is the set of customer_ids the staff member is
    authorised to work on. Populated from the auth token at login.
    """
    if order.customer_id is None:
        raise AccessDeniedError("Access denied.")
    if order.customer_id not in principal.customer_scope:
        raise AccessDeniedError("Access denied.")


def _check_manager(principal: Principal, order: AIServiceOrder) -> None:
    """MANAGER: may see orders within their laboratory scope.

    lab_scope is the set of laboratory_ids the manager oversees.
    An order with no laboratory assignment is outside any manager's scope.
    """
    if order.laboratory_id is None:
        raise AccessDeniedError("Access denied.")
    if order.laboratory_id not in principal.lab_scope:
        raise AccessDeniedError("Access denied.")
