"""
app/routes/audit.py
────────────────────
FastAPI router for audit trail queries.

GET /api/v1/audit/{transaction_id}
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.services.audit_service import fetch_audit_trail

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get(
    "/{transaction_id}",
    summary="Get the full audit trail for a transaction",
)
async def get_audit(transaction_id: str) -> JSONResponse:
    """
    Return all audit entries for a transaction, ordered by decided_at.
    """
    trail = await fetch_audit_trail(transaction_id)
    return JSONResponse(
        status_code=200,
        content={
            "transaction_id": transaction_id,
            "total_entries": len(trail),
            "entries": [
                {
                    "audit_id": e.audit_id,
                    "event_id": e.event_id,
                    "decision": e.decision.value,
                    "failure_category": e.failure_category.value,
                    "policy_rule_applied": e.policy_rule_applied,
                    "reason": e.reason,
                    "llm_confidence": e.llm_confidence,
                    "retry_scheduled_at": (
                        e.retry_scheduled_at.isoformat()
                        if e.retry_scheduled_at
                        else None
                    ),
                    "retry_attempt_number": e.retry_attempt_number,
                    "decided_at": e.decided_at.isoformat(),
                }
                for e in trail
            ],
        },
    )
