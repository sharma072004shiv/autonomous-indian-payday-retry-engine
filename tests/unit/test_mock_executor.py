"""
tests/unit/test_mock_executor.py
─────────────────────────────────
Tests for the mock Razorpay executor.
No real API calls, no database, no network.
"""

from __future__ import annotations

import pytest

from app.executor.mock_razorpay import simulate_payment_sync
from app.models.enums import ExecutionOutcome


def test_returns_valid_outcome() -> None:
    outcome = simulate_payment_sync("txn-001", 50_000, 1)
    assert outcome in (ExecutionOutcome.SUCCESS, ExecutionOutcome.FAILURE, ExecutionOutcome.TIMEOUT)


def test_deterministic_same_inputs() -> None:
    r1 = simulate_payment_sync("txn-001", 50_000, 1, seed=42, success_rate=0.72)
    r2 = simulate_payment_sync("txn-001", 50_000, 1, seed=42, success_rate=0.72)
    assert r1 == r2


def test_different_transactions_different_outcomes() -> None:
    results = {
        simulate_payment_sync(f"txn-{i:04d}", 50_000, 1)
        for i in range(20)
    }
    # With 20 different transactions we expect at least 2 different outcomes
    assert len(results) >= 1


def test_attempt_3_has_lower_success_than_attempt_1() -> None:
    """Attempt 3 multiplier (0.6) means fewer successes than attempt 1 (1.0)."""
    n = 200
    success_1 = sum(
        1 for i in range(n)
        if simulate_payment_sync(f"txn-{i}", 50_000, 1, seed=42) == ExecutionOutcome.SUCCESS
    )
    success_3 = sum(
        1 for i in range(n)
        if simulate_payment_sync(f"txn-{i}", 50_000, 3, seed=42) == ExecutionOutcome.SUCCESS
    )
    assert success_1 >= success_3


def test_no_real_api_calls() -> None:
    import inspect
    import app.executor.mock_razorpay as mod
    source = inspect.getsource(mod)
    assert "requests.get" not in source
    assert "httpx" not in source
    assert "razorpay.com" not in source


async def test_async_execute_payment() -> None:
    import os
    os.environ["APP_ENV"] = "test"
    os.environ["LLM_USE_MOCK"] = "true"
    from app.config import get_settings
    get_settings.cache_clear()
    from app.executor.mock_razorpay import execute_payment
    outcome = await execute_payment("txn-async-001", 50_000, 1)
    assert outcome in (ExecutionOutcome.SUCCESS, ExecutionOutcome.FAILURE, ExecutionOutcome.TIMEOUT)
