"""
tests/unit/test_llm_classifier.py
───────────────────────────────────
Tests for the LLM classifier layer.

All tests use the deterministic mock classifier — no real API keys or
network calls are made in this suite.

Tests cover:
  - mock_classify_failure: all three categories, case-insensitivity, unknowns
  - classify_failure (async): mock path, safe_category property
  - Error handling: LLMClassificationError
  - Trust-boundary: classifier has no execution/DB authority
  - classify_failure_safe_default: sync fallback
"""

from __future__ import annotations

import os
import pytest

# Force mock mode before importing anything from app
os.environ["APP_ENV"] = "test"
os.environ["LLM_USE_MOCK"] = "true"

from app.config import get_settings
from app.llm.classifier import (
    LLMClassificationError,
    classify_failure,
    classify_failure_safe_default,
)
from app.llm.mock_classifier import (
    FAILURE_CODE_MAP,
    mock_classify_failure,
)
from app.models.enums import FailureCategory
from app.models.llm_output import LLMClassificationResult


# ── mock_classify_failure ─────────────────────────────────────────────────────

def test_mock_liquidity_temporary() -> None:
    result = mock_classify_failure("BANK_RESP_51_NO_FUNDS")
    assert result.failure_category == FailureCategory.LIQUIDITY_TEMPORARY
    assert result.safe_category == FailureCategory.LIQUIDITY_TEMPORARY
    assert result.is_confident is True
    assert result.confidence == pytest.approx(0.99)
    assert result.failure_code_matched == "BANK_RESP_51_NO_FUNDS"


def test_mock_bank_surge_temporary() -> None:
    result = mock_classify_failure("NPCI_SURGE_TIMEOUT")
    assert result.failure_category == FailureCategory.BANK_SURGE_TEMPORARY
    assert result.safe_category == FailureCategory.BANK_SURGE_TEMPORARY


def test_mock_hard_decline_mandate_expired() -> None:
    result = mock_classify_failure("MANDATE_EXPIRED")
    assert result.failure_category == FailureCategory.HARD_DECLINE
    assert result.safe_category == FailureCategory.HARD_DECLINE


def test_mock_hard_decline_account_frozen() -> None:
    result = mock_classify_failure("ACCOUNT_FROZEN")
    assert result.failure_category == FailureCategory.HARD_DECLINE


def test_mock_unknown_code_defaults_to_hard_decline() -> None:
    result = mock_classify_failure("TOTALLY_UNKNOWN_ERROR_CODE_XYZ")
    assert result.failure_category == FailureCategory.HARD_DECLINE
    assert result.safe_category == FailureCategory.HARD_DECLINE
    assert result.confidence == pytest.approx(0.99)


def test_mock_case_insensitive() -> None:
    lower = mock_classify_failure("bank_resp_51_no_funds")
    upper = mock_classify_failure("BANK_RESP_51_NO_FUNDS")
    assert lower.failure_category == upper.failure_category
    assert lower.failure_code_matched == upper.failure_code_matched


def test_mock_whitespace_stripped() -> None:
    result = mock_classify_failure("  MANDATE_EXPIRED  ")
    assert result.failure_category == FailureCategory.HARD_DECLINE
    assert result.failure_code_matched == "MANDATE_EXPIRED"


def test_mock_returns_valid_pydantic_model() -> None:
    result = mock_classify_failure("BANK_RESP_51_NO_FUNDS")
    assert isinstance(result, LLMClassificationResult)


def test_mock_rationale_not_blank() -> None:
    for code in FAILURE_CODE_MAP:
        result = mock_classify_failure(code)
        assert result.rationale.strip() != "", f"Blank rationale for {code}"


def test_mock_all_known_codes_classified() -> None:
    """Every code in FAILURE_CODE_MAP must be classified without error."""
    for code, expected_cat in FAILURE_CODE_MAP.items():
        result = mock_classify_failure(code)
        assert result.failure_category == expected_cat, (
            f"{code} → {result.failure_category}, expected {expected_cat}"
        )


def test_mock_limit_exceeded_is_liquidity() -> None:
    result = mock_classify_failure("BANK_RESP_65_LIMIT_EXCEEDED")
    assert result.failure_category == FailureCategory.LIQUIDITY_TEMPORARY


def test_mock_bank_unavailable_is_surge() -> None:
    result = mock_classify_failure("BANK_UNAVAILABLE")
    assert result.failure_category == FailureCategory.BANK_SURGE_TEMPORARY


def test_mock_account_closed_is_hard_decline() -> None:
    result = mock_classify_failure("ACCOUNT_CLOSED")
    assert result.failure_category == FailureCategory.HARD_DECLINE


def test_mock_do_not_honour_is_hard_decline() -> None:
    result = mock_classify_failure("DO_NOT_HONOUR")
    assert result.failure_category == FailureCategory.HARD_DECLINE


# ── classify_failure (async, mock path) ──────────────────────────────────────

async def test_classify_failure_mock_path_liquidity() -> None:
    get_settings.cache_clear()
    result = await classify_failure("BANK_RESP_51_NO_FUNDS")
    assert result.failure_category == FailureCategory.LIQUIDITY_TEMPORARY


async def test_classify_failure_mock_path_surge() -> None:
    get_settings.cache_clear()
    result = await classify_failure("NPCI_SURGE_TIMEOUT")
    assert result.safe_category == FailureCategory.BANK_SURGE_TEMPORARY


async def test_classify_failure_mock_path_hard_decline() -> None:
    get_settings.cache_clear()
    result = await classify_failure("ACCOUNT_FROZEN")
    assert result.safe_category == FailureCategory.HARD_DECLINE


async def test_classify_failure_returns_llm_classification_result() -> None:
    get_settings.cache_clear()
    result = await classify_failure("BANK_RESP_51_NO_FUNDS")
    assert isinstance(result, LLMClassificationResult)


async def test_classify_failure_unknown_code_safe_fallback() -> None:
    """Unknown codes must resolve to HARD_DECLINE via safe_category."""
    get_settings.cache_clear()
    result = await classify_failure("COMPLETELY_UNKNOWN_CODE")
    assert result.safe_category == FailureCategory.HARD_DECLINE


# ── safe_category low-confidence fallback ─────────────────────────────────────

def test_safe_category_falls_back_on_low_confidence() -> None:
    result = LLMClassificationResult(
        failure_category=FailureCategory.LIQUIDITY_TEMPORARY,
        confidence=0.3,   # below 0.5 threshold
        rationale="Uncertain classification",
        failure_code_matched="UNKNOWN_CODE",
    )
    assert result.safe_category == FailureCategory.HARD_DECLINE


def test_safe_category_exact_threshold_passes() -> None:
    result = LLMClassificationResult(
        failure_category=FailureCategory.BANK_SURGE_TEMPORARY,
        confidence=0.5,   # exactly at threshold
        rationale="Borderline classification",
    )
    assert result.safe_category == FailureCategory.BANK_SURGE_TEMPORARY


# ── classify_failure_safe_default ─────────────────────────────────────────────

def test_safe_default_returns_hard_decline() -> None:
    result = classify_failure_safe_default("ANY_CODE")
    assert result.failure_category == FailureCategory.HARD_DECLINE
    assert result.safe_category == FailureCategory.HARD_DECLINE


def test_safe_default_echoes_failure_code() -> None:
    result = classify_failure_safe_default("  my_code  ")
    assert result.failure_code_matched == "MY_CODE"


def test_safe_default_has_non_blank_rationale() -> None:
    result = classify_failure_safe_default("CODE")
    assert result.rationale.strip() != ""


# ── LLMClassificationError ────────────────────────────────────────────────────

def test_llm_classification_error_is_exception() -> None:
    err = LLMClassificationError("LLM timed out")
    assert isinstance(err, Exception)
    assert "timed out" in str(err)


# ── Trust-boundary static checks ─────────────────────────────────────────────

def test_classifier_module_has_no_payment_execution_functions() -> None:
    """
    AGENTS.md: The LLM classifier must never execute payments.
    Verify no execution-related function names exist in the module.
    """
    import app.llm.classifier as mod
    forbidden_names = {
        "execute_payment", "call_razorpay", "debit", "charge",
        "insert_transaction", "update_transaction", "schedule_retry",
    }
    actual_names = {name for name in dir(mod) if not name.startswith("_")}
    overlap = forbidden_names & actual_names
    assert not overlap, (
        f"Classifier module exposes forbidden function names: {overlap}"
    )


def test_mock_classifier_module_has_no_db_imports() -> None:
    """mock_classifier must not import from app.db."""
    import app.llm.mock_classifier as mod
    import inspect
    source = inspect.getsource(mod)
    assert "from app.db" not in source, "mock_classifier must not import from app.db"
    assert "import app.db" not in source, "mock_classifier must not import app.db"


def test_classifier_module_has_no_db_imports() -> None:
    """classifier must not import from app.db."""
    import app.llm.classifier as mod
    import inspect
    source = inspect.getsource(mod)
    assert "from app.db" not in source
    assert "import app.db" not in source


def test_llm_result_cannot_set_retry_allowed() -> None:
    """LLMClassificationResult has no retry_allowed field."""
    fields = set(LLMClassificationResult.model_fields.keys())
    assert "retry_allowed" not in fields
    assert "scheduled_at" not in fields
    assert "execute" not in fields
