"""Calibrate a 1-factor model for the snackpack triplet (PIS / STRAW / RASP)
and patch it into calibration/r5/scenario_params.json.

Why: the existing scenario treats PIS, STRAW, RASP as 3 independent OUs, but
historical pairwise correlations of mid-tick diffs are huge:
    PIS-STRAW   +0.913
    STRAW-RASP  -0.923
    PIS-RASP    -0.831
PCA on the diff covariance shows the top eigenvector explains ~94% of variance
with stable loadings across days (~[-0.395, -0.657, +0.643] in unit norm).

Model: each triplet asset = (independent OU with reduced sigma_idio) + ℓ_i * K_triplet(t)
       K_triplet(t): zero-mean OU process, shared across the 3 assets.
       sigma_idio_i^2 = sigma_total_i^2 - ℓ_i^2 * sigma_K^2
       (so total per-asset variance is preserved, but cov(ΔF_i, ΔF_j) = ℓ_i ℓ_j σ_K^2)

Output:
  - Patches `calibration/r5/scenario_params.json` IN PLACE:
      * adds top-level `snackpack_triplet` block: { members, loadings, sigma_K, theta_K, daily_mu_K }
      * replaces `sigma` field for PIS, STRAW, RASP with their reduced sigma_idio
      * keeps everything else unchanged (theta, daily_mu, h, depth_*, etc. — those still apply)
  - Backs up the original to `scenario_params.json.bak` if it doesn't already exist.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
PARAMS_PATH = REPO_ROOT / "calibration" / "r5" / "scenario_params.json"
DAYS = (2, 3, 4)
TRIPLET = ["SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]


def load_triplet_diffs() -> np.ndarray:
    """Stack tick-tick mid diffs for the 3 triplet assets, within-day only."""
    diffs = []
    for d in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        piv = (df.pivot(index="timestamp", columns="product", values="mid_price")
                 .sort_index())[TRIPLET]
        diffs.append(piv.diff().dropna().values)
    return np.concatenate(diffs, axis=0)  # (~30k, 3)


def load_triplet_levels_per_day() -> dict[int, np.ndarray]:
    """Per-day (n_ticks, 3) level matrix for triplet assets, in TRIPLET order."""
    out = {}
    for d in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        piv = (df.pivot(index="timestamp", columns="product", values="mid_price")
                 .sort_index())[TRIPLET]
        out[d] = piv.values
    return out


def fit_factor() -> dict:
    """Run PCA → loadings + factor diff variance. Then fit OU to factor projection."""
    D = load_triplet_diffs()
    cov = np.cov(D, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending
    loadings = eigvecs[:, -1]  # top eigenvector, unit norm
    # Sign convention: positive RASP loading (matches eyeballed +0.643).
    if loadings[2] < 0:
        loadings = -loadings
    sigma_K2 = float(eigvals[-1])  # variance of factor diffs
    sigma_K = float(np.sqrt(sigma_K2))

    # Per-asset diff variance (matches sigma^2 in the existing OU calibration to
    # within tick-rounding ~0.01).
    sigma_total2 = np.diag(cov)
    sigma_idio2 = sigma_total2 - (loadings ** 2) * sigma_K2
    # Floor at small positive — if PCA over-explains an asset (shouldn't, but guard):
    sigma_idio2 = np.maximum(sigma_idio2, 1e-6)
    sigma_idio = np.sqrt(sigma_idio2)

    # Compute realized factor PATH per day, then DEMEAN per day so the factor
    # is zero-mean by construction. This is critical: the existing per-asset
    # OU calibrations (sigma, theta, daily_mu_i) were fit on the FULL F_i path
    # which already includes the factor contribution at the level. If we now
    # add ℓ_i * K(t) on top of independent OUs around μ_i(d), the mean would
    # double-count by ℓ_i * mean(K). Forcing K to be zero-mean keeps the
    # existing per-asset means correct: E[F_i] = μ_i(d) + ℓ_i * 0 = μ_i(d).
    levels = load_triplet_levels_per_day()
    k_paths = {}
    for d in DAYS:
        raw = levels[d] @ loadings
        k_paths[d] = raw - raw.mean()

    # Fit OU around 0 to the demeaned per-day paths. Per-day mu should fit ~0
    # (we still fit it to be safe and detect issues). Shared theta + sigma.
    days = sorted(k_paths.keys())

    def fit_with_theta(theta: float):
        residuals_all = []
        mus = {}
        for d in days:
            x = k_paths[d]
            y = np.diff(x)
            z = x[:-1]
            if theta == 0:
                a_hat = float(np.mean(y))
                resid = y - a_hat
                mus[d] = float(np.mean(x))
            else:
                a_hat = float(np.mean(y + theta * z))
                mu_hat = a_hat / theta
                pred = a_hat - theta * z
                resid = y - pred
                mus[d] = float(mu_hat)
            residuals_all.extend(resid.tolist())
        residuals_all = np.array(residuals_all)
        sigma2 = float(np.var(residuals_all))
        if sigma2 <= 0:
            return -np.inf, mus, 0.0
        n = len(residuals_all)
        ll = -0.5 * n * np.log(2 * np.pi * sigma2) - 0.5 * n
        return ll, mus, float(np.sqrt(sigma2))

    thetas = np.concatenate([[0.0], np.logspace(-6, -1.3, 80)])
    best = (-np.inf, 0.0, {}, 0.0)
    for theta in thetas:
        ll, mus, sig = fit_with_theta(theta)
        if ll > best[0]:
            best = (ll, theta, mus, sig)
    ll_best, theta_best, mus_best, sigma_best_factor = best

    # Cross-validation: how much variance does the factor explain
    var_total = float(np.diag(cov).sum())
    var_factor = float(eigvals[-1])
    explained = var_factor / var_total

    return {
        "members": list(TRIPLET),
        "loadings": loadings.tolist(),
        "k_factor": {
            "theta": float(theta_best),
            # IMPORTANT: simulator uses sigma of the OU innovations (residual std).
            # We use the OU-fitted residual sigma rather than raw diff std so that
            # the simulator's OU innovation variance matches what theta+mu remove.
            "sigma": float(sigma_best_factor),
            # Also store the raw diff std for reference / debugging.
            "sigma_raw_diffs": sigma_K,
            "daily_mu": {str(d): float(m) for d, m in mus_best.items()},
        },
        "sigma_idio": {
            sym: float(s) for sym, s in zip(TRIPLET, sigma_idio)
        },
        "sigma_total_observed": {
            sym: float(np.sqrt(s2)) for sym, s2 in zip(TRIPLET, sigma_total2)
        },
        "diagnostics": {
            "eigvals_ascending": [float(v) for v in eigvals],
            "factor_var_explained_ratio": explained,
            "pairwise_corr_observed": {
                "PIS_STRAW": float(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])),
                "STRAW_RASP": float(cov[1, 2] / np.sqrt(cov[1, 1] * cov[2, 2])),
                "PIS_RASP": float(cov[0, 2] / np.sqrt(cov[0, 0] * cov[2, 2])),
            },
        },
    }


def patch_scenario_params(triplet_block: dict) -> None:
    backup = PARAMS_PATH.with_suffix(".json.bak")
    if not backup.exists():
        shutil.copy2(PARAMS_PATH, backup)
        print(f"backup: {backup}")
    bundle = json.loads(PARAMS_PATH.read_text())

    bundle["snackpack_triplet"] = {
        "members": triplet_block["members"],
        "loadings": triplet_block["loadings"],
        "k_factor": triplet_block["k_factor"],
    }
    # Overwrite per-asset sigma in `assets` for the 3 triplet members with
    # sigma_idio (the pre-factor noise std).  Theta + daily_mu unchanged: they
    # already capture each asset's own mean reversion of the *level*.
    for sym, s_idio in triplet_block["sigma_idio"].items():
        if sym in bundle["assets"]:
            asset = bundle["assets"][sym]
            asset.setdefault("sigma_total_pre_factor", asset.get("sigma"))
            asset["sigma"] = s_idio
            asset["kind"] = "triplet_factor"

    PARAMS_PATH.write_text(json.dumps(bundle, indent=2))
    print(f"patched: {PARAMS_PATH}")


def main():
    print("Fitting triplet factor model…")
    block = fit_factor()
    print(f"  loadings = {[f'{x:+.4f}' for x in block['loadings']]}")
    print(f"  factor sigma (OU residual) = {block['k_factor']['sigma']:.4f}")
    print(f"  factor sigma (raw diffs)   = {block['k_factor']['sigma_raw_diffs']:.4f}")
    print(f"  factor theta = {block['k_factor']['theta']:.6f}, "
          f"daily_mu = {block['k_factor']['daily_mu']}")
    print(f"  sigma_idio = {block['sigma_idio']}")
    print(f"  sigma_total_observed = {block['sigma_total_observed']}")
    print(f"  factor explains {block['diagnostics']['factor_var_explained_ratio']*100:.1f}% of total var")
    print(f"  observed pairwise corr: {block['diagnostics']['pairwise_corr_observed']}")
    patch_scenario_params(block)


if __name__ == "__main__":
    main()
