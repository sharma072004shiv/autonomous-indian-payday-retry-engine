"""
tests/unit/test_models.py
─────────────────────────
Unit tests for Pydantic models in app/models/.

Tests cover:
  - FailureEvent validation rules
  - Transaction retry_count hard cap
  - LLMClassificationResult.safe_category fallback
  - AuditEntry field types
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.audit import AuditEntry
from app.models.enums import (
    ExecutionOutcome,
    FailureCategory,
    RetryDecision,
    TransactionStatus,
)
from app.models.llm_output import LLMClassificationResult
from app.models.transaction import FailureEvent, Transaction


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_event(**overrides) -> FailureEvent:
    defaults = dict(
        event_id="evt-001",
        transaction_id="txn-001",
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=50_000,
        customer_id="cust-001",
        occurred_at=_now(),
    )
    defaults.update(overrides)
    return FailureEvent(**defaults)


# ── FailureEvent ──────────────────────────────────────────────────────────────

def test_failure_event_valid() -> None:
    evt = _make_event()
    assert evt.failure_code == "BANK_RESP_51_NO_FUNDS"
    assert evt.amount_rupees == 500.0


def test_failure_code_uppercased_and_stripped() -> None:
    evt = _make_event(failure_code="  bank_resp_51_no_funds  ")
    assert evt.failure_code == "BANK_RESP_51_NO_FUNDS"


def test_failure_code_blank_raises() -> None:
    with pytest.raises(ValidationError):
        _make_event(failure_code="   ")


def test_amount_paise_negative_raises() -> None:
    with pytest.raises(ValidationError):
        _make_event(amount_paise=-1)


def test_amount_paise_zero_is_valid() -> None:
    evt = _make_event(amount_paise=0)
    assert evt.amount_rupees == 0.0


# ── Transaction ───────────────────────────────────────────────────────────────

def test_transaction_retry_count_over_cap_raises() -> None:
    """AGENTS.md rule #1: retry_count > 3 must be rejected by the model."""
    with pytest.raises(ValidationError):
        Transaction(
            transaction_id="txn-001",
            failure_code="BANK_RESP_51_NO_FUNDS",
            amount_paise=50_000,
            customer_id="cust-001",
            occurred_at=_now(),
            created_at=_now(),
            updated_at=_now(),
            retry_count=4,  # exceeds hard cap
        )


def test_transaction_retry_count_at_cap_is_valid() -> None:
    tx = Transaction(
        transaction_id="txn-001",
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=50_000,
        customer_id="cust-001",
        occurred_at=_now(),
        created_at=_now(),
        updated_at=_now(),
        retry_count=3,
    )
    assert tx.retry_count == 3


def test_transaction_amount_rupees() -> None:
    tx = Transaction(
        transaction_id="txn-001",
        failure_code="BANK_RESP_51_NO_FUNDS",
        amount_paise=12_345,
        customer_id="cust-001",
        occurred_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert tx.amount_rupees == 123.45


# ── LLMClassificationResult ───────────────────────────────────────────────────

def test_llm_result_safe_category_high_confidence() -> None:
    result = LLMClassificationResult(
        failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        confidence=0.95,
        rationale="Insufficient funds — typical payday gap",
    )
    assert result.safe_category == FailureCategory.LIQUIDITY_TEMPORARY


def test_llm_result_safe_category_low_confidence_defaults_to_hard_decline() -> None:
    """Confidence below 0.5 must fall back to HARD_DECLINE."""
    result = LLMClassificationResult(
        failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        confidence=0.3,
        rationale="Uncertain classification",
    )
    assert result.safe_category == FailureCategory.HARD_DECLINE


def test_llm_result_confidence_boundary_exactly_half() -> None:
    """Confidence == 0.5 is the boundary; is_confident must be True."""
    result = LLMClassificationResult(
        failure_category=FailureCategory.BANK_SURGE_TEMPORARY,
        confidence=0.5,
        rationale="Boundary case",
    )
    assert result.is_confident is True
    assert result.safe_category == FailureCategory.BANK_SURGE_TEMPORARY


def test_llm_result_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        LLMClassificationResult(
            failure_category=FailureCategory.HARD_DECLINE,
            confidence=1.1,
            rationale="Invalid",
        )


def test_llm_result_blank_rationale_raises() -> None:
    with pytest.raises(ValidationError):
        LLMClassificationResult(
            failure_category=FailureCategory.HARD_DECLINE,
            confidence=0.99,
            rationale="   ",
        )


# ── Enums ─────────────────────────────────────────────────────────────────────

def test_failure_category_values() -> None:
    assert FailureCategory.HARD_DECLINE == "HARD_DECLINE"
    assert FailureCategory.LIQUIDITY_TEMPORARY == "LIQUIDITY_TEMPORARY"
    assert FailureCategory.BANK_SURGE_TEMPORARY == "BANK_SURGE_TEMPORARY"


def test_retry_decision_values() -> None:
    assert RetryDecision.APPROVE == "APPROVE"
    assert RetryDecision.REJECT == "REJECT"
    assert RetryDecision.DEFER == "DEFER"


def test_transaction_status_values() -> None:
    assert TransactionStatus.FAILED == "FAILED"
    assert TransactionStatus.RECOVERED == "RECOVERED"
    assert TransactionStatus.PERMANENTLY_FAILED == "PERMANENTLY_FAILED"


def test_execution_outcome_values() -> None:
    assert ExecutionOutcome.SUCCESS == "SUCCESS"
    assert ExecutionOutcome.FAILURE == "FAILURE"
    assert ExecutionOutcome.TIMEOUT == "TIMEOUT"
