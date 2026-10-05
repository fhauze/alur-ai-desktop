"""
backend/domain/AIServiceOrder.py
---------------------------------
Domain model for the AI service-order semantic view.

This module defines the typed value objects consumed by the AI layer.
All fields map 1-to-1 to the columns exposed by:

    public.ai_service_order_summary

See docs/database/ai-service-order-summary.md for the authoritative column
reference.

Design notes
────────────
- Dataclasses (frozen=True) make instances immutable and hashable once built.
- Every enum encodes exactly the values the view can produce — nothing more.
  Adding a value here requires a matching change to the view SQL.
- Optional[X] is used where the view can return NULL (LEFT JOIN paths,
  derived fields with missing inputs). See per-field docstrings.
- No database logic lives here; this module has zero imports from asyncpg
  or the db layer.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ServiceTrack(str, Enum):
    """Which physical service track produced the order row.

    UUT  — Unit Under Test (calibration instruments, laboratory-based).
    UTTP — Ukuran Takar Timbang Perlengkapan (weighing/measuring instruments,
            field inspection).

    Source: literal constant in ai_service_order_summary UNION branches.
    """

    UUT = "UUT"
    UTTP = "UTTP"


class OrderStatus(str, Enum):
    """Normalised lifecycle status derived from the integer status fields.

    Source columns (priority order):
        cancel_at IS NOT NULL → cancelled
        is_nonaktif = TRUE    → cancelled   (UTTP only)
        pending_status > 0    → pending
        is_finish = 1         → completed
        stat_sertifikat > 0   → certified
        stat_service_order > 0→ in_progress
        (default)             → new

    See docs/database/ai-service-order-summary.md §Order Status Logic.
    """

    NEW = "new"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    CERTIFIED = "certified"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InspectionStatus(str, Enum):
    """Aggregated checklist result for the order.

    Source: correlated subquery on service_order_inspections (UUT) or
            service_order_uttp_inspections (UTTP).

    no_inspection — no checklist rows exist for the order.
    passed        — all is_accepted = TRUE.
    failed        — at least one is_accepted = FALSE.
    partial       — mix of TRUE and NULL (some items not yet evaluated).

    See docs/database/ai-service-order-summary.md §Inspection Status Logic.
    """

    NO_INSPECTION = "no_inspection"
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"


class SLAStatus(str, Enum):
    """SLA compliance state relative to CURRENT_DATE at query time.

    no_sla    — sla_deadline could not be computed (missing received_date
                or laboratory sla_day).
    on_track  — order not closed, > 2 days before deadline.
    at_risk   — order not closed, within 2 days of deadline.
    overdue   — order not closed, deadline has passed.
    closed    — order is completed or cancelled; SLA no longer applies.

    See docs/database/ai-service-order-summary.md §SLA Logic.
    """

    NO_SLA = "no_sla"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Domain object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AIServiceOrder:
    """A single row from public.ai_service_order_summary.

    This is a pure value object: no methods, no mutable state, no DB access.
    Use AIServiceOrderRepository to obtain instances.

    Field sources are documented against each attribute.
    """

    # ── Identity ─────────────────────────────────────────────────────────────

    service_order_id: int
    """Primary key of the work-order row.
    Source: service_orders.id (UUT) / service_order_uttps.id (UTTP).
    Not globally unique — use (track, service_order_id) as the surrogate key.
    """

    order_number: Optional[str]
    """Human-readable order number.
    Source: service_requests.no_order / service_request_uttps.no_order.
    NULL when the parent request is missing or no_order was not yet assigned.
    """

    service_request_id: Optional[int]
    """Foreign reference to the originating service request.
    Source: service_orders.service_request_id / service_order_uttps.service_request_id.
    NULL for orphaned orders with no service_request_id set.
    No FK constraint; may reference a deleted or missing request row.
    """

    track: ServiceTrack
    """Discriminator identifying the service track.
    Source: literal 'UUT' or 'UTTP' constant in the view.
    """

    # ── Customer ─────────────────────────────────────────────────────────────

    customer_id: Optional[int]
    """Internal ID of the requesting customer.
    Source: users_customers.id via service_requests.requestor_id.
    NULL when requestor_id has no matching users_customers row.
    """

    customer_name: Optional[str]
    """Full name of the requesting customer.
    Source: users_customers.full_name.
    NULL when customer lookup fails (LEFT JOIN path).
    """

    # ── Service type ─────────────────────────────────────────────────────────

    service_type: Optional[str]
    """Human-readable service type label.
    Source: master_service_types.service_type.
    NULL when service_type_id has no match in master_service_types.
    """

    # ── Laboratory ───────────────────────────────────────────────────────────

    laboratory_id: Optional[int]
    """ID of the assigned laboratory.
    Source: service_orders.laboratory_id / service_order_uttps.laboratory_id.
    NULL for unassigned orders.
    """

    laboratory_name: Optional[str]
    """Human-readable laboratory name.
    Source: master_laboratory.nama_lab.
    NULL when laboratory_id is NULL or unmatched.
    """

    # ── Derived status fields ─────────────────────────────────────────────────

    order_status: OrderStatus
    """Normalised lifecycle status. See OrderStatus enum for derivation logic."""

    inspection_status: InspectionStatus
    """Aggregated checklist result. See InspectionStatus enum."""

    sla_deadline: Optional[datetime.date]
    """Computed target completion date (received_date + sla_day).
    NULL when received_date or sla_day is missing.
    """

    sla_status: SLAStatus
    """SLA compliance state at query time. See SLAStatus enum."""

    # ── Class methods ─────────────────────────────────────────────────────────

    @classmethod
    def from_record(cls, record: dict) -> "AIServiceOrder":
        """Construct an AIServiceOrder from a database record dictionary.

        Args:
            record: A mapping of column name → value, as returned by asyncpg.
                    Keys must match the view column names exactly.

        Returns:
            A frozen AIServiceOrder instance.

        Raises:
            KeyError:  if a required column is absent from the record.
            ValueError: if an enum value is not recognised.
        """
        return cls(
            service_order_id=record["service_order_id"],
            order_number=record["order_number"],
            service_request_id=record["service_request_id"],
            track=ServiceTrack(record["track"]),
            customer_id=record["customer_id"],
            customer_name=record["customer_name"],
            service_type=record["service_type"],
            laboratory_id=record["laboratory_id"],
            laboratory_name=record["laboratory_name"],
            order_status=OrderStatus(record["order_status"]),
            inspection_status=InspectionStatus(record["inspection_status"]),
            sla_deadline=record["sla_deadline"],
            sla_status=SLAStatus(record["sla_status"]),
        )
