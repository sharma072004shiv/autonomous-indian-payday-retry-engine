"""
tests/integration/test_classifier_regression.py
─────────────────────────────────────────────────
Regression tests for the end-to-end bug where BANK_RESP_51_NO_FUNDS
was incorrectly classified as HARD_DECLINE when the real LLM was
unavailable (no API key configured).

Root cause was that classify_failure() raised LLMClassificationError when
_build_agent() failed, and retry_service.py called classify_failure_safe_default()
as the catch handler — which always returns HARD_DECLINE regardless of the
failure code.

Fix: classify_failure() now falls back to the mock classifier (which has
correct deterministic mappings) instead of raising, and retry_service.py
also uses the mock classifier as its catch-handler fallback.

These tests must pass with and without a real LLM API key.
"""

from __future__ import annotations

import asyncio
import os

# Must be set before any app imports so get_settings() picks them up
os.environ["APP_ENV"] = "test"
os.environ["LLM_USE_MOCK"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import init_database, reset_database
from app.llm.classifier import classify_failure
from app.llm.mock_classifier import mock_classify_failure
from app.models.enums import FailureCategory
from app.main import create_app


# ── Pure classifier regression (no DB) ────────────────────────────────────────

async def test_bank_resp_51_classifies_as_liquidity_temporary() -> None:
    """BANK_RESP_51_NO_FUNDS must NEVER be classified as HARD_DECLINE."""
    get_settings.cache_clear()
    result = await classify_failure("BANK_RESP_51_NO_FUNDS")
    assert result.failure_category == FailureCategory.LIQUIDITY_TEMPORARY, (
        f"Expected LIQUIDITY_TEMPORARY, got {result.failure_category.value}"
    )
    assert result.safe_category == FailureCategory.LIQUIDITY_TEMPORARY
    assert result.is_confident is True


async def test_bank_resp_51_is_not_hard_decline() -> None:
    """Explicit assertion that BANK_RESP_51_NO_FUNDS is NOT HARD_DECLINE."""
    get_settings.cache_clear()
    result = await classify_failure("BANK_RESP_51_NO_FUNDS")
    assert result.safe_category != FailureCategory.HARD_DECLINE, (
        "REGRESSION: BANK_RESP_51_NO_FUNDS must not be classified as HARD_DECLINE"
    )


async def test_npci_surge_timeout_classifies_as_bank_surge_temporary() -> None:
    get_settings.cache_clear()
    result = await classify_failure("NPCI_SURGE_TIMEOUT")
    assert result.safe_category == FailureCategory.BANK_SURGE_TEMPORARY


async def test_mandate_expired_remains_hard_decline() -> None:
    """Hard-decline codes must still be classified as HARD_DECLINE."""
    get_settings.cache_clear()
    result = await classify_failure("MANDATE_EXPIRED")
    assert result.safe_category == FailureCategory.HARD_DECLINE


async def test_account_frozen_remains_hard_decline() -> None:
    get_settings.cache_clear()
    result = await classify_failure("ACCOUNT_FROZEN")
    assert result.safe_category == FailureCategory.HARD_DECLINE


def test_mock_classifier_bank_resp_51_is_liquidity() -> None:
    """Direct mock classifier — must never produce HARD_DECLINE for this code."""
    result = mock_classify_failure("BANK_RESP_51_NO_FUNDS")
    assert result.failure_category == FailureCategory.LIQUIDITY_TEMPORARY
    assert result.safe_category == FailureCategory.LIQUIDITY_TEMPORARY
    assert result.confidence == pytest.approx(0.99)


def test_mock_classifier_all_required_mappings() -> None:
    """All four AGENTS.md example codes must map correctly."""
    cases = {
        "BANK_RESP_51_NO_FUNDS": FailureCategory.LIQUIDITY_TEMPORARY,
        "NPCI_SURGE_TIMEOUT":    FailureCategory.BANK_SURGE_TEMPORARY,
        "MANDATE_EXPIRED":       FailureCategory.HARD_DECLINE,
        "ACCOUNT_FROZEN":        FailureCategory.HARD_DECLINE,
    }
    for code, expected in cases.items():
        result = mock_classify_failure(code)
        assert result.safe_category == expected, (
            f"REGRESSION: {code} → {result.safe_category.value}, "
            f"expected {expected.value}"
        )


# ── Non-mock (real server path) fallback regression ───────────────────────────

async def test_classify_failure_falls_back_to_mock_when_llm_unavailable() -> None:
    """
    When the real LLM is unavailable (no API key, or pydantic_ai broken),
    classify_failure() must fall back to the mock classifier — NOT to
    the blanket HARD_DECLINE safe default.

    This is the core regression that caused the Swagger bug.
    """
    import importlib
    from unittest.mock import patch

    # Simulate the real-LLM path failing by patching _build_agent to raise
    with patch("app.llm.classifier._build_agent") as mock_build:
        mock_build.side_effect = Exception("Simulated pydantic_ai import failure")

        # Also reset the cached _agent so _build_agent is called
        import app.llm.classifier as clf_module
        original_agent = clf_module._agent
        clf_module._agent = None

        try:
            # Use non-mock settings to exercise the fallback path
            from app.config import Settings, AppEnv
            with patch.object(clf_module, "get_settings") as mock_settings:
                fake_settings = Settings(
                    app_env=AppEnv.DEVELOPMENT,
                    llm_use_mock=False,
                )
                mock_settings.return_value = fake_settings

                result = await clf_module.classify_failure("BANK_RESP_51_NO_FUNDS")

            assert result.safe_category == FailureCategory.LIQUIDITY_TEMPORARY, (
                f"REGRESSION: fallback path returned {result.safe_category.value} "
                f"instead of LIQUIDITY_TEMPORARY for BANK_RESP_51_NO_FUNDS"
            )
        finally:
            clf_module._agent = original_agent


# ── Full webhook integration regression ──────────────────────────────────────

@pytest.fixture
async def client_with_db():
    """Fresh in-memory DB + TestClient for each test."""
    get_settings.cache_clear()
    await reset_database()
    await init_database(":memory:")
    application = create_app()
    with TestClient(application, raise_server_exceptions=True) as c:
        yield c
    await reset_database()


async def test_webhook_bank_resp_51_produces_approve(client_with_db) -> None:
    """
    Full end-to-end regression:
      BANK_RESP_51_NO_FUNDS + ₹500 + retry_count=0
      → LIQUIDITY_TEMPORARY
      → decision = APPROVE (eligible for retry)
      → NOT HARD_DECLINE

    This is the exact scenario that failed in manual Swagger testing.
    """
    resp = client_with_db.post(
        "/api/v1/webhook/payment-failed",
        json={
            "event_id":        "evt-regression-001",
            "transaction_id":  "txn-regression-001",
            "failure_code":    "BANK_RESP_51_NO_FUNDS",
            "amount_paise":    50_000,   # ₹500 — well above ₹100 threshold
            "customer_id":     "cust-regression",
            "mandate_id":      "mandate-regression",
            "occurred_at":     "2026-09-04T03:30:00Z",
            "raw_payload": {
                "source":      "regression-test",
                "description": "Insufficient funds - temporary liquidity failure",
            },
        },
    )
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
    data = resp.json()

    assert data["decision"] == "APPROVE", (
        f"REGRESSION: BANK_RESP_51_NO_FUNDS + ₹500 should be APPROVE, "
        f"got {data['decision']} (rule={data.get('policy_rule_applied')})"
    )
    assert data["failure_category"] == "LIQUIDITY_TEMPORARY", (
        f"REGRESSION: Expected LIQUIDITY_TEMPORARY, got {data['failure_category']}"
    )
    assert data["policy_rule_applied"] == "APPROVE_LIQUIDITY_TEMPORARY"
    assert data["retry_scheduled_at"] is not None, "Approved retry must have scheduled_at"
    assert data["retry_attempt_number"] == 1


async def test_webhook_mandate_expired_still_rejects(client_with_db) -> None:
    """Hard-decline cases must remain rejected after the fix."""
    resp = client_with_db.post(
        "/api/v1/webhook/payment-failed",
        json={
            "event_id":       "evt-regression-002",
            "transaction_id": "txn-regression-002",
            "failure_code":   "MANDATE_EXPIRED",
            "amount_paise":   50_000,
            "customer_id":    "cust-regression",
            "occurred_at":    "2026-09-04T03:30:00Z",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert data["failure_category"] == "HARD_DECLINE"
    assert data["policy_rule_applied"] == "HARD_DECLINE_BLOCK"
    assert data["retry_scheduled_at"] is None


async def test_webhook_account_frozen_still_rejects(client_with_db) -> None:
    resp = client_with_db.post(
        "/api/v1/webhook/payment-failed",
        json={
            "event_id":       "evt-regression-003",
            "transaction_id": "txn-regression-003",
            "failure_code":   "ACCOUNT_FROZEN",
            "amount_paise":   50_000,
            "customer_id":    "cust-regression",
            "occurred_at":    "2026-09-04T03:30:00Z",
        },
    )
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert data["failure_category"] == "HARD_DECLINE"


async def test_webhook_npci_surge_timeout_produces_approve(client_with_db) -> None:
    """NPCI_SURGE_TIMEOUT → BANK_SURGE_TEMPORARY → APPROVE."""
    resp = client_with_db.post(
        "/api/v1/webhook/payment-failed",
        json={
            "event_id":       "evt-regression-004",
            "transaction_id": "txn-regression-004",
            "failure_code":   "NPCI_SURGE_TIMEOUT",
            "amount_paise":   100_000,
            "customer_id":    "cust-regression",
            "occurred_at":    "2026-09-04T03:30:00Z",
        },
    )
    data = resp.json()
    assert data["decision"] == "APPROVE"
    assert data["failure_category"] == "BANK_SURGE_TEMPORARY"


async def test_webhook_below_100_rupees_still_blocks(client_with_db) -> None:
    """Amount < ₹100 must still be blocked even for LIQUIDITY_TEMPORARY."""
    resp = client_with_db.post(
        "/api/v1/webhook/payment-failed",
        json={
            "event_id":       "evt-regression-005",
            "transaction_id": "txn-regression-005",
            "failure_code":   "BANK_RESP_51_NO_FUNDS",
            "amount_paise":   5_000,   # ₹50 — below threshold
            "customer_id":    "cust-regression",
            "occurred_at":    "2026-09-04T03:30:00Z",
        },
    )
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert data["policy_rule_applied"] == "MIN_AMOUNT_BLOCK"
