"""
app/services/payday_predictor.py
─────────────────────────────────
Deterministic timing predictor for the retry engine.

Responsibilities
────────────────
1. estimate_salary_credit_time()
   Given a transaction's estimated salary-credit day, return the UTC datetime
   of the expected next credit window.

2. suggest_liquidity_retry_time()
   For LIQUIDITY_TEMPORARY failures, return a retry time safely after the
   predicted salary credit (funds should be available then).

3. is_bank_surge_hour()
   Given a datetime, return whether it falls inside a known NPCI/bank surge
   window (peak hours in IST: 9–11 AM and 7–10 PM).

4. suggest_surge_free_retry_time()
   For BANK_SURGE_TEMPORARY failures, return the next datetime that is
   outside any known surge window.

5. suggest_retry_time()
   High-level dispatcher: given a FailureCategory and attempt_number,
   return the recommended retry datetime.

Design rules
────────────
- Deterministic: same inputs → same output (no random elements).
- No LLM calls, no database access, no network I/O.
- No payment scheduling or execution.
- All times are UTC-aware datetimes.
- IST = UTC+05:30 (hardcoded; India has no DST).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.enums import FailureCategory

# ── IST offset ────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# ── Surge window definition (IST hours, inclusive) ───────────────────────────
# Morning rush: 9 AM – 11:59 AM IST  (salary posting, auto-debit batch runs)
# Evening rush: 7 PM – 10:59 PM IST  (end-of-day settlement)
SURGE_WINDOWS_IST: list[tuple[int, int]] = [
    (9, 11),   # morning: hours 9, 10, 11
    (19, 22),  # evening: hours 19, 20, 21, 22
]

# ── Salary credit windows ─────────────────────────────────────────────────────
# Indian salary credits typically arrive between 8 AM and 12 PM IST
# on the salary credit day.
SALARY_CREDIT_HOUR_IST: int = 10  # assume mid-morning credit
SALARY_CREDIT_BUFFER_HOURS: int = 2  # wait 2 h after credit before retrying

# ── Retry back-off windows per category and attempt ──────────────────────────
# attempt_number is 1-indexed (1 = first retry, 2 = second, 3 = third).
# These are used when no richer timing signal is available.
_LIQUIDITY_BACKOFF_HOURS: dict[int, int] = {1: 2, 2: 6, 3: 12}
_SURGE_BACKOFF_HOURS: dict[int, int] = {1: 0, 2: 2, 3: 6}  # 0 = use surge-free window


def _to_ist(dt: datetime) -> datetime:
    """Convert any aware datetime to IST."""
    return dt.astimezone(IST)


def _to_utc(dt: datetime) -> datetime:
    """Convert any aware datetime to UTC."""
    return dt.astimezone(timezone.utc)


# ── Public helpers ────────────────────────────────────────────────────────────

def is_bank_surge_hour(dt: datetime) -> bool:
    """
    Return True if `dt` falls inside a known NPCI/bank surge window.

    Surge windows are defined in IST.  The function converts the input to
    IST before checking.

    Parameters
    ----------
    dt : datetime
        Any timezone-aware datetime.

    Returns
    -------
    bool
    """
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    ist_dt = _to_ist(dt)
    hour = ist_dt.hour
    for start, end in SURGE_WINDOWS_IST:
        if start <= hour <= end:
            return True
    return False


def next_surge_free_time(from_dt: datetime) -> datetime:
    """
    Return the next UTC datetime that is outside all surge windows.

    Steps forward in 30-minute increments until a non-surge slot is found.
    Maximum search window: 24 hours.  If no non-surge slot is found within
    24 hours (should never happen given our windows), returns from_dt + 12h.

    Parameters
    ----------
    from_dt : datetime
        Starting point (must be timezone-aware).

    Returns
    -------
    datetime (UTC)
    """
    if from_dt.tzinfo is None:
        raise ValueError("from_dt must be timezone-aware")

    candidate = from_dt
    step = timedelta(minutes=30)
    limit = from_dt + timedelta(hours=24)

    while candidate < limit:
        if not is_bank_surge_hour(candidate):
            return _to_utc(candidate)
        candidate += step

    # Fallback: 12 hours from now (very defensive)
    return _to_utc(from_dt + timedelta(hours=12))


def estimate_salary_credit_time(
    salary_credit_day: int,
    from_dt: datetime,
) -> datetime:
    """
    Estimate the UTC datetime of the next salary credit.

    Salary is expected on `salary_credit_day` of the month at
    SALARY_CREDIT_HOUR_IST (10 AM IST by default).

    If the estimated credit time is in the past relative to `from_dt`,
    the estimate is advanced to the same day next month.

    Parameters
    ----------
    salary_credit_day : int
        Day of month (1–31) when salary is typically credited.
    from_dt : datetime
        Reference time (must be timezone-aware).

    Returns
    -------
    datetime (UTC)
    """
    if from_dt.tzinfo is None:
        raise ValueError("from_dt must be timezone-aware")
    if not (1 <= salary_credit_day <= 31):
        raise ValueError(f"salary_credit_day must be 1–31, got {salary_credit_day}")

    from_ist = _to_ist(from_dt)

    # Try this month first
    try:
        credit_this_month = from_ist.replace(
            day=min(salary_credit_day, _days_in_month(from_ist.year, from_ist.month)),
            hour=SALARY_CREDIT_HOUR_IST,
            minute=0,
            second=0,
            microsecond=0,
        )
    except ValueError:
        # Day doesn't exist in this month; use last day
        credit_this_month = from_ist.replace(
            day=_days_in_month(from_ist.year, from_ist.month),
            hour=SALARY_CREDIT_HOUR_IST,
            minute=0,
            second=0,
            microsecond=0,
        )

    if credit_this_month > from_ist:
        return _to_utc(credit_this_month)

    # Credit this month has already passed — estimate next month
    next_month_year = from_ist.year + (1 if from_ist.month == 12 else 0)
    next_month = (from_ist.month % 12) + 1
    next_month_day = min(salary_credit_day, _days_in_month(next_month_year, next_month))

    credit_next_month = from_ist.replace(
        year=next_month_year,
        month=next_month,
        day=next_month_day,
        hour=SALARY_CREDIT_HOUR_IST,
        minute=0,
        second=0,
        microsecond=0,
    )
    return _to_utc(credit_next_month)


def suggest_liquidity_retry_time(
    salary_credit_day: int,
    from_dt: datetime,
    attempt_number: int = 1,
) -> datetime:
    """
    Suggest a retry time for LIQUIDITY_TEMPORARY failures.

    Strategy:
      - Attempt 1: retry SALARY_CREDIT_BUFFER_HOURS (2 h) after predicted
                   salary credit, but outside surge windows.
      - Attempt 2: 6 hours after the predicted credit.
      - Attempt 3: 12 hours after the predicted credit.

    Parameters
    ----------
    salary_credit_day : int
        Estimated day of month for salary credit.
    from_dt : datetime
        Current time (must be timezone-aware).
    attempt_number : int
        1-indexed retry attempt number (1, 2, or 3).

    Returns
    -------
    datetime (UTC)  — guaranteed to be after from_dt.
    """
    if attempt_number not in (1, 2, 3):
        raise ValueError(f"attempt_number must be 1–3, got {attempt_number}")

    credit_time = estimate_salary_credit_time(salary_credit_day, from_dt)
    buffer_hours = SALARY_CREDIT_BUFFER_HOURS + _LIQUIDITY_BACKOFF_HOURS.get(attempt_number, 2) - 2
    # Attempt 1 → credit + 2h, Attempt 2 → credit + 6h, Attempt 3 → credit + 12h
    buffer_hours = _LIQUIDITY_BACKOFF_HOURS[attempt_number]
    candidate = credit_time + timedelta(hours=buffer_hours)

    # Ensure we're not in a surge window
    if is_bank_surge_hour(candidate):
        candidate = next_surge_free_time(candidate)

    # Ensure candidate is strictly in the future
    if candidate <= from_dt:
        candidate = from_dt + timedelta(hours=buffer_hours)
        if is_bank_surge_hour(candidate):
            candidate = next_surge_free_time(candidate)

    return _to_utc(candidate)


def suggest_surge_free_retry_time(
    from_dt: datetime,
    attempt_number: int = 1,
    historical_surge_hour_ist: Optional[int] = None,
) -> datetime:
    """
    Suggest a retry time for BANK_SURGE_TEMPORARY failures.

    Strategy:
      - Always retry outside known surge windows.
      - Attempt 1: find the next non-surge slot from now.
      - Attempt 2: add 2 hours then find next non-surge slot.
      - Attempt 3: add 6 hours then find next non-surge slot.

    Parameters
    ----------
    from_dt : datetime
        Current time (must be timezone-aware).
    attempt_number : int
        1-indexed retry attempt number (1, 2, or 3).
    historical_surge_hour_ist : Optional[int]
        IST hour when surges have historically occurred for this transaction.
        If provided, an extra 1-hour margin is added past that hour.

    Returns
    -------
    datetime (UTC)
    """
    if attempt_number not in (1, 2, 3):
        raise ValueError(f"attempt_number must be 1–3, got {attempt_number}")

    extra_hours = _SURGE_BACKOFF_HOURS.get(attempt_number, 0)
    candidate = from_dt + timedelta(hours=extra_hours)

    # If historical surge hour is known, add margin past it
    if historical_surge_hour_ist is not None:
        candidate_ist = _to_ist(candidate)
        if candidate_ist.hour <= historical_surge_hour_ist:
            candidate = candidate + timedelta(hours=1)

    return next_surge_free_time(candidate)


def suggest_retry_time(
    category: FailureCategory,
    attempt_number: int,
    from_dt: datetime,
    salary_credit_day: Optional[int] = None,
    historical_surge_hour_ist: Optional[int] = None,
) -> datetime:
    """
    High-level dispatcher: return the recommended retry datetime.

    Parameters
    ----------
    category : FailureCategory
        Must be LIQUIDITY_TEMPORARY or BANK_SURGE_TEMPORARY.
        Raises ValueError for HARD_DECLINE.
    attempt_number : int
        1-indexed retry attempt number.
    from_dt : datetime
        Current time (must be timezone-aware).
    salary_credit_day : Optional[int]
        Required for LIQUIDITY_TEMPORARY. Day of month for salary credit.
    historical_surge_hour_ist : Optional[int]
        Optional for BANK_SURGE_TEMPORARY.

    Returns
    -------
    datetime (UTC)

    Raises
    ------
    ValueError
        If category is HARD_DECLINE (should never be called for hard declines).
    """
    if from_dt.tzinfo is None:
        raise ValueError("from_dt must be timezone-aware")

    if category == FailureCategory.HARD_DECLINE:
        raise ValueError(
            "suggest_retry_time must never be called for HARD_DECLINE. "
            "AGENTS.md safety rule #3: hard declines must never be retried."
        )

    if category == FailureCategory.LIQUIDITY_TEMPORARY:
        if salary_credit_day is None:
            # Fall back to standard back-off without payday optimisation
            hours = _LIQUIDITY_BACKOFF_HOURS.get(attempt_number, 2)
            candidate = from_dt + timedelta(hours=hours)
            if is_bank_surge_hour(candidate):
                candidate = next_surge_free_time(candidate)
            return _to_utc(candidate)
        return suggest_liquidity_retry_time(salary_credit_day, from_dt, attempt_number)

    if category == FailureCategory.BANK_SURGE_TEMPORARY:
        return suggest_surge_free_retry_time(
            from_dt, attempt_number, historical_surge_hour_ist
        )

    raise ValueError(f"Unhandled FailureCategory: {category}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given month."""
    import calendar
    return calendar.monthrange(year, month)[1]
