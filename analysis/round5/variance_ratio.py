"""Variance-ratio test: is the FV process a free random walk or mean-reverting?

For each product, compute:
  var(X_t - X_{t-H}) / (H * var(X_t - X_{t-1}))
for H in {1, 10, 100, 500, 1000}.

  pure RW: ratio = 1.0 at all horizons
  bid-ask bounce contaminating σ_1: ratio > 1 at short H (because true σ < σ_1
       observed; at long H bounce is averaged out)
  mean reversion: ratio < 1 and decreasing in H

The earlier 'obs_std/RW_expected ≈ 0.2-0.4' could be either MR or bounce-inflated
σ_1. This disambiguates: if ratios at H=1000 are still ≪ 1, it's MR;
if ratios approach 1 at H=1000, σ_1 was just inflated by bounce.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"

CATEGORIES = {
    "GALAXY_": "galaxy_sounds", "SLEEP_": "sleep_pods",
    "MICROCHIP_": "microchips", "PEBBLES_": "pebbles",
    "ROBOT_": "robots", "UV_": "uv_visors",
    "TRANSLATOR_": "translators", "PANEL_": "panels",
    "OXYGEN_": "oxygen_shakes", "SNACKPACK_": "snackpacks",
}


def cat_of(s: str) -> str:
    for prefix, c in CATEGORIES.items():
        if s.startswith(prefix):
            return c
    raise ValueError(s)


def load_mid():
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        f["tick"] = (d - 2) * 10_000 + f["timestamp"] // 100
        frames.append(f.pivot(index="tick", columns="product", values="mid_price"))
    return pd.concat(frames).sort_index()


def variance_ratio(x: np.ndarray, H: int) -> float:
    if H >= len(x):
        return float("nan")
    var_1 = np.var(np.diff(x))
    var_H = np.var(x[H:] - x[:-H])
    if var_1 == 0:
        return float("nan")
    return float(var_H / (H * var_1))


def main():
    mid = load_mid()
    print(f"loaded {mid.shape}\n")

    horizons = [1, 5, 10, 50, 100, 500, 1000, 5000]
    rows = []
    for product in mid.columns:
        v = mid[product].values
        # Detrend first to handle drift
        t = np.arange(len(v))
        slope, intercept = np.polyfit(t, v, 1)
        v_det = v - (intercept + slope * t)
        rec = {"product": product, "category": cat_of(product)}
        for H in horizons:
            rec[f"VR_H{H}"] = variance_ratio(v_det, H)
        rec["sigma_diff"] = float(np.diff(v).std())
        rec["sigma_step100"] = float((v_det[100:] - v_det[:-100]).std() / np.sqrt(100))
        rec["sigma_step1000"] = float((v_det[1000:] - v_det[:-1000]).std() / np.sqrt(1000))
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("product")
    df = df.sort_values(["category"] + [f"VR_H{H}" for H in horizons[-2:]])

    print("=== Variance ratio at each horizon (per product, detrended) ===")
    print("(RW: 1.0 at all H. MR: decreasing in H. Bounce-inflated sigma_1: increasing in H.)\n")
    cols = ["category"] + [f"VR_H{H}" for H in horizons]
    print(df[cols].to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n=== sigma_per_tick estimates ===")
    print("(sigma_diff = first differences; sigma_step100 = 100-step / sqrt(100); sigma_step1000 = 1000-step / sqrt(1000))")
    print("If process is RW with no bounce, all three should match. If bounce inflates sigma_diff, sigma_step100/1000 will be lower.")
    print()
    print(df[["category", "sigma_diff", "sigma_step100", "sigma_step1000"]].to_string(float_format=lambda v: f"{v:.2f}"))

    # Aggregate by category for cleaner read
    print("\n\n=== Per-category summary ===")
    cat_agg = df.groupby("category")[
        [f"VR_H{H}" for H in horizons] + ["sigma_diff", "sigma_step100", "sigma_step1000"]
    ].mean()
    print(cat_agg.to_string(float_format=lambda v: f"{v:.3f}"))

    # Diagnostic: ratio of sigma_step1000 / sigma_diff
    df["true_sigma_ratio"] = df["sigma_step1000"] / df["sigma_diff"]
    print("\n\n=== Bounce indicator: sigma_step1000 / sigma_diff per category ===")
    print("(Pure RW: 1.0. Heavy bounce: <1. MR: <1 too, but variance ratio test discriminates.)")
    print(df.groupby("category")["true_sigma_ratio"].mean().to_string(float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
