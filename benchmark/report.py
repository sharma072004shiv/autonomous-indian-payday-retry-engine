"""
benchmark/report.py
────────────────────
A/B comparison report: Fixed 24-hour baseline vs Autonomous PayDay Engine.

⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️
All numbers are generated from a synthetic dataset with fixed seed=42.
They do not represent real payment recovery rates or production performance.

Usage
-----
    python benchmark/report.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from benchmark.dataset_generator import generate_dataset
from benchmark.baseline_runner import run_baseline
from benchmark.engine_runner import run_engine


def print_report(baseline_metrics: dict, engine_metrics: dict) -> None:
    """Print a formatted A/B comparison to stdout."""
    sep = "=" * 70

    print(f"\n{sep}")
    print("  AUTONOMOUS INDIAN PAYDAY & MANDATE RETRY ENGINE")
    print("  BENCHMARK REPORT — A/B COMPARISON")
    print(f"{sep}")
    print("  ⚠️  SYNTHETIC SIMULATION — NOT REAL-WORLD DATA ⚠️")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"{sep}\n")

    total = baseline_metrics["total_transactions"]
    print(f"  Dataset:  {total} synthetic failed recurring-payment records")
    print(f"  Seed:     42 (deterministic)")
    print()

    _section("A — FIXED 24-HOUR BASELINE", baseline_metrics)
    _section("B — AUTONOMOUS PAYDAY ENGINE", engine_metrics)

    # Comparison
    print(f"\n{sep}")
    print("  COMPARISON: Engine vs Baseline")
    print(f"{sep}")

    b_rec = baseline_metrics["recovered"]
    e_rec = engine_metrics["recovered"]
    b_rate = baseline_metrics["recovery_rate_pct"]
    e_rate = engine_metrics["recovery_rate_pct"]
    b_amt = baseline_metrics["recovered_amount_rupees"]
    e_amt = engine_metrics["recovered_amount_rupees"]

    print(f"  Recovered transactions:  Baseline {b_rec:>4}  |  Engine {e_rec:>4}  "
          f"(Δ {e_rec - b_rec:+d})")
    print(f"  Recovery rate:           Baseline {b_rate:>5.1f}%  |  Engine {e_rate:>5.1f}%  "
          f"(Δ {e_rate - b_rate:+.1f}pp)")
    print(f"  Recovered amount:        Baseline ₹{b_amt:>10,.2f}  |  "
          f"Engine ₹{e_amt:>10,.2f}  (Δ ₹{e_amt - b_amt:+,.2f})")

    b_hd = baseline_metrics["hard_declines_skipped"]
    e_hd = engine_metrics["hard_declines_blocked"]
    print(f"\n  Hard declines prevented: Baseline {b_hd:>4}  |  Engine {e_hd:>4}")

    b_bt = baseline_metrics["below_threshold_skipped"]
    e_bt = engine_metrics["below_threshold_blocked"]
    print(f"  Below-₹100 prevented:   Baseline {b_bt:>4}  |  Engine {e_bt:>4}")

    e_mr = engine_metrics["max_retry_blocked"]
    print(f"  Max-retry blocks:        Engine only: {e_mr}")
    e_avg = engine_metrics["avg_attempts_per_approved"]
    print(f"  Avg attempts/approved:   Engine: {e_avg:.2f}")
    print()
    print(f"{sep}\n")


def _section(title: str, m: dict) -> None:
    print(f"  {'─'*60}")
    print(f"  {title}")
    print(f"  {'─'*60}")
    for key, val in m.items():
        if key in ("strategy", "note"):
            continue
        label = key.replace("_", " ").title()
        if isinstance(val, float):
            print(f"    {label:<35} {val:>10.2f}")
        else:
            print(f"    {label:<35} {val!s:>10}")
    print()


def save_results(baseline: dict, engine: dict, output_dir: Path) -> Path:
    """Save benchmark results as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"benchmark_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": ts,
                "note": "SYNTHETIC SIMULATION — NOT REAL-WORLD DATA",
                "baseline": baseline,
                "engine": engine,
            },
            f,
            indent=2,
        )
    print(f"  Results saved to {out_path}")
    return out_path


if __name__ == "__main__":
    print("Generating benchmark dataset…")
    dataset = generate_dataset()

    print("Running Strategy A (Fixed 24-hour baseline)…")
    baseline = run_baseline(dataset)

    print("Running Strategy B (Autonomous PayDay Engine)…")
    engine = run_engine(dataset)

    print_report(baseline, engine)

    output_dir = Path(__file__).parent / "output"
    save_results(baseline, engine, output_dir)
