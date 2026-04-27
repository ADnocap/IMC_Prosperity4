"""Rank per-strike IV-scalp tuner trials.

Reads tmp/optimizer/iv_scalp_perstrike_<dir>/results.csv and prints:
  - V2 baseline row (trial 0)
  - Top-K by total
  - Top-K by holdout
  - Per-strike contribution breakdown (winner vs V2)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List


STRIKES = (5000, 5100, 5200, 5300, 5400, 5500)
PER_VEV = [f"VEV_{K}" for K in STRIKES]


def read_rows(csv_path: Path) -> List[Dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def i(row: Dict, k: str) -> int:
    v = row.get(k, "")
    if v == "" or v is None:
        return 0
    return int(v)


def fmt_per_strike_thr(row: Dict, mode: str) -> str:
    parts = []
    for K in STRIKES:
        v = row.get(f"THR_OPEN_{K}", "")
        if v == "":
            parts.append("---")
        else:
            parts.append(f"{float(v):.3f}")
    s = " / ".join(parts)
    if mode == "thr_open_size":
        sizes = []
        for K in STRIKES:
            v = row.get(f"SCALP_MAX_PER_TICK_{K}", "")
            if v == "":
                sizes.append("--")
            else:
                sizes.append(f"{int(float(v))}")
        s += "  size: " + "/".join(sizes)
    return s


def per_vev_total(row: Dict) -> Dict[str, int]:
    out = {}
    for asset in PER_VEV:
        out[asset] = sum(i(row, f"d{d}_{asset}") for d in (1, 2, 3))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=str)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--mode", choices=("thr_open", "thr_open_size"),
                    default="thr_open")
    args = ap.parse_args()

    rows = read_rows(Path(args.csv_path))
    rows = [r for r in rows if r.get("ok") == "1"]
    if not rows:
        print("No successful trials.")
        return

    baseline = rows[0]
    bsl_total = i(baseline, "total")
    bsl_train = i(baseline, "train")
    bsl_hold = i(baseline, "holdout")
    bsl_per_vev = per_vev_total(baseline)

    print(f"Baseline trial 0 (V2 uniform):")
    print(f"  total={bsl_total:,}  train={bsl_train:,}  hold={bsl_hold:,}")
    print(f"  per-VEV: " + ", ".join(f"{a}={v:+d}" for a, v in bsl_per_vev.items()))
    print()

    by_total = sorted(rows, key=lambda r: i(r, "total"), reverse=True)
    by_hold = sorted(rows, key=lambda r: i(r, "holdout"), reverse=True)

    print(f"=== TOP {args.top} BY TOTAL ===")
    print(f"{'rk':>2}  {'tr':>4}  {'total':>7}  {'train':>7}  {'hold':>7}  "
          f"{'dHold':>5}  per-strike THR_OPEN (5000/5100/5200/5300/5400/5500)")
    for k, r in enumerate(by_total[:args.top]):
        t = i(r, "total")
        tr = i(r, "train")
        h = i(r, "holdout")
        dh = h - bsl_hold
        print(f"{k+1:>2}  {r['trial']:>4}  {t:>7,}  {tr:>7,}  {h:>7,}  "
              f"{dh:>+5d}  {fmt_per_strike_thr(r, args.mode)}")
    print()

    print(f"=== TOP {args.top} BY HOLDOUT ===")
    print(f"{'rk':>2}  {'tr':>4}  {'total':>7}  {'train':>7}  {'hold':>7}  "
          f"{'dHold':>5}  per-strike THR_OPEN")
    for k, r in enumerate(by_hold[:args.top]):
        t = i(r, "total")
        tr = i(r, "train")
        h = i(r, "holdout")
        dh = h - bsl_hold
        print(f"{k+1:>2}  {r['trial']:>4}  {t:>7,}  {tr:>7,}  {h:>7,}  "
              f"{dh:>+5d}  {fmt_per_strike_thr(r, args.mode)}")
    print()

    print(f"=== PER-VEV BREAKDOWN, top-3 by holdout vs V2 ===")
    for r in by_hold[:3]:
        print(f"trial {r['trial']}: hold={i(r, 'holdout'):,}, total={i(r, 'total'):,}")
        per = per_vev_total(r)
        for a in PER_VEV:
            d = per[a] - bsl_per_vev[a]
            print(f"  {a}: {per[a]:+d} (V2 {bsl_per_vev[a]:+d}, dV2 {d:+d})")
        print()

    # Distribution of holdout
    holds = [i(r, "holdout") for r in rows]
    n_geq = sum(1 for h in holds if h >= bsl_hold)
    print(f"Trials passing holdout >= V2 ({bsl_hold:,}): {n_geq}/{len(rows)} "
          f"({100*n_geq/len(rows):.0f}%)")
    n_geq_total = sum(1 for r in rows if i(r, "total") >= bsl_total + 1000)
    print(f"Trials passing total >= V2+1000 ({bsl_total + 1000:,}): {n_geq_total}/{len(rows)} "
          f"({100*n_geq_total/len(rows):.0f}%)")
    n_both = sum(1 for r in rows if i(r, "holdout") >= bsl_hold and i(r, "total") >= bsl_total + 1000)
    print(f"Trials passing BOTH ship gates: {n_both}/{len(rows)}")


if __name__ == "__main__":
    main()
