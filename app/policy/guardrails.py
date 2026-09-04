"""
app/policy/guardrails.py
────────────────────────
Deterministic guardrail checks enforcing AGENTS.md safety rules.

These are pure functions — no side effects, no DB, no LLM, no scheduling.
Every function returns (allowed: bool, reason: str).

Rules enforced here (AGENTS.md):
  Rule #1 — Maximum 3 retries per transaction.
  Rule #2 — Transactions below ₹100 (10,000 paise) must not be retried.
  Rule #3 — HARD_DECLINE transactions must never be retried.
  Rule #4 — Duplicate webhooks must be rejected (policy layer check only;
             DB-level atomicity is in repo_retries.try_claim_event).
"""

from __future__ import annotations

from app.models.enums import FailureCategory

# Policy rule name constants — used in RetryPolicyDecision.policy_rule and AuditEntry
RULE_HARD_DECLINE_BLOCK = "HARD_DECLINE_BLOCK"
RULE_MIN_AMOUNT_BLOCK = "MIN_AMOUNT_BLOCK"
RULE_MAX_RETRIES_BLOCK = "MAX_RETRIES_BLOCK"
RULE_DUPLICATE_EVENT_BLOCK = "DUPLICATE_EVENT_BLOCK"
RULE_APPROVE_LIQUIDITY = "APPROVE_LIQUIDITY_TEMPORARY"
RULE_APPROVE_SURGE = "APPROVE_BANK_SURGE_TEMPORARY"


def check_hard_decline(category: FailureCategory) -> tuple[bool, str]:
    """
    AGENTS.md safety rule #3: HARD_DECLINE transactions must never be retried.

    Parameters
    ----------
    category : FailureCategory
        The failure category determined by the LLM classifier.

    Returns
    -------
    (True, "")   — category is not HARD_DECLINE; retry is allowed by this rule.
    (False, reason) — category is HARD_DECLINE; retry must be blocked.
    """
    if category == FailureCategory.HARD_DECLINE:
        return (
            False,
            "Failure classified as HARD_DECLINE. "
            "This is a permanent or irrecoverable decline. "
            "Retrying will not resolve it (AGENTS.md rule #3).",
        )
    return True, ""


def check_min_amount(amount_paise: int, min_amount_paise: int = 10_000) -> tuple[bool, str]:
    """
    AGENTS.md safety rule #2: transactions below ₹100 must not be retried.

    Parameters
    ----------
    amount_paise : int
        Transaction amount in paise (100 paise = ₹1).
    min_amount_paise : int
        Minimum allowed amount in paise.  Default 10,000 (= ₹100).

    Returns
    -------
    (True, "")      — amount meets or exceeds threshold.
    (False, reason) — amount is below threshold; retry must be blocked.
    """
    if amount_paise < 0:
        return (
            False,
            f"Amount {amount_paise} paise is negative — invalid transaction.",
        )
    if amount_paise < min_amount_paise:
        amount_rupees = amount_paise / 100.0
        threshold_rupees = min_amount_paise / 100.0
        return (
            False,
            f"Transaction amount ₹{amount_rupees:.2f} is below the minimum "
            f"retry threshold of ₹{threshold_rupees:.2f} "
            "(AGENTS.md rule #2). Retry not economical.",
        )
    return True, ""


def check_max_retries(retry_count: int, max_retries: int = 3) -> tuple[bool, str]:
    """
    AGENTS.md safety rule #1: maximum 3 retries per transaction.

    Parameters
    ----------
    retry_count : int
        Number of retry attempts already made (0 = no retries yet).
    max_retries : int
        Hard cap.  Must not exceed 3 (enforced in Settings).

    Returns
    -------
    (True, "")      — retry count is below the cap.
    (False, reason) — cap reached or exceeded; retry must be blocked.
    """
    if max_retries > 3:
        # Safety net: never allow callers to silently raise the cap above 3.
        raise ValueError(
            f"max_retries={max_retries} exceeds the hard cap of 3 "
            "(AGENTS.md safety rule #1)."
        )
    if retry_count >= max_retries:
        return (
            False,
            f"Retry count {retry_count} has reached the maximum of {max_retries}. "
            "No further retries are permitted (AGENTS.md rule #1).",
        )
    return True, ""


def check_duplicate_event(already_processed: bool) -> tuple[bool, str]:
    """
    AGENTS.md safety rule #4: duplicate webhook events must be rejected.

    This is the policy-layer check.  The authoritative atomic DB-level guard
    is repo_retries.try_claim_event().  This function makes the rule explicit
    in the policy layer for traceability and testability.

    Parameters
    ----------
    already_processed : bool
        Result of repo_retries.event_already_processed() or the return value
        from try_claim_event() (True = new, False = duplicate).

    Returns
    -------
    (True, "")      — event is new; processing may proceed.
    (False, reason) — event is a duplicate; must not be processed again.
    """
    if already_processed:
        return (
            False,
            "This failure event has already been processed. "
            "Duplicate webhook rejected (AGENTS.md rule #4).",
        )
    return True, ""


def run_all_guardrails(
    category: FailureCategory,
    amount_paise: int,
    retry_count: int,
    already_processed: bool = False,
    max_retries: int = 3,
    min_amount_paise: int = 10_000,
) -> tuple[bool, str, str]:
    """
    Run all guardrail checks in priority order.

    Evaluation order (first failure wins):
      1. Duplicate event check
      2. Hard-decline check
      3. Minimum amount check
      4. Maximum retry count check

    Parameters
    ----------
    category : FailureCategory
    amount_paise : int
    retry_count : int
    already_processed : bool
    max_retries : int
    min_amount_paise : int

    Returns
    -------
    (allowed: bool, reason: str, policy_rule: str)
        allowed     — True only when all checks pass.
        reason      — Human-readable explanation.
        policy_rule — Machine-readable rule name (one of the RULE_* constants).
    """
    # 1. Duplicate event
    allowed, reason = check_duplicate_event(already_processed)
    if not allowed:
        return False, reason, RULE_DUPLICATE_EVENT_BLOCK

    # 2. Hard decline
    allowed, reason = check_hard_decline(category)
    if not allowed:
        return False, reason, RULE_HARD_DECLINE_BLOCK

    # 3. Minimum amount
    allowed, reason = check_min_amount(amount_paise, min_amount_paise)
    if not allowed:
        return False, reason, RULE_MIN_AMOUNT_BLOCK

    # 4. Max retries
    allowed, reason = check_max_retries(retry_count, max_retries)
    if not allowed:
        return False, reason, RULE_MAX_RETRIES_BLOCK

    # All guardrails passed
    rule = (
        RULE_APPROVE_LIQUIDITY
        if category == FailureCategory.LIQUIDITY_TEMPORARY
        else RULE_APPROVE_SURGE
    )
    return True, "All guardrail checks passed. Retry approved.", rule
