"""Sweep every 5-product category for hidden linear constraints (basket
arbitrage candidates). For each category compute:
  - PCA eigenvalue spectrum on log-returns (small last-eigenvalues = constraint)
  - Per-day sum/4-of-5/3-of-5 standard deviations (tight = constant sum)
  - Best 2-asset and 3-asset coint linear combos by residual std

Same approach used to crack snackpacks (CHOC+VANILLA constant per day,
PCA showing 2-factor structure with eigvals [2.78, 1.91, 0.20, 0.08, 0.03]).
The signature of a hidden constraint is a small last eigenvalue (≤ 0.1) on
normalized return covariance — a 5-asset matrix with no constraint trends
toward eigvals ≈ [1, 1, 1, 1, 1].
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
OUT_DIR = REPO_ROOT / "analysis" / "round5"

CATEGORIES: Dict[str, List[str]] = {
    "galaxy_sounds": [
        "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "sleep_pods": [
        "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
    ],
    "microchips": [
        "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
    ],
    "pebbles": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "robots": [
        "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
        "ROBOT_LAUNDRY", "ROBOT_IRONING",
    ],
    "uv_visors": [
        "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
        "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    ],
    "translators": [
        "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "panels": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "oxygen_shakes": [
        "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
    ],
    "snackpacks": [
        "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
    ],
}
ALL = [p for ps in CATEGORIES.values() for p in ps]


def load_mid() -> pd.DataFrame:
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        frames.append(df.pivot(index="tick", columns="product", values="mid_price")[ALL])
    return pd.concat(frames).sort_index()


def category_signature(mid: pd.DataFrame, members: List[str]) -> Dict:
    """Look for hidden constraints in a 5-asset bundle."""
    sub = mid[members]
    rets = sub.pct_change().dropna()
    rets_n = (rets - rets.mean()) / rets.std()
    eigvals = np.linalg.eigvalsh(rets_n.cov().values)[::-1]
    eigvals = [float(v) for v in eigvals]
    # absolute level signal: total sum std
    total = sub.sum(axis=1)
    # per-day total stats (3 days x 10K ticks)
    n = len(sub)
    if n == 30_000:
        per_day = total.values.reshape(3, 10_000)
        per_day_means = [float(per_day[d].mean()) for d in range(3)]
        per_day_stds = [float(per_day[d].std()) for d in range(3)]
    else:
        per_day_means, per_day_stds = [], []

    return {
        "eigvals": eigvals,
        "smallest_eigval": eigvals[-1],
        "second_smallest": eigvals[-2],
        "var_explained_top2": (eigvals[0] + eigvals[1]) / sum(eigvals),
        "total_sum_mean": float(total.mean()),
        "total_sum_std": float(total.std()),
        "total_sum_std_normalized": float(total.std() / sub.std().mean()),  # vs avg per-asset σ
        "per_day_total_means": per_day_means,
        "per_day_total_stds": per_day_stds,
    }


def best_pair_constraints(mid: pd.DataFrame, members: List[str]) -> List[Dict]:
    """Find the 2-asset combos within a category whose linear residual is tightest."""
    out: List[Dict] = []
    for a, b in combinations(members, 2):
        x = mid[a].values
        y = mid[b].values
        # fit y = alpha + beta * x
        beta = np.cov(x, y, ddof=0)[0, 1] / np.var(x)
        alpha = y.mean() - beta * x.mean()
        resid = y - (alpha + beta * x)
        # residual AR(1) for half-life
        if resid.std() > 0:
            phi = np.corrcoef(resid[:-1], resid[1:])[0, 1]
            half_life = float(np.log(0.5) / np.log(phi)) if 0 < phi < 1 else float("inf")
        else:
            phi = float("nan")
            half_life = float("inf")
        # also report sum_std (constant-sum check)
        s = x + y
        # check per-day sum_std
        per_day_sum_std = []
        if len(s) == 30_000:
            for d in range(3):
                per_day_sum_std.append(float(s.reshape(3, 10_000)[d].std()))
        out.append({
            "a": a, "b": b,
            "beta": float(beta), "alpha": float(alpha),
            "resid_std": float(resid.std()),
            "resid_phi": float(phi),
            "resid_half_life_ticks": half_life,
            "sum_std_global": float(s.std()),
            "sum_std_per_day": per_day_sum_std,
        })
    out.sort(key=lambda r: r["resid_std"])
    return out


def main():
    mid = load_mid()
    print(f"loaded {mid.shape}\n")

    print("=== Per-category PCA signatures (smallest eigvals = hidden constraints) ===")
    print(f"  Reference: random 5 independent assets → eigvals ~ [1.0, 1.0, 1.0, 1.0, 1.0]")
    print(f"  Snackpacks ground truth → eigvals [2.78, 1.91, 0.20, 0.08, 0.03] (TWO constraints)\n")
    sigs = {}
    for cat, members in CATEGORIES.items():
        sig = category_signature(mid, members)
        sigs[cat] = sig
        ev = sig["eigvals"]
        per_day = sig["per_day_total_stds"]
        print(f"  {cat:14s}  eigvals: " + " ".join(f"{v:5.2f}" for v in ev) +
              f"   total_sum: mean={sig['total_sum_mean']:>10.0f} std={sig['total_sum_std']:>7.1f}" +
              f"   per_day_std: " + " ".join(f"{v:6.1f}" for v in per_day))

    # Per-category best pair
    print("\n=== Best 2-asset pair constraints per category (lowest resid_std) ===")
    pair_results = {}
    for cat, members in CATEGORIES.items():
        pairs = best_pair_constraints(mid, members)
        pair_results[cat] = pairs
        top = pairs[0]
        per_day = top["sum_std_per_day"]
        print(f"\n  {cat}:")
        for p in pairs[:3]:
            pd_str = " ".join(f"{v:5.1f}" for v in p["sum_std_per_day"])
            print(f"    {p['a'][:25]:25s} ~ {p['b'][:25]:25s}  beta={p['beta']:+.4f}  "
                  f"resid_std={p['resid_std']:7.2f}  HL={p['resid_half_life_ticks']:>7.0f}  "
                  f"sum_std_per_day={pd_str}")

    bundle = {
        "category_signatures": sigs,
        "best_pairs_per_category": {c: ps[:5] for c, ps in pair_results.items()},
    }
    out = OUT_DIR / "basket_search.json"
    out.write_text(json.dumps(bundle, indent=2))
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
