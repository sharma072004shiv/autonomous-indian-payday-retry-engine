"""
benchmark/baseline_runner.py
──────────────────────────────
Strategy A: Fixed 24-hour retry baseline.

Rules:
  - HARD_DECLINE codes → never retry
  - Amount < ₹100      → never retry
  - All others         → retry once after 24 hours
  - Max 1 retry (fixed strategy)

Uses mock executor (simulate_payment_sync) with a deterministic seed.

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

from app.executor.mock_razorpay import simulate_payment_sync
from app.llm.mock_classifier import FAILURE_CODE_MAP
from app.models.enums import ExecutionOutcome, FailureCategory
from app.models.transaction import FailureEvent

_HARD_DECLINE_CODES = {
    code for code, cat in FAILURE_CODE_MAP.items()
    if cat == FailureCategory.HARD_DECLINE
}
_MIN_AMOUNT_PAISE = 10_000


def run_baseline(
    dataset: list[FailureEvent],
    seed: int = 42,
    success_rate: float = 0.72,
) -> dict:
    """
    Simulate the fixed 24-hour retry baseline against `dataset`.

    Returns a metrics dictionary.

    ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
    """
    total = len(dataset)
    hard_declines = 0
    below_threshold = 0
    retried = 0
    recovered = 0
    recovered_amount_paise = 0
    failed_after_retry = 0

    for event in dataset:
        failure_code = event.failure_code.upper()

        # Hard decline — never retry
        if failure_code in _HARD_DECLINE_CODES:
            hard_declines += 1
            continue

        # Below ₹100 — never retry
        if event.amount_paise < _MIN_AMOUNT_PAISE:
            below_threshold += 1
            continue

        # Fixed 24-hour retry: attempt #1 always
        retried += 1
        outcome = simulate_payment_sync(
            transaction_id=event.transaction_id,
            amount_paise=event.amount_paise,
            attempt_number=1,
            seed=seed,
            success_rate=success_rate,
        )

        if outcome == ExecutionOutcome.SUCCESS:
            recovered += 1
            recovered_amount_paise += event.amount_paise
        else:
            failed_after_retry += 1

    retried_total = retried
    recovery_rate = (recovered / total * 100.0) if total > 0 else 0.0
    retry_success_rate = (recovered / retried * 100.0) if retried > 0 else 0.0

    return {
        "strategy": "FIXED_24H_BASELINE",
        "note": "SYNTHETIC SIMULATION — NOT REAL-WORLD DATA",
        "total_transactions": total,
        "hard_declines_skipped": hard_declines,
        "below_threshold_skipped": below_threshold,
        "retried": retried_total,
        "recovered": recovered,
        "failed_after_retry": failed_after_retry,
        "recovered_amount_paise": recovered_amount_paise,
        "recovered_amount_rupees": round(recovered_amount_paise / 100.0, 2),
        "recovery_rate_pct": round(recovery_rate, 2),
        "retry_success_rate_pct": round(retry_success_rate, 2),
        "avg_retries_per_recovered": 1.0 if recovered > 0 else 0.0,
    }
