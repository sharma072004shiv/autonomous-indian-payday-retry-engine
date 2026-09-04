"""
tests/integration/test_webhook_api.py
──────────────────────────────────────
Integration tests for the full webhook ingestion flow.

All tests use in-memory SQLite and the mock LLM classifier.
"""

from __future__ import annotations

import os
os.environ["APP_ENV"] = "test"
os.environ["LLM_USE_MOCK"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import init_database, reset_database
from app.main import create_app


@pytest.fixture
async def app_with_db():
    """Fresh in-memory database + app for each test."""
    get_settings.cache_clear()
    await reset_database()
    await init_database(":memory:")
    application = create_app()
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client
    await reset_database()


def _payload(
    event_id: str = "evt-001",
    transaction_id: str = "TXN-001",
    failure_code: str = "BANK_RESP_51_NO_FUNDS",
    amount_paise: int = 50_000,
    customer_id: str = "CUST-001",
) -> dict:
    return {
        "event_id": event_id,
        "transaction_id": transaction_id,
        "failure_code": failure_code,
        "amount_paise": amount_paise,
        "customer_id": customer_id,
        "occurred_at": "2026-07-01T10:00:00+00:00",
    }


# ── 1. Valid webhook ──────────────────────────────────────────────────────────

async def test_valid_webhook_returns_200(app_with_db) -> None:
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=_payload())
    assert resp.status_code == 200


async def test_valid_webhook_response_has_audit_fields(app_with_db) -> None:
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=_payload())
    data = resp.json()
    assert "audit_id" in data
    assert "decision" in data
    assert "policy_rule_applied" in data
    assert "decided_at" in data


async def test_valid_webhook_liquidity_gets_approve(app_with_db) -> None:
    resp = app_with_db.post(
        "/api/v1/webhook/payment-failed",
        json=_payload(failure_code="BANK_RESP_51_NO_FUNDS", amount_paise=50_000),
    )
    data = resp.json()
    assert data["decision"] == "APPROVE"
    assert data["retry_scheduled_at"] is not None


# ── 2. Duplicate webhook ──────────────────────────────────────────────────────

async def test_duplicate_webhook_returns_200(app_with_db) -> None:
    p = _payload()
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    assert resp.status_code == 200


async def test_duplicate_webhook_is_rejected_by_policy(app_with_db) -> None:
    p = _payload()
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert "DUPLICATE" in data["policy_rule_applied"]


async def test_duplicate_does_not_create_second_retry(app_with_db) -> None:
    p = _payload()
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    # Retry status should show only 1 scheduled attempt
    resp = app_with_db.get(f"/api/v1/retries/{p['transaction_id']}")
    data = resp.json()
    assert len(data["attempts"]) == 1


# ── 3. Invalid payload ────────────────────────────────────────────────────────

async def test_missing_event_id_returns_422(app_with_db) -> None:
    bad = _payload()
    del bad["event_id"]
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=bad)
    assert resp.status_code == 422


async def test_blank_failure_code_returns_422(app_with_db) -> None:
    bad = _payload(failure_code="   ")
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=bad)
    assert resp.status_code == 422


async def test_negative_amount_returns_422(app_with_db) -> None:
    bad = _payload(amount_paise=-100)
    resp = app_with_db.post("/api/v1/webhook/payment-failed", json=bad)
    assert resp.status_code == 422


# ── 4. Hard decline ───────────────────────────────────────────────────────────

async def test_hard_decline_is_rejected(app_with_db) -> None:
    resp = app_with_db.post(
        "/api/v1/webhook/payment-failed",
        json=_payload(failure_code="MANDATE_EXPIRED", amount_paise=50_000),
    )
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert data["policy_rule_applied"] == "HARD_DECLINE_BLOCK"


async def test_hard_decline_has_no_scheduled_at(app_with_db) -> None:
    resp = app_with_db.post(
        "/api/v1/webhook/payment-failed",
        json=_payload(failure_code="ACCOUNT_FROZEN", amount_paise=50_000),
    )
    data = resp.json()
    assert data["retry_scheduled_at"] is None


# ── 5. Below ₹100 ─────────────────────────────────────────────────────────────

async def test_below_100_rupees_rejected(app_with_db) -> None:
    resp = app_with_db.post(
        "/api/v1/webhook/payment-failed",
        json=_payload(failure_code="BANK_RESP_51_NO_FUNDS", amount_paise=5_000),
    )
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert data["policy_rule_applied"] == "MIN_AMOUNT_BLOCK"


# ── 6. Eligible retry ─────────────────────────────────────────────────────────

async def test_surge_failure_eligible_for_retry(app_with_db) -> None:
    resp = app_with_db.post(
        "/api/v1/webhook/payment-failed",
        json=_payload(failure_code="NPCI_SURGE_TIMEOUT", amount_paise=100_000),
    )
    data = resp.json()
    assert data["decision"] == "APPROVE"
    assert data["retry_scheduled_at"] is not None


async def test_retry_status_endpoint(app_with_db) -> None:
    p = _payload()
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    resp = app_with_db.get(f"/api/v1/retries/{p['transaction_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["transaction_id"] == p["transaction_id"]


async def test_audit_trail_endpoint(app_with_db) -> None:
    p = _payload()
    app_with_db.post("/api/v1/webhook/payment-failed", json=p)
    resp = app_with_db.get(f"/api/v1/audit/{p['transaction_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_entries"] >= 1


async def test_retry_status_not_found_returns_404(app_with_db) -> None:
    resp = app_with_db.get("/api/v1/retries/no-such-txn")
    assert resp.status_code == 404
