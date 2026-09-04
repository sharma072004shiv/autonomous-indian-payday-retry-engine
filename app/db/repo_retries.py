"""
app/db/repo_retries.py
───────────────────────
Repository functions for idempotency and retry-attempt tracking.

Two responsibilities:
  1. Idempotency guard — processed_events table.
     Uses INSERT OR IGNORE so that the database-level UNIQUE constraint
     on event_id is the atomic check.  Returns whether the row was newly
     inserted (i.e., the event had NOT been seen before).

  2. Retry attempt history — retry_attempts table.
     Records each retry attempt with scheduling and execution metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.db.connection import get_connection
from app.models.enums import ExecutionOutcome

logger = logging.getLogger(__name__)


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Idempotency — processed_events ───────────────────────────────────────────

async def try_claim_event(event_id: str, transaction_id: str) -> bool:
    """
    Atomically claim an event_id for processing.

    Uses INSERT OR IGNORE against the UNIQUE primary-key constraint on
    processed_events.event_id.  This is safe under concurrent requests
    because SQLite serialises all writes.

    Returns
    -------
    True  — the event was not previously seen; the caller should proceed.
    False — the event was already processed; the caller must not retry.

    This replaces the two-step event_already_processed / mark_event_processed
    pattern with a single atomic operation, eliminating the TOCTOU race.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        """
        INSERT OR IGNORE INTO processed_events (event_id, transaction_id, received_at)
        VALUES (?, ?, ?)
        """,
        (event_id, transaction_id, _dt_to_str(datetime.now(timezone.utc))),
    )
    await conn.commit()

    # rowcount == 1 means the INSERT succeeded (event is new).
    # rowcount == 0 means the IGNORE fired (event was already present).
    is_new = cursor.rowcount == 1
    if not is_new:
        logger.warning(
            "Duplicate event rejected: event_id=%s transaction_id=%s",
            event_id,
            transaction_id,
        )
    return is_new


async def event_already_processed(event_id: str) -> bool:
    """
    Check (read-only) whether an event_id has been processed.

    Prefer try_claim_event() for the actual ingestion path because it is
    atomic.  Use this for read-only checks (e.g., diagnostic endpoints).
    """
    conn = await get_connection()
    async with conn.execute(
        "SELECT 1 FROM processed_events WHERE event_id = ?",
        (event_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def mark_event_processed(event_id: str, transaction_id: str) -> None:
    """
    Unconditionally record an event as processed.

    This is a non-atomic fallback for code paths that have already verified
    the event is new.  Prefer try_claim_event() in the ingestion path.
    Raises aiosqlite.IntegrityError on duplicate event_id.
    """
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO processed_events (event_id, transaction_id, received_at)
        VALUES (?, ?, ?)
        """,
        (event_id, transaction_id, _dt_to_str(datetime.now(timezone.utc))),
    )
    await conn.commit()


# ── Retry attempt history ─────────────────────────────────────────────────────

async def insert_retry_attempt(
    attempt_id: str,
    transaction_id: str,
    event_id: str,
    attempt_number: int,
    scheduled_at: datetime,
) -> None:
    """
    Record that a retry has been scheduled.

    executed_at and outcome are NULL until the attempt fires.
    """
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO retry_attempts (
            attempt_id, transaction_id, event_id, attempt_number,
            scheduled_at, executed_at, outcome, failure_code_at_retry,
            diagnosis, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?)
        """,
        (
            attempt_id,
            transaction_id,
            event_id,
            attempt_number,
            _dt_to_str(scheduled_at),
            _dt_to_str(datetime.now(timezone.utc)),
        ),
    )
    await conn.commit()
    logger.debug(
        "Recorded retry attempt %s for transaction %s (attempt #%d)",
        attempt_id, transaction_id, attempt_number,
    )


async def update_retry_attempt(
    attempt_id: str,
    executed_at: datetime,
    outcome: ExecutionOutcome,
    failure_code_at_retry: Optional[str] = None,
    diagnosis: Optional[str] = None,
) -> None:
    """
    Update a retry attempt row with the execution result.

    Called by the mock executor after the simulated payment call completes.
    """
    conn = await get_connection()
    cursor = await conn.execute(
        """
        UPDATE retry_attempts SET
            executed_at          = ?,
            outcome              = ?,
            failure_code_at_retry = ?,
            diagnosis            = ?
        WHERE attempt_id = ?
        """,
        (
            _dt_to_str(executed_at),
            outcome.value,
            failure_code_at_retry,
            diagnosis,
            attempt_id,
        ),
    )
    await conn.commit()

    if cursor.rowcount == 0:
        raise ValueError(
            f"update_retry_attempt: attempt_id '{attempt_id}' not found"
        )
    logger.debug("Updated retry attempt %s (outcome=%s)", attempt_id, outcome.value)


async def get_retry_attempts(transaction_id: str) -> list[dict]:
    """
    Return all retry attempt rows for a transaction as plain dicts.

    Ordered by attempt_number ascending.
    """
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT attempt_id, transaction_id, event_id, attempt_number,
               scheduled_at, executed_at, outcome,
               failure_code_at_retry, diagnosis, created_at
        FROM   retry_attempts
        WHERE  transaction_id = ?
        ORDER BY attempt_number ASC
        """,
        (transaction_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def count_retry_attempts(transaction_id: str) -> int:
    """Return how many retry attempts have been recorded for a transaction."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT COUNT(*) FROM retry_attempts WHERE transaction_id = ?",
        (transaction_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0
