"""
app/routes/retries.py
──────────────────────
FastAPI router for retry status queries.

GET /api/v1/retries/{transaction_id}
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.db.repo_transactions import get_transaction
from app.db.repo_retries import get_retry_attempts

router = APIRouter(prefix="/retries", tags=["Retries"])


@router.get(
    "/{transaction_id}",
    summary="Get retry status for a transaction",
)
async def get_retry_status(transaction_id: str) -> JSONResponse:
    """
    Return the current status, retry count, and scheduled retry time
    for a transaction.
    """
    tx = await get_transaction(transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found",
        )

    attempts = await get_retry_attempts(transaction_id)

    return JSONResponse(
        status_code=200,
        content={
            "transaction_id": tx.transaction_id,
            "status": tx.status.value,
            "failure_category": (
                tx.failure_category.value if tx.failure_category else None
            ),
            "retry_count": tx.retry_count,
            "next_retry_at": (
                tx.next_retry_at.isoformat() if tx.next_retry_at else None
            ),
            "last_retry_at": (
                tx.last_retry_at.isoformat() if tx.last_retry_at else None
            ),
            "amount_rupees": tx.amount_rupees,
            "attempts": [
                {
                    "attempt_number": a["attempt_number"],
                    "scheduled_at": a["scheduled_at"],
                    "executed_at": a["executed_at"],
                    "outcome": a["outcome"],
                    "diagnosis": a["diagnosis"],
                }
                for a in attempts
            ],
        },
    )
