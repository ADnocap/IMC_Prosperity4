"""R5 50-asset PCA factor analysis.

Build a statistical-factor model from historical R5 mid-price tick-tick diffs.

Methodology
-----------
- Load mid prices, days 2/3/4, all 50 assets, on a common timestamp grid.
- Compute tick-tick mid diffs (within-day, drop tick 0).
- Two PCA flavours:
    * COV PCA: on raw diffs covariance (so variance is in price-tick units).
    * CORR PCA: on diffs after per-asset z-score (each asset = unit variance).
  CORR is the right choice when assets have very different vol scales (PEBBLES_XL
  has std ~939 while SNACKPACK_PISTACHIO ~112) and we don't want the loud assets
  to dominate the components mechanically. We report both for transparency.
- For each PCA: scree (eigenvalue / cumulative variance), loadings of PC1..PC10,
  per-day stability check (refit on each day, measure cosine sim to global PCA).
- Compare top-K loading patterns to category structure: for each component, compute
  category-weighted loading sum to see if it aligns with a single category.

Outputs
-------
- analysis/round5/factor_loadings.json — full factor model bundle
- prints scree, top loadings, category alignment
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"
OUT_JSON = Path(__file__).with_name("factor_loadings.json")
OUT_MD = Path(__file__).with_name("FACTOR_MODEL.md")
DAYS = (2, 3, 4)

# 10 categories x 5 products = 50 symbols. Source of truth: traders/round5/submission.py.
CATEGORIES: dict[str, list[str]] = {
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
ASSETS = [s for cat in CATEGORIES.values() for s in cat]
CATEGORY_OF = {s: c for c, syms in CATEGORIES.items() for s in syms}
assert len(ASSETS) == 50


def load_diffs(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_5_day_{day}.csv", sep=";")
    piv = df.pivot(index="timestamp", columns="product", values="mid_price").sort_index()
    piv = piv[ASSETS]  # enforce column order
    return piv.diff().dropna()


def standardize(x: np.ndarray) -> np.ndarray:
    """z-score per column, NaN-safe."""
    mu = np.nanmean(x, axis=0, keepdims=True)
    sd = np.nanstd(x, axis=0, ddof=1, keepdims=True)
    sd = np.where(sd == 0, 1.0, sd)
    return (x - mu) / sd


def pca(M: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric PCA: (n_obs, n_assets) → eigvals desc, eigvecs (n_assets, n_assets) cols."""
    cov = np.cov(M, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    return eigvals[order], eigvecs[:, order]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def per_day_stability(diffs_per_day: dict[int, pd.DataFrame], k: int, mode: str
                      ) -> dict[int, list[float]]:
    """For each day, refit PCA, compute |cos sim| of top-k eigvecs vs global ref."""
    full = pd.concat(diffs_per_day.values(), axis=0).values
    if mode == "corr":
        full = standardize(full)
    _, V_ref = pca(full)
    out = {}
    for d, df in diffs_per_day.items():
        X = df.values
        if mode == "corr":
            X = standardize(X)
        _, V_day = pca(X)
        out[d] = [cosine(V_ref[:, i], V_day[:, i]) for i in range(k)]
    return out


def category_alignment(loading: np.ndarray, assets: list[str]) -> dict[str, float]:
    """Sum of |loadings| in each category, normalized to total |loading|."""
    total = float(np.sum(np.abs(loading)))
    out = {}
    for cat, syms in CATEGORIES.items():
        idx = [assets.index(s) for s in syms]
        out[cat] = float(np.sum(np.abs(loading[idx])) / total) if total > 0 else 0.0
    return out


def category_signs(loading: np.ndarray, assets: list[str]) -> dict[str, str]:
    """For each category, return '+'/'-'/mixed depending on sign of loadings."""
    out = {}
    for cat, syms in CATEGORIES.items():
        signs = [np.sign(loading[assets.index(s)]) for s in syms]
        if all(s >= 0 for s in signs):
            out[cat] = "+"
        elif all(s <= 0 for s in signs):
            out[cat] = "-"
        else:
            n_pos = sum(1 for s in signs if s > 0)
            n_neg = sum(1 for s in signs if s < 0)
            out[cat] = f"mixed({n_pos}+/{n_neg}-)"
    return out


def main() -> None:
    diffs_per_day: dict[int, pd.DataFrame] = {d: load_diffs(d) for d in DAYS}
    full_df = pd.concat(diffs_per_day.values(), axis=0)
    print(f"Loaded {len(full_df)} ticks × {full_df.shape[1]} assets")

    M = full_df.values
    Mz = standardize(M)

    eigvals_cov, V_cov = pca(M)
    eigvals_corr, V_corr = pca(Mz)

    # Scree
    print("\n=== SCREE (corr-PCA, cumulative variance explained) ===")
    cum_corr = np.cumsum(eigvals_corr) / eigvals_corr.sum()
    for i in range(15):
        print(f"  PC{i+1:2d}: var = {eigvals_corr[i]:7.4f}  cum = {100*cum_corr[i]:5.1f}%")

    print("\n=== SCREE (cov-PCA) ===")
    cum_cov = np.cumsum(eigvals_cov) / eigvals_cov.sum()
    for i in range(15):
        print(f"  PC{i+1:2d}: var = {eigvals_cov[i]:11.2f}  cum = {100*cum_cov[i]:5.1f}%")

    # Per-day stability (top 10 components)
    K = 10
    print("\n=== Per-day stability (CORR-PCA, |cos sim| to all-3-day ref) ===")
    stab_corr = per_day_stability(diffs_per_day, K, "corr")
    print("  PC# | day2  day3  day4")
    for i in range(K):
        s = [stab_corr[d][i] for d in DAYS]
        flag = "OK" if min(s) > 0.85 else ("MEH" if min(s) > 0.6 else "UNSTABLE")
        print(f"  PC{i+1:2d} | {s[0]:.3f} {s[1]:.3f} {s[2]:.3f}   {flag}")

    # Category structure of top components
    print("\n=== Category alignment of top corr-PCs (|loading| share per category, top-3) ===")
    for i in range(min(K, V_corr.shape[1])):
        align = category_alignment(V_corr[:, i], ASSETS)
        signs = category_signs(V_corr[:, i], ASSETS)
        top3 = sorted(align.items(), key=lambda x: -x[1])[:3]
        cum_share = sum(v for _, v in top3)
        top3_str = ", ".join(f"{k}:{v*100:.0f}%[{signs[k]}]" for k, v in top3)
        print(f"  PC{i+1:2d}: cum_top3={cum_share*100:.0f}%  {top3_str}")

    # Idio variance per asset (residual after K factors)
    print("\n=== Per-asset idio variance under K=5 factor model (corr-PCA) ===")
    K_factors = 5
    L = V_corr[:, :K_factors] * np.sqrt(eigvals_corr[:K_factors])  # loading matrix in z-space
    explained_per_asset = (L ** 2).sum(axis=1)  # since assets are unit-var in z space
    idio_share = 1.0 - explained_per_asset
    print("  -- worst-fit (highest idio share) 8:")
    order = np.argsort(-idio_share)
    for i in order[:8]:
        print(f"    {ASSETS[i]:32s} idio_share = {idio_share[i]:.3f}")
    print("  -- best-fit (lowest idio share) 8:")
    for i in order[-8:][::-1]:
        print(f"    {ASSETS[i]:32s} idio_share = {idio_share[i]:.3f}")

    # Persist a usable factor model bundle
    bundle = {
        "_doc": (
            "R5 50-asset PCA factor model. Built from mid-tick diffs, days 2/3/4. "
            "CORR-PCA (per-asset z-score before PCA) is the primary model — used "
            "for the trader's factor-neutralization. COV-PCA stored for reference."
        ),
        "assets": ASSETS,
        "categories": CATEGORIES,
        "n_ticks": int(len(full_df)),
        "corr_pca": {
            "eigenvalues": eigvals_corr.tolist(),
            "cum_var": cum_corr.tolist(),
            "loadings_pc1_pc10": V_corr[:, :10].T.tolist(),  # shape (10, 50)
            "stability_top10": {str(d): stab_corr[d] for d in DAYS},
        },
        "cov_pca": {
            "eigenvalues": eigvals_cov.tolist(),
            "cum_var": cum_cov.tolist(),
            "loadings_pc1_pc10": V_cov[:, :10].T.tolist(),
        },
        "per_asset_std_diff": {
            ASSETS[i]: float(np.nanstd(M[:, i], ddof=1))
            for i in range(len(ASSETS))
        },
    }
    OUT_JSON.write_text(json.dumps(bundle, indent=2))
    print(f"\nWrote {OUT_JSON.relative_to(REPO)}")


if __name__ == "__main__":
    main()
