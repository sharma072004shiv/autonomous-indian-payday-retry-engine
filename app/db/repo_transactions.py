"""
app/db/repo_transactions.py
────────────────────────────
Repository functions for the transactions table.

Serialisation contract:
  - Datetimes are stored as ISO-8601 strings (UTC) and parsed back on read.
  - Enum fields are stored as their string values; converted back on read.
  - Optional fields stored as NULL map to None in the Pydantic model.

No raw SQL appears outside this module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.db.connection import get_connection
from app.models.enums import FailureCategory, TransactionStatus
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    """Convert a datetime to a UTC ISO-8601 string, or None."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse a UTC ISO-8601 string back to an aware datetime, or None."""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_transaction(row: aiosqlite.Row) -> Transaction:
    """Convert a database row to a Transaction model."""
    return Transaction(
        transaction_id=row["transaction_id"],
        failure_code=row["failure_code"],
        amount_paise=row["amount_paise"],
        customer_id=row["customer_id"],
        mandate_id=row["mandate_id"],
        occurred_at=_str_to_dt(row["occurred_at"]),
        created_at=_str_to_dt(row["created_at"]),
        updated_at=_str_to_dt(row["updated_at"]),
        status=TransactionStatus(row["status"]),
        failure_category=(
            FailureCategory(row["failure_category"])
            if row["failure_category"] is not None
            else None
        ),
        llm_confidence=row["llm_confidence"],
        retry_count=row["retry_count"],
        next_retry_at=_str_to_dt(row["next_retry_at"]),
        last_retry_at=_str_to_dt(row["last_retry_at"]),
    )


# ── Repository functions ──────────────────────────────────────────────────────

async def insert_transaction(tx: Transaction) -> None:
    """
    Insert a new transaction row.

    Raises aiosqlite.IntegrityError if transaction_id already exists.
    """
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO transactions (
            transaction_id, failure_code, amount_paise, customer_id, mandate_id,
            occurred_at, created_at, updated_at,
            status, failure_category, llm_confidence,
            retry_count, next_retry_at, last_retry_at
        ) VALUES (
            :transaction_id, :failure_code, :amount_paise, :customer_id, :mandate_id,
            :occurred_at, :created_at, :updated_at,
            :status, :failure_category, :llm_confidence,
            :retry_count, :next_retry_at, :last_retry_at
        )
        """,
        {
            "transaction_id": tx.transaction_id,
            "failure_code": tx.failure_code,
            "amount_paise": tx.amount_paise,
            "customer_id": tx.customer_id,
            "mandate_id": tx.mandate_id,
            "occurred_at": _dt_to_str(tx.occurred_at),
            "created_at": _dt_to_str(tx.created_at),
            "updated_at": _dt_to_str(tx.updated_at),
            "status": tx.status.value,
            "failure_category": tx.failure_category.value if tx.failure_category else None,
            "llm_confidence": tx.llm_confidence,
            "retry_count": tx.retry_count,
            "next_retry_at": _dt_to_str(tx.next_retry_at),
            "last_retry_at": _dt_to_str(tx.last_retry_at),
        },
    )
    await conn.commit()
    logger.debug("Inserted transaction %s", tx.transaction_id)


async def get_transaction(transaction_id: str) -> Optional[Transaction]:
    """
    Return the Transaction with the given ID, or None if not found.
    """
    conn = await get_connection()
    async with conn.execute(
        "SELECT * FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return None
    return _row_to_transaction(row)


async def update_transaction(tx: Transaction) -> None:
    """
    Overwrite all mutable fields of an existing transaction row.

    Raises ValueError if the transaction_id does not exist in the database.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        """
        UPDATE transactions SET
            failure_code        = :failure_code,
            amount_paise        = :amount_paise,
            customer_id         = :customer_id,
            mandate_id          = :mandate_id,
            occurred_at         = :occurred_at,
            updated_at          = :updated_at,
            status              = :status,
            failure_category    = :failure_category,
            llm_confidence      = :llm_confidence,
            retry_count         = :retry_count,
            next_retry_at       = :next_retry_at,
            last_retry_at       = :last_retry_at
        WHERE transaction_id = :transaction_id
        """,
        {
            "transaction_id": tx.transaction_id,
            "failure_code": tx.failure_code,
            "amount_paise": tx.amount_paise,
            "customer_id": tx.customer_id,
            "mandate_id": tx.mandate_id,
            "occurred_at": _dt_to_str(tx.occurred_at),
            "updated_at": _dt_to_str(tx.updated_at),
            "status": tx.status.value,
            "failure_category": tx.failure_category.value if tx.failure_category else None,
            "llm_confidence": tx.llm_confidence,
            "retry_count": tx.retry_count,
            "next_retry_at": _dt_to_str(tx.next_retry_at),
            "last_retry_at": _dt_to_str(tx.last_retry_at),
        },
    )
    await conn.commit()

    if cursor.rowcount == 0:
        raise ValueError(
            f"update_transaction: transaction_id '{tx.transaction_id}' not found"
        )
    logger.debug("Updated transaction %s (status=%s)", tx.transaction_id, tx.status.value)


async def list_due_retries(as_of: Optional[datetime] = None) -> list[Transaction]:
    """
    Return all transactions with status=RETRY_SCHEDULED and
    next_retry_at <= as_of (defaults to now UTC).

    The scheduler calls this to find retries that are ready to fire.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    conn = await get_connection()
    async with conn.execute(
        """
        SELECT * FROM transactions
        WHERE  status = 'RETRY_SCHEDULED'
        AND    next_retry_at IS NOT NULL
        AND    next_retry_at <= ?
        ORDER BY next_retry_at ASC
        """,
        (_dt_to_str(as_of),),
    ) as cursor:
        rows = await cursor.fetchall()

    return [_row_to_transaction(row) for row in rows]


async def get_retry_count(transaction_id: str) -> int:
    """
    Return the current retry_count for a transaction.

    Returns 0 if the transaction does not exist (safe default for callers
    that have not yet inserted the row).
    """
    conn = await get_connection()
    async with conn.execute(
        "SELECT retry_count FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return 0
    return int(row["retry_count"])
