"""
app/services/retry_service.py
──────────────────────────────
Main orchestration service for the retry engine.

Flow for each incoming FailureEvent:
  1. Atomic idempotency claim  → reject duplicates
  2. LLM classify failure      → read-only; safe fallback on error
  3. Policy evaluation         → deterministic guardrails decide
  4. If approved: insert/update Transaction, schedule retry attempt
  5. Write immutable AuditEntry

This service has NO payment execution authority.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.db.repo_audit import append_audit_entry
from app.db.repo_retries import insert_retry_attempt, try_claim_event
from app.db.repo_transactions import (
    get_transaction,
    insert_transaction,
    update_transaction,
)
from app.llm.classifier import LLMClassificationError, classify_failure
from app.models.audit import AuditEntry
from app.models.enums import FailureCategory, RetryDecision, TransactionStatus
from app.models.transaction import FailureEvent, Transaction
from app.policy.engine import evaluate

logger = logging.getLogger(__name__)


async def handle_failure_event(
    event: FailureEvent,
    salary_credit_day: Optional[int] = None,
    historical_surge_hour_ist: Optional[int] = None,
) -> AuditEntry:
    """
    Process a single payment failure event end-to-end.

    Parameters
    ----------
    event : FailureEvent
        Validated incoming webhook payload.
    salary_credit_day : Optional[int]
        Day of month for salary credit (used for LIQUIDITY_TEMPORARY timing).
    historical_surge_hour_ist : Optional[int]
        IST hour of historical bank surge (for BANK_SURGE_TEMPORARY).

    Returns
    -------
    AuditEntry
        The decision written to the audit log for this event.
    """
    now = datetime.now(timezone.utc)

    # ── Step 1: Ensure transaction record exists FIRST ───────────────────
    # (Must come before try_claim_event because processed_events has FK to transactions)
    existing = await get_transaction(event.transaction_id)
    if existing is None:
        tx = Transaction(
            transaction_id=event.transaction_id,
            failure_code=event.failure_code,
            amount_paise=event.amount_paise,
            customer_id=event.customer_id,
            mandate_id=event.mandate_id,
            occurred_at=event.occurred_at,
            created_at=now,
            updated_at=now,
            status=TransactionStatus.FAILED,
        )
        await insert_transaction(tx)
        retry_count = 0
    else:
        tx = existing
        retry_count = tx.retry_count

    # ── Step 2: Atomic idempotency claim ─────────────────────────────────
    is_new = await try_claim_event(event.event_id, event.transaction_id)
    if not is_new:
        logger.warning("Duplicate event rejected: event_id=%s", event.event_id)
        return _make_duplicate_audit(event, now)

    # ── Step 3: LLM classification ────────────────────────────────────────
    # classify_failure() handles its own fallback to the mock classifier
    # when the real LLM is unavailable. It only raises LLMClassificationError
    # in genuinely unrecoverable situations. We catch it here as a last resort
    # and use the mock classifier directly rather than blanket HARD_DECLINE.
    try:
        llm_result = await classify_failure(event.failure_code)
    except LLMClassificationError as exc:
        logger.error(
            "LLM classification completely failed for %s: %s — "
            "using mock classifier as final fallback",
            event.failure_code,
            exc,
        )
        from app.llm.mock_classifier import mock_classify_failure
        llm_result = mock_classify_failure(event.failure_code)

    # ── Step 4: Deterministic policy evaluation ───────────────────────────
    decision = evaluate(
        transaction_id=event.transaction_id,
        event_id=event.event_id,
        llm_result=llm_result,
        amount_paise=event.amount_paise,
        retry_count=retry_count,
        already_processed=False,  # already verified new above
        salary_credit_day=salary_credit_day,
        historical_surge_hour_ist=historical_surge_hour_ist,
        as_of=now,
    )

    # ── Step 5: Persist retry schedule if approved ────────────────────────
    if decision.retry_allowed:
        updated_tx = tx.model_copy(update={
            "status": TransactionStatus.RETRY_SCHEDULED,
            "failure_category": decision.failure_category,
            "llm_confidence": decision.llm_confidence,
            "retry_count": retry_count,      # count increments on execution, not schedule
            "next_retry_at": decision.scheduled_at,
            "updated_at": now,
        })
        await update_transaction(updated_tx)

        attempt_id = str(uuid.uuid4())
        await insert_retry_attempt(
            attempt_id=attempt_id,
            transaction_id=event.transaction_id,
            event_id=event.event_id,
            attempt_number=decision.retry_number,
            scheduled_at=decision.scheduled_at,
        )
    else:
        # Permanently failed if not approvable
        new_status = (
            TransactionStatus.PERMANENTLY_FAILED
            if retry_count >= 3 or decision.failure_category == FailureCategory.HARD_DECLINE
            else TransactionStatus.FAILED
        )
        updated_tx = tx.model_copy(update={
            "status": new_status,
            "failure_category": decision.failure_category,
            "llm_confidence": decision.llm_confidence,
            "updated_at": now,
        })
        await update_transaction(updated_tx)

    # ── Step 6: Write immutable audit entry ───────────────────────────────
    audit = AuditEntry(
        audit_id=str(uuid.uuid4()),
        transaction_id=event.transaction_id,
        event_id=event.event_id,
        decision=decision.decision,
        failure_category=decision.failure_category,
        policy_rule_applied=decision.policy_rule,
        reason=decision.reason,
        llm_confidence=decision.llm_confidence,
        llm_rationale=decision.llm_rationale,
        retry_scheduled_at=decision.scheduled_at,
        retry_attempt_number=decision.retry_number,
        decided_at=now,
    )
    await append_audit_entry(audit)

    logger.info(
        "handle_failure_event done: txn=%s decision=%s rule=%s",
        event.transaction_id,
        decision.decision.value,
        decision.policy_rule,
    )
    return audit


def _make_duplicate_audit(event: FailureEvent, now: datetime) -> AuditEntry:
    """Return an in-memory AuditEntry representing a duplicate rejection."""
    return AuditEntry(
        audit_id=str(uuid.uuid4()),
        transaction_id=event.transaction_id,
        event_id=event.event_id,
        decision=RetryDecision.REJECT,
        failure_category=FailureCategory.HARD_DECLINE,
        policy_rule_applied="DUPLICATE_EVENT_BLOCK",
        reason=(
            "Duplicate webhook event rejected. "
            "This event_id has already been processed."
        ),
        llm_confidence=None,
        llm_rationale=None,
        retry_scheduled_at=None,
        retry_attempt_number=0,
        decided_at=now,
    )
