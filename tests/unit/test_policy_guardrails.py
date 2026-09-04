"""
tests/unit/test_policy_guardrails.py
──────────────────────────────────────
Comprehensive unit tests for the policy/guardrails engine.

Covers every AGENTS.md safety rule, all individual guardrail functions,
run_all_guardrails(), retry_rules, idempotency, and the full evaluate()
engine with all decision paths.

No database, no LLM calls, no network I/O — all pure deterministic tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import FailureCategory, RetryDecision
from app.models.llm_output import LLMClassificationResult
from app.models.policy import RetryPolicyDecision
from app.policy.engine import evaluate
from app.policy.guardrails import (
    RULE_APPROVE_LIQUIDITY,
    RULE_APPROVE_SURGE,
    RULE_DUPLICATE_EVENT_BLOCK,
    RULE_HARD_DECLINE_BLOCK,
    RULE_MAX_RETRIES_BLOCK,
    RULE_MIN_AMOUNT_BLOCK,
    check_duplicate_event,
    check_hard_decline,
    check_max_retries,
    check_min_amount,
    run_all_guardrails,
)
from app.policy.idempotency import is_duplicate_event
from app.policy.retry_rules import calculate_next_retry_at


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _llm(
    category: FailureCategory = FailureCategory.LIQUIDITY_TEMPORARY,
    confidence: float = 0.95,
    rationale: str = "Test rationale",
) -> LLMClassificationResult:
    return LLMClassificationResult(
        failure_category=category,
        confidence=confidence,
        rationale=rationale,
        failure_code_matched="TEST_CODE",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# check_hard_decline
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckHardDecline:
    def test_hard_decline_blocked(self) -> None:
        allowed, reason = check_hard_decline(FailureCategory.HARD_DECLINE)
        assert allowed is False
        assert "HARD_DECLINE" in reason
        assert "permanent" in reason.lower() or "irrecoverable" in reason.lower()

    def test_liquidity_allowed(self) -> None:
        allowed, reason = check_hard_decline(FailureCategory.LIQUIDITY_TEMPORARY)
        assert allowed is True
        assert reason == ""

    def test_surge_allowed(self) -> None:
        allowed, reason = check_hard_decline(FailureCategory.BANK_SURGE_TEMPORARY)
        assert allowed is True
        assert reason == ""

    def test_hard_decline_reason_mentions_rule(self) -> None:
        _, reason = check_hard_decline(FailureCategory.HARD_DECLINE)
        assert "rule" in reason.lower() or "AGENTS" in reason

    def test_returns_tuple(self) -> None:
        result = check_hard_decline(FailureCategory.HARD_DECLINE)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# check_min_amount
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckMinAmount:
    # ── Below threshold ──────────────────────────────────────────────────
    def test_amount_below_100_rupees_blocked(self) -> None:
        allowed, reason = check_min_amount(9_999, 10_000)
        assert allowed is False
        assert "₹" in reason or "minimum" in reason.lower()

    def test_amount_1_paise_blocked(self) -> None:
        allowed, reason = check_min_amount(1, 10_000)
        assert allowed is False

    def test_amount_zero_blocked(self) -> None:
        allowed, reason = check_min_amount(0, 10_000)
        assert allowed is False

    def test_negative_amount_blocked(self) -> None:
        allowed, reason = check_min_amount(-100, 10_000)
        assert allowed is False

    # ── At threshold ─────────────────────────────────────────────────────
    def test_amount_exactly_100_rupees_allowed(self) -> None:
        """₹100 exactly (10,000 paise) is at the threshold — must be allowed."""
        allowed, reason = check_min_amount(10_000, 10_000)
        assert allowed is True
        assert reason == ""

    # ── Above threshold ──────────────────────────────────────────────────
    def test_amount_above_threshold_allowed(self) -> None:
        allowed, reason = check_min_amount(50_000, 10_000)
        assert allowed is True

    def test_large_amount_allowed(self) -> None:
        allowed, reason = check_min_amount(5_000_000, 10_000)
        assert allowed is True

    def test_default_threshold_is_10000_paise(self) -> None:
        """Default threshold must be 10,000 paise = ₹100."""
        blocked, _ = check_min_amount(9_999)
        allowed, _ = check_min_amount(10_000)
        assert blocked is False
        assert allowed is True

    def test_custom_threshold(self) -> None:
        allowed, _ = check_min_amount(5_000, min_amount_paise=5_000)
        assert allowed is True
        blocked, _ = check_min_amount(4_999, min_amount_paise=5_000)
        assert blocked is False


# ═══════════════════════════════════════════════════════════════════════════════
# check_max_retries
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckMaxRetries:
    def test_retry_count_0_allowed(self) -> None:
        allowed, reason = check_max_retries(0, 3)
        assert allowed is True
        assert reason == ""

    def test_retry_count_1_allowed(self) -> None:
        allowed, _ = check_max_retries(1, 3)
        assert allowed is True

    def test_retry_count_2_allowed(self) -> None:
        allowed, _ = check_max_retries(2, 3)
        assert allowed is True

    def test_retry_count_3_blocked(self) -> None:
        """retry_count == max_retries (3) must be blocked."""
        allowed, reason = check_max_retries(3, 3)
        assert allowed is False
        assert "3" in reason
        assert "maximum" in reason.lower() or "max" in reason.lower()

    def test_retry_count_above_cap_blocked(self) -> None:
        allowed, reason = check_max_retries(4, 3)
        assert allowed is False

    def test_max_retries_over_hard_cap_raises(self) -> None:
        """Passing max_retries > 3 must raise ValueError (safety net)."""
        with pytest.raises(ValueError, match="hard cap"):
            check_max_retries(0, max_retries=4)

    def test_returns_tuple(self) -> None:
        result = check_max_retries(0, 3)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# check_duplicate_event
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDuplicateEvent:
    def test_new_event_allowed(self) -> None:
        allowed, reason = check_duplicate_event(already_processed=False)
        assert allowed is True
        assert reason == ""

    def test_duplicate_event_blocked(self) -> None:
        allowed, reason = check_duplicate_event(already_processed=True)
        assert allowed is False
        assert "duplicate" in reason.lower()

    def test_returns_tuple(self) -> None:
        result = check_duplicate_event(False)
        assert isinstance(result, tuple)


# ═══════════════════════════════════════════════════════════════════════════════
# is_duplicate_event (idempotency module)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsDuplicateEvent:
    def test_false_means_new(self) -> None:
        assert is_duplicate_event(False) is False

    def test_true_means_duplicate(self) -> None:
        assert is_duplicate_event(True) is True


# ═══════════════════════════════════════════════════════════════════════════════
# run_all_guardrails
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunAllGuardrails:

    # ── Duplicate wins first ─────────────────────────────────────────────
    def test_duplicate_blocks_before_hard_decline(self) -> None:
        allowed, _, rule = run_all_guardrails(
            category=FailureCategory.HARD_DECLINE,
            amount_paise=50_000,
            retry_count=0,
            already_processed=True,
        )
        assert allowed is False
        assert rule == RULE_DUPLICATE_EVENT_BLOCK

    # ── Hard decline ─────────────────────────────────────────────────────
    def test_hard_decline_blocked(self) -> None:
        allowed, reason, rule = run_all_guardrails(
            category=FailureCategory.HARD_DECLINE,
            amount_paise=50_000,
            retry_count=0,
        )
        assert allowed is False
        assert rule == RULE_HARD_DECLINE_BLOCK

    # ── Min amount ───────────────────────────────────────────────────────
    def test_below_min_amount_blocked(self) -> None:
        allowed, reason, rule = run_all_guardrails(
            category=FailureCategory.LIQUIDITY_TEMPORARY,
            amount_paise=5_000,   # ₹50 — below threshold
            retry_count=0,
        )
        assert allowed is False
        assert rule == RULE_MIN_AMOUNT_BLOCK

    def test_amount_exactly_100_rupees_passes_amount_check(self) -> None:
        allowed, _, rule = run_all_guardrails(
            category=FailureCategory.LIQUIDITY_TEMPORARY,
            amount_paise=10_000,  # exactly ₹100
            retry_count=0,
        )
        assert allowed is True
        assert rule == RULE_APPROVE_LIQUIDITY

    # ── Max retries ──────────────────────────────────────────────────────
    def test_max_retries_reached_blocked(self) -> None:
        allowed, reason, rule = run_all_guardrails(
            category=FailureCategory.LIQUIDITY_TEMPORARY,
            amount_paise=50_000,
            retry_count=3,   # at cap
        )
        assert allowed is False
        assert rule == RULE_MAX_RETRIES_BLOCK

    def test_retry_count_2_allowed(self) -> None:
        allowed, _, rule = run_all_guardrails(
            category=FailureCategory.LIQUIDITY_TEMPORARY,
            amount_paise=50_000,
            retry_count=2,   # one more allowed
        )
        assert allowed is True

    # ── Approved paths ───────────────────────────────────────────────────
    def test_liquidity_approved(self) -> None:
        allowed, reason, rule = run_all_guardrails(
            category=FailureCategory.LIQUIDITY_TEMPORARY,
            amount_paise=50_000,
            retry_count=0,
        )
        assert allowed is True
        assert rule == RULE_APPROVE_LIQUIDITY

    def test_surge_approved(self) -> None:
        allowed, reason, rule = run_all_guardrails(
            category=FailureCategory.BANK_SURGE_TEMPORARY,
            amount_paise=50_000,
            retry_count=0,
        )
        assert allowed is True
        assert rule == RULE_APPROVE_SURGE

    # ── Rule order: hard decline wins before amount check ────────────────
    def test_hard_decline_wins_over_min_amount(self) -> None:
        """Even a below-₹100 HARD_DECLINE should be blocked by HARD_DECLINE rule."""
        allowed, _, rule = run_all_guardrails(
            category=FailureCategory.HARD_DECLINE,
            amount_paise=5_000,   # also below ₹100
            retry_count=0,
        )
        assert rule == RULE_HARD_DECLINE_BLOCK  # hard decline wins first

    def test_returns_three_tuple(self) -> None:
        result = run_all_guardrails(
            FailureCategory.LIQUIDITY_TEMPORARY, 50_000, 0
        )
        assert isinstance(result, tuple)
        assert len(result) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# calculate_next_retry_at
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateNextRetryAt:

    def test_liquidity_attempt_1_is_future(self) -> None:
        from_time = _utc(2026, 7, 5, 0)
        result = calculate_next_retry_at(
            FailureCategory.LIQUIDITY_TEMPORARY, 1, from_time, salary_credit_day=15
        )
        assert result > from_time

    def test_surge_attempt_1_not_in_surge(self) -> None:
        from app.services.payday_predictor import is_bank_surge_hour, IST
        from datetime import timedelta
        # Start inside the morning surge window: 10 AM IST = 4:30 AM UTC
        from_time = datetime(2026, 7, 5, 4, 30, tzinfo=timezone.utc)  # 10 AM IST
        result = calculate_next_retry_at(
            FailureCategory.BANK_SURGE_TEMPORARY, 1, from_time
        )
        assert not is_bank_surge_hour(result), (
            f"Result {result} ({result.astimezone(IST)}) is inside a surge window"
        )

    def test_hard_decline_raises(self) -> None:
        with pytest.raises(ValueError, match="HARD_DECLINE"):
            calculate_next_retry_at(
                FailureCategory.HARD_DECLINE, 1, _utc(2026, 7, 5)
            )

    def test_invalid_attempt_number_raises(self) -> None:
        with pytest.raises(ValueError, match="attempt_number"):
            calculate_next_retry_at(
                FailureCategory.LIQUIDITY_TEMPORARY, 0, _utc(2026, 7, 5)
            )

    def test_attempt_number_4_raises(self) -> None:
        with pytest.raises(ValueError, match="attempt_number"):
            calculate_next_retry_at(
                FailureCategory.LIQUIDITY_TEMPORARY, 4, _utc(2026, 7, 5)
            )

    def test_naive_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            calculate_next_retry_at(
                FailureCategory.LIQUIDITY_TEMPORARY, 1,
                datetime(2026, 7, 5)  # naive
            )

    def test_returns_utc(self) -> None:
        result = calculate_next_retry_at(
            FailureCategory.LIQUIDITY_TEMPORARY, 1, _utc(2026, 7, 5)
        )
        assert result.utcoffset() == timedelta(0)

    def test_attempt_2_later_than_attempt_1(self) -> None:
        from_time = _utc(2026, 7, 5, 0)
        r1 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_time, salary_credit_day=15)
        r2 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 2, from_time, salary_credit_day=15)
        assert r2 >= r1

    def test_attempt_3_latest(self) -> None:
        from_time = _utc(2026, 7, 5, 0)
        r1 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_time, salary_credit_day=15)
        r3 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 3, from_time, salary_credit_day=15)
        assert r3 >= r1

    def test_deterministic(self) -> None:
        from_time = _utc(2026, 7, 5, 0)
        r1 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_time, salary_credit_day=10)
        r2 = calculate_next_retry_at(FailureCategory.LIQUIDITY_TEMPORARY, 1, from_time, salary_credit_day=10)
        assert r1 == r2


# ═══════════════════════════════════════════════════════════════════════════════
# evaluate() — full engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluate:

    # ── Hard decline → always reject ─────────────────────────────────────
    def test_hard_decline_rejected(self) -> None:
        decision = evaluate(
            transaction_id="txn-hd",
            event_id="evt-hd",
            llm_result=_llm(FailureCategory.HARD_DECLINE),
            amount_paise=50_000,
            retry_count=0,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.decision == RetryDecision.REJECT
        assert decision.policy_rule == RULE_HARD_DECLINE_BLOCK
        assert decision.scheduled_at is None
        assert decision.retry_number == 0

    # ── Below ₹100 → reject ──────────────────────────────────────────────
    def test_below_100_rupees_rejected(self) -> None:
        decision = evaluate(
            transaction_id="txn-small",
            event_id="evt-small",
            llm_result=_llm(FailureCategory.LIQUIDITY_TEMPORARY),
            amount_paise=5_000,   # ₹50
            retry_count=0,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.policy_rule == RULE_MIN_AMOUNT_BLOCK

    # ── Exactly ₹100 → approve ───────────────────────────────────────────
    def test_exactly_100_rupees_approved(self) -> None:
        decision = evaluate(
            transaction_id="txn-100",
            event_id="evt-100",
            llm_result=_llm(FailureCategory.LIQUIDITY_TEMPORARY),
            amount_paise=10_000,  # exactly ₹100
            retry_count=0,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True
        assert decision.scheduled_at is not None

    # ── Above ₹100 → approve ─────────────────────────────────────────────
    def test_above_100_rupees_approved(self) -> None:
        decision = evaluate(
            transaction_id="txn-large",
            event_id="evt-large",
            llm_result=_llm(FailureCategory.LIQUIDITY_TEMPORARY),
            amount_paise=500_000,
            retry_count=0,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True

    # ── Retry counts ─────────────────────────────────────────────────────
    def test_retry_count_0_approved(self) -> None:
        decision = evaluate(
            "txn-rc0", "evt-rc0",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True
        assert decision.retry_number == 1

    def test_retry_count_2_approved(self) -> None:
        decision = evaluate(
            "txn-rc2", "evt-rc2",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 2, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True
        assert decision.retry_number == 3

    def test_retry_count_3_rejected(self) -> None:
        decision = evaluate(
            "txn-rc3", "evt-rc3",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 3, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.policy_rule == RULE_MAX_RETRIES_BLOCK

    # ── Failure categories ────────────────────────────────────────────────
    def test_liquidity_temporary_approved(self) -> None:
        decision = evaluate(
            "txn-liq", "evt-liq",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True
        assert decision.policy_rule == RULE_APPROVE_LIQUIDITY
        assert decision.failure_category == FailureCategory.LIQUIDITY_TEMPORARY

    def test_bank_surge_approved(self) -> None:
        decision = evaluate(
            "txn-surge", "evt-surge",
            _llm(FailureCategory.BANK_SURGE_TEMPORARY),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is True
        assert decision.policy_rule == RULE_APPROVE_SURGE

    # ── Duplicate event ───────────────────────────────────────────────────
    def test_duplicate_event_rejected(self) -> None:
        decision = evaluate(
            "txn-dup", "evt-dup",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 0,
            already_processed=True,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.policy_rule == RULE_DUPLICATE_EVENT_BLOCK

    # ── Low confidence → HARD_DECLINE safe fallback ───────────────────────
    def test_low_confidence_llm_forces_hard_decline(self) -> None:
        """
        LLM said LIQUIDITY_TEMPORARY but confidence=0.3 → safe_category
        returns HARD_DECLINE → policy rejects.
        """
        low_conf = _llm(FailureCategory.LIQUIDITY_TEMPORARY, confidence=0.3)
        decision = evaluate(
            "txn-lowconf", "evt-lowconf",
            low_conf, 50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.failure_category == FailureCategory.HARD_DECLINE
        assert decision.policy_rule == RULE_HARD_DECLINE_BLOCK

    # ── Decision fields ───────────────────────────────────────────────────
    def test_approved_decision_has_scheduled_at(self) -> None:
        decision = evaluate(
            "txn-sched", "evt-sched",
            _llm(FailureCategory.BANK_SURGE_TEMPORARY),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.scheduled_at is not None
        assert decision.scheduled_at > _utc(2026, 7, 5)

    def test_rejected_decision_has_no_scheduled_at(self) -> None:
        decision = evaluate(
            "txn-rej", "evt-rej",
            _llm(FailureCategory.HARD_DECLINE),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.scheduled_at is None

    def test_decision_carries_llm_traceability(self) -> None:
        llm = _llm(FailureCategory.LIQUIDITY_TEMPORARY, confidence=0.88,
                   rationale="Payday gap detected")
        decision = evaluate(
            "txn-trace", "evt-trace", llm, 50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.llm_confidence == pytest.approx(0.88)
        assert decision.llm_rationale == "Payday gap detected"

    def test_returns_retry_policy_decision(self) -> None:
        decision = evaluate(
            "txn-type", "evt-type",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY),
            50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert isinstance(decision, RetryPolicyDecision)

    # ── Determinism ───────────────────────────────────────────────────────
    def test_evaluate_is_deterministic(self) -> None:
        kwargs = dict(
            transaction_id="txn-det",
            event_id="evt-det",
            llm_result=_llm(FailureCategory.LIQUIDITY_TEMPORARY),
            amount_paise=50_000,
            retry_count=1,
            salary_credit_day=15,
            as_of=_utc(2026, 7, 5),
        )
        d1 = evaluate(**kwargs)
        d2 = evaluate(**kwargs)
        assert d1.retry_allowed == d2.retry_allowed
        assert d1.scheduled_at == d2.scheduled_at
        assert d1.policy_rule == d2.policy_rule

    # ── LLM cannot override policy ────────────────────────────────────────
    def test_llm_cannot_approve_hard_decline(self) -> None:
        """
        TRUST BOUNDARY: Even if the LLM says LIQUIDITY_TEMPORARY with high
        confidence, a HARD_DECLINE category (e.g. from safe_category due to
        a truly hard code) is always rejected.
        """
        # Simulate a case where safe_category returns HARD_DECLINE
        hard = LLMClassificationResult(
            failure_category=FailureCategory.HARD_DECLINE,
            confidence=0.99,
            rationale="Account frozen — permanent",
            failure_code_matched="ACCOUNT_FROZEN",
        )
        decision = evaluate(
            "txn-trust", "evt-trust", hard, 50_000, 0, as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False

    def test_llm_cannot_bypass_max_retries(self) -> None:
        """LLM approving a category does not bypass the retry count cap."""
        decision = evaluate(
            "txn-maxret", "evt-maxret",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY, confidence=0.99),
            50_000, retry_count=3,   # already at max
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.policy_rule == RULE_MAX_RETRIES_BLOCK

    def test_llm_cannot_bypass_min_amount(self) -> None:
        """LLM approving a category does not bypass the amount check."""
        decision = evaluate(
            "txn-minam", "evt-minam",
            _llm(FailureCategory.LIQUIDITY_TEMPORARY, confidence=0.99),
            amount_paise=1_000,  # ₹10 — below threshold
            retry_count=0,
            as_of=_utc(2026, 7, 5),
        )
        assert decision.retry_allowed is False
        assert decision.policy_rule == RULE_MIN_AMOUNT_BLOCK

    # ── engine module static checks ───────────────────────────────────────
    def test_engine_has_no_db_imports(self) -> None:
        import inspect
        import app.policy.engine as mod
        source = inspect.getsource(mod)
        assert "from app.db" not in source
        assert "import app.db" not in source

    def test_engine_has_no_execute_payment_call(self) -> None:
        import inspect
        import app.policy.engine as mod
        source = inspect.getsource(mod)
        assert "execute_payment" not in source
        assert "call_razorpay" not in source

    def test_evaluate_all_policies_have_reason(self) -> None:
        """Every decision must carry a non-blank reason for the audit log."""
        cases = [
            (_llm(FailureCategory.HARD_DECLINE), 50_000, 0),
            (_llm(FailureCategory.LIQUIDITY_TEMPORARY), 5_000, 0),   # amount block
            (_llm(FailureCategory.LIQUIDITY_TEMPORARY), 50_000, 3),  # retries block
            (_llm(FailureCategory.LIQUIDITY_TEMPORARY), 50_000, 0),  # approve
            (_llm(FailureCategory.BANK_SURGE_TEMPORARY), 50_000, 0), # approve surge
        ]
        for llm, amount, retries in cases:
            d = evaluate("txn-x", "evt-x", llm, amount, retries, as_of=_utc(2026, 7, 5))
            assert d.reason.strip() != "", f"Blank reason for policy_rule={d.policy_rule}"
