"""
app/services/metrics_service.py
────────────────────────────────
Compute aggregate metrics from the database.

All metrics are derived from existing database records — no separate
counters or caches.  This keeps the metrics consistent with the audit log.

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

import logging

from app.db.connection import get_connection

logger = logging.getLogger(__name__)


async def compute_metrics() -> dict:
    """
    Return a metrics dictionary derived from the live database.

    Returns
    -------
    dict with the following keys:
      note, total_transactions, by_status (breakdown),
      by_failure_category, below_threshold_count,
      retry_attempts_total, retry_success, retry_failure,
      retry_timeout, recovered_amount_paise, recovered_amount_rupees,
      recovery_rate_pct, duplicate_events_rejected
    """
    conn = await get_connection()

    # Total transactions
    async with conn.execute("SELECT COUNT(*) FROM transactions") as cur:
        row = await cur.fetchone()
    total = int(row[0])

    # By status
    async with conn.execute(
        "SELECT status, COUNT(*) FROM transactions GROUP BY status"
    ) as cur:
        rows = await cur.fetchall()
    by_status = {r[0]: int(r[1]) for r in rows}

    # By failure category
    async with conn.execute(
        "SELECT failure_category, COUNT(*) FROM transactions "
        "WHERE failure_category IS NOT NULL GROUP BY failure_category"
    ) as cur:
        rows = await cur.fetchall()
    by_category = {r[0]: int(r[1]) for r in rows}

    # Below ₹100 (below 10,000 paise)
    async with conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE amount_paise < 10000"
    ) as cur:
        row = await cur.fetchone()
    below_threshold = int(row[0])

    # Retry attempts by outcome
    async with conn.execute(
        "SELECT outcome, COUNT(*) FROM retry_attempts "
        "WHERE outcome IS NOT NULL GROUP BY outcome"
    ) as cur:
        rows = await cur.fetchall()
    by_outcome = {r[0]: int(r[1]) for r in rows}

    # Recovered amount
    async with conn.execute(
        "SELECT COALESCE(SUM(t.amount_paise), 0) "
        "FROM transactions t WHERE t.status = 'RECOVERED'"
    ) as cur:
        row = await cur.fetchone()
    recovered_paise = int(row[0])

    # Duplicate events rejected (audit entries with DUPLICATE_EVENT_BLOCK rule)
    async with conn.execute(
        "SELECT COUNT(*) FROM audit_log "
        "WHERE policy_rule_applied = 'DUPLICATE_EVENT_BLOCK'"
    ) as cur:
        row = await cur.fetchone()
    duplicates_rejected = int(row[0])

    retry_success = by_outcome.get("SUCCESS", 0)
    retry_failure = by_outcome.get("FAILURE", 0)
    retry_timeout = by_outcome.get("TIMEOUT", 0)
    retry_total = retry_success + retry_failure + retry_timeout

    recovered_count = by_status.get("RECOVERED", 0)
    recovery_rate = (recovered_count / total * 100.0) if total > 0 else 0.0

    return {
        "note": "SYNTHETIC SIMULATION — NOT REAL-WORLD DATA",
        "total_transactions": total,
        "by_status": by_status,
        "by_failure_category": by_category,
        "below_threshold_count": below_threshold,
        "retry_attempts_total": retry_total,
        "retry_success": retry_success,
        "retry_failure": retry_failure,
        "retry_timeout": retry_timeout,
        "recovered_count": recovered_count,
        "recovered_amount_paise": recovered_paise,
        "recovered_amount_rupees": round(recovered_paise / 100.0, 2),
        "recovery_rate_pct": round(recovery_rate, 2),
        "duplicate_events_rejected": duplicates_rejected,
    }
