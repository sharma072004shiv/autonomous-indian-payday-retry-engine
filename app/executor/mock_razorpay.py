"""
app/executor/mock_razorpay.py
─────────────────────────────
Mock Razorpay payment executor.

AGENTS.md safety rule #6 (STRICTLY ENFORCED):
  This module MUST NEVER connect to real Razorpay APIs.
  All payment execution is simulated using a seeded RNG so that
  benchmark and test results are deterministic and reproducible.

Design
──────
- Uses a module-level seeded `random.Random` instance.
- Seed comes from Settings.mock_executor_seed (default 42).
- Success probability from Settings.mock_executor_success_rate (default 0.72).
- On attempt 1 the success probability is full.
- On attempt 2 it is 80% of the base rate (more realistic).
- On attempt 3 it is 60% of the base rate.
- Timeouts are simulated with 5% probability.
- The RNG is reset per-call using a deterministic sub-seed derived from
  (global_seed, transaction_id, attempt_number) so individual calls are
  repeatable even if called in different orders.
"""

from __future__ import annotations

import hashlib
import logging
import random

from app.models.enums import ExecutionOutcome

logger = logging.getLogger(__name__)

# Attempt-number → multiplier on the base success rate
_ATTEMPT_MULTIPLIER: dict[int, float] = {1: 1.0, 2: 0.80, 3: 0.60}
_TIMEOUT_PROBABILITY: float = 0.05


def _make_rng(seed: int, transaction_id: str, attempt_number: int) -> random.Random:
    """
    Return a deterministic RNG seeded by (seed, transaction_id, attempt_number).

    This makes each (transaction, attempt) pair produce the same outcome
    regardless of call order or process restarts.
    """
    key = f"{seed}:{transaction_id}:{attempt_number}"
    digest = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return random.Random(digest % (2**32))


async def execute_payment(
    transaction_id: str,
    amount_paise: int,
    attempt_number: int,
) -> ExecutionOutcome:
    """
    Simulate a Razorpay payment attempt.

    Returns ExecutionOutcome.SUCCESS, FAILURE, or TIMEOUT.
    NEVER connects to any external service.

    Parameters
    ----------
    transaction_id : str
        Used as part of the RNG seed for deterministic per-transaction outcomes.
    amount_paise : int
        Amount in paise. Not used for the outcome decision but logged.
    attempt_number : int
        1-indexed attempt number. Higher attempts have lower success probability.

    Returns
    -------
    ExecutionOutcome
    """
    from app.config import get_settings
    settings = get_settings()

    rng = _make_rng(settings.mock_executor_seed, transaction_id, attempt_number)

    multiplier = _ATTEMPT_MULTIPLIER.get(attempt_number, 0.50)
    effective_success_rate = settings.mock_executor_success_rate * multiplier

    roll = rng.random()

    if roll < _TIMEOUT_PROBABILITY:
        outcome = ExecutionOutcome.TIMEOUT
    elif roll < _TIMEOUT_PROBABILITY + effective_success_rate:
        outcome = ExecutionOutcome.SUCCESS
    else:
        outcome = ExecutionOutcome.FAILURE

    logger.debug(
        "mock_razorpay: txn=%s attempt=%d amount_paise=%d roll=%.4f "
        "success_rate=%.4f outcome=%s",
        transaction_id,
        attempt_number,
        amount_paise,
        roll,
        effective_success_rate,
        outcome.value,
    )
    return outcome


def simulate_payment_sync(
    transaction_id: str,
    amount_paise: int,
    attempt_number: int,
    seed: int = 42,
    success_rate: float = 0.72,
) -> ExecutionOutcome:
    """
    Synchronous version for use in benchmark runners (no event loop needed).

    Uses the same deterministic logic as execute_payment().
    """
    rng = _make_rng(seed, transaction_id, attempt_number)
    multiplier = _ATTEMPT_MULTIPLIER.get(attempt_number, 0.50)
    effective_success_rate = success_rate * multiplier
    roll = rng.random()

    if roll < _TIMEOUT_PROBABILITY:
        return ExecutionOutcome.TIMEOUT
    if roll < _TIMEOUT_PROBABILITY + effective_success_rate:
        return ExecutionOutcome.SUCCESS
    return ExecutionOutcome.FAILURE
