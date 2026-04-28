"""Pebbles total-sum constraint verification + snackpack 3-asset constraint
characterization.

Pebbles preview: total mid sum across all 5 = 50,000 with std 2.8 over 30K
ticks. If the constraint is exact (sum = 50,000), this is risk-free arb at
the residual scale. The std=2.8 is small enough to be quote-noise (rounding,
half-tick mids).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"

PEBBLES = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"]
SNACKPACKS = ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
              "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]


def load_mid(symbols):
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        frames.append(df.pivot(index="tick", columns="product", values="mid_price")[symbols])
    return pd.concat(frames).sort_index()


def main():
    mid = load_mid(PEBBLES + SNACKPACKS)

    # --- PEBBLES total ---
    print("=== PEBBLES total sum ===")
    pebs = mid[PEBBLES]
    total = pebs.sum(axis=1)
    print(f"  total: mean={total.mean():.4f}  std={total.std():.4f}")
    print(f"  total: min={total.min():.2f}  max={total.max():.2f}")
    print(f"  unique values of total: {sorted(total.unique().tolist())[:20]}")
    print(f"  bin counts of (total - 50000):")
    diff = (total - 50000).round(1)
    for v, n in diff.value_counts().head(15).items():
        pct = 100 * n / len(diff)
        print(f"    {v:+6.1f}  count={n:>6d}  ({pct:5.2f}%)")

    # Check whether each pebble's mid is half-integer or integer
    print("\n=== Are pebble mids half-integers? ===")
    for p in PEBBLES:
        v = mid[p]
        frac = (v - v.astype(int)).abs()
        unique_fracs = sorted(frac.unique().tolist())
        print(f"  {p:15s} unique fractions: {unique_fracs[:5]}  n_unique={len(unique_fracs)}")

    # --- PEBBLES PCA eigenvector for smallest eigenvalue ---
    print("\n=== Pebbles PCA: smallest-eigval direction ===")
    rets = pebs.pct_change().dropna()
    rets_n = (rets - rets.mean()) / rets.std()
    cov = rets_n.cov().values
    eigvals, eigvecs = np.linalg.eigh(cov)
    print(f"  eigvals: {eigvals.tolist()}")
    print(f"  smallest-eigval eigvector (should be ~constant if constraint is sum):")
    smallest_vec = eigvecs[:, 0]
    for i, p in enumerate(PEBBLES):
        print(f"    {p:15s}  {smallest_vec[i]:+.4f}")
    # try level-space PCA too
    print("\n  level-space PCA (no return scaling):")
    cov_lvl = pebs.cov().values
    ev_lvl, evec_lvl = np.linalg.eigh(cov_lvl)
    print(f"  eigvals: {ev_lvl.tolist()}")
    print(f"  smallest eigvector:")
    for i, p in enumerate(PEBBLES):
        print(f"    {p:15s}  {evec_lvl[:, 0][i]:+.4f}")

    # --- Per-day diagnostic ---
    print("\n=== PEBBLES per-day total ===")
    n = len(total)
    if n == 30_000:
        per_day = total.values.reshape(3, 10_000)
        for d in range(3):
            print(f"  day {d + 2}: mean={per_day[d].mean():.4f}  std={per_day[d].std():.4f}  "
                  f"min={per_day[d].min():.2f}  max={per_day[d].max():.2f}")

    # --- SNACKPACKS 3-asset constraint (PISTACHIO/STRAW/RASP) ---
    print("\n=== SNACKPACKS 3-asset constraint (PIS/STRAW/RASP) ===")
    triplet = ["SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
    sub = mid[triplet]
    # sum
    s = sub.sum(axis=1)
    print(f"  PIS+STRAW+RASP   mean={s.mean():.2f}  std={s.std():.2f}")
    # PCA smallest direction
    cov = sub.cov().values
    eigvals, eigvecs = np.linalg.eigh(cov)
    print(f"  eigvals: {eigvals.tolist()}")
    print(f"  smallest-eigval direction:")
    for i, p in enumerate(triplet):
        print(f"    {p:25s}  {eigvecs[:, 0][i]:+.4f}")
    # full 3-asset combo: try fit STRAW + RASP - 2*PIS or similar
    # The eigvec gives the linear combo whose std is minimized
    proj = sub.values @ eigvecs[:, 0]
    print(f"  projection on smallest eigvec: mean={proj.mean():.2f}  std={proj.std():.4f}")

    # try 2nd smallest too
    proj2 = sub.values @ eigvecs[:, 1]
    print(f"  projection on 2nd smallest:    mean={proj2.mean():.2f}  std={proj2.std():.4f}")

    # Try simple combos: STRAW + RASP - 2*PIS, STRAW - RASP, etc.
    combos = {
        "STRAW + RASP": mid["SNACKPACK_STRAWBERRY"] + mid["SNACKPACK_RASPBERRY"],
        "STRAW - RASP": mid["SNACKPACK_STRAWBERRY"] - mid["SNACKPACK_RASPBERRY"],
        "PIS + STRAW + RASP": mid[triplet].sum(axis=1),
        "PIS + STRAW - RASP": mid["SNACKPACK_PISTACHIO"] + mid["SNACKPACK_STRAWBERRY"] - mid["SNACKPACK_RASPBERRY"],
        "PIS + RASP - STRAW": mid["SNACKPACK_PISTACHIO"] + mid["SNACKPACK_RASPBERRY"] - mid["SNACKPACK_STRAWBERRY"],
        "STRAW + RASP - 2*PIS": mid["SNACKPACK_STRAWBERRY"] + mid["SNACKPACK_RASPBERRY"] - 2 * mid["SNACKPACK_PISTACHIO"],
        "2*PIS - STRAW - RASP": 2 * mid["SNACKPACK_PISTACHIO"] - mid["SNACKPACK_STRAWBERRY"] - mid["SNACKPACK_RASPBERRY"],
    }
    print("\n  integer-coef combos:")
    for name, v in combos.items():
        print(f"    {name:32s}  mean={v.mean():>10.2f}  std={v.std():.3f}")


if __name__ == "__main__":
    main()
