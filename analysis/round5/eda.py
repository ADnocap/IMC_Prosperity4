"""Round 5 EDA — per-product behavior classification + cross-asset structure.

Loads 3 days of R5 prices (10K ticks/day, 50 products) and computes:
  - per-product: mid mean/std, drift slope, AR(1) phi on returns, MR half-life,
    median spread, # trades, σ_per_tick, total range
  - within-category 5×5 correlation matrices (mid levels + log-returns)
  - cross-category 50×50 correlation matrix
  - ladder analysis (Pebbles XS<S<M<L<XL, Panels 1x2/2x2/1x4/2x4/4x4)

Writes:
  analysis/round5/eda_per_product.csv
  analysis/round5/eda_correlations.json
  analysis/round5/eda_ladders.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
OUT_DIR = REPO_ROOT / "analysis" / "round5"

DAYS = (2, 3, 4)
TICKS_PER_DAY = 10_000
TICK_SIZE = 100  # timestamps increment by 100

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
ALL_PRODUCTS = [p for ps in CATEGORIES.values() for p in ps]
CATEGORY_OF = {p: c for c, ps in CATEGORIES.items() for p in ps}


def load_prices() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (mid_df, spread_df) indexed by global tick (day*10K + t/100)."""
    frames_mid: List[pd.DataFrame] = []
    frames_spread: List[pd.DataFrame] = []
    for d in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - DAYS[0]) * TICKS_PER_DAY + df["timestamp"] // TICK_SIZE
        df["spread"] = df["ask_price_1"] - df["bid_price_1"]
        mid = df.pivot(index="tick", columns="product", values="mid_price")
        spr = df.pivot(index="tick", columns="product", values="spread")
        frames_mid.append(mid)
        frames_spread.append(spr)
    mid_df = pd.concat(frames_mid).sort_index()
    spread_df = pd.concat(frames_spread).sort_index()
    mid_df = mid_df[ALL_PRODUCTS]
    spread_df = spread_df[ALL_PRODUCTS]
    return mid_df, spread_df


def load_trades() -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for d in DAYS:
        df = pd.read_csv(DATA_DIR / f"trades_round_5_day_{d}.csv", sep=";")
        df["day"] = d
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def per_product_stats(mid: pd.DataFrame, spread: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Compute per-product summary stats."""
    rows = []
    n = len(mid)
    t = np.arange(n)
    trade_counts = trades["symbol"].value_counts().to_dict()
    for p in ALL_PRODUCTS:
        mids = mid[p].values
        # drift via OLS on time
        slope, intercept = np.polyfit(t, mids, 1)
        # detrended residuals
        detrended = mids - (intercept + slope * t)
        # AR(1) on first differences (returns) — phi close to 0 = RW, phi negative = MR
        rets = np.diff(mids)
        if len(rets) > 1 and rets.std() > 0:
            phi_ret = np.corrcoef(rets[:-1], rets[1:])[0, 1]
        else:
            phi_ret = float("nan")
        # AR(1) on level — phi close to 1 = RW, phi < 1 = MR with half-life ln(.5)/ln(phi)
        if mids.std() > 0:
            phi_level = np.corrcoef(mids[:-1], mids[1:])[0, 1]
        else:
            phi_level = float("nan")
        # half-life from detrended AR(1)
        if detrended.std() > 0:
            phi_det = np.corrcoef(detrended[:-1], detrended[1:])[0, 1]
            if 0 < phi_det < 1:
                half_life = float(np.log(0.5) / np.log(phi_det))
            else:
                half_life = float("inf")
        else:
            phi_det = float("nan")
            half_life = float("inf")

        rows.append({
            "product": p,
            "category": CATEGORY_OF[p],
            "mid_mean": float(mids.mean()),
            "mid_std": float(mids.std()),
            "mid_min": float(mids.min()),
            "mid_max": float(mids.max()),
            "range": float(mids.max() - mids.min()),
            "drift_per_tick": float(slope),  # mid units per tick
            "drift_per_day": float(slope * TICKS_PER_DAY),
            "sigma_ret_per_tick": float(rets.std()),
            "phi_returns": float(phi_ret),
            "phi_level": float(phi_level),
            "phi_detrended": float(phi_det),
            "half_life_ticks": half_life,
            "spread_median": float(np.nanmedian(spread[p].values)),
            "spread_mean": float(np.nanmean(spread[p].values)),
            "n_trades": int(trade_counts.get(p, 0)),
            # MM edge proxy: half-spread / per-tick σ — higher = better passive MM Sharpe
            "spread_over_sigma": float(np.nanmedian(spread[p].values) / max(rets.std(), 1e-9)),
        })

    df = pd.DataFrame(rows).set_index("product")

    def classify(row: pd.Series) -> str:
        # heuristic buckets:
        # stationary if range < 5 * sigma_ret_per_tick * sqrt(N) (much tighter than RW would predict)
        # drift if |drift_per_day| > 0.5 * sigma_ret_per_tick * sqrt(TICKS_PER_DAY)
        # else: random_walk
        n = len(mid)
        rw_expected_range = row["sigma_ret_per_tick"] * np.sqrt(n) * 3  # ~3σ
        drift_total = abs(row["drift_per_tick"]) * n
        if row["half_life_ticks"] < 500 and row["range"] < rw_expected_range * 0.6:
            return "stationary"
        if drift_total > rw_expected_range * 0.5:
            return "drift"
        if row["mid_std"] > 1000:
            return "volatile_rw"
        return "random_walk"

    df["regime"] = df.apply(classify, axis=1)
    return df


def category_correlations(mid: pd.DataFrame) -> Dict[str, Dict]:
    """5×5 correlation matrices on mid levels and log-returns, per category."""
    out = {}
    for cat, members in CATEGORIES.items():
        sub_levels = mid[members]
        sub_rets = sub_levels.pct_change().dropna()
        out[cat] = {
            "members": members,
            "level_corr": sub_levels.corr().round(3).values.tolist(),
            "return_corr": sub_rets.corr().round(3).values.tolist(),
            "level_corr_mean_offdiag": float(off_diag_mean(sub_levels.corr().values)),
            "return_corr_mean_offdiag": float(off_diag_mean(sub_rets.corr().values)),
        }
    return out


def off_diag_mean(corr: np.ndarray) -> float:
    n = corr.shape[0]
    mask = ~np.eye(n, dtype=bool)
    return float(corr[mask].mean())


def cross_pairs(mid: pd.DataFrame, threshold: float = 0.7) -> List[Dict]:
    """Find pairs with |corr| > threshold across the entire universe."""
    rets = mid.pct_change().dropna()
    corr = rets.corr()
    pairs: List[Dict] = []
    for i, p1 in enumerate(corr.columns):
        for j, p2 in enumerate(corr.columns):
            if j <= i:
                continue
            r = corr.iloc[i, j]
            if abs(r) >= threshold:
                pairs.append({
                    "a": p1,
                    "b": p2,
                    "corr": round(float(r), 4),
                    "same_category": CATEGORY_OF[p1] == CATEGORY_OF[p2],
                })
    pairs.sort(key=lambda r: -abs(r["corr"]))
    return pairs


def ladder_analysis(mid: pd.DataFrame) -> Dict:
    """Pebbles + Panels ladder regressions."""
    out: Dict[str, Dict] = {}

    # Pebbles: try basket = sum of all 5 (anchor) + per-product residual stats
    for cat, sizes in [
        ("pebbles", {"PEBBLES_XS": 1, "PEBBLES_S": 2, "PEBBLES_M": 3, "PEBBLES_L": 4, "PEBBLES_XL": 5}),
        ("panels", {"PANEL_1X2": 2, "PANEL_2X2": 4, "PANEL_1X4": 4, "PANEL_2X4": 8, "PANEL_4X4": 16}),
    ]:
        members = list(sizes.keys())
        m = mid[members].values  # (T, 5)
        # equal-weight basket
        basket_eq = m.mean(axis=1)
        # size-weighted basket (treats size as area/scale weight)
        weights = np.array([sizes[p] for p in members], dtype=float)
        basket_sw = (m * weights).sum(axis=1) / weights.sum()
        # for each member, fit member ~ alpha + beta * basket_sw and report residual std
        member_fits: Dict[str, Dict] = {}
        for i, p in enumerate(members):
            y = m[:, i]
            x = basket_sw
            beta = np.cov(y, x, ddof=0)[0, 1] / np.var(x)
            alpha = y.mean() - beta * x.mean()
            resid = y - (alpha + beta * x)
            # AR(1) on residuals + half-life
            if resid.std() > 0:
                phi = np.corrcoef(resid[:-1], resid[1:])[0, 1]
                half_life = float(np.log(0.5) / np.log(phi)) if 0 < phi < 1 else float("inf")
            else:
                phi = float("nan")
                half_life = float("inf")
            member_fits[p] = {
                "size_weight": sizes[p],
                "alpha": float(alpha),
                "beta": float(beta),
                "resid_std": float(resid.std()),
                "resid_phi": float(phi),
                "resid_half_life_ticks": half_life,
            }
        # adjacent ratios
        ratios = {}
        for a, b in zip(members, members[1:]):
            ratios[f"{b}/{a}"] = float((mid[b] / mid[a]).mean())
        # rolling correlation between basket_eq and members
        out[cat] = {
            "members": members,
            "size_weights": sizes,
            "basket_eq_std": float(basket_eq.std()),
            "basket_sw_std": float(basket_sw.std()),
            "member_fits": member_fits,
            "adjacent_ratios": ratios,
        }
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("loading prices…")
    mid, spread = load_prices()
    print(f"  mid shape: {mid.shape}, spread shape: {spread.shape}")
    print("loading trades…")
    trades = load_trades()
    print(f"  trades rows: {len(trades)}")

    print("per-product stats…")
    pp = per_product_stats(mid, spread, trades)
    pp.to_csv(OUT_DIR / "eda_per_product.csv")
    print(f"  written: {OUT_DIR / 'eda_per_product.csv'}")
    print("\nregime counts:")
    print(pp["regime"].value_counts().to_string())

    print("\ncategory correlations…")
    cat_corr = category_correlations(mid)
    print("\nwithin-category mean off-diagonal correlations (returns):")
    for cat, info in cat_corr.items():
        print(f"  {cat:14s}  level={info['level_corr_mean_offdiag']:+.3f}   "
              f"returns={info['return_corr_mean_offdiag']:+.3f}")

    print("\ncross-pair screening (|corr| ≥ 0.5)…")
    pairs = cross_pairs(mid, threshold=0.5)
    pairs_high = cross_pairs(mid, threshold=0.7)
    print(f"  found {len(pairs)} pairs ≥0.5,  {len(pairs_high)} pairs ≥0.7")
    if pairs_high[:10]:
        print("  top 10 |corr|:")
        for p in pairs_high[:10]:
            tag = "(same cat)" if p["same_category"] else "(CROSS)"
            print(f"    {p['corr']:+.3f}  {p['a']:30s}  {p['b']:30s}  {tag}")

    print("\nladder analysis…")
    ladders = ladder_analysis(mid)

    # write json bundle
    bundle = {
        "n_ticks": int(len(mid)),
        "products": ALL_PRODUCTS,
        "categories": CATEGORIES,
        "category_correlations": cat_corr,
        "high_corr_pairs": pairs,
        "ladders": ladders,
    }
    out_json = OUT_DIR / "eda_correlations.json"
    out_json.write_text(json.dumps(bundle, indent=2))
    print(f"  written: {out_json}")

    print("\ndone.")


if __name__ == "__main__":
    main()
