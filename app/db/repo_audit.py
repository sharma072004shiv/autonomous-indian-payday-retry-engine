"""
app/db/repo_audit.py
─────────────────────
Repository functions for the audit_log table.

The audit log is append-only.  This module exposes no UPDATE or DELETE
operations.  Any attempt to modify an existing entry must be rejected at
the application layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.db.connection import get_connection
from app.models.audit import AuditEntry
from app.models.enums import FailureCategory, RetryDecision

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


def _row_to_audit_entry(row: aiosqlite.Row) -> AuditEntry:
    return AuditEntry(
        audit_id=row["audit_id"],
        transaction_id=row["transaction_id"],
        event_id=row["event_id"],
        decision=RetryDecision(row["decision"]),
        failure_category=FailureCategory(row["failure_category"]),
        policy_rule_applied=row["policy_rule_applied"],
        reason=row["reason"],
        llm_confidence=row["llm_confidence"],
        llm_rationale=row["llm_rationale"],
        retry_scheduled_at=_str_to_dt(row["retry_scheduled_at"]),
        retry_attempt_number=row["retry_attempt_number"],
        decided_at=_str_to_dt(row["decided_at"]),
    )


# ── Repository functions ──────────────────────────────────────────────────────

async def append_audit_entry(entry: AuditEntry) -> None:
    """
    Insert a new audit log entry.

    Raises aiosqlite.IntegrityError if audit_id already exists (should never
    happen in practice since audit_ids are UUIDs).
    """
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO audit_log (
            audit_id, transaction_id, event_id,
            decision, failure_category, policy_rule_applied, reason,
            llm_confidence, llm_rationale,
            retry_scheduled_at, retry_attempt_number,
            decided_at
        ) VALUES (
            :audit_id, :transaction_id, :event_id,
            :decision, :failure_category, :policy_rule_applied, :reason,
            :llm_confidence, :llm_rationale,
            :retry_scheduled_at, :retry_attempt_number,
            :decided_at
        )
        """,
        {
            "audit_id": entry.audit_id,
            "transaction_id": entry.transaction_id,
            "event_id": entry.event_id,
            "decision": entry.decision.value,
            "failure_category": entry.failure_category.value,
            "policy_rule_applied": entry.policy_rule_applied,
            "reason": entry.reason,
            "llm_confidence": entry.llm_confidence,
            "llm_rationale": entry.llm_rationale,
            "retry_scheduled_at": _dt_to_str(entry.retry_scheduled_at),
            "retry_attempt_number": entry.retry_attempt_number,
            "decided_at": _dt_to_str(entry.decided_at),
        },
    )
    await conn.commit()
    logger.debug(
        "Appended audit entry %s for transaction %s (decision=%s)",
        entry.audit_id,
        entry.transaction_id,
        entry.decision.value,
    )


async def get_audit_trail(transaction_id: str) -> list[AuditEntry]:
    """
    Return all audit entries for a transaction, ordered by decided_at ascending.

    Returns an empty list if the transaction has no audit entries.
    """
    conn = await get_connection()
    async with conn.execute(
        """
        SELECT * FROM audit_log
        WHERE  transaction_id = ?
        ORDER BY decided_at ASC
        """,
        (transaction_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    return [_row_to_audit_entry(row) for row in rows]


async def count_audit_entries(transaction_id: str) -> int:
    """Return the number of audit entries for a given transaction."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE transaction_id = ?",
        (transaction_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0
