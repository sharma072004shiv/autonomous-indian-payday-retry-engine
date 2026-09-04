"""
app/services/ingestion_service.py
──────────────────────────────────
Batch CSV ingestion for the synthetic dataset.

Reuses the same pipeline as the live webhook:
  classify → policy evaluate → schedule/reject → audit

This ensures CSV and webhook processing are never divergent.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.models.transaction import FailureEvent
from app.services.retry_service import handle_failure_event

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "transaction_id", "customer_id", "amount",
    "failure_code", "failed_at",
}


async def ingest_csv(
    csv_path: Path,
    salary_credit_day: Optional[int] = None,
) -> dict:
    """
    Ingest a CSV file of failed transactions through the full pipeline.

    Parameters
    ----------
    csv_path : Path
        Path to the CSV file (must match the schema produced by generate_data.py).
    salary_credit_day : Optional[int]
        Default salary credit day for all records that don't supply their own.

    Returns
    -------
    dict — processing summary with counts.

    ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
    """
    total = valid = invalid = approved = rejected = hard_decline = 0
    below_threshold = max_retry_blocked = duplicate = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)

    for i, row in enumerate(rows):
        # Validate row
        try:
            occurred_at = datetime.fromisoformat(row["failed_at"])
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)

            amount_paise = int(row["amount"])
            event = FailureEvent(
                event_id=f"csv-{row['transaction_id']}-{i}",
                transaction_id=row["transaction_id"],
                failure_code=row["failure_code"],
                amount_paise=amount_paise,
                customer_id=row["customer_id"],
                occurred_at=occurred_at,
            )
        except (ValidationError, KeyError, ValueError) as exc:
            invalid += 1
            logger.debug("CSV row %d invalid: %s", i, exc)
            continue

        valid += 1

        # Use per-row salary day if available
        row_salary_day = salary_credit_day
        if "salary_credit_date_estimated" in row:
            try:
                row_salary_day = int(row["salary_credit_date_estimated"])
            except (ValueError, TypeError):
                pass

        row_surge_hour: Optional[int] = None
        if "historical_bank_surge_hour" in row:
            try:
                row_surge_hour = int(row["historical_bank_surge_hour"])
            except (ValueError, TypeError):
                pass

        audit = await handle_failure_event(
            event,
            salary_credit_day=row_salary_day,
            historical_surge_hour_ist=row_surge_hour,
        )

        rule = audit.policy_rule_applied
        if rule == "DUPLICATE_EVENT_BLOCK":
            duplicate += 1
            rejected += 1
        elif audit.retry_allowed if hasattr(audit, "retry_allowed") else (
            audit.decision.value == "APPROVE"
        ):
            approved += 1
        else:
            rejected += 1
            if rule == "HARD_DECLINE_BLOCK":
                hard_decline += 1
            elif rule == "MIN_AMOUNT_BLOCK":
                below_threshold += 1
            elif rule == "MAX_RETRIES_BLOCK":
                max_retry_blocked += 1

    return {
        "note": "SYNTHETIC SIMULATION — NOT REAL-WORLD DATA",
        "csv_path": str(csv_path),
        "total_records": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "eligible_for_retry": approved,
        "blocked": rejected,
        "hard_declines": hard_decline,
        "below_threshold": below_threshold,
        "max_retry_blocked": max_retry_blocked,
        "duplicate_rejected": duplicate,
    }
