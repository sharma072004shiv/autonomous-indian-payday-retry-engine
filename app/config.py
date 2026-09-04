"""
app/config.py
─────────────
Application settings loaded exclusively from environment variables or a .env
file.  No secrets or defaults with real values are stored here.

All modules must import `get_settings()` and never instantiate Settings
directly, so the singleton is cached and the .env file is read only once.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    GROQ = "groq"


class Settings(BaseSettings):
    """
    All configuration for the PayDay Retry Engine.

    Values are read from environment variables first, then from a .env file in
    the project root.  The .env file must never be committed to version control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: AppEnv = Field(default=AppEnv.DEVELOPMENT, description="Runtime environment")
    app_debug: bool = Field(default=False, description="Enable debug mode")
    app_log_level: LogLevel = Field(default=LogLevel.INFO, description="Log verbosity")

    # ── Database ─────────────────────────────────────────────────────────────
    database_path: str = Field(
        default="./data/payday_engine.db",
        description="Path to the SQLite database file",
    )

    # ── LLM / PydanticAI ─────────────────────────────────────────────────────
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="LLM provider used by PydanticAI",
    )
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    gemini_api_key: str = Field(default="", description="Gemini API key")
    llm_model: str = Field(default="gpt-4o-mini", description="Model name for PydanticAI")
    llm_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description="Seconds before LLM call times out and falls back to HARD_DECLINE",
    )
    llm_use_mock: bool = Field(
        default=False,
        description="Use deterministic mock classifier instead of a real LLM",
    )

    # ── Retry Policy ─────────────────────────────────────────────────────────
    policy_max_retries: int = Field(
        default=3,
        ge=1,
        le=3,
        description="Hard cap on retries per transaction",
    )
    policy_min_amount_paise: int = Field(
        default=10_000,
        ge=1,
        description="Minimum transaction amount in paise below which retries are blocked",
    )

    # ── Scheduler ────────────────────────────────────────────────────────────
    scheduler_poll_interval_seconds: int = Field(
        default=60,
        ge=5,
        description="How often the retry scheduler polls for due retries",
    )
    scheduler_enabled: bool = Field(
        default=True,
        description="Enable or disable the background retry scheduler",
    )

    # ── Mock Razorpay Executor ───────────────────────────────────────────────
    mock_executor_success_rate: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description="Simulated success probability for mock payment attempts",
    )
    mock_executor_seed: int = Field(
        default=42,
        description="RNG seed for deterministic mock executor behaviour",
    )

    # ── Derived helpers ──────────────────────────────────────────────────────
    @property
    def is_test(self) -> bool:
        """True when running under pytest or APP_ENV=test."""
        return self.app_env == AppEnv.TEST

    @property
    def policy_min_amount_rupees(self) -> float:
        """Minimum amount expressed in rupees (convenience property)."""
        return self.policy_min_amount_paise / 100.0

    @field_validator("policy_max_retries")
    @classmethod
    def max_retries_must_not_exceed_hard_cap(cls, v: int) -> int:
        """
        AGENTS.md safety rule #1: maximum 3 retries.
        This validator ensures the environment cannot silently raise the cap.
        """
        if v > 3:
            raise ValueError(
                "policy_max_retries cannot exceed 3 (AGENTS.md safety rule #1)"
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    Call this everywhere instead of constructing Settings() directly.
    The cache means .env is read exactly once per process.

    In tests, call get_settings.cache_clear() after monkeypatching env vars.
    """
    return Settings()
