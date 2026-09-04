"""
benchmark/engine_runner.py
───────────────────────────
Strategy B: Autonomous PayDay Retry Engine.

Uses:
  - Mock LLM classifier
  - Deterministic policy engine (guardrails)
  - Timing predictor (payday / surge avoidance)
  - Mock executor (up to 3 retry attempts)

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from data.generate_data import generate_dataset as _generate_raw
from app.executor.mock_razorpay import simulate_payment_sync
from app.llm.mock_classifier import mock_classify_failure
from app.models.enums import ExecutionOutcome, FailureCategory
from app.models.transaction import FailureEvent
from app.policy.engine import evaluate
from datetime import datetime, timezone


def run_engine(
    dataset: list[FailureEvent],
    seed: int = 42,
    success_rate: float = 0.72,
) -> dict:
    """
    Simulate the autonomous retry engine against `dataset`.

    Respects all AGENTS.md safety rules deterministically:
      - HARD_DECLINE → never retry
      - amount < ₹100 → never retry
      - retry_count >= 3 → never retry
      - All timing is handled by the policy engine + predictor

    ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
    """
    # Load per-record metadata from the raw generator for timing hints
    raw_by_txn = {
        r["transaction_id"]: r
        for r in _generate_raw(seed=seed, n=len(dataset))
    }

    total = len(dataset)
    hard_declines = 0
    below_threshold = 0
    max_retry_blocked = 0
    approved_count = 0
    recovered = 0
    recovered_amount_paise = 0
    total_attempts = 0
    failed_permanently = 0

    # Track retry state per transaction (since we run all attempts synchronously)
    retry_counts: dict[str, int] = {}

    for event in dataset:
        raw = raw_by_txn.get(event.transaction_id, {})
        salary_credit_day = raw.get("salary_credit_date_estimated")
        surge_hour = raw.get("historical_bank_surge_hour")

        # Classify with mock LLM
        llm_result = mock_classify_failure(event.failure_code)
        retry_count = retry_counts.get(event.transaction_id, 0)

        # Policy evaluation
        decision = evaluate(
            transaction_id=event.transaction_id,
            event_id=event.event_id,
            llm_result=llm_result,
            amount_paise=event.amount_paise,
            retry_count=retry_count,
            already_processed=False,
            salary_credit_day=salary_credit_day,
            historical_surge_hour_ist=surge_hour,
            as_of=datetime.now(timezone.utc),
        )

        if not decision.retry_allowed:
            rule = decision.policy_rule
            if rule == "HARD_DECLINE_BLOCK":
                hard_declines += 1
            elif rule == "MIN_AMOUNT_BLOCK":
                below_threshold += 1
            elif rule == "MAX_RETRIES_BLOCK":
                max_retry_blocked += 1
            failed_permanently += 1
            continue

        approved_count += 1

        # Simulate up to 3 attempts for this transaction
        txn_recovered = False
        for attempt_num in range(1, 4):
            total_attempts += 1
            outcome = simulate_payment_sync(
                transaction_id=event.transaction_id,
                amount_paise=event.amount_paise,
                attempt_number=attempt_num,
                seed=seed,
                success_rate=success_rate,
            )

            if outcome == ExecutionOutcome.SUCCESS:
                recovered += 1
                recovered_amount_paise += event.amount_paise
                txn_recovered = True
                break

            # Check if another retry is allowed
            retry_counts[event.transaction_id] = attempt_num
            next_decision = evaluate(
                transaction_id=event.transaction_id,
                event_id=f"{event.event_id}-retry-{attempt_num}",
                llm_result=llm_result,
                amount_paise=event.amount_paise,
                retry_count=attempt_num,
                already_processed=False,
                salary_credit_day=salary_credit_day,
                historical_surge_hour_ist=surge_hour,
                as_of=datetime.now(timezone.utc),
            )
            if not next_decision.retry_allowed:
                break

        if not txn_recovered:
            failed_permanently += 1

    recovery_rate = (recovered / total * 100.0) if total > 0 else 0.0
    avg_attempts = (total_attempts / approved_count) if approved_count > 0 else 0.0

    return {
        "strategy": "AUTONOMOUS_PAYDAY_ENGINE",
        "note": "SYNTHETIC SIMULATION — NOT REAL-WORLD DATA",
        "total_transactions": total,
        "hard_declines_blocked": hard_declines,
        "below_threshold_blocked": below_threshold,
        "max_retry_blocked": max_retry_blocked,
        "approved_for_retry": approved_count,
        "total_retry_attempts": total_attempts,
        "recovered": recovered,
        "failed_permanently": failed_permanently,
        "recovered_amount_paise": recovered_amount_paise,
        "recovered_amount_rupees": round(recovered_amount_paise / 100.0, 2),
        "recovery_rate_pct": round(recovery_rate, 2),
        "avg_attempts_per_approved": round(avg_attempts, 2),
    }
