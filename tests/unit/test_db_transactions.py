"""
tests/unit/test_db_transactions.py
────────────────────────────────────
Tests for repo_transactions: insert, get, update, list_due_retries,
get_retry_count, and schema-enforced constraints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import aiosqlite

from app.db.repo_transactions import (
    get_retry_count,
    get_transaction,
    insert_transaction,
    list_due_retries,
    update_transaction,
)
from app.models.enums import FailureCategory, TransactionStatus
from app.models.transaction import Transaction


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_tx(
    transaction_id: str = "txn-001",
    amount_paise: int = 50_000,
    status: TransactionStatus = TransactionStatus.FAILED,
    retry_count: int = 0,
    next_retry_at: datetime | None = None,
    failure_category: FailureCategory | None = None,
) -> Transaction:
    now = _now()
    return Transaction(
        transaction_id=transaction_id,
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=amount_paise,
        customer_id="cust-001",
        mandate_id="mand-001",
        occurred_at=now,
        created_at=now,
        updated_at=now,
        status=status,
        failure_category=failure_category,
        retry_count=retry_count,
        next_retry_at=next_retry_at,
    )


# ── Insert & get ──────────────────────────────────────────────────────────────

async def test_insert_and_get_transaction(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    fetched = await get_transaction("txn-001")
    assert fetched is not None
    assert fetched.transaction_id == "txn-001"
    assert fetched.amount_paise == 50_000
    assert fetched.status == TransactionStatus.FAILED
    assert fetched.retry_count == 0


async def test_get_nonexistent_transaction_returns_none(db) -> None:
    result = await get_transaction("does-not-exist")
    assert result is None


async def test_insert_duplicate_raises(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)
    with pytest.raises(aiosqlite.IntegrityError):
        await insert_transaction(tx)


async def test_amount_rupees_property_after_roundtrip(db) -> None:
    tx = _make_tx(amount_paise=12_345)
    await insert_transaction(tx)
    fetched = await get_transaction("txn-001")
    assert fetched.amount_rupees == 123.45


async def test_mandate_id_stored_and_retrieved(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)
    fetched = await get_transaction("txn-001")
    assert fetched.mandate_id == "mand-001"


async def test_nullable_mandate_id(db) -> None:
    now = _now()
    tx = Transaction(
        transaction_id="txn-no-mandate",
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=10_000,
        customer_id="cust-001",
        occurred_at=now,
        created_at=now,
        updated_at=now,
    )
    await insert_transaction(tx)
    fetched = await get_transaction("txn-no-mandate")
    assert fetched.mandate_id is None


async def test_failure_category_roundtrip(db) -> None:
    tx = _make_tx(failure_category=FailureCategory.LIQUIDITY_TEMPORARY)
    await insert_transaction(tx)
    fetched = await get_transaction("txn-001")
    assert fetched.failure_category == FailureCategory.LIQUIDITY_TEMPORARY


async def test_null_failure_category_roundtrip(db) -> None:
    tx = _make_tx(failure_category=None)
    await insert_transaction(tx)
    fetched = await get_transaction("txn-001")
    assert fetched.failure_category is None


async def test_datetime_roundtrip_preserves_utc(db) -> None:
    """Datetimes must survive serialisation to TEXT and back."""
    now = datetime(2026, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
    tx = Transaction(
        transaction_id="txn-dt",
        failure_code="NPCI_SURGE_TIMEOUT",
        amount_paise=20_000,
        customer_id="cust-dt",
        occurred_at=now,
        created_at=now,
        updated_at=now,
    )
    await insert_transaction(tx)
    fetched = await get_transaction("txn-dt")
    assert fetched.occurred_at == now
    assert fetched.created_at.tzinfo is not None


# ── Update ────────────────────────────────────────────────────────────────────

async def test_update_transaction_status(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    updated = tx.model_copy(update={
        "status": TransactionStatus.RETRY_SCHEDULED,
        "retry_count": 1,
        "updated_at": _now(),
    })
    await update_transaction(updated)

    fetched = await get_transaction("txn-001")
    assert fetched.status == TransactionStatus.RETRY_SCHEDULED
    assert fetched.retry_count == 1


async def test_update_nonexistent_raises(db) -> None:
    tx = _make_tx(transaction_id="ghost-txn")
    with pytest.raises(ValueError, match="not found"):
        await update_transaction(tx)


async def test_update_sets_next_retry_at(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    future = _now() + timedelta(hours=2)
    updated = tx.model_copy(update={
        "status": TransactionStatus.RETRY_SCHEDULED,
        "next_retry_at": future,
        "updated_at": _now(),
    })
    await update_transaction(updated)

    fetched = await get_transaction("txn-001")
    assert fetched.next_retry_at is not None
    # Allow 1 second tolerance for serialisation rounding
    diff = abs((fetched.next_retry_at - future).total_seconds())
    assert diff < 1.0


async def test_update_failure_category(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)
    updated = tx.model_copy(update={
        "failure_category": FailureCategory.HARD_DECLINE,
        "updated_at": _now(),
    })
    await update_transaction(updated)
    fetched = await get_transaction("txn-001")
    assert fetched.failure_category == FailureCategory.HARD_DECLINE


# ── list_due_retries ──────────────────────────────────────────────────────────

async def test_list_due_retries_returns_scheduled_past(db) -> None:
    past = _now() - timedelta(minutes=5)
    tx = _make_tx(
        status=TransactionStatus.RETRY_SCHEDULED,
        next_retry_at=past,
    )
    await insert_transaction(tx)

    due = await list_due_retries()
    assert len(due) == 1
    assert due[0].transaction_id == "txn-001"


async def test_list_due_retries_excludes_future(db) -> None:
    future = _now() + timedelta(hours=2)
    tx = _make_tx(
        status=TransactionStatus.RETRY_SCHEDULED,
        next_retry_at=future,
    )
    await insert_transaction(tx)

    due = await list_due_retries()
    assert len(due) == 0


async def test_list_due_retries_excludes_wrong_status(db) -> None:
    past = _now() - timedelta(minutes=5)
    # FAILED status — should not appear in due retries
    tx = _make_tx(
        status=TransactionStatus.FAILED,
        next_retry_at=past,
    )
    await insert_transaction(tx)

    due = await list_due_retries()
    assert len(due) == 0


async def test_list_due_retries_multiple_ordered(db) -> None:
    """list_due_retries returns rows ordered by next_retry_at ascending."""
    now = _now()
    tx_later = _make_tx(
        transaction_id="txn-later",
        status=TransactionStatus.RETRY_SCHEDULED,
        next_retry_at=now - timedelta(minutes=1),
    )
    tx_earlier = _make_tx(
        transaction_id="txn-earlier",
        status=TransactionStatus.RETRY_SCHEDULED,
        next_retry_at=now - timedelta(minutes=10),
    )
    await insert_transaction(tx_earlier)
    await insert_transaction(tx_later)

    due = await list_due_retries()
    assert len(due) == 2
    assert due[0].transaction_id == "txn-earlier"
    assert due[1].transaction_id == "txn-later"


async def test_list_due_retries_excludes_recovered(db) -> None:
    past = _now() - timedelta(minutes=5)
    tx = _make_tx(
        status=TransactionStatus.RECOVERED,
        next_retry_at=past,
    )
    await insert_transaction(tx)
    due = await list_due_retries()
    assert len(due) == 0


# ── get_retry_count ───────────────────────────────────────────────────────────

async def test_get_retry_count_zero_for_new(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)
    count = await get_retry_count("txn-001")
    assert count == 0


async def test_get_retry_count_after_update(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    updated = tx.model_copy(update={"retry_count": 2, "updated_at": _now()})
    await update_transaction(updated)

    count = await get_retry_count("txn-001")
    assert count == 2


async def test_get_retry_count_nonexistent_returns_zero(db) -> None:
    count = await get_retry_count("no-such-txn")
    assert count == 0


# ── Schema CHECK constraints ──────────────────────────────────────────────────

async def test_schema_rejects_invalid_status(db) -> None:
    """The CHECK constraint on status must fire for unknown values."""
    from app.db.connection import get_connection
    conn = await get_connection()
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO transactions (transaction_id, failure_code, amount_paise, "
            "customer_id, occurred_at, created_at, updated_at, status, retry_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad-txn", "CODE", 100, "cust", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "NOT_A_STATUS", 0),
        )
        await conn.commit()


async def test_schema_rejects_negative_amount(db) -> None:
    from app.db.connection import get_connection
    conn = await get_connection()
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO transactions (transaction_id, failure_code, amount_paise, "
            "customer_id, occurred_at, created_at, updated_at, status, retry_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("neg-txn", "CODE", -1, "cust", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "FAILED", 0),
        )
        await conn.commit()


async def test_schema_rejects_retry_count_over_3(db) -> None:
    from app.db.connection import get_connection
    conn = await get_connection()
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO transactions (transaction_id, failure_code, amount_paise, "
            "customer_id, occurred_at, created_at, updated_at, status, retry_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("over-txn", "CODE", 100, "cust", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "FAILED", 4),
        )
        await conn.commit()
