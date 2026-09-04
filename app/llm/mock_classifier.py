"""
app/llm/mock_classifier.py
──────────────────────────
Deterministic mock classifier used when:
  - LLM_USE_MOCK=true (dev / CI)
  - Any test that must not make real API calls

Maps known failure codes → categories without any network call.
Unknown codes → HARD_DECLINE (safe-fail behaviour per AGENTS.md).

This module is pure and side-effect-free.
"""

from __future__ import annotations

from app.models.enums import FailureCategory
from app.models.llm_output import LLMClassificationResult

# ── Canonical mapping ─────────────────────────────────────────────────────────
# Must match the examples in AGENTS.md and the synthetic dataset.
FAILURE_CODE_MAP: dict[str, FailureCategory] = {
    "BANK_RESP_51_NO_FUNDS":      FailureCategory.LIQUIDITY_TEMPORARY,
    "BANK_RESP_65_LIMIT_EXCEEDED": FailureCategory.LIQUIDITY_TEMPORARY,
    "NPCI_SURGE_TIMEOUT":         FailureCategory.BANK_SURGE_TEMPORARY,
    "BANK_UNAVAILABLE":           FailureCategory.BANK_SURGE_TEMPORARY,
    "MANDATE_EXPIRED":            FailureCategory.HARD_DECLINE,
    "ACCOUNT_FROZEN":             FailureCategory.HARD_DECLINE,
    "ACCOUNT_CLOSED":             FailureCategory.HARD_DECLINE,
    "INVALID_ACCOUNT":            FailureCategory.HARD_DECLINE,
    "DO_NOT_HONOUR":              FailureCategory.HARD_DECLINE,
}

# Human-readable rationales kept consistent for audit reproducibility
_RATIONALES: dict[FailureCategory, str] = {
    FailureCategory.LIQUIDITY_TEMPORARY: (
        "Failure code indicates a temporary insufficiency of funds. "
        "Recovery is likely after the next salary credit."
    ),
    FailureCategory.BANK_SURGE_TEMPORARY: (
        "Failure code indicates bank or NPCI infrastructure congestion. "
        "Retry outside the known surge window."
    ),
    FailureCategory.HARD_DECLINE: (
        "Failure code indicates a permanent or irrecoverable decline. "
        "No retry should be attempted."
    ),
}


def mock_classify_failure(failure_code: str) -> LLMClassificationResult:
    """
    Return a deterministic LLMClassificationResult for the given failure code.

    Parameters
    ----------
    failure_code : str
        Raw bank/NPCI failure code, e.g. "BANK_RESP_51_NO_FUNDS".
        Case-insensitive; normalised to upper-case internally.

    Returns
    -------
    LLMClassificationResult
        Always returns a fully valid, Pydantic-validated result.
        Unknown codes map to HARD_DECLINE with confidence=0.99.

    Notes
    -----
    - This function never makes network calls.
    - The returned object is always valid — it will never raise after creation.
    - Confidence is set to 0.99 for known codes, 0.99 for unknown (safe-fail
      default is HARD_DECLINE so high confidence is correct).
    """
    normalised = failure_code.strip().upper()
    category = FAILURE_CODE_MAP.get(normalised, FailureCategory.HARD_DECLINE)
    rationale = _RATIONALES[category]

    # For known codes we're fully certain; unknown → safe hard-decline
    confidence = 0.99

    return LLMClassificationResult(
        failure_category=category,
        confidence=confidence,
        rationale=rationale,
        failure_code_matched=normalised,
    )
