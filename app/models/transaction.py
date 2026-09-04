"""
app/models/transaction.py
─────────────────────────
Pydantic models for payment transactions and failure events.

These are the primary domain objects.  Database repositories accept and
return these models; route handlers validate incoming payloads against them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import FailureCategory, TransactionStatus


class FailureEvent(BaseModel):
    """
    Represents a single failed payment attempt reported via webhook or
    injected by the benchmark dataset generator.

    This is the input to the retry engine.
    """

    event_id: str = Field(
        description="Unique identifier for this failure event (used for idempotency)"
    )
    transaction_id: str = Field(
        description="Identifier of the underlying payment transaction"
    )
    failure_code: str = Field(
        description="Raw failure code returned by the bank/NPCI (e.g. BANK_RESP_51_NO_FUNDS)"
    )
    amount_paise: int = Field(
        ge=0,
        description="Transaction amount in paise (100 paise = ₹1)",
    )
    customer_id: str = Field(description="Opaque identifier for the customer")
    mandate_id: Optional[str] = Field(
        default=None,
        description="Razorpay mandate ID for recurring payment mandates",
    )
    occurred_at: datetime = Field(
        description="UTC timestamp when the failure occurred"
    )
    raw_payload: Optional[dict] = Field(
        default=None,
        description="Original webhook payload stored for audit purposes",
    )

    @field_validator("failure_code")
    @classmethod
    def failure_code_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("failure_code must not be blank")
        return v.strip().upper()

    @field_validator("amount_paise")
    @classmethod
    def amount_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount_paise must be >= 0")
        return v

    @property
    def amount_rupees(self) -> float:
        return self.amount_paise / 100.0


class Transaction(BaseModel):
    """
    Full transaction record as stored in the database.

    Extends FailureEvent with lifecycle state, retry tracking, and
    the failure category assigned by the LLM classifier.
    """

    # Core identity (mirrors FailureEvent fields)
    transaction_id: str
    failure_code: str
    amount_paise: int = Field(ge=0)
    customer_id: str
    mandate_id: Optional[str] = None

    # Timestamps
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime

    # Lifecycle
    status: TransactionStatus = TransactionStatus.FAILED

    # LLM output (set after classification, before policy evaluation)
    failure_category: Optional[FailureCategory] = None
    llm_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Retry tracking
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: Optional[datetime] = None
    last_retry_at: Optional[datetime] = None

    @property
    def amount_rupees(self) -> float:
        return self.amount_paise / 100.0

    @model_validator(mode="after")
    def retry_count_within_hard_cap(self) -> "Transaction":
        # AGENTS.md safety rule #1: max 3 retries
        if self.retry_count > 3:
            raise ValueError(
                "retry_count exceeds hard cap of 3 (AGENTS.md safety rule #1)"
            )
        return self


class TransactionSummary(BaseModel):
    """Lightweight view returned by the retry status API endpoint."""

    transaction_id: str
    status: TransactionStatus
    failure_category: Optional[FailureCategory]
    retry_count: int
    next_retry_at: Optional[datetime]
    amount_rupees: float
