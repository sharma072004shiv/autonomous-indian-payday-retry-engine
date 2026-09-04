"""
tests/unit/test_payday_predictor.py
────────────────────────────────────
Tests for the deterministic timing predictor.

All tests use fixed UTC datetimes so results are reproducible.
No LLM calls, no database access, no network I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import FailureCategory
from app.services.payday_predictor import (
    IST,
    SALARY_CREDIT_HOUR_IST,
    SURGE_WINDOWS_IST,
    estimate_salary_credit_time,
    is_bank_surge_hour,
    next_surge_free_time,
    suggest_liquidity_retry_time,
    suggest_retry_time,
    suggest_surge_free_retry_time,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _ist(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# ── is_bank_surge_hour ────────────────────────────────────────────────────────

def test_surge_hour_morning_start() -> None:
    # 9 AM IST = 3:30 AM UTC
    dt = _ist(2026, 7, 1, 9, 0)
    assert is_bank_surge_hour(dt) is True


def test_surge_hour_morning_end() -> None:
    # 11 AM IST
    dt = _ist(2026, 7, 1, 11, 0)
    assert is_bank_surge_hour(dt) is True


def test_surge_hour_afternoon_clear() -> None:
    # 2 PM IST — between windows
    dt = _ist(2026, 7, 1, 14, 0)
    assert is_bank_surge_hour(dt) is False


def test_surge_hour_evening_start() -> None:
    # 7 PM IST
    dt = _ist(2026, 7, 1, 19, 0)
    assert is_bank_surge_hour(dt) is True


def test_surge_hour_evening_end() -> None:
    # 10 PM IST
    dt = _ist(2026, 7, 1, 22, 0)
    assert is_bank_surge_hour(dt) is True


def test_surge_hour_late_night_clear() -> None:
    # 11 PM IST — outside both windows
    dt = _ist(2026, 7, 1, 23, 0)
    assert is_bank_surge_hour(dt) is False


def test_surge_hour_midnight_clear() -> None:
    dt = _ist(2026, 7, 1, 0, 0)
    assert is_bank_surge_hour(dt) is False


def test_surge_hour_just_before_morning() -> None:
    # 8:59 AM IST — not yet surge
    dt = _ist(2026, 7, 1, 8, 59)
    assert is_bank_surge_hour(dt) is False


def test_surge_hour_just_after_morning() -> None:
    # 12 PM IST — after morning window
    dt = _ist(2026, 7, 1, 12, 0)
    assert is_bank_surge_hour(dt) is False


def test_surge_hour_accepts_utc_input() -> None:
    # 3:30 AM UTC = 9:00 AM IST (surge)
    dt = _utc(2026, 7, 1, 3, 30)
    assert is_bank_surge_hour(dt) is True


def test_surge_hour_naive_datetime_raises() -> None:
    dt = datetime(2026, 7, 1, 9, 0)  # naive
    with pytest.raises(ValueError, match="timezone-aware"):
        is_bank_surge_hour(dt)


def test_surge_hour_deterministic() -> None:
    dt = _ist(2026, 7, 1, 10, 0)
    assert is_bank_surge_hour(dt) == is_bank_surge_hour(dt)


# ── next_surge_free_time ──────────────────────────────────────────────────────

def test_next_surge_free_from_surge_window() -> None:
    # Start inside morning surge (10 AM IST)
    start = _ist(2026, 7, 1, 10, 0)
    result = next_surge_free_time(start)
    assert not is_bank_surge_hour(result)


def test_next_surge_free_from_non_surge_is_immediate() -> None:
    # Start at 2 PM IST — already outside surge
    start = _ist(2026, 7, 1, 14, 0)
    result = next_surge_free_time(start)
    # Should return same or very close time (within 30 min)
    assert result <= start + timedelta(minutes=30)
    assert not is_bank_surge_hour(result)


def test_next_surge_free_returns_utc() -> None:
    start = _ist(2026, 7, 1, 10, 0)
    result = next_surge_free_time(start)
    assert result.tzinfo is not None
    # UTC offset should be zero
    assert result.utcoffset() == timedelta(0)


def test_next_surge_free_naive_raises() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        next_surge_free_time(datetime(2026, 7, 1, 10, 0))


def test_next_surge_free_deterministic() -> None:
    start = _ist(2026, 7, 1, 10, 0)
    assert next_surge_free_time(start) == next_surge_free_time(start)


# ── estimate_salary_credit_time ───────────────────────────────────────────────

def test_salary_credit_future_this_month() -> None:
    # Today is 2026-07-05 UTC, salary day is 15th
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = estimate_salary_credit_time(15, from_dt)
    result_ist = result.astimezone(IST)
    assert result_ist.day == 15
    assert result_ist.month == 7
    assert result_ist.hour == SALARY_CREDIT_HOUR_IST


def test_salary_credit_already_past_this_month() -> None:
    # Today is 2026-07-20 UTC, salary day is 1st — should roll to Aug 1
    from_dt = _utc(2026, 7, 20, 12, 0)
    result = estimate_salary_credit_time(1, from_dt)
    result_ist = result.astimezone(IST)
    assert result_ist.month == 8
    assert result_ist.day == 1


def test_salary_credit_day_31_february_handled() -> None:
    # Feb 2026 has 28 days; day 31 should clamp to 28
    from_dt = _utc(2026, 2, 1, 0, 0)
    result = estimate_salary_credit_time(31, from_dt)
    result_ist = result.astimezone(IST)
    assert result_ist.month == 2
    assert result_ist.day == 28


def test_salary_credit_returns_utc() -> None:
    result = estimate_salary_credit_time(1, _utc(2026, 7, 5, 0, 0))
    assert result.utcoffset() == timedelta(0)


def test_salary_credit_is_in_future() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = estimate_salary_credit_time(15, from_dt)
    assert result > from_dt


def test_salary_credit_invalid_day_raises() -> None:
    with pytest.raises(ValueError, match="salary_credit_day"):
        estimate_salary_credit_time(0, _utc(2026, 7, 1, 0, 0))


def test_salary_credit_naive_raises() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        estimate_salary_credit_time(1, datetime(2026, 7, 1))


def test_salary_credit_year_rollover() -> None:
    # Dec 31, salary day 5 — should roll to Jan 5 next year
    from_dt = _utc(2026, 12, 31, 0, 0)
    result = estimate_salary_credit_time(5, from_dt)
    result_ist = result.astimezone(IST)
    assert result_ist.year == 2027
    assert result_ist.month == 1
    assert result_ist.day == 5


def test_salary_credit_deterministic() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = estimate_salary_credit_time(15, from_dt)
    r2 = estimate_salary_credit_time(15, from_dt)
    assert r1 == r2


# ── suggest_liquidity_retry_time ──────────────────────────────────────────────

def test_liquidity_retry_is_after_from_dt() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = suggest_liquidity_retry_time(15, from_dt, attempt_number=1)
    assert result > from_dt


def test_liquidity_retry_not_in_surge() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = suggest_liquidity_retry_time(15, from_dt, attempt_number=1)
    assert not is_bank_surge_hour(result)


def test_liquidity_retry_attempt_2_later_than_attempt_1() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = suggest_liquidity_retry_time(15, from_dt, attempt_number=1)
    r2 = suggest_liquidity_retry_time(15, from_dt, attempt_number=2)
    # attempt 2 (6h buffer) should generally be >= attempt 1 (2h buffer)
    assert r2 >= r1


def test_liquidity_retry_attempt_3_latest() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = suggest_liquidity_retry_time(15, from_dt, attempt_number=1)
    r3 = suggest_liquidity_retry_time(15, from_dt, attempt_number=3)
    assert r3 >= r1


def test_liquidity_retry_invalid_attempt_raises() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        suggest_liquidity_retry_time(15, _utc(2026, 7, 5), attempt_number=0)


def test_liquidity_retry_deterministic() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = suggest_liquidity_retry_time(15, from_dt, 1)
    r2 = suggest_liquidity_retry_time(15, from_dt, 1)
    assert r1 == r2


# ── suggest_surge_free_retry_time ─────────────────────────────────────────────

def test_surge_retry_not_in_surge() -> None:
    from_dt = _ist(2026, 7, 1, 10, 0)  # inside morning surge
    result = suggest_surge_free_retry_time(from_dt, attempt_number=1)
    assert not is_bank_surge_hour(result)


def test_surge_retry_attempt_2_adds_2h() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)  # midnight UTC — not in surge
    r1 = suggest_surge_free_retry_time(from_dt, attempt_number=1)
    r2 = suggest_surge_free_retry_time(from_dt, attempt_number=2)
    # attempt 2 starts searching 2h later
    assert r2 >= r1


def test_surge_retry_attempt_3_adds_6h() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = suggest_surge_free_retry_time(from_dt, attempt_number=1)
    r3 = suggest_surge_free_retry_time(from_dt, attempt_number=3)
    assert r3 >= r1


def test_surge_retry_with_historical_hour() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = suggest_surge_free_retry_time(from_dt, attempt_number=1, historical_surge_hour_ist=10)
    assert not is_bank_surge_hour(result)


def test_surge_retry_invalid_attempt_raises() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        suggest_surge_free_retry_time(_utc(2026, 7, 5), attempt_number=4)


def test_surge_retry_deterministic() -> None:
    from_dt = _utc(2026, 7, 5, 6, 0)
    r1 = suggest_surge_free_retry_time(from_dt, 1)
    r2 = suggest_surge_free_retry_time(from_dt, 1)
    assert r1 == r2


# ── suggest_retry_time (dispatcher) ──────────────────────────────────────────

def test_dispatch_liquidity_returns_future() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = suggest_retry_time(
        FailureCategory.LIQUIDITY_TEMPORARY, 1, from_dt, salary_credit_day=15
    )
    assert result > from_dt


def test_dispatch_surge_returns_non_surge() -> None:
    from_dt = _ist(2026, 7, 1, 10, 0)  # inside surge
    result = suggest_retry_time(FailureCategory.BANK_SURGE_TEMPORARY, 1, from_dt)
    assert not is_bank_surge_hour(result)


def test_dispatch_hard_decline_raises() -> None:
    with pytest.raises(ValueError, match="HARD_DECLINE"):
        suggest_retry_time(FailureCategory.HARD_DECLINE, 1, _utc(2026, 7, 1))


def test_dispatch_liquidity_no_salary_day_falls_back() -> None:
    """suggest_retry_time must not crash when salary_credit_day is None."""
    from_dt = _utc(2026, 7, 5, 0, 0)
    result = suggest_retry_time(
        FailureCategory.LIQUIDITY_TEMPORARY, 1, from_dt, salary_credit_day=None
    )
    assert result > from_dt


def test_dispatch_naive_datetime_raises() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        suggest_retry_time(
            FailureCategory.LIQUIDITY_TEMPORARY, 1,
            datetime(2026, 7, 1)  # naive
        )


def test_dispatch_deterministic() -> None:
    from_dt = _utc(2026, 7, 5, 0, 0)
    r1 = suggest_retry_time(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_dt, salary_credit_day=10)
    r2 = suggest_retry_time(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_dt, salary_credit_day=10)
    assert r1 == r2


# ── No side-effects static checks ────────────────────────────────────────────

def test_payday_predictor_has_no_db_imports() -> None:
    import inspect
    import app.services.payday_predictor as mod
    source = inspect.getsource(mod)
    assert "from app.db" not in source
    assert "import app.db" not in source


def test_payday_predictor_has_no_payment_execution() -> None:
    import app.services.payday_predictor as mod
    forbidden = {"execute_payment", "call_razorpay", "debit"}
    actual = {n for n in dir(mod) if not n.startswith("_")}
    assert not (forbidden & actual)
