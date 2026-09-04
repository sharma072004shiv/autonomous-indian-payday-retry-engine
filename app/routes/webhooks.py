"""
app/routes/webhooks.py
───────────────────────
FastAPI router for incoming payment failure webhooks.

POST /api/v1/webhook/payment-failed

This route handler:
  - Validates the incoming payload against FailureEvent
  - Delegates immediately to retry_service.handle_failure_event
  - Returns the AuditEntry created for the decision
  - Never contains business logic
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.models.transaction import FailureEvent
from app.services.retry_service import handle_failure_event

router = APIRouter(prefix="/webhook", tags=["Webhooks"])


@router.post(
    "/payment-failed",
    status_code=status.HTTP_200_OK,
    summary="Ingest a failed payment webhook",
    response_description="Audit entry for the retry decision made",
)
async def ingest_payment_failed(
    payload: FailureEvent,
    salary_credit_day: Optional[int] = Query(
        default=None,
        ge=1,
        le=31,
        description="Day of month when salary is typically credited (optional)",
    ),
    historical_surge_hour_ist: Optional[int] = Query(
        default=None,
        ge=0,
        le=23,
        description="IST hour when bank/NPCI surges historically occur (optional)",
    ),
) -> JSONResponse:
    """
    Process a failed payment event.

    - Validates the payload with Pydantic.
    - Rejects duplicate event_ids idempotently (returns 200 with duplicate notice).
    - Runs LLM classification → policy evaluation → schedules retry if approved.
    - Returns the audit entry for the decision.
    """
    audit = await handle_failure_event(
        payload,
        salary_credit_day=salary_credit_day,
        historical_surge_hour_ist=historical_surge_hour_ist,
    )
    return JSONResponse(
        status_code=200,
        content={
            "audit_id": audit.audit_id,
            "transaction_id": audit.transaction_id,
            "event_id": audit.event_id,
            "decision": audit.decision.value,
            "failure_category": audit.failure_category.value,
            "policy_rule_applied": audit.policy_rule_applied,
            "reason": audit.reason,
            "retry_scheduled_at": (
                audit.retry_scheduled_at.isoformat()
                if audit.retry_scheduled_at
                else None
            ),
            "retry_attempt_number": audit.retry_attempt_number,
            "decided_at": audit.decided_at.isoformat(),
        },
    )
