"""
app/main.py
───────────
FastAPI application factory.

Responsibilities:
- Create and configure the FastAPI app instance
- Register routers (added as each module is implemented)
- Manage application lifespan (startup / shutdown hooks)
- Expose a /health endpoint for basic liveness checks

This file must stay thin.  No business logic lives here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.connection import close_database, init_database

logger = logging.getLogger(__name__)

# Module-level scheduler instance (started/stopped in lifespan)
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan manager.

    Startup tasks (before yield):
    - Configure logging
    - Initialise database (added in Step 2)
    - Start background scheduler (added in Step 6)

    Shutdown tasks (after yield):
    - Stop scheduler gracefully
    - Close database connections
    """
    settings = get_settings()

    # Configure root logger
    logging.basicConfig(
        level=settings.app_log_level.value,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    logger.info(
        "PayDay Retry Engine starting",
        extra={
            "env": settings.app_env.value,
            "debug": settings.app_debug,
            "llm_use_mock": settings.llm_use_mock,
        },
    )

    # ── Startup hooks ─────────────────────────────────────────────────────
    await init_database()          # Step 2 ✓

    if settings.scheduler_enabled:
        global _scheduler
        from app.scheduler.retry_scheduler import RetryScheduler
        _scheduler = RetryScheduler(
            poll_interval_seconds=settings.scheduler_poll_interval_seconds
        )
        _scheduler.start()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    if _scheduler is not None:
        _scheduler.stop()
    await close_database()         # Step 2 ✓

    logger.info("PayDay Retry Engine shut down cleanly")


def create_app() -> FastAPI:
    """
    Construct and return the configured FastAPI application.

    Import and call this in tests and in the uvicorn entry point.
    Every call returns a fully wired app including the /health route,
    so tests that call create_app() get an identical app to `uvicorn app.main:app`.
    """
    settings = get_settings()

    application = FastAPI(
        title="Autonomous Indian PayDay & Mandate Retry Engine",
        description=(
            "AI-augmented fintech retry engine for failed recurring payment "
            "transactions in India. Built for the Razorpay AI Buildathon.\n\n"
            "**Trust boundary**: The LLM classifies failures only. "
            "All retry decisions are made by deterministic Python policy logic."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    # Allow the Vite dev server (localhost:5173) and any other local origin.
    # In production this list should be restricted.
    _cors_origins = ["http://localhost:5173", "http://localhost:5174",
                     "http://127.0.0.1:5173", "http://127.0.0.1:5174",
                     "http://localhost:3000", "http://127.0.0.1:3000"]
    if settings.app_debug:
        _cors_origins = ["*"]

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Built-in routes ────────────────────────────────────────────────────

    @application.get("/health", tags=["Health"], summary="Liveness check")
    async def health_check() -> JSONResponse:
        """
        Returns 200 OK with basic runtime info.

        This endpoint is always available and has no auth requirement.
        It does NOT check database connectivity or scheduler status yet;
        those will be added when those components are implemented.
        """
        s = get_settings()
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": "payday-retry-engine",
                "version": "0.1.0",
                "env": s.app_env.value,
                "llm_use_mock": s.llm_use_mock,
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────
    from app.routes.webhooks import router as webhooks_router
    from app.routes.retries  import router as retries_router
    from app.routes.audit    import router as audit_router
    from app.routes.metrics  import router as metrics_router
    application.include_router(webhooks_router, prefix="/api/v1")
    application.include_router(retries_router,  prefix="/api/v1")
    application.include_router(audit_router,    prefix="/api/v1")
    application.include_router(metrics_router,  prefix="/api/v1")

    return application


# ── Module-level app instance ─────────────────────────────────────────────────
# Used by:  uvicorn app.main:app
# Tests should call create_app() directly to get a fresh instance.
app = create_app()
