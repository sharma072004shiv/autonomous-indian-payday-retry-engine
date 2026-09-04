"""
tests/unit/test_db_audit.py
────────────────────────────
Tests for the audit log: append, retrieve, ordering, completeness,
and enforcement of the append-only contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import aiosqlite

from app.db.repo_audit import (
    append_audit_entry,
    count_audit_entries,
    get_audit_trail,
)
from app.db.repo_transactions import insert_transaction
from app.models.audit import AuditEntry
from app.models.enums import FailureCategory, RetryDecision, TransactionStatus
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


def _make_entry(
    audit_id: str = "aud-001",
    transaction_id: str = "txn-001",
    event_id: str = "evt-001",
    decision: RetryDecision = RetryDecision.APPROVE,
    failure_category: FailureCategory = FailureCategory.LIQUIDITY_TEMPORARY,
    policy_rule_applied: str = "APPROVE_LIQUIDITY_TEMPORARY",
    reason: str = "Funds likely to recover",
    llm_confidence: float | None = 0.91,
    llm_rationale: str | None = "BANK_RESP_51 indicates temporary insufficiency",
    retry_scheduled_at: datetime | None = None,
    retry_attempt_number: int = 1,
    decided_at: datetime | None = None,
) -> AuditEntry:
    return AuditEntry(
        audit_id=audit_id,
        transaction_id=transaction_id,
        event_id=event_id,
        decision=decision,
        failure_category=failure_category,
        policy_rule_applied=policy_rule_applied,
        reason=reason,
        llm_confidence=llm_confidence,
        llm_rationale=llm_rationale,
        retry_scheduled_at=retry_scheduled_at or (_now() + timedelta(hours=2)),
        retry_attempt_number=retry_attempt_number,
        decided_at=decided_at or _now(),
    )


# ── Append & retrieve ─────────────────────────────────────────────────────────

async def test_append_and_retrieve_single_entry(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    entry = _make_entry()
    await append_audit_entry(entry)

    trail = await get_audit_trail("txn-001")
    assert len(trail) == 1
    assert trail[0].audit_id == "aud-001"
    assert trail[0].decision == RetryDecision.APPROVE
    assert trail[0].failure_category == FailureCategory.LIQUIDITY_TEMPORARY


async def test_get_audit_trail_empty_returns_empty_list(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    trail = await get_audit_trail("txn-001")
    assert trail == []


async def test_get_audit_trail_nonexistent_transaction(db) -> None:
    trail = await get_audit_trail("no-such-txn")
    assert trail == []


async def test_all_fields_survive_roundtrip(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    scheduled = _now() + timedelta(hours=6)
    decided = _now()

    entry = AuditEntry(
        audit_id="aud-full",
        transaction_id="txn-001",
        event_id="evt-full",
        decision=RetryDecision.REJECT,
        failure_category=FailureCategory.HARD_DECLINE,
        policy_rule_applied="HARD_DECLINE_BLOCK",
        reason="Mandate expired — permanent failure",
        llm_confidence=0.99,
        llm_rationale="MANDATE_EXPIRED is an irrecoverable error",
        retry_scheduled_at=scheduled,
        retry_attempt_number=0,
        decided_at=decided,
    )
    await append_audit_entry(entry)

    trail = await get_audit_trail("txn-001")
    a = trail[0]

    assert a.audit_id == "aud-full"
    assert a.decision == RetryDecision.REJECT
    assert a.failure_category == FailureCategory.HARD_DECLINE
    assert a.policy_rule_applied == "HARD_DECLINE_BLOCK"
    assert a.reason == "Mandate expired — permanent failure"
    assert a.llm_confidence == pytest.approx(0.99)
    assert a.llm_rationale == "MANDATE_EXPIRED is an irrecoverable error"
    assert a.retry_attempt_number == 0
    # Datetime within 1 second
    assert abs((a.decided_at - decided).total_seconds()) < 1.0


async def test_null_optional_fields_roundtrip(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    entry = AuditEntry(
        audit_id="aud-null",
        transaction_id="txn-001",
        event_id="evt-null",
        decision=RetryDecision.REJECT,
        failure_category=FailureCategory.HARD_DECLINE,
        policy_rule_applied="HARD_DECLINE_BLOCK",
        reason="Hard decline",
        llm_confidence=None,
        llm_rationale=None,
        retry_scheduled_at=None,
        retry_attempt_number=0,
        decided_at=_now(),
    )
    await append_audit_entry(entry)

    trail = await get_audit_trail("txn-001")
    assert trail[0].llm_confidence is None
    assert trail[0].llm_rationale is None
    assert trail[0].retry_scheduled_at is None


# ── Ordering ──────────────────────────────────────────────────────────────────

async def test_audit_trail_ordered_by_decided_at(db) -> None:
    """get_audit_trail must return entries in ascending decided_at order."""
    tx = _make_tx()
    await insert_transaction(tx)

    base = _now()
    e1 = _make_entry("aud-t1", decided_at=base)
    e2 = _make_entry("aud-t2", decided_at=base + timedelta(seconds=10),
                     event_id="evt-002")
    e3 = _make_entry("aud-t3", decided_at=base + timedelta(seconds=20),
                     event_id="evt-003", decision=RetryDecision.REJECT,
                     failure_category=FailureCategory.HARD_DECLINE,
                     policy_rule_applied="HARD_DECLINE_BLOCK",
                     reason="Third attempt rejected")

    # Insert out of order deliberately
    await append_audit_entry(e3)
    await append_audit_entry(e1)
    await append_audit_entry(e2)

    trail = await get_audit_trail("txn-001")
    assert len(trail) == 3
    ids = [e.audit_id for e in trail]
    assert ids == ["aud-t1", "aud-t2", "aud-t3"]


# ── Multiple transactions isolation ──────────────────────────────────────────

async def test_audit_trails_are_isolated_per_transaction(db) -> None:
    tx1 = _make_tx("txn-A")
    tx2 = _make_tx("txn-B")
    await insert_transaction(tx1)
    await insert_transaction(tx2)

    e_a = _make_entry("aud-A", transaction_id="txn-A", event_id="evt-A")
    e_b = _make_entry("aud-B", transaction_id="txn-B", event_id="evt-B")
    await append_audit_entry(e_a)
    await append_audit_entry(e_b)

    trail_a = await get_audit_trail("txn-A")
    trail_b = await get_audit_trail("txn-B")

    assert len(trail_a) == 1
    assert trail_a[0].audit_id == "aud-A"
    assert len(trail_b) == 1
    assert trail_b[0].audit_id == "aud-B"


# ── count_audit_entries ───────────────────────────────────────────────────────

async def test_count_audit_entries_empty(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)
    assert await count_audit_entries("txn-001") == 0


async def test_count_audit_entries_after_appends(db) -> None:
    tx = _make_tx()
    await insert_transaction(tx)

    await append_audit_entry(_make_entry("aud-1", event_id="evt-1"))
    assert await count_audit_entries("txn-001") == 1

    await append_audit_entry(_make_entry("aud-2", event_id="evt-2"))
    assert await count_audit_entries("txn-001") == 2


# ── Append-only enforcement ───────────────────────────────────────────────────

async def test_duplicate_audit_id_raises(db) -> None:
    """Inserting the same audit_id twice must raise IntegrityError."""
    tx = _make_tx()
    await insert_transaction(tx)

    entry = _make_entry()
    await append_audit_entry(entry)

    with pytest.raises(aiosqlite.IntegrityError):
        await append_audit_entry(entry)


async def test_no_delete_path_in_repo_audit() -> None:
    """
    repo_audit must not expose a delete function.
    This is a static check — if someone adds a delete function
    it must be caught here.
    """
    import app.db.repo_audit as module
    assert not hasattr(module, "delete_audit_entry"), (
        "repo_audit must not expose a delete operation (append-only contract)"
    )


async def test_no_update_path_in_repo_audit() -> None:
    import app.db.repo_audit as module
    assert not hasattr(module, "update_audit_entry"), (
        "repo_audit must not expose an update operation (append-only contract)"
    )


# ── Audit record sufficiency ──────────────────────────────────────────────────

async def test_audit_entry_contains_all_decision_fields(db) -> None:
    """
    An audit entry must contain enough fields to reconstruct the decision:
    decision, failure_category, policy_rule_applied, reason, llm_confidence,
    llm_rationale, retry_attempt_number, decided_at.
    """
    tx = _make_tx()
    await insert_transaction(tx)

    entry = _make_entry(
        llm_confidence=0.87,
        llm_rationale="Temporary insufficiency detected",
        retry_attempt_number=2,
    )
    await append_audit_entry(entry)

    trail = await get_audit_trail("txn-001")
    a = trail[0]

    # Every field needed for a complete audit reconstruction must be present
    assert a.decision is not None
    assert a.failure_category is not None
    assert a.policy_rule_applied != ""
    assert a.reason != ""
    assert a.llm_confidence is not None
    assert a.llm_rationale is not None
    assert a.retry_attempt_number == 2
    assert a.decided_at is not None
