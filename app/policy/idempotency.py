"""
app/policy/idempotency.py
─────────────────────────
Policy-layer idempotency check.

AGENTS.md safety rule #4: duplicate webhooks must be rejected so the same
failure event never triggers two retry schedules.

This module provides the pure-function policy check.  The authoritative
atomic DB operation is repo_retries.try_claim_event(), which uses an
INSERT OR IGNORE against the UNIQUE constraint on processed_events.event_id.

Separating the policy check from the DB operation allows the policy layer
to be unit-tested without a database fixture.
"""

from __future__ import annotations


def is_duplicate_event(already_processed: bool) -> bool:
    """
    Return True if this event has already been processed (i.e. is a duplicate).

    Parameters
    ----------
    already_processed : bool
        Pass the result of repo_retries.event_already_processed(event_id)
        for a read-only check, or the NEGATION of try_claim_event() for
        the atomic ingestion path.

    Returns
    -------
    bool
        True  → duplicate; the caller must reject this event.
        False → new event; the caller may proceed.
    """
    return already_processed
