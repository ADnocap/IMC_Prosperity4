"""Drive Pebble_fucker_v1 through the calibrated Python R5 simulator.

The prebuilt rust_simulator.exe predates R5 calibration and we don't have
cargo on this box to rebuild, so we use the Python end-to-end sim
(analysis/round5/r5_python_sim.py — same calibration bundle, same pulse
process, same order book / fill semantics) instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "analysis" / "round5"))

from r5_python_sim import (  # noqa: E402
    R5Scenario, ALL_PRODUCTS, load_calibration_bundle, load_trader,
    simulate_session,
)


PEBBLES = (
    "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
)


def main() -> None:
    trader_path = Path(__file__).parent / "Pebble_fucker_v1.py"

    print("Loading R5 calibration bundle…")
    cal, k_cal, qty_dist = load_calibration_bundle()
    scenario = R5Scenario(cal, k_cal, qty_dist)

    n_seeds = 50
    days = (2, 3, 4)
    ticks_per_day = 10_000

    print(f"\nRunning Pebble_fucker_v1 — {n_seeds} seeds × {len(days)} days "
          f"× {ticks_per_day:,} ticks each")
    print(f"Trader: {trader_path}")

    session_pnls = []  # one entry per (seed, day)
    daily_totals = []  # sum across days per seed
    per_pebble: dict[str, list[float]] = {p: [] for p in PEBBLES}

    for seed in range(n_seeds):
        seed_total = 0.0
        for day in days:
            rng = np.random.default_rng(seed * 100 + day)
            trader = load_trader(trader_path)
            result = simulate_session(scenario, trader, day=day,
                                       n_ticks=ticks_per_day, rng=rng)
            day_total = result["__total__"]["pnl"]
            session_pnls.append(day_total)
            seed_total += day_total
            for p in PEBBLES:
                per_pebble[p].append(result[p]["pnl"])
        daily_totals.append(seed_total)

        if (seed + 1) % 10 == 0:
            arr = np.array(daily_totals)
            print(f"  seed {seed+1:3d}/{n_seeds}: "
                  f"running {len(days)}-day-total mean={arr.mean():.0f} "
                  f"std={arr.std():.0f}")

    daily_totals = np.array(daily_totals)
    session_pnls = np.array(session_pnls)

    print("\n=== Aggregate (3-day total per seed) ===")
    print(f"  n_seeds = {n_seeds}")
    print(f"  mean    = {daily_totals.mean():>10,.2f}")
    print(f"  std     = {daily_totals.std():>10,.2f}")
    print(f"  median  = {np.median(daily_totals):>10,.2f}")
    print(f"  p05     = {np.percentile(daily_totals, 5):>10,.2f}")
    print(f"  p95     = {np.percentile(daily_totals, 95):>10,.2f}")
    print(f"  min     = {daily_totals.min():>10,.2f}")
    print(f"  max     = {daily_totals.max():>10,.2f}")

    print("\n=== Per-day PnL (across all seeds × days) ===")
    print(f"  mean per day = {session_pnls.mean():>10,.2f}")
    print(f"  std per day  = {session_pnls.std():>10,.2f}")

    print("\n=== Per-pebble breakdown (mean PnL per session) ===")
    for p in PEBBLES:
        arr = np.array(per_pebble[p])
        print(f"  {p:14s}  mean={arr.mean():>9,.2f}  std={arr.std():>9,.2f}")


if __name__ == "__main__":
    main()
