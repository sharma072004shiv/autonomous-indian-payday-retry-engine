"""
app/models/enums.py
───────────────────
Shared enumerations used across models, policy, and LLM layers.

All values are strings so they serialise cleanly to/from JSON and SQLite.
"""

from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    """
    Top-level classification produced by the LLM classifier.

    AGENTS.md trust boundary: the LLM returns one of these values.
    The policy engine acts on it; the LLM never acts on its own output.
    """
    LIQUIDITY_TEMPORARY = "LIQUIDITY_TEMPORARY"
    BANK_SURGE_TEMPORARY = "BANK_SURGE_TEMPORARY"
    HARD_DECLINE = "HARD_DECLINE"


class RetryDecision(str, Enum):
    """
    Decision produced by the deterministic policy engine.

    APPROVE  — schedule a retry attempt
    REJECT   — block retry, record reason, do not reschedule
    DEFER    — delay retry (e.g. within-day surge window)
    """
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"


class TransactionStatus(str, Enum):
    """Lifecycle state of a payment transaction."""
    PENDING = "PENDING"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_IN_PROGRESS = "RETRY_IN_PROGRESS"
    RECOVERED = "RECOVERED"
    PERMANENTLY_FAILED = "PERMANENTLY_FAILED"


class ExecutionOutcome(str, Enum):
    """Result reported by the mock Razorpay executor."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
