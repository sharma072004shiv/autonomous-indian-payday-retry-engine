"""
tests/unit/test_policy_schema.py
──────────────────────────────────
Unit tests for RetryPolicyDecision and FailedTransactionEvent schemas.
Validates the trust-boundary invariants baked into the models.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import FailureCategory, RetryDecision
from app.models.policy import FailedTransactionEvent, RetryPolicyDecision


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _future() -> datetime:
    from datetime import timedelta
    return datetime.now(tz=timezone.utc) + timedelta(hours=2)


# ── RetryPolicyDecision — approved ────────────────────────────────────────────

def test_approved_decision_valid() -> None:
    d = RetryPolicyDecision(
        transaction_id="txn-001",
        event_id="evt-001",
        retry_allowed=True,
        decision=RetryDecision.APPROVE,
        scheduled_at=_future(),
        retry_number=1,
        policy_rule="APPROVE_LIQUIDITY_TEMPORARY",
        reason="Temporary liquidity shortfall; retry after payday",
        failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        llm_confidence=0.92,
        llm_rationale="BANK_RESP_51 indicates payday gap",
    )
    assert d.retry_allowed is True
    assert d.retry_number == 1
    assert d.scheduled_at is not None


def test_approved_decision_missing_scheduled_at_raises() -> None:
    with pytest.raises(ValidationError, match="scheduled_at must be set"):
        RetryPolicyDecision(
            transaction_id="txn-001",
            event_id="evt-001",
            retry_allowed=True,
            decision=RetryDecision.APPROVE,
            scheduled_at=None,   # invalid — must be set when approved
            retry_number=1,
            policy_rule="APPROVE_LIQUIDITY_TEMPORARY",
            reason="Retry approved",
            failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        )


def test_approved_decision_zero_retry_number_raises() -> None:
    with pytest.raises(ValidationError, match="retry_number must be >= 1"):
        RetryPolicyDecision(
            transaction_id="txn-001",
            event_id="evt-001",
            retry_allowed=True,
            decision=RetryDecision.APPROVE,
            scheduled_at=_future(),
            retry_number=0,   # invalid when approved
            policy_rule="APPROVE_LIQUIDITY_TEMPORARY",
            reason="Retry approved",
            failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        )


# ── RetryPolicyDecision — rejected ────────────────────────────────────────────

def test_rejected_decision_valid() -> None:
    d = RetryPolicyDecision(
        transaction_id="txn-002",
        event_id="evt-002",
        retry_allowed=False,
        decision=RetryDecision.REJECT,
        scheduled_at=None,
        retry_number=0,
        policy_rule="HARD_DECLINE_BLOCK",
        reason="Mandate expired — permanent failure",
        failure_category=FailureCategory.HARD_DECLINE,
    )
    assert d.retry_allowed is False
    assert d.scheduled_at is None
    assert d.retry_number == 0


def test_rejected_decision_with_scheduled_at_raises() -> None:
    with pytest.raises(ValidationError, match="scheduled_at must be None"):
        RetryPolicyDecision(
            transaction_id="txn-002",
            event_id="evt-002",
            retry_allowed=False,
            decision=RetryDecision.REJECT,
            scheduled_at=_future(),   # invalid when rejected
            retry_number=0,
            policy_rule="HARD_DECLINE_BLOCK",
            reason="Hard decline",
            failure_category=FailureCategory.HARD_DECLINE,
        )


def test_rejected_decision_nonzero_retry_number_raises() -> None:
    with pytest.raises(ValidationError, match="retry_number must be 0"):
        RetryPolicyDecision(
            transaction_id="txn-002",
            event_id="evt-002",
            retry_allowed=False,
            decision=RetryDecision.REJECT,
            scheduled_at=None,
            retry_number=2,   # invalid when rejected
            policy_rule="HARD_DECLINE_BLOCK",
            reason="Hard decline",
            failure_category=FailureCategory.HARD_DECLINE,
        )


# ── RetryPolicyDecision — LLM fields are traceability only ───────────────────

def test_llm_fields_optional_on_reject() -> None:
    """LLM fields must be optional — policy can reject without LLM input."""
    d = RetryPolicyDecision(
        transaction_id="txn-003",
        event_id="evt-003",
        retry_allowed=False,
        decision=RetryDecision.REJECT,
        scheduled_at=None,
        retry_number=0,
        policy_rule="MIN_AMOUNT_BLOCK",
        reason="Amount below ₹100",
        failure_category=FailureCategory.HARD_DECLINE,
        llm_confidence=None,
        llm_rationale=None,
    )
    assert d.llm_confidence is None
    assert d.llm_rationale is None


def test_llm_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        RetryPolicyDecision(
            transaction_id="txn-x",
            event_id="evt-x",
            retry_allowed=False,
            decision=RetryDecision.REJECT,
            scheduled_at=None,
            retry_number=0,
            policy_rule="MIN_AMOUNT_BLOCK",
            reason="Test",
            failure_category=FailureCategory.HARD_DECLINE,
            llm_confidence=1.5,   # out of range
        )


def test_retry_policy_decision_has_no_execute_payment_field() -> None:
    """LLM must have no field that authorises payment execution."""
    import app.models.policy as module
    # Check that RetryPolicyDecision has no execution-related fields
    fields = set(RetryPolicyDecision.model_fields.keys())
    forbidden = {"execute", "payment_authorised", "call_razorpay", "debit_amount"}
    overlap = fields & forbidden
    assert not overlap, f"Forbidden fields found in RetryPolicyDecision: {overlap}"


# ── FailedTransactionEvent ────────────────────────────────────────────────────

def test_failed_transaction_event_valid() -> None:
    e = FailedTransactionEvent(
        transaction_id="TXN-42-00001",
        customer_id="CUST-0001",
        amount_paise=50_000,
        payment_method="NACH",
        failure_code="BANK_RESP_51_NO_FUNDS",
        failed_at=_now(),
        salary_credit_date_estimated=1,
        historical_bank_surge_hour=10,
        retry_count=0,
    )
    assert e.amount_rupees == 500.0


def test_failed_transaction_event_below_100() -> None:
    e = FailedTransactionEvent(
        transaction_id="TXN-42-00002",
        customer_id="CUST-0001",
        amount_paise=5_000,
        payment_method="NACH",
        failure_code="BANK_RESP_51_NO_FUNDS",
        failed_at=_now(),
        salary_credit_date_estimated=1,
        historical_bank_surge_hour=10,
        retry_count=0,
    )
    assert e.amount_rupees == 50.0


def test_failed_transaction_event_negative_amount_raises() -> None:
    with pytest.raises(ValidationError):
        FailedTransactionEvent(
            transaction_id="TXN-x",
            customer_id="CUST-x",
            amount_paise=-1,
            payment_method="NACH",
            failure_code="BANK_RESP_51_NO_FUNDS",
            failed_at=_now(),
            salary_credit_date_estimated=1,
            historical_bank_surge_hour=10,
            retry_count=0,
        )


def test_failed_transaction_event_retry_count_over_3_raises() -> None:
    with pytest.raises(ValidationError):
        FailedTransactionEvent(
            transaction_id="TXN-x",
            customer_id="CUST-x",
            amount_paise=50_000,
            payment_method="NACH",
            failure_code="BANK_RESP_51_NO_FUNDS",
            failed_at=_now(),
            salary_credit_date_estimated=1,
            historical_bank_surge_hour=10,
            retry_count=4,   # exceeds cap
        )


def test_failed_transaction_event_invalid_salary_day_raises() -> None:
    with pytest.raises(ValidationError):
        FailedTransactionEvent(
            transaction_id="TXN-x",
            customer_id="CUST-x",
            amount_paise=50_000,
            payment_method="NACH",
            failure_code="BANK_RESP_51_NO_FUNDS",
            failed_at=_now(),
            salary_credit_date_estimated=0,   # day 0 invalid
            historical_bank_surge_hour=10,
            retry_count=0,
        )


def test_failed_transaction_event_invalid_surge_hour_raises() -> None:
    with pytest.raises(ValidationError):
        FailedTransactionEvent(
            transaction_id="TXN-x",
            customer_id="CUST-x",
            amount_paise=50_000,
            payment_method="NACH",
            failure_code="BANK_RESP_51_NO_FUNDS",
            failed_at=_now(),
            salary_credit_date_estimated=1,
            historical_bank_surge_hour=24,   # hour 24 invalid
            retry_count=0,
        )
