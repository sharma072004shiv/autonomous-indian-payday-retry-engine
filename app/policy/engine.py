"""
app/policy/engine.py
─────────────────────
Deterministic policy engine — the central trust-boundary enforcer.

This is the MOST IMPORTANT component in the system.

Responsibility
──────────────
Given a classified failure event, decide whether a retry is allowed,
when it should fire, and produce an auditable RetryPolicyDecision.

The policy engine:
  ✅ DOES:  apply all AGENTS.md safety rules deterministically
  ✅ DOES:  use LLM output as READ-ONLY input (failure_category + confidence)
  ✅ DOES:  call the timing predictor for smart retry windows
  ✅ DOES:  produce a fully auditable RetryPolicyDecision

  ❌ NEVER: execute payments
  ❌ NEVER: call Razorpay or any payment API
  ❌ NEVER: allow the LLM to override safety rules
  ❌ NEVER: write to the database (that is the service layer's job)
  ❌ NEVER: schedule retries directly (that is the scheduler's job)

Evaluation order
────────────────
  1. Duplicate event check          → DUPLICATE_EVENT_BLOCK
  2. Hard-decline check             → HARD_DECLINE_BLOCK
  3. Minimum amount check           → MIN_AMOUNT_BLOCK
  4. Maximum retry count check      → MAX_RETRIES_BLOCK
  5. All checks passed              → calculate retry time → APPROVE
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.models.enums import FailureCategory, RetryDecision
from app.models.llm_output import LLMClassificationResult
from app.models.policy import RetryPolicyDecision
from app.policy.guardrails import run_all_guardrails
from app.policy.retry_rules import calculate_next_retry_at

logger = logging.getLogger(__name__)


def evaluate(
    transaction_id: str,
    event_id: str,
    llm_result: LLMClassificationResult,
    amount_paise: int,
    retry_count: int,
    already_processed: bool = False,
    salary_credit_day: Optional[int] = None,
    historical_surge_hour_ist: Optional[int] = None,
    as_of: Optional[datetime] = None,
) -> RetryPolicyDecision:
    """
    Evaluate whether a retry should be approved for a failed transaction.

    This function is the single authoritative entry point for all retry
    decisions.  It is deterministic: same inputs always produce the same
    output.

    Parameters
    ----------
    transaction_id : str
        ID of the transaction being evaluated.
    event_id : str
        ID of the failure event (used for idempotency tracking).
    llm_result : LLMClassificationResult
        Output of the LLM classifier.  The policy engine reads
        llm_result.safe_category (which falls back to HARD_DECLINE on
        low confidence) — never llm_result.failure_category directly.
    amount_paise : int
        Transaction amount in paise.
    retry_count : int
        Number of retry attempts already made.
    already_processed : bool
        True if this event_id has already been processed (duplicate check).
    salary_credit_day : Optional[int]
        Day of month for salary credit (used for LIQUIDITY_TEMPORARY timing).
    historical_surge_hour_ist : Optional[int]
        IST hour of known surge (used for BANK_SURGE_TEMPORARY timing).
    as_of : Optional[datetime]
        Reference time for scheduling.  Defaults to now UTC.

    Returns
    -------
    RetryPolicyDecision
        Fully populated, Pydantic-validated decision object.
        retry_allowed=True  → caller should schedule retry at scheduled_at.
        retry_allowed=False → caller should mark transaction as PERMANENTLY_FAILED
                              (if MAX_RETRIES or HARD_DECLINE) or simply not process.
    """
    settings = get_settings()
    now = as_of or datetime.now(timezone.utc)

    # ── CRITICAL: use safe_category, never failure_category directly ──────
    # safe_category returns HARD_DECLINE if confidence < 0.5.
    # This ensures low-confidence LLM outputs are treated conservatively.
    category: FailureCategory = llm_result.safe_category

    logger.info(
        "Policy engine evaluating: txn=%s event=%s category=%s "
        "amount_paise=%d retry_count=%d",
        transaction_id,
        event_id,
        category.value,
        amount_paise,
        retry_count,
    )

    # ── Run all guardrails ────────────────────────────────────────────────
    allowed, reason, policy_rule = run_all_guardrails(
        category=category,
        amount_paise=amount_paise,
        retry_count=retry_count,
        already_processed=already_processed,
        max_retries=settings.policy_max_retries,
        min_amount_paise=settings.policy_min_amount_paise,
    )

    if not allowed:
        logger.info(
            "Policy REJECTED txn=%s rule=%s reason=%s",
            transaction_id,
            policy_rule,
            reason,
        )
        return RetryPolicyDecision(
            transaction_id=transaction_id,
            event_id=event_id,
            retry_allowed=False,
            decision=RetryDecision.REJECT,
            scheduled_at=None,
            retry_number=0,
            policy_rule=policy_rule,
            reason=reason,
            failure_category=category,
            llm_confidence=llm_result.confidence,
            llm_rationale=llm_result.rationale,
        )

    # ── All guardrails passed — calculate retry schedule ──────────────────
    attempt_number = retry_count + 1  # next attempt is one more than current count

    try:
        scheduled_at = calculate_next_retry_at(
            category=category,
            attempt_number=attempt_number,
            from_time=now,
            salary_credit_day=salary_credit_day,
            historical_surge_hour_ist=historical_surge_hour_ist,
        )
    except Exception as exc:
        # Defensive: if timing calculation fails, reject rather than crash.
        logger.error(
            "Timing calculation failed for txn=%s: %s — rejecting retry",
            transaction_id,
            exc,
        )
        return RetryPolicyDecision(
            transaction_id=transaction_id,
            event_id=event_id,
            retry_allowed=False,
            decision=RetryDecision.REJECT,
            scheduled_at=None,
            retry_number=0,
            policy_rule="TIMING_ERROR_BLOCK",
            reason=f"Retry timing calculation failed: {exc}",
            failure_category=category,
            llm_confidence=llm_result.confidence,
            llm_rationale=llm_result.rationale,
        )

    logger.info(
        "Policy APPROVED txn=%s rule=%s attempt=%d scheduled_at=%s",
        transaction_id,
        policy_rule,
        attempt_number,
        scheduled_at.isoformat(),
    )

    return RetryPolicyDecision(
        transaction_id=transaction_id,
        event_id=event_id,
        retry_allowed=True,
        decision=RetryDecision.APPROVE,
        scheduled_at=scheduled_at,
        retry_number=attempt_number,
        policy_rule=policy_rule,
        reason=reason,
        failure_category=category,
        llm_confidence=llm_result.confidence,
        llm_rationale=llm_result.rationale,
    )
