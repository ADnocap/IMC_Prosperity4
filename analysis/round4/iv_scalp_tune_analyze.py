"""Analyze iv_scalp_tune results CSV: rank trials, gate by holdout."""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

CSV_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else
                 "tmp/optimizer/iv_scalp_tune_main/results.csv")

PARAM_NAMES = [
    "THR_OPEN", "THR_CLOSE", "IV_SCALPING_THR", "SCALP_MAX_PER_TICK",
    "THEO_NORM_WINDOW", "IV_SCALPING_WINDOW",
    "LOW_VEGA_THR_ADJ", "LOW_VEGA_CUTOFF", "SMILE_A_ALPHA",
]

BASELINE_TOTAL = 27444
BASELINE_HOLDOUT = 11901
SHIP_UPLIFT = 1500


def load(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("ok") != "1":
                continue
            r["total"] = int(r["total"])
            r["train"] = int(r["train"])
            r["holdout"] = int(r["holdout"])
            r["d1_total"] = int(r["d1_total"])
            r["d2_total"] = int(r["d2_total"])
            r["d3_total"] = int(r["d3_total"])
            rows.append(r)
    return rows


def fmt_params(r):
    parts = []
    for n in PARAM_NAMES:
        v = r[n]
        try:
            f = float(v)
            if f == int(f):
                parts.append(f"{n}={int(f)}")
            else:
                parts.append(f"{n}={f:g}")
        except ValueError:
            parts.append(f"{n}={v}")
    return ", ".join(parts)


def main():
    rows = load(CSV_PATH)
    print(f"Loaded {len(rows)} ok trials from {CSV_PATH}")
    print(f"Baseline: total={BASELINE_TOTAL}, holdout={BASELINE_HOLDOUT}")
    print(f"Ship gate: total >= {BASELINE_TOTAL + SHIP_UPLIFT}, "
          f"holdout >= {BASELINE_HOLDOUT}")
    print()

    # Top 10 by total
    by_total = sorted(rows, key=lambda r: r["total"], reverse=True)
    print("=== Top 10 by TOTAL ===")
    for r in by_total[:10]:
        gate = "PASS" if r["holdout"] >= BASELINE_HOLDOUT else "FAIL_HOLDOUT"
        print(f"  trial {r['trial']:>3}: total={r['total']:6d} "
              f"train={r['train']:5d} hold={r['holdout']:5d} "
              f"d1={r['d1_total']:5d} d2={r['d2_total']:5d} "
              f"d3={r['d3_total']:5d}  [{gate}]")
        print(f"      {fmt_params(r)}")
    print()

    # Trials passing both ship gates
    candidates = [r for r in rows
                  if r["total"] >= BASELINE_TOTAL + SHIP_UPLIFT
                  and r["holdout"] >= BASELINE_HOLDOUT]
    candidates.sort(key=lambda r: r["total"], reverse=True)
    print(f"=== Trials passing BOTH ship gates "
          f"(total>={BASELINE_TOTAL+SHIP_UPLIFT}, "
          f"holdout>={BASELINE_HOLDOUT}): {len(candidates)} ===")
    for r in candidates[:15]:
        print(f"  trial {r['trial']:>3}: total={r['total']:6d} "
              f"train={r['train']:5d} hold={r['holdout']:5d} "
              f"d1={r['d1_total']:5d} d2={r['d2_total']:5d} "
              f"d3={r['d3_total']:5d}")
        print(f"      {fmt_params(r)}")
    print()

    # Top 5 by holdout (OOS robustness)
    by_hold = sorted(rows, key=lambda r: r["holdout"], reverse=True)
    print("=== Top 10 by HOLDOUT (D3) ===")
    for r in by_hold[:10]:
        gate = "PASS" if r["total"] >= BASELINE_TOTAL + SHIP_UPLIFT else "fail_total"
        print(f"  trial {r['trial']:>3}: total={r['total']:6d} "
              f"train={r['train']:5d} hold={r['holdout']:5d}  [{gate}]")

    # Print best candidate as JSON
    if candidates:
        best = candidates[0]
        params = {n: float(best[n]) for n in PARAM_NAMES}
        # ints stay ints
        for k in ("SCALP_MAX_PER_TICK", "THEO_NORM_WINDOW", "IV_SCALPING_WINDOW"):
            params[k] = int(params[k])
        print()
        print("=== BEST SHIPPABLE CANDIDATE ===")
        print(json.dumps(params, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
