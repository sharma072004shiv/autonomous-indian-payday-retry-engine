"""
app/routes/metrics.py
─────────────────────
FastAPI router for aggregate metrics.

GET /api/v1/metrics
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.metrics_service import compute_metrics

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get(
    "",
    summary="Get aggregate engine metrics",
)
async def get_metrics() -> JSONResponse:
    """
    Return aggregate counts and rates for the retry engine.

    ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
    All numbers reflect the synthetic test dataset, not real transactions.
    """
    m = await compute_metrics()
    return JSONResponse(status_code=200, content=m)
