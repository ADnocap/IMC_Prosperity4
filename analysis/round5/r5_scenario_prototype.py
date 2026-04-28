"""R5Scenario Python prototype.

Generates synthetic 3-day R5 sessions respecting:
  - 50 product symbols across 10 categories
  - Pebbles sum = 50,000 exactly (4 free RWs + 1 derived)
  - Snackpack CHOC + VANILLA = K_day (slow K walk)
  - Per-asset σ from historical sigma_step1000
  - 3 independent Poisson pulse processes (V/P/M) with calibrated rates,
    direction balance, qty distribution
  - Symmetric L1+L2 books with per-asset half-spread h and depth

Validates by comparing synthetic statistics (per-asset σ, basket sum std,
pulse rates, direction balance, trade direction balance) to the historical
data in `data/prosperity4/round5/`.

If statistics match, this is the canonical model to port to Rust.
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
OUT_DIR = REPO_ROOT / "analysis" / "round5" / "scenario_out"

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
PEBBLE_FREE = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L"]
PEBBLE_DERIVED = "PEBBLES_XL"

VANILLA_PRODUCTS = [p for c, ps in CATEGORIES.items()
                    for p in ps if c not in ("pebbles", "microchips")]


# ---------------------------------------------------------------------------
# Per-asset and per-pulse calibration
# ---------------------------------------------------------------------------

@dataclass
class AssetCfg:
    symbol: str
    category: str
    sigma: float            # σ per tick (RW/OU innovation in level units)
    h: float                # half-spread (FV - bid_1 = h)
    depth_l1: int
    depth_l2: int
    l2_lift: int            # bid_2 = bid_1 - l2_lift
    derived: bool = False   # True for PEBBLES_XL and SNACKPACK_VANILLA
    # OU parameters (None → pure RW). theta = ln(2) / half_life
    half_life_ticks: Optional[float] = None
    daily_mu: Optional[Dict[int, float]] = None  # per-day OU mean (set by calibrator)


@dataclass
class PulseCfg:
    name: str               # "V" / "P" / "M"
    members: List[str]
    rate_per_tick: float    # P(pulse fires this tick) = rate
    qty_min: int
    qty_max: int            # discrete uniform inclusive
    p_buy: float = 0.5


# ---------------------------------------------------------------------------
# Calibration loader: build per-asset configs from the historical CSVs.
# ---------------------------------------------------------------------------

def calibrate_from_history() -> Tuple[Dict[str, AssetCfg], List[PulseCfg], Dict[int, Dict[str, float]]]:
    """Returns (asset_cfg, pulse_cfg, per_day_starting_FVs)."""
    # Load all 3 days of prices for sigma + h + depth + starting FVs
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        if "day" not in f.columns:
            f["day"] = d
        frames.append(f)
    prices = pd.concat(frames, ignore_index=True)

    # σ per asset: use sigma_step1000 (1000-step variance / sqrt(1000))
    sigmas = {}
    for sym in ALL_PRODUCTS:
        v = prices[prices["product"] == sym].sort_values(["day", "timestamp"])["mid_price"].values
        if len(v) >= 1001:
            sigmas[sym] = float((v[1000:] - v[:-1000]).std() / np.sqrt(1000))
        else:
            sigmas[sym] = float(np.diff(v).std())

    # h per asset: use median (mid - bid_1)
    hs = {}
    for sym in ALL_PRODUCTS:
        sub = prices[prices["product"] == sym]
        h = (sub["mid_price"] - sub["bid_price_1"]).median()
        hs[sym] = float(h)

    # depth per asset
    depths = {}
    for sym in ALL_PRODUCTS:
        sub = prices[prices["product"] == sym]
        depths[sym] = (
            int(sub["bid_volume_1"].median()),
            int(sub["bid_volume_2"].median()),
            int((sub["bid_price_1"] - sub["bid_price_2"]).median()),
        )

    # asset cfg
    asset_cfg = {}
    for sym in ALL_PRODUCTS:
        derived = sym in (PEBBLE_DERIVED, "SNACKPACK_VANILLA")
        d_l1, d_l2, lift = depths[sym]
        asset_cfg[sym] = AssetCfg(
            symbol=sym,
            category=CATEGORY_OF[sym],
            sigma=sigmas[sym],
            h=hs[sym],
            depth_l1=d_l1,
            depth_l2=d_l2,
            l2_lift=lift,
            derived=derived,
        )

    # Starting FVs per day = first observed mid per (day, sym)
    starting_fvs = {}
    for d in (2, 3, 4):
        starts = (prices[prices["day"] == d]
                  .sort_values("timestamp")
                  .groupby("product")
                  .first()["mid_price"]
                  .to_dict())
        starting_fvs[d] = starts

    # Pulse calibration: load trades, count pulses per day per group
    tframes = []
    for d in (2, 3, 4):
        t = pd.read_csv(DATA_DIR / f"trades_round_5_day_{d}.csv", sep=";")
        t["day"] = d
        tframes.append(t)
    trades = pd.concat(tframes, ignore_index=True)
    trades["cat"] = trades["symbol"].map(CATEGORY_OF)
    trades["group"] = trades["cat"].apply(
        lambda c: "P" if c == "pebbles" else "M" if c == "microchips" else "V"
    )

    n_ticks = 30_000
    pulse_cfg = []
    for grp, members, qty_min, qty_max in [
        ("V", VANILLA_PRODUCTS, 1, 4),
        ("P", CATEGORIES["pebbles"], 2, 5),
        ("M", CATEGORIES["microchips"], 1, 3),
    ]:
        sub = trades[trades["group"] == grp]
        n_pulses = sub.groupby(["day", "timestamp"]).size().shape[0]
        rate = n_pulses / n_ticks
        # measure empirical p_buy from trade-vs-bid_1/ask_1: derived in pulse_dive
        p_buy = 0.5  # known to be ~0.5 from pulse_dive
        pulse_cfg.append(PulseCfg(
            name=grp, members=list(members),
            rate_per_tick=rate,
            qty_min=qty_min, qty_max=qty_max,
            p_buy=p_buy,
        ))

    return asset_cfg, pulse_cfg, starting_fvs


# ---------------------------------------------------------------------------
# Scenario generator
# ---------------------------------------------------------------------------

class R5Scenario:
    def __init__(self, asset_cfg: Dict[str, AssetCfg], pulse_cfg: List[PulseCfg],
                 starting_fvs: Dict[int, Dict[str, float]], k_day_start: float = 20025.0):
        self.asset_cfg = asset_cfg
        self.pulse_cfg = pulse_cfg
        self.starting_fvs = starting_fvs
        # Daily K_day for CHOC + VANILLA pair (calibrated initial value)
        self.k_day_init = k_day_start

    def generate_day(self, day: int, n_ticks: int, rng: np.random.Generator) -> Dict:
        """Generate one synthetic day. Returns dict with keys:
          fv_paths: {symbol: [n_ticks floats]}
          pulses:   list of dicts with (tick, members, direction, qty)
        """
        fvs: Dict[str, np.ndarray] = {}

        # Starting FVs
        starts = self.starting_fvs.get(day, self.starting_fvs[next(iter(self.starting_fvs))])
        # Independent OU/RW walks for non-derived assets
        for sym in ALL_PRODUCTS:
            cfg = self.asset_cfg[sym]
            if cfg.derived:
                continue
            innovations = rng.normal(0, cfg.sigma, size=n_ticks)
            v = np.empty(n_ticks)
            v[0] = starts[sym]
            v[1:] = starts[sym] + np.cumsum(innovations[:-1])
            # snap to half-integer
            fvs[sym] = np.round(v * 2) / 2

        # Derived pebble: XL = 50000 - sum(other 4)
        sum_free = sum(fvs[p] for p in PEBBLE_FREE)
        fvs[PEBBLE_DERIVED] = np.round((50_000 - sum_free) * 2) / 2

        # Derived snackpack: VANILLA = K_day - CHOC. Use a slow K_day walk.
        k_day_path = self._k_day_path(day, n_ticks, rng)
        fvs["SNACKPACK_VANILLA"] = np.round((k_day_path - fvs["SNACKPACK_CHOCOLATE"]) * 2) / 2

        # Pulse generation
        pulses: List[Dict] = []
        for cfg in self.pulse_cfg:
            n_pulses = rng.binomial(n_ticks, cfg.rate_per_tick)
            ticks = sorted(rng.choice(n_ticks, size=n_pulses, replace=False))
            for tick in ticks:
                direction = "BUY" if rng.random() < cfg.p_buy else "SELL"
                qty = int(rng.integers(cfg.qty_min, cfg.qty_max + 1))
                pulses.append({
                    "tick": int(tick),
                    "group": cfg.name,
                    "members": cfg.members,
                    "direction": direction,
                    "qty": qty,
                })
        # Sort pulses by tick
        pulses.sort(key=lambda p: p["tick"])

        return {"fv_paths": fvs, "pulses": pulses, "k_day": k_day_path}

    def _k_day_path(self, day: int, n_ticks: int, rng: np.random.Generator) -> np.ndarray:
        """Slow random walk for CHOC + VANILLA constraint K_day, std ≈ 0.5/tick."""
        # within-day std around 30-50 over 10K ticks → σ_per_tick ≈ 0.4
        sigma_k = 0.4
        # Starting K_day per day from history: 20025 / 19927 / 19870
        k_starts = {2: 20025.0, 3: 19927.0, 4: 19870.0}
        start = k_starts.get(day, 20025.0)
        innov = rng.normal(0, sigma_k, size=n_ticks)
        path = np.empty(n_ticks)
        path[0] = start
        path[1:] = start + np.cumsum(innov[:-1])
        return path

    def make_book(self, fv: float, cfg: AssetCfg) -> Dict:
        """Produce L1+L2 book. fv is half-integer; bid/ask integer."""
        bid_1 = int(np.floor(fv - cfg.h + 0.5))
        ask_1 = int(np.ceil(fv + cfg.h - 0.5))
        bid_2 = bid_1 - cfg.l2_lift
        ask_2 = ask_1 + cfg.l2_lift
        return {
            "bid": [(bid_1, cfg.depth_l1), (bid_2, cfg.depth_l2)],
            "ask": [(ask_1, cfg.depth_l1), (ask_2, cfg.depth_l2)],
        }


# ---------------------------------------------------------------------------
# Validation: compare synthetic stats vs historical
# ---------------------------------------------------------------------------

def validate(scenario: R5Scenario, asset_cfg: Dict[str, AssetCfg],
             n_seeds: int = 5, n_ticks: int = 10_000) -> pd.DataFrame:
    """Generate n_seeds synthetic days; return per-asset stats."""
    syn_records: List[Dict] = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        # use day=2 as the "synthetic representative" day
        synth = scenario.generate_day(2, n_ticks, rng)
        for sym in ALL_PRODUCTS:
            v = synth["fv_paths"][sym]
            syn_records.append({
                "seed": seed,
                "product": sym,
                "category": asset_cfg[sym].category,
                "mean": float(v.mean()),
                "std": float(v.std()),
                "sigma_diff": float(np.diff(v).std()),
                "sigma_step1000": float((v[1000:] - v[:-1000]).std() / np.sqrt(1000))
                                  if len(v) > 1000 else float("nan"),
            })

    syn = pd.DataFrame(syn_records).groupby(["product", "category"]).mean().reset_index()
    return syn


def compare_with_historical(syn: pd.DataFrame) -> pd.DataFrame:
    """Compute historical stats and compare side-by-side with synthetic."""
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        frames.append(f)
    prices = pd.concat(frames, ignore_index=True)

    hist_records = []
    for sym in ALL_PRODUCTS:
        # Use day 2 for hist comparison (synthetic is "day 2")
        v = prices[(prices["product"] == sym) & (prices.get("day", -1) == 2)] \
            .sort_values("timestamp")["mid_price"].values
        if len(v) == 0:
            v = prices[prices["product"] == sym].sort_values("timestamp")["mid_price"].values[:10000]
        hist_records.append({
            "product": sym,
            "hist_mean": float(v.mean()),
            "hist_std": float(v.std()),
            "hist_sigma_diff": float(np.diff(v).std()),
            "hist_sigma_step1000": float((v[1000:] - v[:-1000]).std() / np.sqrt(1000))
                                   if len(v) > 1000 else float("nan"),
        })
    hist = pd.DataFrame(hist_records)

    merged = syn.merge(hist, on="product")
    merged = merged[["product", "category",
                      "mean", "hist_mean",
                      "std", "hist_std",
                      "sigma_diff", "hist_sigma_diff",
                      "sigma_step1000", "hist_sigma_step1000"]]
    merged["std_ratio"] = merged["std"] / merged["hist_std"]
    merged["sigma_diff_ratio"] = merged["sigma_diff"] / merged["hist_sigma_diff"]
    return merged


def basket_validation(scenario: R5Scenario, n_seeds: int = 5, n_ticks: int = 10_000) -> Dict:
    """Verify Pebbles sum=50K + Snackpack pair K constraint hold in synthesis."""
    out = {}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        synth = scenario.generate_day(2, n_ticks, rng)
        peb = sum(synth["fv_paths"][p] for p in CATEGORIES["pebbles"])
        cv = synth["fv_paths"]["SNACKPACK_CHOCOLATE"] + synth["fv_paths"]["SNACKPACK_VANILLA"]
        out[seed] = {
            "pebble_sum_mean": float(peb.mean()),
            "pebble_sum_std": float(peb.std()),
            "pebble_sum_min": float(peb.min()),
            "pebble_sum_max": float(peb.max()),
            "cv_sum_mean": float(cv.mean()),
            "cv_sum_std": float(cv.std()),
        }
    return out


def pulse_validation(scenario: R5Scenario, n_seeds: int = 5, n_ticks: int = 10_000) -> Dict:
    """Verify pulse rates and direction balance."""
    out = {"V": [], "P": [], "M": []}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        synth = scenario.generate_day(2, n_ticks, rng)
        for grp in ["V", "P", "M"]:
            sub = [p for p in synth["pulses"] if p["group"] == grp]
            n = len(sub)
            n_buy = sum(1 for p in sub if p["direction"] == "BUY")
            qtys = [p["qty"] for p in sub]
            out[grp].append({
                "seed": seed,
                "n_pulses": n,
                "p_buy": n_buy / n if n > 0 else float("nan"),
                "qty_mean": float(np.mean(qtys)) if qtys else float("nan"),
            })
    return out


# ---------------------------------------------------------------------------

def main():
    print("=== Calibrating from history… ===")
    asset_cfg, pulse_cfg, starting_fvs = calibrate_from_history()
    print(f"  {len(asset_cfg)} asset configs, {len(pulse_cfg)} pulse processes")
    print(f"  starting FVs available for days: {sorted(starting_fvs.keys())}")
    print()
    print("Pulse rates per tick:")
    for cfg in pulse_cfg:
        print(f"  {cfg.name}  rate={cfg.rate_per_tick:.5f} ({cfg.rate_per_tick*10000:.0f} per 10K-tick day)  "
              f"qty=Uniform({cfg.qty_min}, {cfg.qty_max})  p_buy={cfg.p_buy}")

    scenario = R5Scenario(asset_cfg, pulse_cfg, starting_fvs)

    print("\n=== Generating 1 synthetic day (seed 0) ===")
    rng = np.random.default_rng(0)
    synth = scenario.generate_day(2, 10_000, rng)
    print(f"  fv_paths for {len(synth['fv_paths'])} products")
    print(f"  {len(synth['pulses'])} pulses")
    print(f"  pebble sum: mean={sum(synth['fv_paths'][p] for p in CATEGORIES['pebbles']).mean():.4f}, "
          f"std={sum(synth['fv_paths'][p] for p in CATEGORIES['pebbles']).std():.4f}")
    cv = synth['fv_paths']['SNACKPACK_CHOCOLATE'] + synth['fv_paths']['SNACKPACK_VANILLA']
    print(f"  CHOC+VANILLA: mean={cv.mean():.2f}, std={cv.std():.2f}")

    print("\n=== Validation: 5 seeds, comparing to historical ===")
    syn = validate(scenario, asset_cfg, n_seeds=5, n_ticks=10_000)
    cmp = compare_with_historical(syn)
    print(cmp.sort_values("category").to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n=== Basket constraint validation (5 seeds) ===")
    basket = basket_validation(scenario, n_seeds=5)
    for seed, stats in basket.items():
        print(f"  seed={seed}: peb_sum mean={stats['pebble_sum_mean']:.4f} std={stats['pebble_sum_std']:.4f} "
              f"min={stats['pebble_sum_min']:.1f} max={stats['pebble_sum_max']:.1f}   "
              f"cv mean={stats['cv_sum_mean']:.2f} std={stats['cv_sum_std']:.2f}")

    print("\n=== Pulse validation (5 seeds) ===")
    pulse_v = pulse_validation(scenario, n_seeds=5)
    for grp, runs in pulse_v.items():
        n_means = np.mean([r["n_pulses"] for r in runs])
        p_buy_means = np.mean([r["p_buy"] for r in runs])
        qty_means = np.mean([r["qty_mean"] for r in runs])
        print(f"  group {grp}: n_pulses ~ {n_means:.0f}, p_buy ~ {p_buy_means:.3f}, qty_mean ~ {qty_means:.3f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmp.to_csv(OUT_DIR / "validation.csv", index=False)
    print(f"\nwritten: {OUT_DIR / 'validation.csv'}")


if __name__ == "__main__":
    main()
