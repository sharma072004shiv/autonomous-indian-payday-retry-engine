"""
app/scheduler/retry_scheduler.py
─────────────────────────────────
Autonomous background scheduler that polls for due retries and triggers
the mock executor.

The scheduler:
  - Runs as a background asyncio task started by app/main.py lifespan
  - Polls repo_transactions.list_due_retries() every N seconds
  - For each due retry, calls the mock executor
  - Updates transaction status and writes an audit entry
  - Never makes retry DECISIONS — those were made when the event arrived

Policy enforced here:
  - Skips any transaction whose retry_count is already >= max_retries
  - Skips any transaction not in RETRY_SCHEDULED status
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class RetryScheduler:
    """Background scheduler for autonomous retry execution."""

    def __init__(self, poll_interval_seconds: int = 60) -> None:
        self._poll_interval = poll_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            logger.debug("RetryScheduler already running")
            return
        self._running = True
        self._task = asyncio.ensure_future(self._poll_loop())
        logger.info(
            "RetryScheduler started (poll_interval=%ds)", self._poll_interval
        )

    def stop(self) -> None:
        """Signal the loop to stop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("RetryScheduler stopped")

    async def _poll_loop(self) -> None:
        """Poll for due retries and execute them."""
        while self._running:
            try:
                await self._execute_due_retries()
            except Exception as exc:
                logger.error("RetryScheduler poll error: %s", exc, exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def _execute_due_retries(self) -> None:
        """Find all due retries and execute them via the mock executor."""
        from app.config import get_settings
        from app.db.repo_transactions import list_due_retries, update_transaction
        from app.db.repo_retries import update_retry_attempt, get_retry_attempts
        from app.db.repo_audit import append_audit_entry
        from app.executor.mock_razorpay import execute_payment
        from app.models.enums import ExecutionOutcome, TransactionStatus
        from app.models.audit import AuditEntry

        settings = get_settings()
        now = datetime.now(timezone.utc)
        due = await list_due_retries(as_of=now)

        if not due:
            return

        logger.info("RetryScheduler: %d retries due", len(due))

        for tx in due:
            # Safety: never exceed max retries
            if tx.retry_count >= settings.policy_max_retries:
                logger.warning(
                    "Skipping txn=%s: retry_count=%d already at max",
                    tx.transaction_id,
                    tx.retry_count,
                )
                continue

            attempt_number = tx.retry_count + 1
            executed_at = datetime.now(timezone.utc)

            # Mark in-progress
            in_progress = tx.model_copy(update={
                "status": TransactionStatus.RETRY_IN_PROGRESS,
                "updated_at": executed_at,
            })
            await update_transaction(in_progress)

            # Execute via mock
            outcome = await execute_payment(
                transaction_id=tx.transaction_id,
                amount_paise=tx.amount_paise,
                attempt_number=attempt_number,
            )

            # Update attempt record
            attempts = await get_retry_attempts(tx.transaction_id)
            pending = [a for a in attempts if a["outcome"] is None]
            if pending:
                await update_retry_attempt(
                    attempt_id=pending[-1]["attempt_id"],
                    executed_at=executed_at,
                    outcome=outcome,
                    diagnosis=f"Mock executor outcome: {outcome.value}",
                )

            # Update transaction status
            if outcome == ExecutionOutcome.SUCCESS:
                new_status = TransactionStatus.RECOVERED
            elif tx.retry_count + 1 >= settings.policy_max_retries:
                new_status = TransactionStatus.PERMANENTLY_FAILED
            else:
                new_status = TransactionStatus.FAILED

            final_tx = tx.model_copy(update={
                "status": new_status,
                "retry_count": tx.retry_count + 1,
                "last_retry_at": executed_at,
                "next_retry_at": None,
                "updated_at": executed_at,
            })
            await update_transaction(final_tx)

            # Audit the execution
            from app.models.enums import RetryDecision, FailureCategory
            audit = AuditEntry(
                audit_id=str(uuid.uuid4()),
                transaction_id=tx.transaction_id,
                event_id=f"scheduler-{tx.transaction_id}-attempt-{attempt_number}",
                decision=(
                    RetryDecision.APPROVE
                    if outcome == ExecutionOutcome.SUCCESS
                    else RetryDecision.REJECT
                ),
                failure_category=tx.failure_category or FailureCategory.HARD_DECLINE,
                policy_rule_applied=(
                    "EXECUTION_SUCCESS" if outcome == ExecutionOutcome.SUCCESS
                    else "EXECUTION_FAILURE"
                ),
                reason=f"Mock Razorpay execution: {outcome.value} for attempt {attempt_number}",
                llm_confidence=tx.llm_confidence,
                llm_rationale=None,
                retry_scheduled_at=None,
                retry_attempt_number=attempt_number,
                decided_at=executed_at,
            )
            await append_audit_entry(audit)

            logger.info(
                "RetryScheduler: txn=%s attempt=%d outcome=%s new_status=%s",
                tx.transaction_id,
                attempt_number,
                outcome.value,
                new_status.value,
            )
