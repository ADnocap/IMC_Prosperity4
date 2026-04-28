"""FV dynamics deep-dive: per-asset FV process classification + cross-asset
constraint dynamics.

For each asset, fit:
  - random walk: σ_per_tick estimate (return std)
  - mean reversion: AR(1) phi on detrended levels, half-life
  - drift: linear trend test (is the slope significant given σ?)
  - Ornstein-Uhlenbeck: combined drift + MR on levels

For Pebbles + Snackpacks, characterize the constraint dynamics:
  - is the constraint exact (within rounding) or approximate?
  - day-to-day evolution of the constraint constant
  - innovation correlation matrix among free DoF
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
OUT_DIR = REPO_ROOT / "analysis" / "round5"

CATEGORIES = {
    "GALAXY_": "galaxy_sounds", "SLEEP_": "sleep_pods",
    "MICROCHIP_": "microchips", "PEBBLES_": "pebbles",
    "ROBOT_": "robots", "UV_": "uv_visors",
    "TRANSLATOR_": "translators", "PANEL_": "panels",
    "OXYGEN_": "oxygen_shakes", "SNACKPACK_": "snackpacks",
}


def cat_of(symbol: str) -> str:
    for prefix, c in CATEGORIES.items():
        if symbol.startswith(prefix):
            return c
    raise ValueError(symbol)


def load_mid_per_day():
    """Returns a dict {day: pd.DataFrame (10K x 50)}."""
    out = {}
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        out[d] = f.pivot(index="timestamp", columns="product", values="mid_price").sort_index()
    return out


def fit_per_asset(mid_per_day: Dict[int, pd.DataFrame]):
    """Per-asset FV process diagnostics, day-by-day."""
    rows = []
    products = list(mid_per_day[2].columns)
    for sym in products:
        for d, mid in mid_per_day.items():
            v = mid[sym].values
            t = np.arange(len(v))
            slope, intercept = np.polyfit(t, v, 1)
            detrended = v - (intercept + slope * t)
            rets = np.diff(v)
            sigma_ret = float(rets.std())

            # AR(1) on detrended
            if detrended.std() > 0:
                phi = np.corrcoef(detrended[:-1], detrended[1:])[0, 1]
                hl = float(np.log(0.5) / np.log(phi)) if 0 < phi < 1 else float("inf")
            else:
                phi, hl = float("nan"), float("inf")

            # ADF-style: ratio of detrended std to RW expected std
            rw_expected = sigma_ret * np.sqrt(len(v))
            obs_std = detrended.std()
            ratio = obs_std / rw_expected if rw_expected > 0 else float("nan")

            rows.append({
                "product": sym,
                "category": cat_of(sym),
                "day": d,
                "n": len(v),
                "mean": float(v.mean()),
                "std": float(v.std()),
                "min": float(v.min()),
                "max": float(v.max()),
                "drift_per_tick": float(slope),
                "drift_per_day": float(slope * len(v)),
                "sigma_ret_per_tick": sigma_ret,
                "phi_detrended": float(phi),
                "half_life_ticks": hl,
                "obs_std_over_RW": float(ratio),
            })
    return pd.DataFrame(rows)


def constraint_dynamics(mid_per_day: Dict[int, pd.DataFrame]):
    """Characterize Pebbles + Snackpack constraint dynamics across days."""
    out = {}
    PEBBLES = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"]
    SNACKPACKS = ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                  "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]

    print("\n=== Pebbles total sum per day ===")
    for d, mid in mid_per_day.items():
        s = mid[PEBBLES].sum(axis=1)
        # also test: deviation distribution
        dev = (s - 50_000).round(1)
        print(f"  day {d}: mean={s.mean():.4f}  std={s.std():.4f}  "
              f"min={s.min():.1f}  max={s.max():.1f}")
        print(f"    deviation distribution: "
              + " ".join(f"{v:+.1f}={dev.value_counts().get(v, 0)}" for v in [-1.0, -0.5, 0.0, 0.5, 1.0]))
    out["pebbles_constraint"] = {
        "constant": 50_000.0,
        "per_day_summary": {
            d: {
                "mean": float(mid[PEBBLES].sum(axis=1).mean()),
                "std": float(mid[PEBBLES].sum(axis=1).std()),
                "core_band_pct": float(((mid[PEBBLES].sum(axis=1) - 50_000).abs() <= 1).mean() * 100),
            } for d, mid in mid_per_day.items()
        }
    }

    print("\n=== Snackpack pair: CHOC + VANILLA per day ===")
    for d, mid in mid_per_day.items():
        s = mid["SNACKPACK_CHOCOLATE"] + mid["SNACKPACK_VANILLA"]
        print(f"  day {d}: mean={s.mean():.2f}  std={s.std():.3f}  "
              f"first_100_mean={s.iloc[:100].mean():.2f}  last_100_mean={s.iloc[-100:].mean():.2f}")

    print("\n=== Snackpack triplet: PCA per day ===")
    triplet = ["SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
    for d, mid in mid_per_day.items():
        sub = mid[triplet]
        cov = sub.cov().values
        eig, vec = np.linalg.eigh(cov)
        # smallest direction
        smallest = vec[:, 0]
        proj = sub.values @ smallest
        print(f"  day {d}: smallest_eigval={eig[0]:.2f}  combo_dir={smallest}  "
              f"combo_mean={proj.mean():.2f}  combo_std={proj.std():.3f}")

    # Cross-day: how does the constraint constant evolve?
    print("\n=== Constraint constant day-to-day evolution ===")
    pebble_means = {d: mid_per_day[d][PEBBLES].sum(axis=1).mean() for d in mid_per_day}
    cv_means = {d: (mid_per_day[d]["SNACKPACK_CHOCOLATE"] + mid_per_day[d]["SNACKPACK_VANILLA"]).mean()
                for d in mid_per_day}
    print(f"  pebble sum (constant): {pebble_means}  -- delta day-over-day: "
          f"d3-d2={pebble_means[3] - pebble_means[2]:+.4f}, d4-d3={pebble_means[4] - pebble_means[3]:+.4f}")
    print(f"  CHOC+VAN K_day:        {cv_means}  -- delta: "
          f"d3-d2={cv_means[3] - cv_means[2]:+.4f}, d4-d3={cv_means[4] - cv_means[3]:+.4f}")

    # Innovations of the free DoF (4 free pebbles)
    print("\n=== Pebbles 4-DoF innovation correlations (within day) ===")
    free_4 = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L"]  # XL = 50K - sum
    for d, mid in mid_per_day.items():
        sub = mid[free_4]
        rets = sub.diff().dropna()
        corr = rets.corr().round(3)
        print(f"  day {d} (4 free pebbles, return correlations):")
        print(corr.to_string())

    return out


def main():
    mid_per_day = load_mid_per_day()
    print(f"loaded 3 days of mid prices, each shape {mid_per_day[2].shape}")

    # Per-asset stats per day
    df = fit_per_asset(mid_per_day)
    df.to_csv(OUT_DIR / "fv_per_asset_per_day.csv", index=False)

    # Per-asset summary across days
    print("\n=== Per-asset FV process summary (across 3 days) ===")
    summary = df.groupby("product").agg({
        "category": "first",
        "drift_per_day": ["mean", "std"],
        "sigma_ret_per_tick": ["mean", "std"],
        "obs_std_over_RW": ["mean", "min", "max"],
    })
    summary.columns = ["_".join(c).strip("_") for c in summary.columns]
    print(summary.sort_values(["category_first", "drift_per_day_mean"]).to_string())

    # Identify drift products
    print("\n=== Drift products: |drift_per_day| > 100 (significant) ===")
    drifters = df.groupby("product").agg(
        drift_mean=("drift_per_day", "mean"),
        sigma_mean=("sigma_ret_per_tick", "mean"),
    )
    # drift t-stat: if drift over a day is > sigma * sqrt(N) then significant
    drifters["drift_zscore"] = drifters["drift_mean"] / (drifters["sigma_mean"] * np.sqrt(10000))
    drifters = drifters.sort_values("drift_zscore", key=lambda s: s.abs(), ascending=False)
    print(drifters.head(15).to_string())

    # Constraint dynamics
    constraint_dynamics(mid_per_day)


if __name__ == "__main__":
    main()
