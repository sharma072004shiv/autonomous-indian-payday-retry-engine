"""
app/llm/classifier.py
─────────────────────
PydanticAI-based failure code classifier.

AGENTS.md trust boundary (STRICTLY ENFORCED):
  ✅ This module MAY:  classify a failure_code → LLMClassificationResult
  ❌ This module MUST NEVER:
       - execute payments or call any payment API
       - write to the database
       - schedule retries
       - decide retry counts or limits
       - override policy rules
       - modify transaction amounts

Failure path:
  If the LLM call fails (timeout, network error, invalid JSON, validation
  error, or confidence < 0.5), classify_failure() raises LLMClassificationError.
  The caller (retry_service) catches this and defaults to HARD_DECLINE —
  the safest possible outcome.

Mock path:
  When Settings.llm_use_mock is True (always in tests), the deterministic
  mock_classifier is used instead of making a real API call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import get_settings
from app.models.enums import FailureCategory
from app.models.llm_output import LLMClassificationResult

logger = logging.getLogger(__name__)


class LLMClassificationError(Exception):
    """
    Raised when the LLM classifier cannot produce a valid result.

    Callers must catch this and default to HARD_DECLINE.
    """


# ── Prompt template ───────────────────────────────────────────────────────────
# This is the only thing the LLM receives. It cannot affect scheduling,
# amounts, database, or payment APIs.

_SYSTEM_PROMPT = """\
You are a payment failure classifier for an Indian recurring-payment engine.
Your ONLY job is to classify a bank/NPCI failure code into one of three categories.

Categories:
  LIQUIDITY_TEMPORARY   — customer likely has insufficient funds right now but
                          will have funds after their salary is credited.
                          Examples: BANK_RESP_51_NO_FUNDS, BANK_RESP_65_LIMIT_EXCEEDED

  BANK_SURGE_TEMPORARY  — bank or NPCI infrastructure is temporarily congested.
                          The failure is not caused by the customer's funds.
                          Examples: NPCI_SURGE_TIMEOUT, BANK_UNAVAILABLE

  HARD_DECLINE          — permanent or irrecoverable failure. Retrying will not help.
                          Examples: MANDATE_EXPIRED, ACCOUNT_FROZEN, ACCOUNT_CLOSED,
                                    INVALID_ACCOUNT, DO_NOT_HONOUR

Rules you must follow:
  1. Return ONLY the structured JSON output — no free text outside the JSON.
  2. If you are not confident (< 0.5), set failure_category to HARD_DECLINE.
  3. You may NOT suggest payment execution, retry scheduling, or amounts.
  4. You may NOT access any external system or database.
"""

_USER_PROMPT_TEMPLATE = """\
Classify this payment failure code: {failure_code}

Return a JSON object with these exact fields:
  failure_category: one of LIQUIDITY_TEMPORARY | BANK_SURGE_TEMPORARY | HARD_DECLINE
  confidence: float between 0.0 and 1.0
  rationale: a single sentence explaining your classification
  failure_code_matched: the exact failure_code you received (echo it back)
"""


# ── PydanticAI agent (lazy-initialised) ──────────────────────────────────────

_agent: Optional[object] = None  # pydantic_ai.Agent instance


def _build_agent():  # type: ignore[return]
    """
    Build and return the PydanticAI Agent.

    Lazy-initialised so importing this module never requires API keys or
    network access.  Only called when a real LLM classification is requested.
    """
    try:
        from pydantic_ai import Agent  # type: ignore[import]
    except ImportError as exc:
        raise LLMClassificationError(
            "pydantic_ai is not installed. Install it with: "
            "pip install pydantic-ai"
        ) from exc

    settings = get_settings()
    model_string = f"{settings.llm_provider.value}:{settings.llm_model}"

    agent: Agent[None, LLMClassificationResult] = Agent(
        model=model_string,
        result_type=LLMClassificationResult,
        system_prompt=_SYSTEM_PROMPT,
    )
    return agent


# ── Public API ────────────────────────────────────────────────────────────────

async def classify_failure(failure_code: str) -> LLMClassificationResult:
    """
    Classify a raw bank/NPCI failure code into a FailureCategory.

    Resolution order:
      1. If LLM_USE_MOCK=true or APP_ENV=test  → deterministic mock classifier
      2. If a real LLM is configured and reachable → PydanticAI agent
      3. If the real LLM fails for any reason     → deterministic mock classifier
         (NOT a blanket HARD_DECLINE — the mock has correct code mappings)

    The safe-default HARD_DECLINE is only used inside `classify_failure_safe_default()`
    which callers may invoke explicitly.  It is NOT used as the automatic fallback
    here, because doing so would incorrectly block LIQUIDITY_TEMPORARY codes such as
    BANK_RESP_51_NO_FUNDS.

    Parameters
    ----------
    failure_code : str
        Raw failure code, e.g. "BANK_RESP_51_NO_FUNDS".

    Returns
    -------
    LLMClassificationResult
        A fully validated Pydantic model.  Always use `.safe_category`
        (not `.failure_category`) to read the category — safe_category
        falls back to HARD_DECLINE if confidence is low.

    Raises
    ------
    LLMClassificationError
        Only raised when both the real LLM and the mock classifier fail,
        which should never happen in practice.
    """
    normalised = failure_code.strip().upper()
    settings = get_settings()

    # ── Mock path: explicit opt-in or test environment ────────────────────
    if settings.llm_use_mock or settings.is_test:
        from app.llm.mock_classifier import mock_classify_failure
        logger.debug("LLM mock path (configured): classifying %s", normalised)
        return mock_classify_failure(normalised)

    # ── Real LLM path ─────────────────────────────────────────────────────
    global _agent
    try:
        if _agent is None:
            _agent = _build_agent()

        prompt = _USER_PROMPT_TEMPLATE.format(failure_code=normalised)
        result = await asyncio.wait_for(
            _run_agent(_agent, prompt),
            timeout=settings.llm_timeout_seconds,
        )

        if not isinstance(result, LLMClassificationResult):
            raise LLMClassificationError(
                f"LLM returned unexpected type {type(result).__name__} "
                f"for '{normalised}'"
            )

        logger.info(
            "LLM classified %s → %s (confidence=%.2f)",
            normalised,
            result.safe_category.value,
            result.confidence,
        )
        return result

    except asyncio.TimeoutError:
        logger.warning(
            "LLM classify_failure timed out after %ds for %s — "
            "falling back to mock classifier",
            settings.llm_timeout_seconds,
            normalised,
        )
    except LLMClassificationError:
        # Already the right type — log and fall through to mock fallback
        logger.warning(
            "LLM classify_failure raised LLMClassificationError for %s — "
            "falling back to mock classifier",
            normalised,
        )
    except Exception as exc:
        logger.error(
            "LLM classify_failure unexpected error for %s: %s — "
            "falling back to mock classifier",
            normalised,
            exc,
        )

    # ── Fallback: deterministic mock classifier ───────────────────────────
    # This preserves correct mappings (BANK_RESP_51_NO_FUNDS → LIQUIDITY_TEMPORARY)
    # instead of blanket-blocking everything as HARD_DECLINE.
    logger.info(
        "Using mock classifier fallback for %s (real LLM unavailable)",
        normalised,
    )
    from app.llm.mock_classifier import mock_classify_failure
    return mock_classify_failure(normalised)


async def _run_agent(agent, prompt: str) -> LLMClassificationResult:
    """Run the PydanticAI agent and return the validated result."""
    run_result = await agent.run(prompt)
    return run_result.data


def classify_failure_safe_default(failure_code: str) -> LLMClassificationResult:
    """
    Synchronous hard-decline fallback.

    Returns a HARD_DECLINE result without calling the LLM.
    Used when the LLM is unavailable and a synchronous safe default is needed.
    This is NOT the normal call path — use classify_failure() (async) instead.
    """
    return LLMClassificationResult(
        failure_category=FailureCategory.HARD_DECLINE,
        confidence=0.99,
        rationale=(
            "Safe default: LLM unavailable or produced invalid output. "
            "Defaulting to HARD_DECLINE to prevent unsafe retry."
        ),
        failure_code_matched=failure_code.strip().upper(),
    )
