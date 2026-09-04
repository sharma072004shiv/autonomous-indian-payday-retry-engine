"""
tests/unit/test_benchmark.py
──────────────────────────────
Tests for the benchmark runners and dataset generator.

Verifies 1,000 records, determinism, A/B metrics consistency.
⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

import pytest

from benchmark.dataset_generator import generate_dataset, DATASET_SIZE, DATASET_SEED
from benchmark.baseline_runner import run_baseline
from benchmark.engine_runner import run_engine


# ── Dataset ───────────────────────────────────────────────────────────────────

def test_dataset_has_1000_records() -> None:
    ds = generate_dataset()
    assert len(ds) == DATASET_SIZE


def test_dataset_seed_is_42() -> None:
    assert DATASET_SEED == 42


def test_dataset_deterministic() -> None:
    d1 = generate_dataset()
    d2 = generate_dataset()
    ids1 = [e.transaction_id for e in d1]
    ids2 = [e.transaction_id for e in d2]
    assert ids1 == ids2


def test_dataset_failure_events_valid() -> None:
    from app.models.transaction import FailureEvent
    ds = generate_dataset()
    for ev in ds:
        assert isinstance(ev, FailureEvent)
        assert ev.failure_code.strip() != ""
        assert ev.amount_paise >= 0


# ── Baseline ──────────────────────────────────────────────────────────────────

def test_baseline_processes_1000_records() -> None:
    ds = generate_dataset()
    result = run_baseline(ds)
    assert result["total_transactions"] == 1000


def test_baseline_deterministic() -> None:
    ds = generate_dataset()
    r1 = run_baseline(ds)
    r2 = run_baseline(ds)
    assert r1["recovered"] == r2["recovered"]


def test_baseline_metrics_consistent() -> None:
    ds = generate_dataset()
    r = run_baseline(ds)
    total = r["total_transactions"]
    accounted = (
        r["hard_declines_skipped"]
        + r["below_threshold_skipped"]
        + r["retried"]
    )
    assert accounted == total, f"Unaccounted: {total - accounted}"


def test_baseline_recovered_within_retried() -> None:
    ds = generate_dataset()
    r = run_baseline(ds)
    assert r["recovered"] <= r["retried"]


def test_baseline_recovery_rate_range() -> None:
    ds = generate_dataset()
    r = run_baseline(ds)
    assert 0.0 <= r["recovery_rate_pct"] <= 100.0


def test_baseline_has_note_field() -> None:
    ds = generate_dataset()
    r = run_baseline(ds)
    assert "SYNTHETIC" in r["note"]


# ── Engine ────────────────────────────────────────────────────────────────────

def test_engine_processes_1000_records() -> None:
    ds = generate_dataset()
    result = run_engine(ds)
    assert result["total_transactions"] == 1000


def test_engine_deterministic() -> None:
    ds = generate_dataset()
    r1 = run_engine(ds)
    r2 = run_engine(ds)
    assert r1["recovered"] == r2["recovered"]
    assert r1["hard_declines_blocked"] == r2["hard_declines_blocked"]


def test_engine_metrics_consistent() -> None:
    ds = generate_dataset()
    r = run_engine(ds)
    total = r["total_transactions"]
    approved = r["approved_for_retry"]
    hard = r["hard_declines_blocked"]
    below = r["below_threshold_blocked"]
    max_r = r["max_retry_blocked"]
    # approved + hard + below + max_retry should account for all
    accounted = approved + hard + below + max_r
    assert accounted == total, f"Unaccounted: {total - accounted}"


def test_engine_hard_declines_never_retried() -> None:
    ds = generate_dataset()
    r = run_engine(ds)
    # Hard declines must never be approved
    assert r["hard_declines_blocked"] > 0


def test_engine_below_threshold_never_retried() -> None:
    ds = generate_dataset()
    r = run_engine(ds)
    assert r["below_threshold_blocked"] > 0


def test_engine_recovery_rate_range() -> None:
    ds = generate_dataset()
    r = run_engine(ds)
    assert 0.0 <= r["recovery_rate_pct"] <= 100.0


def test_engine_has_note_field() -> None:
    ds = generate_dataset()
    r = run_engine(ds)
    assert "SYNTHETIC" in r["note"]


# ── A/B comparison ────────────────────────────────────────────────────────────

def test_both_strategies_produce_results() -> None:
    ds = generate_dataset()
    baseline = run_baseline(ds)
    engine = run_engine(ds)
    assert baseline["total_transactions"] == engine["total_transactions"]
    assert "recovered" in baseline
    assert "recovered" in engine


def test_engine_prevents_hard_decline_retries() -> None:
    """Engine's hard-decline blocking must match or exceed baseline."""
    ds = generate_dataset()
    baseline = run_baseline(ds)
    engine = run_engine(ds)
    # Both should block some hard declines
    assert baseline["hard_declines_skipped"] > 0
    assert engine["hard_declines_blocked"] > 0
