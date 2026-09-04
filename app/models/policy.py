"""
app/models/policy.py
────────────────────
Pydantic models for the deterministic policy engine's input and output.

AGENTS.md trust boundary:
  - RetryPolicyDecision is the ONLY output the policy engine produces.
  - The LLM has no field in this model — it cannot approve, schedule, or
    modify amounts.
  - The policy engine creates this model; it is consumed by the service
    layer to schedule retries and write audit entries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import FailureCategory, RetryDecision


class RetryPolicyDecision(BaseModel):
    """
    Result produced by the deterministic policy engine for a single failure event.

    This is the authoritative record of what the policy decided and why.
    It drives:
      - whether a retry is scheduled (retry_allowed)
      - when the retry fires (scheduled_at)
      - what audit trail entry is created (policy_rule, reason)

    The LLM contributes ONLY the failure_category and llm_rationale fields,
    both of which are read-only inputs to this model.  The LLM cannot set
    retry_allowed, scheduled_at, or retry_number.
    """

    # ── Core decision ─────────────────────────────────────────────────────
    transaction_id: str = Field(description="Transaction this decision applies to")
    event_id: str = Field(description="Failure event that triggered this decision")

    retry_allowed: bool = Field(
        description="True only when all guardrails pass and a retry is approved"
    )
    decision: RetryDecision = Field(
        description="APPROVE / REJECT / DEFER"
    )

    # ── Scheduling ────────────────────────────────────────────────────────
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description=(
            "UTC datetime the retry should execute. "
            "None when retry_allowed is False."
        ),
    )
    retry_number: int = Field(
        default=0,
        ge=0,
        description="Which retry attempt this will be (1-indexed, 0 = not scheduled)",
    )

    # ── Auditability ──────────────────────────────────────────────────────
    policy_rule: str = Field(
        description=(
            "Machine-readable name of the policy rule that produced this decision. "
            "Examples: HARD_DECLINE_BLOCK, MIN_AMOUNT_BLOCK, MAX_RETRIES_BLOCK, "
            "APPROVE_LIQUIDITY_TEMPORARY, APPROVE_BANK_SURGE_TEMPORARY, "
            "DUPLICATE_EVENT_BLOCK."
        )
    )
    reason: str = Field(
        description="Human-readable explanation of the decision."
    )

    # ── LLM input traceability (read-only — does NOT grant LLM authority) ─
    failure_category: FailureCategory = Field(
        description=(
            "Failure category determined by the LLM classifier. "
            "The policy engine uses this as INPUT only; the LLM does not "
            "set retry_allowed or scheduled_at."
        )
    )
    llm_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence reported by the LLM (stored for audit traceability).",
    )
    llm_rationale: Optional[str] = Field(
        default=None,
        description="Rationale from the LLM (stored for audit traceability only).",
    )

    @model_validator(mode="after")
    def scheduled_at_requires_retry_allowed(self) -> "RetryPolicyDecision":
        """
        Invariant: scheduled_at must be None when retry is not allowed,
        and must be set when retry IS allowed.
        """
        if self.retry_allowed and self.scheduled_at is None:
            raise ValueError(
                "scheduled_at must be set when retry_allowed is True"
            )
        if not self.retry_allowed and self.scheduled_at is not None:
            raise ValueError(
                "scheduled_at must be None when retry_allowed is False"
            )
        return self

    @model_validator(mode="after")
    def retry_number_requires_retry_allowed(self) -> "RetryPolicyDecision":
        if self.retry_allowed and self.retry_number == 0:
            raise ValueError(
                "retry_number must be >= 1 when retry_allowed is True"
            )
        if not self.retry_allowed and self.retry_number != 0:
            raise ValueError(
                "retry_number must be 0 when retry_allowed is False"
            )
        return self


class FailedTransactionEvent(BaseModel):
    """
    Domain model that bridges the synthetic dataset CSV fields and the
    FailureEvent webhook model.

    Used by the benchmark runner and dataset ingestion path.  Not used
    by the live webhook endpoint (which uses FailureEvent directly).
    """

    transaction_id: str
    customer_id: str
    amount_paise: int = Field(ge=0, description="Amount in paise (100 paise = ₹1)")
    payment_method: str
    failure_code: str
    failed_at: datetime
    salary_credit_date_estimated: int = Field(
        ge=1, le=31,
        description="Estimated day of month when salary is credited",
    )
    historical_bank_surge_hour: int = Field(
        ge=0, le=23,
        description="IST hour when bank/NPCI surges historically occur",
    )
    retry_count: int = Field(
        ge=0, le=3,
        description="Number of retry attempts already made",
    )

    @property
    def amount_rupees(self) -> float:
        return self.amount_paise / 100.0
