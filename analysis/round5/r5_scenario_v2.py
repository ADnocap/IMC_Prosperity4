"""R5Scenario v2 — calibrated from rigorous_calibration.py output.

Per-asset model:
  - 34 OU processes: dF = theta*(mu_day - F)*dt + sigma*dW (Euler in discrete ticks)
  - 14 RW processes: F_{t+1} = F_t + sigma*N(0,1), starting at observed day-start
  - 2 derived:
      PEBBLES_XL = 50_000 - sum(other 4 pebbles)
      SNACKPACK_VANILLA = K_day(t) - SNACKPACK_CHOCOLATE(t)
  - K_day itself is an OU process (calibrated separately) since pair-sum
    has within-day std bounded at ~40 (would be 270 under pure RW)

Validation:
  - Per-asset within-day std distribution (50 seeds vs historical 3 days)
  - Per-asset variance ratio at multiple horizons
  - Pebble basket sum constraint (should be 50,000 ± 0)
  - Snackpack pair K trajectory + within-day std
  - Pulse rates + direction balance + qty distribution
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
OUT_DIR = REPO_ROOT / "analysis" / "round5"
CAL_PATH = OUT_DIR / "calibration_r5.json"

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
DAYS = (2, 3, 4)
PEBBLE_FREE = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L"]
PEBBLE_DERIVED = "PEBBLES_XL"


# ---------------------------------------------------------------------------
# K_day (CHOC+VANILLA pair sum) calibration: fit OU to the pair-sum trajectory
# ---------------------------------------------------------------------------

def fit_k_day_ou(mid_per_day: Dict[int, pd.DataFrame]) -> Dict:
    """Fit OU to K_day = CHOC + VANILLA. Returns sigma, theta, half_life, daily_mu."""
    series_per_day = {}
    for d, mid in mid_per_day.items():
        series_per_day[d] = (mid["SNACKPACK_CHOCOLATE"] + mid["SNACKPACK_VANILLA"]).values

    # MLE grid search (same approach as per-asset)
    def fit_with_theta(theta: float):
        residuals_all, mus = [], {}
        for d in DAYS:
            x = series_per_day[d]
            y = np.diff(x)
            z = x[:-1]
            if theta == 0:
                a_hat = float(np.mean(y))
                resid = y - a_hat
                mus[d] = float(np.mean(x))
            else:
                a_hat = float(np.mean(y + theta * z))
                mus[d] = a_hat / theta
                pred = a_hat - theta * z
                resid = y - pred
            residuals_all.extend(resid.tolist())
        residuals_all = np.array(residuals_all)
        sigma2 = float(np.var(residuals_all))
        if sigma2 <= 0:
            return -np.inf, mus, 0.0
        n = len(residuals_all)
        ll = -0.5 * n * np.log(2 * np.pi * sigma2) - 0.5 * n
        return ll, mus, np.sqrt(sigma2)

    thetas = np.concatenate([np.array([0.0]), np.logspace(-6, -1.3, 80)])
    best = (-np.inf, 0.0, {}, 0.0)
    for theta in thetas:
        ll, mus, sig = fit_with_theta(theta)
        if ll > best[0]:
            best = (ll, theta, mus, sig)
    ll, theta, mus, sig = best
    return {
        "theta": float(theta),
        "half_life_ticks": float(np.log(2) / theta) if theta > 0 else float("inf"),
        "sigma": float(sig),
        "daily_mu": mus,
    }


# ---------------------------------------------------------------------------
# Process generators
# ---------------------------------------------------------------------------

def simulate_ou(
    n: int, x0: float, mu: float, theta: float, sigma: float, rng: np.random.Generator
) -> np.ndarray:
    """Discrete-time OU: x_{t+1} = x_t + theta*(mu - x_t) + sigma*N(0,1).

    Returns array of length n with x[0] = x0.
    """
    if theta == 0:
        innov = rng.normal(0, sigma, size=n - 1)
        return np.concatenate([[x0], x0 + np.cumsum(innov)])
    x = np.empty(n)
    x[0] = x0
    eps = rng.normal(0, sigma, size=n - 1)
    for t in range(n - 1):
        x[t + 1] = x[t] + theta * (mu - x[t]) + eps[t]
    return x


def simulate_rw(
    n: int, x0: float, sigma: float, rng: np.random.Generator
) -> np.ndarray:
    innov = rng.normal(0, sigma, size=n - 1)
    return np.concatenate([[x0], x0 + np.cumsum(innov)])


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------

class R5Scenario:
    SCENARIO_PARAMS_PATH = REPO_ROOT / "calibration" / "r5" / "scenario_params.json"
    TRIPLET_MEMBERS = ("SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY")

    def __init__(self, calibration: Dict, k_day_cal: Dict,
                 pulse_qty_dist: Optional[Dict[str, np.ndarray]] = None,
                 triplet_block: Optional[Dict] = None):
        self.cal = calibration
        self.k_day_cal = k_day_cal
        # pulse_qty_dist: optional empirical qty histograms per group
        self.pulse_qty_dist = pulse_qty_dist or {}
        # snackpack_triplet factor model (loaded from scenario_params.json by default).
        # When None the triplet falls back to the legacy independent-OU behaviour
        # so older calibration bundles still work.
        if triplet_block is None and self.SCENARIO_PARAMS_PATH.is_file():
            try:
                triplet_block = json.loads(
                    self.SCENARIO_PARAMS_PATH.read_text()
                ).get("snackpack_triplet")
            except Exception:
                triplet_block = None
        self.triplet_block = triplet_block
        # Per-asset sigma_idio (after factor variance is pulled out). Only used
        # for the 3 triplet members; other assets use cal["asset_fits"][sym]["sigma"].
        if triplet_block is not None:
            members = triplet_block["members"]
            loadings = triplet_block["loadings"]
            sigma_K = float(triplet_block["k_factor"]["sigma"])
            sigma_total = {sym: float(self.cal["asset_fits"][sym]["sigma"])
                           for sym in members}
            self._triplet_sigma_idio: Dict[str, float] = {}
            for sym, ell in zip(members, loadings):
                idio2 = sigma_total[sym] ** 2 - (ell ** 2) * (sigma_K ** 2)
                self._triplet_sigma_idio[sym] = float(np.sqrt(max(idio2, 1e-6)))
        else:
            self._triplet_sigma_idio = {}

    def generate_day(self, day: int, n_ticks: int, rng: np.random.Generator) -> Dict:
        fvs: Dict[str, np.ndarray] = {}
        starts = self._daily_starts(day)
        triplet_set = set(self.TRIPLET_MEMBERS) if self.triplet_block else set()
        # Generate independent OU/RW for non-derived assets except SNACKPACK_VANILLA
        for sym in ALL_PRODUCTS:
            if sym == PEBBLE_DERIVED or sym == "SNACKPACK_VANILLA":
                continue
            fit = self.cal["asset_fits"][sym]
            x0 = starts[sym]
            # For triplet members the factor carries part of their variance, so
            # the independent OU step uses the reduced idiosyncratic sigma.
            sigma = self._triplet_sigma_idio.get(sym, fit["sigma"])
            if fit["model"] == "OU":
                theta = fit.get("theta", 0.0)
                mu = float(fit["daily_mu"].get(str(day), x0))
                v = simulate_ou(n_ticks, x0, mu, theta, sigma, rng)
            else:
                v = simulate_rw(n_ticks, x0, sigma, rng)
            # Defer half-integer snap until after the factor overlay (below) so
            # the loading * K addition isn't quantised away tick-by-tick.
            fvs[sym] = v

        # --- Snackpack triplet factor overlay ----------------------------------
        # K_triplet is a zero-mean OU process driven by the same shared shocks
        # for all 3 triplet assets. Adding loading_i * K_triplet(t) to each
        # asset's independent path produces the historical pairwise correlations
        # (PIS-STRAW +0.91, STRAW-RASP -0.92, PIS-RASP -0.83) without affecting
        # daily means (factor is centred).
        if self.triplet_block is not None:
            kf = self.triplet_block["k_factor"]
            mu_K = float(kf["daily_mu"].get(str(day), 0.0))  # ~0 by construction
            k_path = simulate_ou(n_ticks, mu_K, mu_K,
                                 float(kf["theta"]), float(kf["sigma"]), rng)
            # Center to zero mean for safety (calibration already enforces this).
            k_path = k_path - mu_K
            for sym, ell in zip(self.triplet_block["members"],
                                self.triplet_block["loadings"]):
                fvs[sym] = fvs[sym] + float(ell) * k_path

        # Snap all generated paths to half-integer now that overlays are applied.
        for sym in list(fvs.keys()):
            fvs[sym] = np.round(fvs[sym] * 2) / 2

        # Pebbles derived
        sum_free = sum(fvs[p] for p in PEBBLE_FREE)
        fvs[PEBBLE_DERIVED] = np.round((50_000 - sum_free) * 2) / 2

        # K_day OU process for snackpack pair
        kc = self.k_day_cal
        k_day_start = float(kc["daily_mu"].get(str(day), kc["daily_mu"][next(iter(kc["daily_mu"]))]))
        k_day = simulate_ou(
            n_ticks, k_day_start, k_day_start, kc["theta"], kc["sigma"], rng
        )
        fvs["SNACKPACK_VANILLA"] = np.round((k_day - fvs["SNACKPACK_CHOCOLATE"]) * 2) / 2

        pulses = self._generate_pulses(n_ticks, rng)
        return {"fv_paths": fvs, "pulses": pulses, "k_day": k_day}

    def _daily_starts(self, day: int) -> Dict[str, float]:
        # use observed day-start FVs from the calibration (loaded externally)
        return self.cal.get("day_starts", {}).get(str(day), {})

    def _generate_pulses(self, n_ticks: int, rng: np.random.Generator) -> List[Dict]:
        pulses = []
        for cfg in self.cal["pulses"]:
            n = rng.binomial(n_ticks, cfg["rate_per_tick"])
            ticks = sorted(rng.choice(n_ticks, size=n, replace=False).tolist())
            for tick in ticks:
                direction = "BUY" if rng.random() < cfg["p_buy"] else "SELL"
                # qty: sample from observed empirical distribution if available, else uniform
                qty_dist = self.pulse_qty_dist.get(cfg["name"])
                if qty_dist is not None:
                    qty = int(rng.choice(qty_dist))
                else:
                    qty = int(rng.integers(cfg["qty_min"], cfg["qty_max"] + 1))
                pulses.append({
                    "tick": int(tick),
                    "group": cfg["name"],
                    "members": cfg["members"],
                    "direction": direction,
                    "qty": qty,
                })
        pulses.sort(key=lambda p: p["tick"])
        return pulses


# ---------------------------------------------------------------------------
# Calibration loader: read calibration_r5.json + day-start FVs + qty histograms
# ---------------------------------------------------------------------------

def load_calibration_bundle() -> Tuple[Dict, Dict, Dict[str, np.ndarray]]:
    cal = json.loads(CAL_PATH.read_text())

    # Daily start FVs
    pframes = []
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        if "day" not in f.columns:
            f["day"] = d
        pframes.append(f)
    prices = pd.concat(pframes, ignore_index=True)
    day_starts = {}
    for d in DAYS:
        sub = prices[prices["day"] == d].sort_values("timestamp")
        starts = sub.groupby("product").first()["mid_price"].to_dict()
        day_starts[str(d)] = {k: float(v) for k, v in starts.items()}
    cal["day_starts"] = day_starts

    # K_day calibration
    mid_per_day = {d: prices[prices["day"] == d]
                       .pivot(index="timestamp", columns="product", values="mid_price")
                       .sort_index() for d in DAYS}
    k_cal = fit_k_day_ou(mid_per_day)
    k_cal["daily_mu"] = {str(d): v for d, v in k_cal["daily_mu"].items()}

    # Empirical pulse qty histograms (one array per group, sampled from observed counts)
    pulse_qty_dist = {}
    for cfg in cal["pulses"]:
        counts = cfg["qty_observed_counts"]  # {qty_str: count}
        arr = []
        for k, v in counts.items():
            arr.extend([int(k)] * int(v))
        pulse_qty_dist[cfg["name"]] = np.array(arr)

    return cal, k_cal, pulse_qty_dist


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def historical_per_day_stats() -> pd.DataFrame:
    rows = []
    for d in DAYS:
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        for sym in ALL_PRODUCTS:
            v = f[f["product"] == sym].sort_values("timestamp")["mid_price"].values
            rows.append({
                "product": sym, "day": d,
                "mean": float(v.mean()),
                "std": float(v.std()),
                "sigma_diff": float(np.diff(v).std()),
                "min": float(v.min()),
                "max": float(v.max()),
                "range": float(v.max() - v.min()),
            })
    return pd.DataFrame(rows)


def synthetic_per_day_stats(scenario: R5Scenario, n_seeds: int, n_ticks: int) -> pd.DataFrame:
    rows = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        for d in DAYS:
            synth = scenario.generate_day(d, n_ticks, rng)
            for sym in ALL_PRODUCTS:
                v = synth["fv_paths"][sym]
                rows.append({
                    "seed": seed, "product": sym, "day": d,
                    "mean": float(v.mean()),
                    "std": float(v.std()),
                    "sigma_diff": float(np.diff(v).std()),
                    "min": float(v.min()),
                    "max": float(v.max()),
                    "range": float(v.max() - v.min()),
                })
    return pd.DataFrame(rows)


def compare(syn: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    syn_agg = syn.groupby(["product", "day"]).agg(
        syn_std_mean=("std", "mean"),
        syn_std_p10=("std", lambda s: s.quantile(0.1)),
        syn_std_p90=("std", lambda s: s.quantile(0.9)),
        syn_sigma_diff_mean=("sigma_diff", "mean"),
        syn_range_mean=("range", "mean"),
    ).reset_index()
    merged = syn_agg.merge(hist, on=["product", "day"], suffixes=("_syn", "_hist"))
    merged["std_in_band"] = (
        (merged["std"] >= merged["syn_std_p10"]) &
        (merged["std"] <= merged["syn_std_p90"])
    )
    return merged


# ---------------------------------------------------------------------------

def main():
    print("Loading calibration bundle…")
    cal, k_cal, qty_dist = load_calibration_bundle()
    print(f"  asset fits: {len(cal['asset_fits'])}, pulses: {len(cal['pulses'])}")
    print(f"  K_day OU fit: theta={k_cal['theta']:.6f}, half_life={k_cal['half_life_ticks']:.0f}, "
          f"sigma={k_cal['sigma']:.3f}, daily_mu={k_cal['daily_mu']}")

    scenario = R5Scenario(cal, k_cal, qty_dist)

    print("\nGenerating 50 seeds × 3 days × 10K ticks…")
    syn = synthetic_per_day_stats(scenario, n_seeds=50, n_ticks=10_000)
    print(f"  {len(syn)} synthetic (seed, day, product) rows")

    print("Loading historical 3-day stats…")
    hist = historical_per_day_stats()

    cmp = compare(syn, hist)

    # Per-product summary: how often historical std falls within synthetic 10-90 percentile band?
    coverage = cmp.groupby("product")["std_in_band"].mean()
    print(f"\nHistorical-in-synthetic-band coverage: mean={coverage.mean():.2f}, "
          f"min={coverage.min():.2f}, products with coverage<0.5: "
          f"{(coverage < 0.5).sum()}/{len(coverage)}")

    # Print products where coverage is bad
    bad = coverage[coverage < 0.5].index.tolist()
    if bad:
        print(f"\nProducts with poor coverage:")
        for prod in bad:
            sub = cmp[cmp["product"] == prod]
            print(f"  {prod}: hist_std={sub['std'].tolist()}, "
                  f"syn_p10-p90={[(round(p10,1), round(p90,1)) for p10, p90 in zip(sub['syn_std_p10'], sub['syn_std_p90'])]}")

    # Pebble basket constraint
    print("\n=== Pebble basket validation (5 sample seeds) ===")
    for seed in range(5):
        rng = np.random.default_rng(seed)
        s = scenario.generate_day(2, 10_000, rng)
        peb_sum = sum(s["fv_paths"][p] for p in CATEGORIES["pebbles"])
        print(f"  seed={seed}: peb_sum mean={peb_sum.mean():.4f} std={peb_sum.std():.4f}")

    # Snackpack pair validation
    print("\n=== Snackpack pair K validation (5 sample seeds) ===")
    for seed in range(5):
        rng = np.random.default_rng(seed)
        for d in DAYS:
            s = scenario.generate_day(d, 10_000, rng)
            cv = s["fv_paths"]["SNACKPACK_CHOCOLATE"] + s["fv_paths"]["SNACKPACK_VANILLA"]
            print(f"  seed={seed} day={d}: cv mean={cv.mean():.2f} std={cv.std():.2f} "
                  f"first100={cv[:100].mean():.1f} last100={cv[-100:].mean():.1f}")
        break  # one seed enough

    # Pulse validation
    print("\n=== Pulse stats (averaged over 50 seeds) ===")
    pulse_summary = {}
    for seed in range(50):
        rng = np.random.default_rng(seed)
        for d in DAYS:
            synth = scenario.generate_day(d, 10_000, rng)
            for grp in ("V", "P", "M"):
                sub = [p for p in synth["pulses"] if p["group"] == grp]
                if not sub:
                    continue
                pulse_summary.setdefault(grp, []).append({
                    "n": len(sub),
                    "p_buy": sum(1 for p in sub if p["direction"] == "BUY") / len(sub),
                    "qty_mean": np.mean([p["qty"] for p in sub]),
                })
    for grp, stats in pulse_summary.items():
        ns = [s["n"] for s in stats]
        pbs = [s["p_buy"] for s in stats]
        qms = [s["qty_mean"] for s in stats]
        print(f"  {grp}: n_pulses {np.mean(ns):.1f} ± {np.std(ns):.1f}, "
              f"p_buy {np.mean(pbs):.3f} ± {np.std(pbs):.3f}, "
              f"qty_mean {np.mean(qms):.3f} ± {np.std(qms):.3f}")

    # Save summary
    cmp.to_csv(OUT_DIR / "scenario_v2_validation.csv", index=False)
    print(f"\nwritten: scenario_v2_validation.csv")


if __name__ == "__main__":
    main()
