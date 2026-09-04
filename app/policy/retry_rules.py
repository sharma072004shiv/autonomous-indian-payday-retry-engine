"""
app/policy/retry_rules.py
─────────────────────────
Deterministic retry window calculation.

Given a failure category, attempt number, and timing context, returns the
UTC datetime at which the next retry should be executed.

No LLM involvement.  The timing predictor (payday_predictor.py) provides
the salary-credit and surge-window intelligence; this module orchestrates it.

Retry windows
─────────────
LIQUIDITY_TEMPORARY   — Attempt 1: 2h after predicted salary credit
                        Attempt 2: 6h after predicted salary credit
                        Attempt 3: 12h after predicted salary credit

BANK_SURGE_TEMPORARY  — Attempt 1: next surge-free slot (≥ 0h offset)
                        Attempt 2: next surge-free slot (≥ 2h offset)
                        Attempt 3: next surge-free slot (≥ 6h offset)

HARD_DECLINE          — Must never reach this function.  Raises ValueError.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.enums import FailureCategory
from app.services.payday_predictor import suggest_retry_time


def calculate_next_retry_at(
    category: FailureCategory,
    attempt_number: int,
    from_time: datetime,
    salary_credit_day: Optional[int] = None,
    historical_surge_hour_ist: Optional[int] = None,
) -> datetime:
    """
    Return the UTC datetime for the next retry attempt.

    Parameters
    ----------
    category : FailureCategory
        Must be LIQUIDITY_TEMPORARY or BANK_SURGE_TEMPORARY.
        Raises ValueError for HARD_DECLINE.
    attempt_number : int
        1-indexed retry number (1, 2, or 3).
    from_time : datetime
        Reference time — must be timezone-aware (UTC recommended).
    salary_credit_day : Optional[int]
        Day of month (1–31) when salary is typically credited.
        Used for LIQUIDITY_TEMPORARY to align retry with payday.
        If None, a standard back-off from from_time is used.
    historical_surge_hour_ist : Optional[int]
        IST hour when surges have historically occurred.
        Used for BANK_SURGE_TEMPORARY to add margin past that hour.

    Returns
    -------
    datetime (UTC, timezone-aware)
        Always strictly greater than from_time.

    Raises
    ------
    ValueError
        If category is HARD_DECLINE, or attempt_number is outside [1, 3],
        or from_time is timezone-naive.
    """
    if from_time.tzinfo is None:
        raise ValueError("from_time must be timezone-aware")

    if category == FailureCategory.HARD_DECLINE:
        raise ValueError(
            "calculate_next_retry_at must never be called for HARD_DECLINE. "
            "AGENTS.md safety rule #3: hard declines must never be retried."
        )

    if attempt_number not in (1, 2, 3):
        raise ValueError(
            f"attempt_number must be 1, 2, or 3 — got {attempt_number}."
        )

    result = suggest_retry_time(
        category=category,
        attempt_number=attempt_number,
        from_dt=from_time,
        salary_credit_day=salary_credit_day,
        historical_surge_hour_ist=historical_surge_hour_ist,
    )

    # Enforce the invariant: result must always be in the future
    if result <= from_time:
        from datetime import timedelta
        result = from_time + timedelta(minutes=30)

    return result.astimezone(timezone.utc)
