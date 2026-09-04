"""
app/models/audit.py
───────────────────
Pydantic model for immutable audit log entries.

Every retry decision (APPROVE / REJECT / DEFER) must produce one AuditEntry.
The database repository appends entries; it never updates or deletes them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import FailureCategory, RetryDecision


class AuditEntry(BaseModel):
    """
    Immutable record of a single retry decision made by the policy engine.

    Fields are intentionally append-only.  Nothing in the system should
    ever mutate an existing AuditEntry after it is written.
    """

    audit_id: str = Field(description="UUID for this audit entry")
    transaction_id: str = Field(description="Transaction this decision relates to")
    event_id: str = Field(description="FailureEvent that triggered this decision")

    # Decision context
    decision: RetryDecision
    failure_category: FailureCategory
    policy_rule_applied: str = Field(
        description=(
            "Human-readable name of the policy rule that produced this decision, "
            "e.g. 'HARD_DECLINE_BLOCK', 'MIN_AMOUNT_BLOCK', 'MAX_RETRIES_BLOCK', "
            "'APPROVE_LIQUIDITY_TEMPORARY'"
        )
    )
    reason: str = Field(
        description="Free-text explanation of why this decision was made"
    )

    # LLM input traceability
    llm_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score from the LLM classifier",
    )
    llm_rationale: Optional[str] = Field(
        default=None,
        description="Rationale string returned by the LLM (for traceability only)",
    )

    # Retry scheduling output
    retry_scheduled_at: Optional[datetime] = Field(
        default=None,
        description="UTC time the retry was scheduled for (None if REJECT/DEFER)",
    )
    retry_attempt_number: int = Field(
        default=0,
        ge=0,
        description="Which retry attempt number this is (0 = first attempt)",
    )

    # Timestamp
    decided_at: datetime = Field(description="UTC timestamp when the decision was made")
