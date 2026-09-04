"""
tests/unit/test_db_idempotency.py
──────────────────────────────────
Tests for webhook idempotency: processed_events table, try_claim_event,
duplicate rejection, and concurrent-safe claim behaviour.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import aiosqlite

from app.db.repo_retries import (
    count_retry_attempts,
    event_already_processed,
    get_retry_attempts,
    insert_retry_attempt,
    mark_event_processed,
    try_claim_event,
    update_retry_attempt,
)
from app.db.repo_transactions import insert_transaction
from app.models.enums import ExecutionOutcome, TransactionStatus
from app.models.transaction import Transaction


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_tx(transaction_id: str = "txn-001") -> Transaction:
    now = _now()
    return Transaction(
        transaction_id=transaction_id,
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=50_000,
        customer_id="cust-001",
        occurred_at=now,
        created_at=now,
        updated_at=now,
    )


# ── try_claim_event ───────────────────────────────────────────────────────────

async def test_claim_new_event_returns_true(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    is_new = await try_claim_event("evt-001", "txn-001")
    assert is_new is True


async def test_claim_duplicate_event_returns_false(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await try_claim_event("evt-001", "txn-001")
    is_new = await try_claim_event("evt-001", "txn-001")
    assert is_new is False


async def test_claim_same_event_id_different_transaction(db) -> None:
    """Same event_id must be rejected even for a different transaction_id."""
    tx1 = _make_tx("txn-001")
    tx2 = _make_tx("txn-002")
    await insert_transaction(tx1)
    await insert_transaction(tx2)

    await try_claim_event("evt-shared", "txn-001")
    is_new = await try_claim_event("evt-shared", "txn-002")
    assert is_new is False


async def test_claim_different_event_ids_both_succeed(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    first = await try_claim_event("evt-A", "txn-001")
    second = await try_claim_event("evt-B", "txn-001")
    assert first is True
    assert second is True


# ── event_already_processed ───────────────────────────────────────────────────

async def test_event_not_processed_initially(db) -> None:
    result = await event_already_processed("evt-unknown")
    assert result is False


async def test_event_processed_after_claim(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await try_claim_event("evt-001", "txn-001")
    result = await event_already_processed("evt-001")
    assert result is True


async def test_event_processed_after_mark(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await mark_event_processed("evt-mk-001", "txn-001")
    result = await event_already_processed("evt-mk-001")
    assert result is True


# ── mark_event_processed ──────────────────────────────────────────────────────

async def test_mark_duplicate_raises_integrity_error(db) -> None:
    """mark_event_processed must not silently swallow duplicates."""
    tx = _make_tx()
    await insert_transaction(tx)

    await mark_event_processed("evt-dup", "txn-001")
    with pytest.raises(aiosqlite.IntegrityError):
        await mark_event_processed("evt-dup", "txn-001")


# ── Database UNIQUE constraint ────────────────────────────────────────────────

async def test_unique_constraint_on_event_id(db) -> None:
    """The UNIQUE constraint on processed_events.event_id must be enforced."""
    from app.db.connection import get_connection
    conn = await get_connection()
    now_str = _now().isoformat()

    tx = _make_tx()
    await insert_transaction(tx)

    await conn.execute(
        "INSERT INTO processed_events (event_id, transaction_id, received_at) "
        "VALUES (?, ?, ?)",
        ("evt-unique-test", "txn-001", now_str),
    )
    await conn.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO processed_events (event_id, transaction_id, received_at) "
            "VALUES (?, ?, ?)",
            ("evt-unique-test", "txn-001", now_str),
        )
        await conn.commit()


# ── Concurrent duplicate handling ─────────────────────────────────────────────

async def test_concurrent_claims_exactly_one_wins(db) -> None:
    """
    Simulate two coroutines racing to claim the same event_id.

    Because aiosqlite serialises writes through a single background thread,
    exactly one INSERT succeeds and the other is ignored.  The sum of
    True results must equal 1.
    """
    tx = _make_tx()
    await insert_transaction(tx)

    results = await asyncio.gather(
        try_claim_event("evt-race", "txn-001"),
        try_claim_event("evt-race", "txn-001"),
        try_claim_event("evt-race", "txn-001"),
    )
    # Exactly one coroutine must have won the race
    assert sum(results) == 1


async def test_concurrent_different_events_all_win(db) -> None:
    """Different event_ids do not conflict; all should succeed."""
    tx = _make_tx()
    await insert_transaction(tx)

    results = await asyncio.gather(
        try_claim_event("evt-1", "txn-001"),
        try_claim_event("evt-2", "txn-001"),
        try_claim_event("evt-3", "txn-001"),
    )
    assert all(results)


# ── Retry attempts ────────────────────────────────────────────────────────────

async def test_insert_retry_attempt(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await insert_retry_attempt(
        attempt_id="att-001",
        transaction_id="txn-001",
        event_id="evt-001",
        attempt_number=1,
        scheduled_at=_now(),
    )

    attempts = await get_retry_attempts("txn-001")
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == "att-001"
    assert attempts[0]["attempt_number"] == 1
    assert attempts[0]["outcome"] is None  # not yet executed


async def test_update_retry_attempt_outcome(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await insert_retry_attempt(
        attempt_id="att-001",
        transaction_id="txn-001",
        event_id="evt-001",
        attempt_number=1,
        scheduled_at=_now(),
    )

    executed_at = _now()
    await update_retry_attempt(
        attempt_id="att-001",
        executed_at=executed_at,
        outcome=ExecutionOutcome.SUCCESS,
        diagnosis="Mock payment succeeded",
    )

    attempts = await get_retry_attempts("txn-001")
    assert attempts[0]["outcome"] == "SUCCESS"
    assert attempts[0]["diagnosis"] == "Mock payment succeeded"


async def test_update_nonexistent_attempt_raises(db) -> None:
    with pytest.raises(ValueError, match="not found"):
        await update_retry_attempt(
            attempt_id="no-such-attempt",
            executed_at=_now(),
            outcome=ExecutionOutcome.FAILURE,
        )


async def test_count_retry_attempts(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    assert await count_retry_attempts("txn-001") == 0

    await insert_retry_attempt("att-001", "txn-001", "evt-001", 1, _now())
    assert await count_retry_attempts("txn-001") == 1

    await insert_retry_attempt("att-002", "txn-001", "evt-002", 2, _now())
    assert await count_retry_attempts("txn-001") == 2


async def test_retry_attempts_ordered_by_number(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    # Insert in reverse order to verify ordering
    await insert_retry_attempt("att-003", "txn-001", "evt-003", 3, _now())
    await insert_retry_attempt("att-001", "txn-001", "evt-001", 1, _now())
    await insert_retry_attempt("att-002", "txn-001", "evt-002", 2, _now())

    attempts = await get_retry_attempts("txn-001")
    numbers = [a["attempt_number"] for a in attempts]
    assert numbers == [1, 2, 3]


async def test_schema_rejects_attempt_number_zero(db) -> None:
    """attempt_number CHECK constraint: must be >= 1."""
    tx = _make_tx()
    await insert_transaction(tx)

    from app.db.connection import get_connection
    conn = await get_connection()
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO retry_attempts "
            "(attempt_id, transaction_id, event_id, attempt_number, "
            " scheduled_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("bad-att", "txn-001", "evt-001", 0,
             _now().isoformat(), _now().isoformat()),
        )
        await conn.commit()


async def test_schema_rejects_attempt_number_four(db) -> None:
    """attempt_number CHECK constraint: must be <= 3."""
    tx = _make_tx()
    await insert_transaction(tx)

    from app.db.connection import get_connection
    conn = await get_connection()
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO retry_attempts "
            "(attempt_id, transaction_id, event_id, attempt_number, "
            " scheduled_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("bad-att4", "txn-001", "evt-001", 4,
             _now().isoformat(), _now().isoformat()),
        )
        await conn.commit()
