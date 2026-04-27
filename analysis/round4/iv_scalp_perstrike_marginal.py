"""Marginal analysis: which per-strike THR_OPEN values deliver per-strike PnL
above V2's per-strike PnL?  This isolates each strike (rather than relying on
total, which is noisy)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List


STRIKES = (5000, 5100, 5200, 5300, 5400, 5500)


def main():
    csv_path = Path(sys.argv[1])
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("ok") != "1":
                continue
            rows.append(r)

    bsl = rows[0]
    bsl_per_vev = {K: sum(int(bsl[f"d{d}_VEV_{K}"]) for d in (1, 2, 3))
                   for K in STRIKES}

    # For each strike, fit per-strike PnL as a function of THR_OPEN. Show the
    # buckets.
    print(f"V2 per-VEV totals: " + ", ".join(
        f"VEV_{K}={bsl_per_vev[K]}" for K in STRIKES))
    print()

    BUCKETS = [(0.20, 0.40), (0.40, 0.60), (0.60, 0.80), (0.80, 1.00),
               (1.00, 1.20), (1.20, 1.50)]
    for K in STRIKES:
        print(f"--- VEV_{K} (V2 PnL = {bsl_per_vev[K]}) ---")
        print(f"{'THR_OPEN bucket':>16}  {'n':>4}  {'mean PnL':>9}  {'best PnL':>9}  {'dV2(mean)':>10}")
        for lo, hi in BUCKETS:
            sub = []
            for r in rows[1:]:
                v = float(r[f"THR_OPEN_{K}"])
                if lo <= v < hi:
                    pnl = sum(int(r[f"d{d}_VEV_{K}"]) for d in (1, 2, 3))
                    sub.append(pnl)
            if not sub:
                continue
            mean = sum(sub) / len(sub)
            best = max(sub)
            print(f"  [{lo:.2f}, {hi:.2f})  {len(sub):>4}  {mean:>9.0f}  "
                  f"{best:>9d}  {mean - bsl_per_vev[K]:>+10.1f}")
        print()


if __name__ == "__main__":
    main()
