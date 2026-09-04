"""
tests/unit/test_config.py
─────────────────────────
Unit tests for app/config.py.

These tests verify that:
  - Settings loads with defaults when no .env file is present
  - The policy_max_retries hard cap validator fires correctly
  - Derived properties return correct values
  - get_settings() returns a singleton
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import AppEnv, LogLevel, Settings, get_settings


def test_default_settings_load() -> None:
    """
    Settings should load DEVELOPMENT defaults when constructed with explicit values.

    We pass the environment fields explicitly to avoid picking up APP_ENV=test
    that may be set in the shell running the test suite.
    """
    s = Settings(
        app_env=AppEnv.DEVELOPMENT,
        app_debug=False,
        llm_use_mock=False,
        scheduler_enabled=True,
    )
    assert s.app_env == AppEnv.DEVELOPMENT
    assert s.app_debug is False
    assert s.app_log_level == LogLevel.INFO
    assert s.policy_max_retries == 3
    assert s.policy_min_amount_paise == 10_000
    assert s.scheduler_enabled is True
    assert s.llm_use_mock is False


def test_policy_min_amount_rupees_conversion() -> None:
    """10_000 paise should equal ₹100.00."""
    s = Settings()
    assert s.policy_min_amount_rupees == 100.0


def test_policy_min_amount_custom() -> None:
    """Custom paise value should convert correctly."""
    s = Settings(policy_min_amount_paise=25000)
    assert s.policy_min_amount_rupees == 250.0


def test_is_test_false_by_default() -> None:
    """is_test should be False when app_env is set to DEVELOPMENT explicitly."""
    s = Settings(app_env=AppEnv.DEVELOPMENT)
    assert s.is_test is False


def test_is_test_true_when_env_is_test() -> None:
    """is_test should be True when APP_ENV=test."""
    s = Settings(app_env=AppEnv.TEST)
    assert s.is_test is True


def test_max_retries_hard_cap_enforced() -> None:
    """policy_max_retries > 3 must raise a ValidationError (enforced by le=3 constraint)."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(policy_max_retries=4)
    # Pydantic v2 fires the le=3 Field constraint; confirm it catches the value
    assert "policy_max_retries" in str(exc_info.value)
    assert "4" in str(exc_info.value)


def test_max_retries_at_cap_is_valid() -> None:
    """policy_max_retries == 3 is the boundary; must be accepted."""
    s = Settings(policy_max_retries=3)
    assert s.policy_max_retries == 3


def test_get_settings_returns_singleton() -> None:
    """get_settings() must return the same cached instance on repeated calls."""
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_mock_executor_success_rate_bounds() -> None:
    """Success rate must be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        Settings(mock_executor_success_rate=1.5)
    with pytest.raises(ValidationError):
        Settings(mock_executor_success_rate=-0.1)


def test_llm_timeout_minimum() -> None:
    """LLM timeout must be >= 1 second."""
    with pytest.raises(ValidationError):
        Settings(llm_timeout_seconds=0)
