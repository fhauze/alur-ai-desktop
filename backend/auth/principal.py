"""
backend/auth/principal.py
--------------------------
Caller identity and role model for the ServiceIQ AI API.

A Principal is the authenticated identity attached to every request.
It is produced by the auth middleware from a validated token and injected
into every route handler. No network calls or database queries happen here.

Role semantics
──────────────
  CUSTOMER  — External requestor. May only see their own orders (where
              Principal.customer_id == AIServiceOrder.customer_id).

  STAFF     — Internal lab/field worker. May see orders they are assigned to
              (where Principal.user_id appears in the order's staff references).
              Because the semantic view does not expose staff columns, access is
              granted to any order whose customer_id is within the Principal's
              customer_scope, OR any order where order's customer_id matches a
              scope entry. Staff scope is set by the auth token.

  MANAGER   — Internal supervisor with organisational scope. May see any order
              whose laboratory_id is within Principal.lab_scope.

The Principal is immutable (frozen dataclass). It is created once per request
and never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional


class Role(str, Enum):
    """Access role granted by the authentication token."""

    CUSTOMER = "customer"
    STAFF = "staff"
    MANAGER = "manager"


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity.

    Attributes:
        user_id:        Internal user ID from the auth token. Always present.
        role:           The single role granted by the token.
        customer_id:    Set for CUSTOMER role — the users_customers.id that
                        the caller owns. None for STAFF and MANAGER.
        customer_scope: For STAFF — the set of customer_ids the staff member
                        is authorised to act on behalf of. Empty for others.
        lab_scope:      For MANAGER — the set of laboratory_ids within the
                        manager's organisational scope. Empty for others.
    """

    user_id: int
    role: Role
    customer_id: Optional[int] = None
    customer_scope: FrozenSet[int] = field(default_factory=frozenset)
    lab_scope: FrozenSet[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Invariant: a CUSTOMER principal must carry their own customer_id.
        if self.role == Role.CUSTOMER and self.customer_id is None:
            raise ValueError("Principal with role CUSTOMER must have customer_id set.")
