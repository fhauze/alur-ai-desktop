"""
backend/repositories/AIServiceOrderRepository.py
--------------------------------------------------
Read-only repository for the AI service-order semantic view.

This is the **only** permitted data-access path for service-order intelligence
in the ServiceIQ AI layer.

Rules enforced by this module
──────────────────────────────
1. Queries only public.ai_service_order_summary — never raw transactional tables.
2. All query parameters are passed as positional asyncpg placeholders ($1, $2, …).
   No string interpolation of any kind is used for filter values.
3. Returns typed AIServiceOrder domain objects; raw asyncpg records are never
   surfaced to callers.
4. Missing / not-found cases are represented by Optional[…] or empty lists —
   never by raising unexpected exceptions.
5. No database credentials are referenced here.

Dependency
──────────
  asyncpg.Connection  — injected by the caller (from backend.db.connection)
  AIServiceOrder      — domain object defined in backend.domain.AIServiceOrder
"""

from __future__ import annotations

from typing import Optional, Sequence

import asyncpg

from backend.domain.AIServiceOrder import (
    AIServiceOrder,
    OrderStatus,
    SLAStatus,
    ServiceTrack,
)

# ---------------------------------------------------------------------------
# View name constant — single point of truth; never interpolated into WHERE
# values, only into the structural (FROM) part of SQL which is not user-supplied.
# ---------------------------------------------------------------------------
_VIEW = "public.ai_service_order_summary"

# ---------------------------------------------------------------------------
# Column list — explicit, matches view definition exactly.
# Never use SELECT * so that column additions to the view do not silently
# change the shape of objects returned to callers.
# ---------------------------------------------------------------------------
_COLUMNS = (
    "service_order_id",
    "order_number",
    "service_request_id",
    "track",
    "customer_id",
    "customer_name",
    "service_type",
    "laboratory_id",
    "laboratory_name",
    "order_status",
    "inspection_status",
    "sla_deadline",
    "sla_status",
)
_SELECT = f"SELECT {', '.join(_COLUMNS)} FROM {_VIEW}"


class AIServiceOrderRepository:
    """Read-only repository for public.ai_service_order_summary.

    All methods are coroutines. Instantiate with an asyncpg Connection or Pool.

    Example::

        pool = await asyncpg.create_pool(dsn=...)
        repo = AIServiceOrderRepository(pool)

        order = await repo.get_by_id(track=ServiceTrack.UUT, service_order_id=42)
        if order is None:
            ...  # not found
    """

    def __init__(self, conn: asyncpg.Connection | asyncpg.Pool) -> None:
        """
        Args:
            conn: An asyncpg Connection or Pool.
                  A Pool is preferred for production use — each method
                  acquires a connection from the pool for the duration of
                  the query and releases it immediately afterward.
        """
        self._conn = conn

    # ------------------------------------------------------------------
    # Private helper
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(record: asyncpg.Record) -> AIServiceOrder:
        """Convert one asyncpg Record to an AIServiceOrder domain object."""
        return AIServiceOrder.from_record(dict(record))

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        track: ServiceTrack,
        service_order_id: int,
    ) -> Optional[AIServiceOrder]:
        """Fetch a single order by its surrogate key (track, service_order_id).

        Returns None when no matching row exists in the view.

        Args:
            track:            The service track ('UUT' or 'UTTP').
            service_order_id: The integer primary key of the work order.

        Returns:
            AIServiceOrder if found, None otherwise.
        """
        query = f"{_SELECT} WHERE track = $1 AND service_order_id = $2"
        record = await self._conn.fetchrow(query, track.value, service_order_id)
        if record is None:
            return None
        return self._to_domain(record)

    async def list_by_customer(
        self,
        customer_id: int,
        *,
        track: Optional[ServiceTrack] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AIServiceOrder]:
        """Retrieve all orders belonging to a customer.

        Args:
            customer_id: The users_customers.id of the requesting customer.
            track:       Optional filter to a single service track.
            limit:       Maximum number of rows to return (default 100).
            offset:      Row offset for pagination (default 0).

        Returns:
            A (possibly empty) sequence of AIServiceOrder objects,
            ordered by service_order_id descending (most recent first).
        """
        if track is not None:
            query = (
                f"{_SELECT}"
                " WHERE customer_id = $1 AND track = $2"
                " ORDER BY service_order_id DESC"
                " LIMIT $3 OFFSET $4"
            )
            rows = await self._conn.fetch(
                query, customer_id, track.value, limit, offset
            )
        else:
            query = (
                f"{_SELECT}"
                " WHERE customer_id = $1"
                " ORDER BY service_order_id DESC"
                " LIMIT $2 OFFSET $3"
            )
            rows = await self._conn.fetch(query, customer_id, limit, offset)

        return [self._to_domain(r) for r in rows]

    async def list_by_order_status(
        self,
        status: OrderStatus,
        *,
        track: Optional[ServiceTrack] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AIServiceOrder]:
        """Retrieve orders filtered by order_status.

        Args:
            status: The OrderStatus value to filter on.
            track:  Optional filter to a single service track.
            limit:  Maximum rows (default 100).
            offset: Pagination offset (default 0).

        Returns:
            A (possibly empty) sequence of AIServiceOrder objects.
        """
        if track is not None:
            query = (
                f"{_SELECT}"
                " WHERE order_status = $1 AND track = $2"
                " ORDER BY service_order_id DESC"
                " LIMIT $3 OFFSET $4"
            )
            rows = await self._conn.fetch(
                query, status.value, track.value, limit, offset
            )
        else:
            query = (
                f"{_SELECT}"
                " WHERE order_status = $1"
                " ORDER BY service_order_id DESC"
                " LIMIT $2 OFFSET $3"
            )
            rows = await self._conn.fetch(query, status.value, limit, offset)

        return [self._to_domain(r) for r in rows]

    async def list_by_sla_status(
        self,
        sla_status: SLAStatus,
        *,
        track: Optional[ServiceTrack] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AIServiceOrder]:
        """Retrieve orders filtered by SLA compliance status.

        Primarily used to surface overdue or at-risk orders for AI alerting.

        Args:
            sla_status: The SLAStatus value to filter on.
            track:      Optional filter to a single service track.
            limit:      Maximum rows (default 100).
            offset:     Pagination offset (default 0).

        Returns:
            A (possibly empty) sequence of AIServiceOrder objects,
            ordered by sla_deadline ascending (most urgent first) when the
            deadline is available, then by service_order_id descending.
        """
        if track is not None:
            query = (
                f"{_SELECT}"
                " WHERE sla_status = $1 AND track = $2"
                " ORDER BY sla_deadline ASC NULLS LAST, service_order_id DESC"
                " LIMIT $3 OFFSET $4"
            )
            rows = await self._conn.fetch(
                query, sla_status.value, track.value, limit, offset
            )
        else:
            query = (
                f"{_SELECT}"
                " WHERE sla_status = $1"
                " ORDER BY sla_deadline ASC NULLS LAST, service_order_id DESC"
                " LIMIT $2 OFFSET $3"
            )
            rows = await self._conn.fetch(query, sla_status.value, limit, offset)

        return [self._to_domain(r) for r in rows]

    async def list_by_laboratory(
        self,
        laboratory_id: int,
        *,
        track: Optional[ServiceTrack] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AIServiceOrder]:
        """Retrieve orders assigned to a specific laboratory.

        Args:
            laboratory_id: The master_laboratory.id of the target lab.
            track:         Optional track filter.
            limit:         Maximum rows (default 100).
            offset:        Pagination offset (default 0).

        Returns:
            A (possibly empty) sequence of AIServiceOrder objects.
        """
        if track is not None:
            query = (
                f"{_SELECT}"
                " WHERE laboratory_id = $1 AND track = $2"
                " ORDER BY service_order_id DESC"
                " LIMIT $3 OFFSET $4"
            )
            rows = await self._conn.fetch(
                query, laboratory_id, track.value, limit, offset
            )
        else:
            query = (
                f"{_SELECT}"
                " WHERE laboratory_id = $1"
                " ORDER BY service_order_id DESC"
                " LIMIT $2 OFFSET $3"
            )
            rows = await self._conn.fetch(query, laboratory_id, limit, offset)

        return [self._to_domain(r) for r in rows]

    async def list_by_service_request(
        self,
        service_request_id: int,
    ) -> Sequence[AIServiceOrder]:
        """Retrieve all work orders associated with a service request.

        A single service request may produce multiple work orders (one per
        line item / inspection).

        Args:
            service_request_id: The service_requests.id or service_request_uttps.id.

        Returns:
            A (possibly empty) sequence of AIServiceOrder objects.
        """
        query = (
            f"{_SELECT}"
            " WHERE service_request_id = $1"
            " ORDER BY track, service_order_id"
        )
        rows = await self._conn.fetch(query, service_request_id)
        return [self._to_domain(r) for r in rows]

    async def get_by_order_number(
        self,
        order_number: str,
    ) -> Optional[AIServiceOrder]:
        """Fetch the first order matching a human-readable order_number.

        order_number is passed as a parameterised value — never interpolated
        into the SQL string — preventing any form of SQL injection.

        When multiple orders share the same order_number (e.g. across tracks)
        the UUT row is returned preferentially; use list_by_order_number for
        all matching rows.

        Args:
            order_number: The human-readable order number from the request URL.

        Returns:
            AIServiceOrder if found, None otherwise.
        """
        query = (
            f"{_SELECT}"
            " WHERE order_number = $1"
            " ORDER BY track, service_order_id"
            " LIMIT 1"
        )
        record = await self._conn.fetchrow(query, order_number)
        if record is None:
            return None
        return self._to_domain(record)
