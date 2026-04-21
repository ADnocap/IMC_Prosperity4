"""
Validate the R2 PEPPER starting FV and drift continuity from the hold-1 submission.

The R2 hypothesis: PEPPER does NOT reset to 10,000 at the start of R2 — the +0.1/tick
drift that ran across R1 days -2/-1/0 keeps going. R1 day 0 ended at ~13,000, so R2
day 1 should start at ~13,000.

We extracted the true server FV path from portal hold-1 submission 274082
(`traders/trader_hold1.py`) into `calibration/intarian_pepper_root/data/r2_day1_fv.json`.
This script walks that path and reports:

  * Starting FV (should be ~13,000)
  * Per-tick drift (should be ~+0.1)
  * Residual std (should be ~0, since PEPPER is deterministic)

Run:
    py -3.13 analysis/round2/check_pepper_start.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
FV_JSON = REPO / "calibration" / "intarian_pepper_root" / "data" / "r2_day1_fv.json"


def main() -> int:
    with open(FV_JSON) as f:
        d = json.load(f)

    # Index 0 is the t=0 buy-at-ask anchor (the price we paid, not the server FV).
    # True server FV starts at index 1, after the first PnL update is observable.
    pepper_full = d["pepper"]
    buy_anchor = pepper_full[0]
    fv = pepper_full[1:]
    n = len(fv)
    start = fv[0]
    end = fv[-1]

    diffs = [fv[i + 1] - fv[i] for i in range(n - 1)]
    drift_mean = statistics.fmean(diffs)
    drift_std = statistics.pstdev(diffs)

    residuals = [fv[i] - (start + 0.1 * i) for i in range(n)]
    residual_std = statistics.pstdev(residuals)
    residual_max = max(abs(r) for r in residuals)

    print("PEPPER R2 day 1 drift check")
    print(f"  Source:           {d.get('source', FV_JSON.name)}")
    print(f"  Ticks (FV):       {n}")
    print(f"  Buy-at-ask (t=0): {buy_anchor:.4f}")
    print(f"  Start FV (t=1):   {start:.4f}   (expected ≈ 13000)")
    print(f"  End FV:           {end:.4f}   (expected ≈ 13100 after ~1000 ticks)")
    print(f"  Mean per-tick Δ:  {drift_mean:+.6f}   (expected +0.100000)")
    print(f"  Std of Δ:         {drift_std:.6f}   (expected ≈ 0.0005 quantization)")
    print(f"  Max residual vs deterministic line: {residual_max:.4f}")
    print(f"  Residual std:     {residual_std:.4f}")

    # Pass/fail gates
    gates = [
        ("Start ~ 13,000",       abs(start - 13_000) < 20,         f"|start − 13000| = {abs(start - 13_000):.2f}"),
        ("Drift ~ +0.1",         abs(drift_mean - 0.1) < 0.001,    f"|Δmean − 0.1| = {abs(drift_mean - 0.1):.6f}"),
        ("Residual std ~ 0",     residual_std < 0.01,              f"residual std = {residual_std:.4f}"),
    ]

    print("\nGates")
    all_ok = True
    for name, ok, detail in gates:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}  —  {detail}")
        all_ok = all_ok and ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
