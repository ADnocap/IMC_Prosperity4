"""SNACKPACK structure dive — chase the -0.92 return correlation between
STRAWBERRY/RASPBERRY and -0.91 between CHOC/VANILLA. Hypotheses:
  H1: pairs sum to a constant (e.g. CHOC + VANILLA = K1, STRAW + RASP = K2)
  H2: each pack is a function of one shared latent
  H3: PISTACHIO is the wildcard / tracker
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"

PACKS = ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
         "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]


def load_mid() -> pd.DataFrame:
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        frames.append(df.pivot(index="tick", columns="product", values="mid_price")[PACKS])
    return pd.concat(frames).sort_index()


def main():
    mid = load_mid()
    print(f"shape: {mid.shape}\n")

    # H1: pair sums
    print("=== H1: pair sums (looking for constants) ===")
    pairs = [
        ("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"),
        ("SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"),
        ("SNACKPACK_CHOCOLATE", "SNACKPACK_PISTACHIO"),
        ("SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO"),
        ("SNACKPACK_STRAWBERRY", "SNACKPACK_PISTACHIO"),
        ("SNACKPACK_RASPBERRY", "SNACKPACK_PISTACHIO"),
    ]
    for a, b in pairs:
        s = mid[a] + mid[b]
        d = mid[a] - mid[b]
        print(f"  {a:25s} + {b:25s}  mean={s.mean():>9.2f}  std={s.std():>7.3f}  "
              f"range=[{s.min():>9.2f},{s.max():>9.2f}]  diff_std={d.std():>7.3f}")

    # H1b: total sum (5-pack basket constant?)
    total = mid.sum(axis=1)
    print(f"\n  TOTAL (all 5):           mean={total.mean():9.2f}  std={total.std():7.3f}  "
          f"range=[{total.min():9.2f},{total.max():9.2f}]")

    # 4-pack subsets
    print("\n=== 4-pack subset sums (drop one) ===")
    for drop in PACKS:
        keep = [p for p in PACKS if p != drop]
        s = mid[keep].sum(axis=1)
        print(f"  drop {drop:25s}  sum_std={s.std():7.3f}")

    # H2: PCA / shared latent
    print("\n=== H2: PCA (return-space, demeaned/normalized) ===")
    rets = mid.pct_change().dropna()
    rets_n = (rets - rets.mean()) / rets.std()
    cov = rets_n.cov()
    eigvals, eigvecs = np.linalg.eigh(cov.values)
    eigvals = eigvals[::-1]
    eigvecs = eigvecs[:, ::-1]
    print(f"  eigvals: {[round(v, 4) for v in eigvals]}")
    print(f"  variance explained: {[round(v / eigvals.sum() * 100, 2) for v in eigvals]} %")
    print("  PC loadings (rows = packs, columns = PCs):")
    for i, p in enumerate(PACKS):
        print(f"    {p:25s}  " + "  ".join(f"{eigvecs[i, j]:+.3f}" for j in range(5)))

    # H3: linear combos with integer-ish coefficients
    print("\n=== H3: try integer-coef linear combos that null out variance ===")
    # The two strongest negative pairs suggest CHOC = -VANILLA + const, STRAW = -RASP + const.
    # Check: regression beta of CHOC ~ VANILLA, RASP ~ STRAW
    for y, x in [("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"),
                 ("SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY")]:
        beta = np.polyfit(mid[x].values, mid[y].values, 1)
        resid = mid[y].values - (beta[0] * mid[x].values + beta[1])
        print(f"  {y} = {beta[0]:.4f} * {x} + {beta[1]:.2f}   resid_std={resid.std():.3f}")

    # H4: rolling sums + adjacency
    print("\n=== H4: short-window stationarity check ===")
    for a, b in [("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"),
                 ("SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY")]:
        s = mid[a] + mid[b]
        # check if sum is locally constant per day
        per_day = s.values.reshape(3, 10_000) if len(s) == 30_000 else None
        if per_day is not None:
            for d in range(3):
                print(f"  day {d + 2}  {a}+{b}  mean={per_day[d].mean():9.2f}  "
                      f"std={per_day[d].std():7.3f}")


if __name__ == "__main__":
    main()
