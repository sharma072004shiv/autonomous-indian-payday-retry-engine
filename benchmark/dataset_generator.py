"""
benchmark/dataset_generator.py
────────────────────────────────
Generates the deterministic 1,000-record synthetic dataset as FailureEvent
objects for use by the benchmark runners.

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing from project root when run as a script
sys.path.insert(0, str(Path(__file__).parents[1]))

from data.generate_data import generate_dataset as _generate_raw
from app.models.transaction import FailureEvent
from datetime import datetime, timezone

DATASET_SIZE: int = 1_000
DATASET_SEED: int = 42


def generate_dataset(seed: int = DATASET_SEED, n: int = DATASET_SIZE) -> list[FailureEvent]:
    """
    Return n deterministic FailureEvent objects for the benchmark.

    Uses data/generate_data.py as the canonical generator so that the
    benchmark and CSV ingestion always use identical records.
    """
    raw = _generate_raw(seed=seed, n=n)
    events: list[FailureEvent] = []
    for i, r in enumerate(raw):
        occurred_at = datetime.fromisoformat(r["failed_at"])
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        events.append(
            FailureEvent(
                event_id=f"bench-{r['transaction_id']}-{i}",
                transaction_id=r["transaction_id"],
                failure_code=r["failure_code"],
                amount_paise=int(r["amount"]),
                customer_id=r["customer_id"],
                occurred_at=occurred_at,
            )
        )
    return events
