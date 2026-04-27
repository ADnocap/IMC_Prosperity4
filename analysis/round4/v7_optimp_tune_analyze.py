"""Analyze v7_optimp_tune results.csv for overfit signature.

Usage: py -3.13 analysis/round4/v7_optimp_tune_analyze.py [results.csv]
       (defaults to tmp/optimizer/v7_optimp_main/results.csv)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from statistics import median, stdev


V2_TRAIN = 14_675 + 2_946  # 17,621
V2_HOLDOUT = 12_312
V2_TOTAL = 29_934

# Ship gates
GATE_TOTAL = V2_TOTAL + 1_500   # 31,434
GATE_HOLDOUT = V2_HOLDOUT + 500  # 12,812


def load(path: Path):
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("ok") != "1":
                continue
            try:
                r["train"] = int(r["train"])
                r["holdout"] = int(r["holdout"])
                r["total"] = int(r["total"])
                r["d1_total"] = int(r["d1_total"])
                r["d2_total"] = int(r["d2_total"])
                r["d3_total"] = int(r["d3_total"])
                r["OPTIMP_THR"] = float(r["OPTIMP_THR"])
                r["OPTIMP_TAKE_SIZE"] = int(float(r["OPTIMP_TAKE_SIZE"]))
                r["OPTIMP_COOLDOWN"] = int(float(r["OPTIMP_COOLDOWN"]))
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path("tmp/optimizer/v7_optimp_main/results.csv")
    rows = load(path)
    print(f"loaded {len(rows)} valid trials from {path}")
    print(f"V2 baseline: train {V2_TRAIN:,} | holdout {V2_HOLDOUT:,} | total {V2_TOTAL:,}")
    print(f"Ship gates:  total >= {GATE_TOTAL:,} AND holdout >= {GATE_HOLDOUT:,}")
    print()

    # Top by train (D1+D2 — the overfit-prone direction).
    by_train = sorted(rows, key=lambda r: -r["train"])[:10]
    print("TOP 10 BY TRAIN (D1+D2). Watch holdout to detect overfit.")
    hdr = "rank | thr  sz  cd | train  holdout  total | beats V2 holdout?"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(by_train, 1):
        beats = "YES" if r["holdout"] >= V2_HOLDOUT else "no "
        print(f"{i:4d} | {r['OPTIMP_THR']:4.1f} {r['OPTIMP_TAKE_SIZE']:3d} {r['OPTIMP_COOLDOWN']:4d} "
              f"| {r['train']:6d}  {r['holdout']:6d}  {r['total']:6d} | {beats}")
    print()

    # Top by holdout — these are the *robust* configs, if any.
    by_hold = sorted(rows, key=lambda r: -r["holdout"])[:10]
    print("TOP 10 BY HOLDOUT (D3, only true OOS sample).")
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(by_hold, 1):
        gate = "SHIP" if (r["total"] >= GATE_TOTAL and r["holdout"] >= GATE_HOLDOUT) else "    "
        print(f"{i:4d} | {r['OPTIMP_THR']:4.1f} {r['OPTIMP_TAKE_SIZE']:3d} {r['OPTIMP_COOLDOWN']:4d} "
              f"| {r['train']:6d}  {r['holdout']:6d}  {r['total']:6d} | {gate}")
    print()

    # Top by min(train_uplift, holdout_uplift) — most balanced
    def balanced(r):
        return min(r["train"] - V2_TRAIN, r["holdout"] - V2_HOLDOUT)
    by_balance = sorted(rows, key=lambda r: -balanced(r))[:10]
    print("TOP 10 BY min(train_uplift, holdout_uplift). Most balanced wins.")
    print(hdr + "  | min_uplift")
    print("-" * len(hdr))
    for i, r in enumerate(by_balance, 1):
        print(f"{i:4d} | {r['OPTIMP_THR']:4.1f} {r['OPTIMP_TAKE_SIZE']:3d} {r['OPTIMP_COOLDOWN']:4d} "
              f"| {r['train']:6d}  {r['holdout']:6d}  {r['total']:6d} | {balanced(r):+6d}")
    print()

    # Configs passing ship gates
    passers = [r for r in rows if r["total"] >= GATE_TOTAL and r["holdout"] >= GATE_HOLDOUT]
    print(f"CONFIGS PASSING SHIP GATES: {len(passers)} / {len(rows)} ({100*len(passers)/max(1,len(rows)):.1f}%)")
    if passers:
        for r in sorted(passers, key=lambda r: -r["total"])[:5]:
            print(f"  thr={r['OPTIMP_THR']:.1f} sz={r['OPTIMP_TAKE_SIZE']} cd={r['OPTIMP_COOLDOWN']} | "
                  f"train={r['train']} hold={r['holdout']} total={r['total']}")
    print()

    # Beats V2 in BOTH train and holdout
    both = [r for r in rows if r["train"] > V2_TRAIN and r["holdout"] > V2_HOLDOUT]
    print(f"CONFIGS BEATING V2 IN BOTH TRAIN AND HOLDOUT: {len(both)} / {len(rows)}")
    if both:
        for r in sorted(both, key=lambda r: -(r["train"] + r["holdout"]))[:10]:
            print(f"  thr={r['OPTIMP_THR']:.1f} sz={r['OPTIMP_TAKE_SIZE']} cd={r['OPTIMP_COOLDOWN']} | "
                  f"train={r['train']:+,} hold={r['holdout']:+,}")
    print()

    # Scatter summary: train vs holdout correlation
    if len(rows) >= 5:
        trains = [r["train"] for r in rows]
        holds = [r["holdout"] for r in rows]
        n = len(rows)
        mt = sum(trains) / n
        mh = sum(holds) / n
        cov = sum((t - mt) * (h - mh) for t, h in zip(trains, holds)) / n
        st = stdev(trains) if n > 1 else 1
        sh = stdev(holds) if n > 1 else 1
        corr = cov / (st * sh) if st * sh > 0 else 0
        print(f"TRAIN vs HOLDOUT correlation: {corr:+.3f}")
        print(f"  positive = params that work on train also work on holdout (good)")
        print(f"  negative = OVERFIT signature (train winners lose on holdout)")
        print(f"  near 0   = no relationship; signal is sample-specific")


if __name__ == "__main__":
    main()
