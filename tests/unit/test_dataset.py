"""
tests/unit/test_dataset.py
───────────────────────────
Tests for the synthetic dataset generator (data/generate_data.py).

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

# Add the repo root to sys.path so data/ is importable
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from data.generate_data import (
    COLUMN_NAMES,
    FAILURE_CATEGORY_MAP,
    FAILURE_CODES,
    OUTPUT_FILE,
    TOTAL_RECORDS,
    generate_dataset,
    save_csv,
)


# ── Determinism ───────────────────────────────────────────────────────────────

def test_generate_is_deterministic() -> None:
    """Two calls with the same seed must return identical records."""
    r1 = generate_dataset(seed=42)
    r2 = generate_dataset(seed=42)
    assert r1 == r2


def test_different_seeds_produce_different_data() -> None:
    r1 = generate_dataset(seed=42)
    r2 = generate_dataset(seed=99)
    assert r1 != r2


# ── Record count ──────────────────────────────────────────────────────────────

def test_exactly_1000_records() -> None:
    records = generate_dataset()
    assert len(records) == TOTAL_RECORDS
    assert len(records) == 1_000


def test_custom_n_respected() -> None:
    records = generate_dataset(n=50)
    assert len(records) == 50


# ── Required columns ─────────────────────────────────────────────────────────

def test_required_columns_present() -> None:
    records = generate_dataset()
    required = {
        "transaction_id", "customer_id", "amount", "payment_method",
        "failure_code", "failed_at", "salary_credit_date_estimated",
        "historical_bank_surge_hour", "retry_count",
    }
    actual = set(records[0].keys())
    assert required.issubset(actual), f"Missing columns: {required - actual}"


def test_all_column_names_present() -> None:
    records = generate_dataset()
    for col in COLUMN_NAMES:
        assert col in records[0], f"Column '{col}' missing from record"


# ── Unique transaction IDs ────────────────────────────────────────────────────

def test_transaction_ids_are_unique() -> None:
    records = generate_dataset()
    ids = [r["transaction_id"] for r in records]
    assert len(ids) == len(set(ids)), "Duplicate transaction_id found"


# ── Valid failure codes ───────────────────────────────────────────────────────

def test_only_valid_failure_codes() -> None:
    records = generate_dataset()
    valid = set(FAILURE_CODES)
    for r in records:
        assert r["failure_code"] in valid, f"Invalid failure code: {r['failure_code']}"


def test_required_failure_codes_present() -> None:
    records = generate_dataset()
    codes_seen = {r["failure_code"] for r in records}
    required_codes = {
        "BANK_RESP_51_NO_FUNDS",
        "NPCI_SURGE_TIMEOUT",
        "MANDATE_EXPIRED",
        "ACCOUNT_FROZEN",
    }
    assert required_codes.issubset(codes_seen)


# ── Failure categories ────────────────────────────────────────────────────────

def test_all_three_failure_categories_represented() -> None:
    records = generate_dataset()
    cats = {r["failure_category"] for r in records}
    assert "LIQUIDITY_TEMPORARY" in cats
    assert "BANK_SURGE_TEMPORARY" in cats
    assert "HARD_DECLINE" in cats


def test_failure_category_matches_code() -> None:
    records = generate_dataset()
    for r in records:
        expected = FAILURE_CATEGORY_MAP[r["failure_code"]]
        assert r["failure_category"] == expected, (
            f"Code {r['failure_code']} mapped to {r['failure_category']} "
            f"but expected {expected}"
        )


# ── Amount constraints ────────────────────────────────────────────────────────

def test_all_amounts_non_negative() -> None:
    records = generate_dataset()
    for r in records:
        assert r["amount"] >= 0, f"Negative amount: {r['amount']}"


def test_below_100_rupees_records_exist() -> None:
    """Dataset must contain records with amount < ₹100 (< 10,000 paise)."""
    records = generate_dataset()
    below = [r for r in records if r["amount"] < 10_000]
    assert len(below) > 0, "No records below ₹100 found"


def test_above_100_rupees_records_exist() -> None:
    """Dataset must contain records with amount >= ₹100 (>= 10,000 paise)."""
    records = generate_dataset()
    above = [r for r in records if r["amount"] >= 10_000]
    assert len(above) > 0, "No records at/above ₹100 found"


def test_amount_rupees_is_amount_divided_by_100() -> None:
    records = generate_dataset()
    for r in records:
        assert abs(r["amount_rupees"] - r["amount"] / 100.0) < 0.01


# ── Retry count ───────────────────────────────────────────────────────────────

def test_retry_count_within_bounds() -> None:
    records = generate_dataset()
    for r in records:
        assert 0 <= r["retry_count"] <= 3, (
            f"retry_count {r['retry_count']} out of range [0, 3]"
        )


def test_all_retry_count_values_represented() -> None:
    """All values 0–3 must appear in the dataset."""
    records = generate_dataset()
    values_seen = {r["retry_count"] for r in records}
    assert values_seen == {0, 1, 2, 3}


# ── Salary credit / surge hour ────────────────────────────────────────────────

def test_salary_credit_day_in_valid_range() -> None:
    records = generate_dataset()
    for r in records:
        assert 1 <= r["salary_credit_date_estimated"] <= 31


def test_surge_hour_in_valid_range() -> None:
    records = generate_dataset()
    for r in records:
        assert 0 <= r["historical_bank_surge_hour"] <= 23


# ── CSV round-trip ────────────────────────────────────────────────────────────

def test_csv_file_exists() -> None:
    assert OUTPUT_FILE.exists(), f"CSV not found at {OUTPUT_FILE}"


def test_csv_has_1000_data_rows() -> None:
    with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1_000


def test_csv_columns_match_column_names() -> None:
    with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None
        assert set(COLUMN_NAMES) == set(reader.fieldnames)


def test_csv_save_and_reload(tmp_path) -> None:
    """save_csv then reload must produce identical column names and row count."""
    records = generate_dataset(n=10)
    out = tmp_path / "test_out.csv"
    save_csv(records, path=out)
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 10
    assert set(rows[0].keys()) == set(COLUMN_NAMES)
