"""
app/services/audit_service.py
──────────────────────────────
Service layer for the audit log.

Wraps repo_audit so that no other module imports from app.db directly.
"""

from __future__ import annotations

import logging

from app.db.repo_audit import (
    append_audit_entry,
    count_audit_entries,
    get_audit_trail,
)
from app.models.audit import AuditEntry

logger = logging.getLogger(__name__)


async def record_decision(entry: AuditEntry) -> None:
    """Persist an audit entry. Delegates to repo_audit.append_audit_entry."""
    await append_audit_entry(entry)
    logger.debug(
        "Audit recorded: audit_id=%s txn=%s decision=%s rule=%s",
        entry.audit_id,
        entry.transaction_id,
        entry.decision.value,
        entry.policy_rule_applied,
    )


async def fetch_audit_trail(transaction_id: str) -> list[AuditEntry]:
    """Return all audit entries for a transaction, ordered by decided_at."""
    return await get_audit_trail(transaction_id)


async def count_decisions(transaction_id: str) -> int:
    """Return the number of audit entries for a transaction."""
    return await count_audit_entries(transaction_id)
