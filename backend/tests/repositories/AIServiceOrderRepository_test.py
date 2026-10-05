"""
backend/tests/repositories/AIServiceOrderRepository_test.py
-------------------------------------------------------------
Unit tests for AIServiceOrderRepository.

Strategy
────────
All tests use a mock asyncpg connection injected into the repository.
No live database connection is required. This keeps tests fast, hermetic,
and free of infrastructure dependencies.

The mock is built with pytest-mock (MockerFixture) and configured so that:
  - conn.fetchrow(...)  returns a single asyncpg.Record-like dict or None.
  - conn.fetch(...)     returns a list of dicts.

asyncpg Records support dict-style key access, so plain dicts are sufficient
as stand-ins for the mock. AIServiceOrder.from_record() receives dict(record),
so this is compatible.

Test matrix
───────────
 1. get_by_id — valid UUT order, all fields populated
 2. get_by_id — valid UTTP order
 3. get_by_id — not found (returns None)
 4. list_by_customer — customer with multiple orders
 5. list_by_customer — customer with no orders (empty list)
 6. list_by_customer — filtered to one track
 7. list_by_order_status — status filter, both tracks
 8. list_by_order_status — status filter, single track
 9. list_by_sla_status — overdue orders surfaced
10. list_by_sla_status — no_sla orders
11. list_by_laboratory — orders for a lab
12. list_by_laboratory — lab with no orders
13. list_by_service_request — multiple orders for one request
14. list_by_service_request — request with no orders (empty list)
15. AIServiceOrder.from_record — all fields round-trip correctly
16. AIServiceOrder.from_record — NULL optional fields are preserved
17. OrderStatus enum — only declared values accepted
18. SLAStatus enum   — only declared values accepted
19. Repository: correct SQL placeholder usage (no string injection)
20. Repository: limit/offset forwarded correctly to the connection
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.domain.AIServiceOrder import (
    AIServiceOrder,
    InspectionStatus,
    OrderStatus,
    SLAStatus,
    ServiceTrack,
)
from backend.repositories.AIServiceOrderRepository import AIServiceOrderRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(**overrides: Any) -> dict:
    """Return a minimal valid view-row dict, with optional overrides."""
    base: dict[str, Any] = {
        "service_order_id": 1,
        "order_number": "ORD-2024-001",
        "service_request_id": 10,
        "track": "UUT",
        "customer_id": 100,
        "customer_name": "PT Maju Bersama",
        "service_type": "Kalibrasi",
        "laboratory_id": 5,
        "laboratory_name": "Lab Massa dan Volume",
        "order_status": "in_progress",
        "inspection_status": "passed",
        "sla_deadline": datetime.date(2024, 12, 31),
        "sla_status": "on_track",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def mock_conn() -> MagicMock:
    """A mock asyncpg Connection with AsyncMock query methods."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    return conn


@pytest.fixture()
def repo(mock_conn: MagicMock) -> AIServiceOrderRepository:
    return AIServiceOrderRepository(mock_conn)


# ---------------------------------------------------------------------------
# Test 1 — get_by_id: valid UUT order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_returns_uut_order(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    record = _make_record(
        service_order_id=42,
        track="UUT",
        order_status="in_progress",
        inspection_status="passed",
        sla_status="on_track",
    )
    mock_conn.fetchrow.return_value = record

    result = await repo.get_by_id(ServiceTrack.UUT, 42)

    assert result is not None
    assert result.service_order_id == 42
    assert result.track == ServiceTrack.UUT
    assert result.order_status == OrderStatus.IN_PROGRESS
    assert result.inspection_status == InspectionStatus.PASSED
    assert result.sla_status == SLAStatus.ON_TRACK
    assert result.customer_name == "PT Maju Bersama"
    assert result.laboratory_name == "Lab Massa dan Volume"


# ---------------------------------------------------------------------------
# Test 2 — get_by_id: valid UTTP order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_returns_uttp_order(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    record = _make_record(
        service_order_id=99,
        track="UTTP",
        order_status="certified",
        inspection_status="passed",
        sla_status="closed",
    )
    mock_conn.fetchrow.return_value = record

    result = await repo.get_by_id(ServiceTrack.UTTP, 99)

    assert result is not None
    assert result.service_order_id == 99
    assert result.track == ServiceTrack.UTTP
    assert result.order_status == OrderStatus.CERTIFIED
    assert result.sla_status == SLAStatus.CLOSED


# ---------------------------------------------------------------------------
# Test 3 — get_by_id: not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetchrow.return_value = None

    result = await repo.get_by_id(ServiceTrack.UUT, -1)

    assert result is None


# ---------------------------------------------------------------------------
# Test 4 — list_by_customer: customer with multiple orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_customer_returns_multiple_orders(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [
        _make_record(service_order_id=10, customer_id=55),
        _make_record(service_order_id=11, customer_id=55),
        _make_record(service_order_id=12, customer_id=55),
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_customer(customer_id=55)

    assert len(results) == 3
    assert all(r.customer_id == 55 for r in results)
    assert [r.service_order_id for r in results] == [10, 11, 12]


# ---------------------------------------------------------------------------
# Test 5 — list_by_customer: no orders (empty list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_customer_returns_empty_when_none(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    results = await repo.list_by_customer(customer_id=9999)

    assert results == []


# ---------------------------------------------------------------------------
# Test 6 — list_by_customer: filtered to one track
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_customer_with_track_filter(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [_make_record(service_order_id=7, track="UUT", customer_id=55)]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_customer(customer_id=55, track=ServiceTrack.UUT)

    assert len(results) == 1
    assert results[0].track == ServiceTrack.UUT
    # Confirm the query passed the track parameter as $2
    call_args = mock_conn.fetch.call_args
    assert "UUT" in call_args.args


# ---------------------------------------------------------------------------
# Test 7 — list_by_order_status: both tracks, status = 'pending'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_order_status_both_tracks(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [
        _make_record(service_order_id=20, track="UUT", order_status="pending"),
        _make_record(service_order_id=21, track="UTTP", order_status="pending"),
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_order_status(OrderStatus.PENDING)

    assert len(results) == 2
    assert all(r.order_status == OrderStatus.PENDING for r in results)


# ---------------------------------------------------------------------------
# Test 8 — list_by_order_status: single track filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_order_status_single_track(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [_make_record(service_order_id=30, track="UTTP", order_status="new")]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_order_status(OrderStatus.NEW, track=ServiceTrack.UTTP)

    assert len(results) == 1
    assert results[0].track == ServiceTrack.UTTP
    # Confirm track was passed as a bound parameter
    call_args = mock_conn.fetch.call_args
    assert "UTTP" in call_args.args


# ---------------------------------------------------------------------------
# Test 9 — list_by_sla_status: overdue orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_sla_status_overdue(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    overdue_deadline = datetime.date(2023, 1, 1)
    records = [
        _make_record(
            service_order_id=40,
            sla_status="overdue",
            sla_deadline=overdue_deadline,
            order_status="in_progress",
        )
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_sla_status(SLAStatus.OVERDUE)

    assert len(results) == 1
    assert results[0].sla_status == SLAStatus.OVERDUE
    assert results[0].sla_deadline == overdue_deadline


# ---------------------------------------------------------------------------
# Test 10 — list_by_sla_status: no_sla (missing lab data)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_sla_status_no_sla(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [
        _make_record(
            service_order_id=50,
            sla_status="no_sla",
            sla_deadline=None,
            laboratory_id=None,
            laboratory_name=None,
        )
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_sla_status(SLAStatus.NO_SLA)

    assert len(results) == 1
    assert results[0].sla_status == SLAStatus.NO_SLA
    assert results[0].sla_deadline is None
    assert results[0].laboratory_id is None
    assert results[0].laboratory_name is None


# ---------------------------------------------------------------------------
# Test 11 — list_by_laboratory: orders for a lab
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_laboratory_returns_orders(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [
        _make_record(service_order_id=60, laboratory_id=7, laboratory_name="Lab Listrik"),
        _make_record(service_order_id=61, laboratory_id=7, laboratory_name="Lab Listrik"),
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_laboratory(laboratory_id=7)

    assert len(results) == 2
    assert all(r.laboratory_id == 7 for r in results)
    assert all(r.laboratory_name == "Lab Listrik" for r in results)


# ---------------------------------------------------------------------------
# Test 12 — list_by_laboratory: lab with no orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_laboratory_returns_empty(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    results = await repo.list_by_laboratory(laboratory_id=999)

    assert results == []


# ---------------------------------------------------------------------------
# Test 13 — list_by_service_request: multiple orders for one request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_service_request_multiple_orders(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    records = [
        _make_record(service_order_id=70, service_request_id=200, track="UUT"),
        _make_record(service_order_id=71, service_request_id=200, track="UUT"),
    ]
    mock_conn.fetch.return_value = records

    results = await repo.list_by_service_request(service_request_id=200)

    assert len(results) == 2
    assert all(r.service_request_id == 200 for r in results)


# ---------------------------------------------------------------------------
# Test 14 — list_by_service_request: request with no orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_service_request_empty(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    results = await repo.list_by_service_request(service_request_id=9999)

    assert results == []


# ---------------------------------------------------------------------------
# Test 15 — AIServiceOrder.from_record: all fields round-trip
# ---------------------------------------------------------------------------


def test_from_record_all_fields() -> None:
    deadline = datetime.date(2024, 6, 30)
    record = _make_record(
        service_order_id=1,
        order_number="ORD-001",
        service_request_id=10,
        track="UUT",
        customer_id=100,
        customer_name="Budi Santoso",
        service_type="Kalibrasi",
        laboratory_id=5,
        laboratory_name="Lab Suhu",
        order_status="completed",
        inspection_status="passed",
        sla_deadline=deadline,
        sla_status="closed",
    )
    order = AIServiceOrder.from_record(record)

    assert order.service_order_id == 1
    assert order.order_number == "ORD-001"
    assert order.service_request_id == 10
    assert order.track == ServiceTrack.UUT
    assert order.customer_id == 100
    assert order.customer_name == "Budi Santoso"
    assert order.service_type == "Kalibrasi"
    assert order.laboratory_id == 5
    assert order.laboratory_name == "Lab Suhu"
    assert order.order_status == OrderStatus.COMPLETED
    assert order.inspection_status == InspectionStatus.PASSED
    assert order.sla_deadline == deadline
    assert order.sla_status == SLAStatus.CLOSED


# ---------------------------------------------------------------------------
# Test 16 — AIServiceOrder.from_record: NULL optional fields preserved
# ---------------------------------------------------------------------------


def test_from_record_null_optional_fields() -> None:
    record = _make_record(
        order_number=None,
        service_request_id=None,
        customer_id=None,
        customer_name=None,
        service_type=None,
        laboratory_id=None,
        laboratory_name=None,
        sla_deadline=None,
        sla_status="no_sla",
    )
    order = AIServiceOrder.from_record(record)

    assert order.order_number is None
    assert order.service_request_id is None
    assert order.customer_id is None
    assert order.customer_name is None
    assert order.service_type is None
    assert order.laboratory_id is None
    assert order.laboratory_name is None
    assert order.sla_deadline is None
    assert order.sla_status == SLAStatus.NO_SLA


# ---------------------------------------------------------------------------
# Test 17 — OrderStatus enum: only declared values accepted
# ---------------------------------------------------------------------------


def test_order_status_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        OrderStatus("unknown_status")


def test_order_status_all_values_round_trip() -> None:
    for status in OrderStatus:
        assert OrderStatus(status.value) == status


# ---------------------------------------------------------------------------
# Test 18 — SLAStatus enum: only declared values accepted
# ---------------------------------------------------------------------------


def test_sla_status_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        SLAStatus("not_a_status")


def test_sla_status_all_values_round_trip() -> None:
    for status in SLAStatus:
        assert SLAStatus(status.value) == status


# ---------------------------------------------------------------------------
# Test 19 — No string injection: query uses $-placeholders for user values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_uses_parameterized_query(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetchrow.return_value = None

    await repo.get_by_id(ServiceTrack.UUT, 42)

    call_args = mock_conn.fetchrow.call_args
    sql: str = call_args.args[0]

    # The filter values must not be embedded in the SQL string
    assert "42" not in sql
    assert "UUT" not in sql
    # Parameters are positional placeholders
    assert "$1" in sql
    assert "$2" in sql
    # The actual values are passed as separate positional arguments
    assert call_args.args[1] == "UUT"
    assert call_args.args[2] == 42


@pytest.mark.asyncio
async def test_list_by_customer_uses_parameterized_query(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    await repo.list_by_customer(customer_id=77)

    call_args = mock_conn.fetch.call_args
    sql: str = call_args.args[0]

    assert "77" not in sql
    assert "$1" in sql
    assert call_args.args[1] == 77


# ---------------------------------------------------------------------------
# Test 20 — limit/offset forwarded correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_customer_forwards_limit_and_offset(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    await repo.list_by_customer(customer_id=5, limit=25, offset=50)

    call_args = mock_conn.fetch.call_args
    # Without track filter: $1=customer_id, $2=limit, $3=offset
    assert call_args.args[2] == 25
    assert call_args.args[3] == 50


@pytest.mark.asyncio
async def test_list_by_sla_status_forwards_limit_and_offset(
    repo: AIServiceOrderRepository, mock_conn: MagicMock
) -> None:
    mock_conn.fetch.return_value = []

    await repo.list_by_sla_status(SLAStatus.OVERDUE, limit=10, offset=20)

    call_args = mock_conn.fetch.call_args
    # Without track filter: $1=sla_status, $2=limit, $3=offset
    assert call_args.args[2] == 10
    assert call_args.args[3] == 20
