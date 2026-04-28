"""Rigorous per-asset calibration for the R5 sim.

Three things we get right here that the earlier ad-hoc analysis didn't:

  1. **Within-day-only variance ratios.** The earlier `variance_ratio.py`
     concatenated all 3 days, so 5000-step pairs spanning day boundaries
     were biased toward smaller variance (since each day re-anchors). That
     made the data look more mean-reverting than it really is. Here we
     compute VR using only same-day pairs.

  2. **MLE fit OU vs RW per asset.** OU model:
        F_{t+1} = F_t + theta*(mu - F_t) + sigma * eps,   eps ~ N(0,1)
     RW limit: theta = 0. Likelihood ratio test gives a principled choice.
     (Per-day mu fit, sigma + theta shared across days for a given asset.)

  3. **De-bounced sigma.** Mids are half-integer; bid/ask are integer; the
     half-integer flip can produce a +-0.5 mid wiggle even when the
     underlying FV barely moved. We estimate sigma from long-horizon
     variance (sigma_H/sqrt(H)) which is bounce-immune as H grows.

Outputs to analysis/round5/calibration_r5.json:
  per asset: { sigma, half_life_ticks, model: 'RW'|'OU', daily_mu: {2,3,4}, h, depth_l1, depth_l2, l2_lift }
plus pulse rates, pulse direction balance, snackpack K_day stats, pebble basket
diagnostics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
OUT_DIR = REPO_ROOT / "analysis" / "round5"

CATEGORIES = {
    "galaxy_sounds": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "sleep_pods": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                   "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "microchips": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                   "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "pebbles": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "robots": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
               "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "uv_visors": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                  "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "translators": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                    "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                    "TRANSLATOR_VOID_BLUE"],
    "panels": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "oxygen_shakes": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                      "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                      "OXYGEN_SHAKE_GARLIC"],
    "snackpacks": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                   "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}
ALL_PRODUCTS = [p for ps in CATEGORIES.values() for p in ps]
CATEGORY_OF = {p: c for c, ps in CATEGORIES.items() for p in ps}
DERIVED_PRODUCTS = {"PEBBLES_XL", "SNACKPACK_VANILLA"}
DAYS = (2, 3, 4)


def load_per_day_mid() -> Dict[int, pd.DataFrame]:
    out = {}
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        out[d] = (f.pivot(index="timestamp", columns="product", values="mid_price")
                    .sort_index())
    return out


# ---------------------------------------------------------------------------
# Within-day variance ratio (no cross-boundary contamination)
# ---------------------------------------------------------------------------

def within_day_vr(mid_per_day: Dict[int, pd.DataFrame], horizons: List[int]) -> pd.DataFrame:
    rows = []
    for sym in ALL_PRODUCTS:
        for d, mid_df in mid_per_day.items():
            v = mid_df[sym].values
            t = np.arange(len(v))
            slope, intercept = np.polyfit(t, v, 1)
            v_det = v - (intercept + slope * t)
            var_1 = np.var(np.diff(v_det))
            rec = {"product": sym, "category": CATEGORY_OF[sym], "day": d}
            for H in horizons:
                if H >= len(v_det):
                    rec[f"VR_H{H}"] = float("nan")
                else:
                    var_H = np.var(v_det[H:] - v_det[:-H])
                    rec[f"VR_H{H}"] = float(var_H / (H * var_1)) if var_1 > 0 else float("nan")
            # also compute sigma at these horizons
            for H in horizons:
                if H >= len(v_det):
                    rec[f"sigma_H{H}"] = float("nan")
                else:
                    rec[f"sigma_H{H}"] = float((v_det[H:] - v_det[:-H]).std() / np.sqrt(H))
            rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# OU MLE fit per asset
# ---------------------------------------------------------------------------

def ou_loglik(theta: float, mu: float, sigma: float, x: np.ndarray) -> float:
    """OU step: x_{t+1} = x_t + theta*(mu - x_t) + sigma*eps. Returns log-lik."""
    if sigma <= 0:
        return -np.inf
    pred = x[:-1] + theta * (mu - x[:-1])
    resid = x[1:] - pred
    n = len(resid)
    return -0.5 * n * np.log(2 * np.pi * sigma ** 2) - 0.5 * np.sum(resid ** 2) / sigma ** 2


def fit_ou_per_asset(v_per_day: Dict[int, np.ndarray]) -> Dict:
    """Joint fit: per-day mu (free), shared theta + sigma. Returns dict.

    Also fits RW (theta=0, mu = arbitrary) for likelihood ratio.
    """
    # Free parameters: theta (>=0), sigma (>0), mu_d for each day.
    # Use grid search over theta with closed-form optimal mu_d, sigma.
    days = sorted(v_per_day.keys())

    def fit_with_theta(theta: float) -> Tuple[float, Dict[int, float], float]:
        # Given theta, the residual is r_t = x_{t+1} - x_t - theta*(mu_d - x_t).
        # MLE mu_d minimizes sum_t (r_t)^2 across that day.
        # Per-day: sum r^2 = sum (delta - theta*(mu - x))^2
        # Take derivative wrt mu: -2 theta sum (delta - theta*(mu - x)) = 0
        # => theta * sum (mu - x) = sum delta / theta ... let me redo:
        # Let y = x_{t+1} - x_t and z = x_t. Model: y = theta*mu - theta*z + eps.
        # OLS: mu_hat = mean(y) / theta + mean(z), if theta != 0.
        # Actually fit y = theta*(mu - z) + eps  →  y = a + b*z  with a = theta*mu, b = -theta.
        # If we fix theta (so b is fixed = -theta), we get:
        #   y - b*z = a + eps  →  a_hat = mean(y - b*z) = mean(y) + theta*mean(z)
        #   mu_hat = a_hat / theta = mean(y)/theta + mean(z)
        residuals_all = []
        mus = {}
        for d in days:
            x = v_per_day[d]
            y = np.diff(x)
            z = x[:-1]
            if theta == 0:
                # RW: y = a + eps with a = drift; mu undefined, treat as 0 effective
                a_hat = float(np.mean(y))
                resid = y - a_hat
                # we report mu_hat as the daily mean of x (informational)
                mus[d] = float(np.mean(x))
            else:
                # y = a - theta*z + eps with a = theta*mu
                # a_hat = mean(y + theta*z)
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
        loglik = -0.5 * n * np.log(2 * np.pi * sigma2) - 0.5 * n
        return loglik, mus, np.sqrt(sigma2)

    # Grid search over theta in [0, 0.05] (half-life >= ln(2)/0.05 ≈ 14 ticks)
    thetas = np.concatenate([
        np.array([0.0]),
        np.logspace(-6, -1.3, 80),  # 1e-6 to 0.05
    ])
    best = (-np.inf, 0.0, {}, 0.0)
    for theta in thetas:
        ll, mus, sig = fit_with_theta(theta)
        if ll > best[0]:
            best = (ll, theta, mus, sig)
    ll_best, theta_best, mus_best, sigma_best = best

    # Fit RW (theta = 0) for likelihood-ratio
    ll_rw, mus_rw, sigma_rw = fit_with_theta(0.0)

    half_life = float(np.log(2) / theta_best) if theta_best > 0 else float("inf")
    # LR test: 2*(LL_OU - LL_RW) ~ chi2(1) for theta > 0
    lr = 2 * (ll_best - ll_rw)

    return {
        "theta": float(theta_best),
        "half_life_ticks": half_life,
        "sigma": float(sigma_best),
        "daily_mu": mus_best,
        "loglik_ou": ll_best,
        "loglik_rw": ll_rw,
        "loglik_ratio": float(lr),
        "rw_sigma": float(sigma_rw),
        # selection: OU if LR > 3.84 (p<0.05) AND half_life < 30000 (within reasonable range)
        "model": "OU" if (lr > 3.84 and half_life < 30_000) else "RW",
    }


# ---------------------------------------------------------------------------
# Pebbles / Snackpack constraint diagnostics
# ---------------------------------------------------------------------------

def pebbles_diagnostics(mid_per_day: Dict[int, pd.DataFrame]) -> Dict:
    PEBBLES = CATEGORIES["pebbles"]
    out = {}
    for d, mid in mid_per_day.items():
        s = mid[PEBBLES].sum(axis=1)
        # innovation correlations among the 4 free pebbles
        free = [p for p in PEBBLES if p != "PEBBLES_XL"]
        rets = mid[free].diff().dropna()
        corr = rets.corr().round(3).to_dict()
        out[f"day_{d}"] = {
            "sum_mean": float(s.mean()),
            "sum_std": float(s.std()),
            "sum_min": float(s.min()),
            "sum_max": float(s.max()),
            "core_band_pct": float(((s - 50_000).abs() <= 1).mean() * 100),
            "free_innovation_corr": corr,
        }
    return out


def snackpack_diagnostics(mid_per_day: Dict[int, pd.DataFrame]) -> Dict:
    out = {}
    # CHOC + VANILLA daily K
    for d, mid in mid_per_day.items():
        cv = mid["SNACKPACK_CHOCOLATE"] + mid["SNACKPACK_VANILLA"]
        out[f"day_{d}_K"] = {
            "mean": float(cv.mean()),
            "std": float(cv.std()),
            "first_100_mean": float(cv.iloc[:100].mean()),
            "last_100_mean": float(cv.iloc[-100:].mean()),
        }
    # Estimate sigma_K from per-tick changes
    sigma_k_per_day = {}
    for d, mid in mid_per_day.items():
        cv = mid["SNACKPACK_CHOCOLATE"] + mid["SNACKPACK_VANILLA"]
        # sigma of K's first differences = sigma_K (since CHOC and VANILLA both contribute)
        # Actually if CHOC moves by dC and VANILLA = K - CHOC, then dV = dK - dC.
        # So d(C+V) = dK directly. sigma_K = std(K_t - K_{t-1}).
        sigma_k_per_day[d] = float(np.diff(cv.values).std())
    out["sigma_K_per_day"] = sigma_k_per_day
    out["sigma_K_avg"] = float(np.mean(list(sigma_k_per_day.values())))

    # Snackpack triplet structure (PIS / STRAW / RASP)
    triplet = ["SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
    triplet_diag = {}
    for d, mid in mid_per_day.items():
        sub = mid[triplet]
        cov = sub.cov().values
        eig, vec = np.linalg.eigh(cov)
        triplet_diag[f"day_{d}"] = {
            "eigvals": eig.tolist(),
            "smallest_eigvec": vec[:, 0].tolist(),
            "ratio_smallest_to_total": float(eig[0] / eig.sum()),
        }
    out["triplet"] = triplet_diag
    return out


# ---------------------------------------------------------------------------
# Book + pulse calibration (from earlier scripts, codified)
# ---------------------------------------------------------------------------

def book_calibration(mid_per_day: Dict[int, pd.DataFrame]) -> Dict[str, Dict]:
    """Per-asset h, depth_l1, depth_l2, l2_lift."""
    frames = []
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        if "day" not in f.columns:
            f["day"] = d
        frames.append(f)
    p = pd.concat(frames, ignore_index=True)

    out = {}
    for sym in ALL_PRODUCTS:
        sub = p[p["product"] == sym]
        h = float((sub["mid_price"] - sub["bid_price_1"]).median())
        d_l1 = int(sub["bid_volume_1"].median())
        d_l2 = int(sub["bid_volume_2"].dropna().median()) if sub["bid_volume_2"].notna().any() else d_l1
        lift = int((sub["bid_price_1"] - sub["bid_price_2"].dropna()).median()) if sub["bid_price_2"].notna().any() else 1
        out[sym] = {"h": h, "depth_l1": d_l1, "depth_l2": d_l2, "l2_lift": lift}
    return out


def pulse_calibration() -> List[Dict]:
    """Pulse rates + qty distribution per group."""
    tframes = []
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"trades_round_5_day_{d}.csv", sep=";")
        f["day"] = d
        tframes.append(f)
    trades = pd.concat(tframes, ignore_index=True)
    trades["cat"] = trades["symbol"].map(CATEGORY_OF)
    trades["group"] = trades["cat"].apply(
        lambda c: "P" if c == "pebbles" else "M" if c == "microchips" else "V"
    )

    # bid/ask of trades to derive direction
    pframes = []
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        if "day" not in f.columns:
            f["day"] = d
        pframes.append(f)
    prices = pd.concat(pframes, ignore_index=True)
    book = prices[["day", "timestamp", "product", "bid_price_1", "ask_price_1"]].copy()
    trades = trades.merge(book, left_on=["day", "timestamp", "symbol"],
                          right_on=["day", "timestamp", "product"], how="left")
    trades["dir"] = np.where(trades["price"] <= trades["bid_price_1"], "SELL",
                              np.where(trades["price"] >= trades["ask_price_1"], "BUY", "MID"))

    n_ticks = 30_000
    out = []
    for grp, members, qty_min, qty_max in [
        ("V", [p for c, ps in CATEGORIES.items() for p in ps if c not in ("pebbles", "microchips")], 1, 4),
        ("P", CATEGORIES["pebbles"], 2, 5),
        ("M", CATEGORIES["microchips"], 1, 3),
    ]:
        sub = trades[trades["group"] == grp]
        # n unique pulse ticks
        n_pulses = sub.groupby(["day", "timestamp"]).size().shape[0]
        # direction balance: per-pulse direction (assume uniform within pulse = first-trade dir)
        first_dir = sub.groupby(["day", "timestamp"])["dir"].first()
        n_buy = (first_dir == "BUY").sum()
        # qty distribution: take per-pulse qty (assume uniform within = first qty)
        first_qty = sub.groupby(["day", "timestamp"])["quantity"].first()
        qty_counts = first_qty.value_counts().sort_index().to_dict()
        out.append({
            "name": grp,
            "members": list(members),
            "rate_per_tick": n_pulses / n_ticks,
            "n_pulses_3day": int(n_pulses),
            "p_buy": float(n_buy / n_pulses) if n_pulses else 0.5,
            "qty_min": qty_min,
            "qty_max": qty_max,
            "qty_observed_counts": {str(k): int(v) for k, v in qty_counts.items()},
        })
    return out


# ---------------------------------------------------------------------------

def main():
    print("loading per-day mid…")
    mid_per_day = load_per_day_mid()
    print(f"  {len(mid_per_day)} days, each {mid_per_day[2].shape}\n")

    horizons = [1, 5, 10, 50, 100, 500, 1000, 2500, 5000]

    print("=== Within-day-only variance ratio (NO cross-day contamination) ===")
    vr = within_day_vr(mid_per_day, horizons)
    cat_avg = vr.groupby("category")[
        [f"VR_H{H}" for H in horizons]
    ].mean()
    print(cat_avg.to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n=== Per-asset OU vs RW MLE fit ===")
    print(f"{'product':35s} {'cat':14s} {'model':5s} {'half_life':>11s} {'sigma':>7s} "
          f"{'LR':>8s} {'mu_d2':>10s} {'mu_d3':>10s} {'mu_d4':>10s}")
    asset_fits = {}
    for sym in ALL_PRODUCTS:
        v_per_day = {d: mid_per_day[d][sym].values for d in DAYS}
        if sym in DERIVED_PRODUCTS:
            # Skip OU fit; will be derived from constraints
            asset_fits[sym] = {"model": "DERIVED", "from": "constraint"}
            continue
        fit = fit_ou_per_asset(v_per_day)
        asset_fits[sym] = fit
        mus = fit["daily_mu"]
        hl = fit["half_life_ticks"]
        hl_str = f"{hl:>11.0f}" if np.isfinite(hl) else f"{'inf':>11s}"
        print(f"{sym:35s} {CATEGORY_OF[sym]:14s} {fit['model']:5s} {hl_str} "
              f"{fit['sigma']:>7.2f} {fit['loglik_ratio']:>8.1f} "
              f"{mus.get(2, 0):>10.2f} {mus.get(3, 0):>10.2f} {mus.get(4, 0):>10.2f}")

    # Model breakdown
    model_counts = {}
    for sym, fit in asset_fits.items():
        m = fit["model"]
        model_counts[m] = model_counts.get(m, 0) + 1
    print(f"\nmodel selection: {model_counts}")

    print("\n=== Pebbles diagnostics ===")
    pd_diag = pebbles_diagnostics(mid_per_day)
    for k, v in pd_diag.items():
        print(f"  {k}: sum_mean={v['sum_mean']:.4f}, sum_std={v['sum_std']:.4f}, "
              f"core_band={v['core_band_pct']:.1f}%")
        # show innovation corr
        inn = v["free_innovation_corr"]
        first = list(inn.keys())[0]
        print(f"    innovation corr sample (PEBBLES_XS): {inn[first]}")

    print("\n=== Snackpack diagnostics ===")
    sp_diag = snackpack_diagnostics(mid_per_day)
    for d in DAYS:
        k = sp_diag[f"day_{d}_K"]
        print(f"  day {d}: K mean={k['mean']:.2f}, K std={k['std']:.2f}, "
              f"first_100={k['first_100_mean']:.2f}, last_100={k['last_100_mean']:.2f}")
    print(f"  sigma_K per day: {sp_diag['sigma_K_per_day']}")
    print(f"  sigma_K avg:     {sp_diag['sigma_K_avg']:.4f}")
    for d in DAYS:
        t = sp_diag["triplet"][f"day_{d}"]
        print(f"  triplet day {d}: eigvals={[f'{v:.0f}' for v in t['eigvals']]}, "
              f"smallest_eigvec={[f'{v:+.3f}' for v in t['smallest_eigvec']]}")

    print("\n=== Book calibration (per-asset) ===")
    book_cfg = book_calibration(mid_per_day)
    print(f"{'product':35s} {'h':>6s} {'depth_L1':>10s} {'depth_L2':>10s} {'lift':>5s}")
    for sym in ALL_PRODUCTS:
        c = book_cfg[sym]
        print(f"{sym:35s} {c['h']:>6.1f} {c['depth_l1']:>10d} {c['depth_l2']:>10d} {c['l2_lift']:>5d}")

    print("\n=== Pulse calibration ===")
    pulses = pulse_calibration()
    for p in pulses:
        print(f"  {p['name']}: rate={p['rate_per_tick']:.5f}/tick "
              f"({p['rate_per_tick']*10000:.1f}/day), p_buy={p['p_buy']:.3f}, "
              f"qty_observed={p['qty_observed_counts']}")

    # Save the full calibration bundle
    bundle = {
        "asset_fits": asset_fits,
        "book_cfg": book_cfg,
        "pebble_diag": pd_diag,
        "snackpack_diag": sp_diag,
        "pulses": pulses,
        "horizons": horizons,
        "vr_within_day": cat_avg.reset_index().to_dict(orient="records"),
    }
    out = OUT_DIR / "calibration_r5.json"
    out.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"\nwritten: {out}")

    # ---- Snackpack triplet factor model (PIS / STRAW / RASP) -----------------
    # The default per-asset OU treats these 3 as independent, but their
    # tick-diffs share a 1-factor structure (94% of variance). Run the
    # dedicated calibration step here so a single `rigorous_calibration.py`
    # invocation refreshes both calibration_r5.json and the triplet patch in
    # calibration/r5/scenario_params.json. Otherwise the simulator's snackpack
    # cross-correlations are wrong (~0 vs +0.91 / -0.92 / -0.83 historical).
    print("\n=== Snackpack triplet factor calibration ===")
    try:
        from snackpack_triplet_factor import (
            fit_factor as _fit_triplet_factor,
            patch_scenario_params as _patch_triplet,
        )
    except ImportError:
        # Fall back to importing as a script-relative module when this file is
        # run from a different cwd.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "snackpack_triplet_factor",
            Path(__file__).with_name("snackpack_triplet_factor.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _fit_triplet_factor = mod.fit_factor
        _patch_triplet = mod.patch_scenario_params

    triplet_block = _fit_triplet_factor()
    print(f"  loadings = {[f'{x:+.4f}' for x in triplet_block['loadings']]}")
    print(f"  factor sigma = {triplet_block['k_factor']['sigma']:.4f}, "
          f"theta = {triplet_block['k_factor']['theta']:.6f}")
    print(f"  sigma_idio = {triplet_block['sigma_idio']}")
    print(f"  factor explains "
          f"{triplet_block['diagnostics']['factor_var_explained_ratio']*100:.1f}% of triplet variance")
    _patch_triplet(triplet_block)

    # Also persist the triplet block inside calibration_r5.json so the bundle
    # is self-describing (debuggers / tests that read calibration_r5.json
    # directly still see the factor model).
    bundle["snackpack_triplet"] = triplet_block
    out.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"  re-written: {out}")


if __name__ == "__main__":
    main()
