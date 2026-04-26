"""Round 3 — FINAL deep audit before submission lock-in.

Investigates ten areas not yet covered by prior analyses:

  1. VELVETFRUIT-only deep dive (analogous to hydrogel_deep)
  2. Deep ITM voucher MM (VEV_4000/4500) — alt sizing & OBI skew
  3. Time-of-day signal Sharpe per quarter
  4. Spread-condition gating on HYDROGEL
  5. Inventory autocorrelation (proxy: signed-flow autocorr per asset)
  6. MAF auction guidance for R3 (recap from R2 calibration)
  7. Cross-strike vert-spread MR replay on full 3-day data (rothschild logic)
  8. Trade volume vs our quote saturation
  9. Fresh signals on HYDROGEL/VELVET/VEV_5000-5500 (microprice, stale-quote)
 10. Recommendation summary in JSON

Strict per-day stratification on every finding. Skeptical reporting.

Run:
  py -3.13 analysis/round3/final_audit.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "prosperity4" / "round3"
OUT_DIR = ROOT / "analysis" / "round3"
OUT_JSON = OUT_DIR / "final_audit.json"

DAYS = (0, 1, 2)
PRODUCTS = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500",
    "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300",
    "VEV_5400", "VEV_5500",
]
LIMITS = {
    "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
}
STRIKES = {"VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
           "VEV_5200": 5200, "VEV_5100": 5100, "VEV_5000": 5000}
SMILE_A = 0.24874922943238548
SMILE_B = 0.0033068871733395525
SMILE_C = 0.027240641751624436
SMILE_T = 6.0 / 365.0


# -------------------- IO --------------------
def load_prices(symbol: str) -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for d in DAYS:
        df = pd.read_parquet(DATA / f"prices_round_3_day_{d}.parquet")
        df = df[df["product"] == symbol].sort_values("timestamp").reset_index(drop=True)
        out[d] = df
    return out


def load_trades(symbol: str) -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for d in DAYS:
        df = pd.read_parquet(DATA / f"trades_round_3_day_{d}.parquet")
        df = df[df["symbol"] == symbol].sort_values("timestamp").reset_index(drop=True)
        out[d] = df
    return out


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    bv1 = df["bid_volume_1"].fillna(0).astype(float)
    av1 = df["ask_volume_1"].fillna(0).astype(float)
    bp1 = df["bid_price_1"].astype(float)
    ap1 = df["ask_price_1"].astype(float)
    mid = df["mid_price"].astype(float)
    df["mid"] = mid
    df["spread"] = ap1 - bp1
    denom = bv1 + av1
    df["l1_obi"] = np.where(denom > 0, (bv1 - av1) / denom, 0.0)
    df["microprice"] = np.where(denom > 0, (bp1 * av1 + ap1 * bv1) / denom, mid)
    df["micro_dev"] = df["microprice"] - mid
    return df


# -------------------- 1. VELVETFRUIT deep dive --------------------
def velvet_deep(prices: dict[int, pd.DataFrame]) -> dict:
    """Test multiple signal styles per-day."""
    out = {"signals": {}, "spread_dist": {}, "stats": {}}

    for d, df in prices.items():
        df = add_features(df)
        out["spread_dist"][f"day{d}"] = {
            "median": float(df["spread"].median()),
            "mean": float(df["spread"].mean()),
            "p25": float(df["spread"].quantile(0.25)),
            "p75": float(df["spread"].quantile(0.75)),
            "p95": float(df["spread"].quantile(0.95)),
        }
        out["stats"][f"day{d}"] = {
            "mid_std": float(df["mid"].diff().std()),
            "mid_first": float(df["mid"].iloc[0]),
            "mid_last": float(df["mid"].iloc[-1]),
            "n_ticks": int(len(df)),
        }

    # Sweep rev_z windows per-day (5 horizons each, fwd return = +H ticks)
    sweeps = []
    for w in (20, 50, 200, 500):
        for thresh in (1.0, 1.5, 2.0):
            for H in (1, 5, 20, 100):
                per_day = []
                for d, df in prices.items():
                    df = add_features(df)
                    ma = df["mid"].rolling(w, min_periods=w).mean()
                    sd = df["mid"].rolling(w, min_periods=w).std(ddof=0)
                    z = (df["mid"] - ma) / sd
                    fwd = df["mid"].shift(-H) - df["mid"]
                    fire = z.abs() > thresh
                    pnl = -np.sign(z[fire]) * fwd[fire]
                    pnl = pnl.dropna()
                    if len(pnl) < 5:
                        per_day.append((0, 0.0, 0.0))
                    else:
                        per_day.append((int(len(pnl)), float(pnl.mean()), float(pnl.std() or 1.0)))
                # Aggregate across days
                total_n = sum(p[0] for p in per_day)
                if total_n == 0:
                    continue
                weighted_mean = sum(p[0] * p[1] for p in per_day) / total_n
                # 3-day sign-consistent?
                consistent = all(p[1] > 0 for p in per_day if p[0] > 0)
                sweeps.append({
                    "window": w, "thresh": thresh, "H": H,
                    "n_total": total_n, "mean_pnl_per_sig": float(weighted_mean),
                    "per_day_means": [p[1] for p in per_day],
                    "consistent_3d": bool(consistent),
                })
    sweeps.sort(key=lambda x: x["mean_pnl_per_sig"], reverse=True)
    out["signals"]["rev_z_sweep_top10"] = sweeps[:10]

    # OBI tier H=1 drift per day
    obi_buckets = {}
    for d, df in prices.items():
        df = add_features(df)
        fwd = df["mid"].shift(-1) - df["mid"]
        bins = [-1.01, -0.3, -0.05, 0.05, 0.3, 1.01]
        labels = ["<<-0.3", "-0.3..-0.05", "neutral", "0.05..0.3", ">>0.3"]
        df["bucket"] = pd.cut(df["l1_obi"], bins=bins, labels=labels)
        agg = []
        for lbl in labels:
            mask = df["bucket"] == lbl
            if mask.sum() < 5:
                agg.append({"label": lbl, "n": int(mask.sum()), "mean_drift": 0.0})
            else:
                agg.append({"label": lbl, "n": int(mask.sum()),
                             "mean_drift": float(fwd[mask].mean())})
        obi_buckets[f"day{d}"] = agg
    out["signals"]["obi_tier_drift_h1"] = obi_buckets

    # Microprice deviation as direct signal
    micro_results = []
    for thresh in (0.05, 0.10, 0.20, 0.35):
        for H in (1, 5, 20):
            per_day = []
            for d, df in prices.items():
                df = add_features(df)
                fwd = df["mid"].shift(-H) - df["mid"]
                fire = df["micro_dev"].abs() > thresh
                pnl = np.sign(df["micro_dev"][fire]) * fwd[fire]
                pnl = pnl.dropna()
                per_day.append((int(len(pnl)), float(pnl.mean()) if len(pnl) > 5 else 0.0))
            total_n = sum(p[0] for p in per_day)
            if total_n == 0:
                continue
            wm = sum(p[0] * p[1] for p in per_day) / total_n
            consistent = all(p[1] > 0 for p in per_day if p[0] > 0)
            micro_results.append({
                "thresh": thresh, "H": H, "n": total_n,
                "mean_pnl": float(wm),
                "per_day": [p[1] for p in per_day],
                "consistent": bool(consistent),
            })
    micro_results.sort(key=lambda x: x["mean_pnl"], reverse=True)
    out["signals"]["microprice_top5"] = micro_results[:5]

    return out


# -------------------- 2. Deep ITM voucher MM analysis --------------------
def deep_itm_analysis(prices_4000: dict, prices_4500: dict) -> dict:
    """For VEV_4000 and VEV_4500: characterise spread, OBI predictive power,
    and estimate the value of a confidence-sized OBI handler."""
    out = {}
    for sym, prices in [("VEV_4000", prices_4000), ("VEV_4500", prices_4500)]:
        per_day_stats = {}
        per_day_obi = {}
        for d, df in prices.items():
            df = add_features(df)
            per_day_stats[f"day{d}"] = {
                "spread_median": float(df["spread"].median()),
                "spread_mean": float(df["spread"].mean()),
                "mid_std_diff": float(df["mid"].diff().std()),
                "ticks": int(len(df)),
            }
            # OBI tier H=1 drift
            fwd = df["mid"].shift(-1) - df["mid"]
            bins = [-1.01, -0.3, -0.05, 0.05, 0.3, 1.01]
            labels = ["<<-0.3", "-0.3..-0.05", "neutral", "0.05..0.3", ">>0.3"]
            df["bucket"] = pd.cut(df["l1_obi"], bins=bins, labels=labels)
            buckets = []
            for lbl in labels:
                mask = df["bucket"] == lbl
                if mask.sum() < 5:
                    buckets.append({"label": lbl, "n": int(mask.sum()), "drift": 0.0})
                else:
                    buckets.append({"label": lbl, "n": int(mask.sum()),
                                     "drift": float(fwd[mask].mean())})
            per_day_obi[f"day{d}"] = buckets

        # OBI passive-skew implied PnL (mid-tick-points): for each tick where
        # |OBI| > 0.05, capture sign(OBI) * fwd_ret * size_proxy
        capture = {}
        for size_max in (40, 80, 150):
            tot = 0.0
            n_signals = 0
            for d, df in prices.items():
                df = add_features(df)
                fwd = df["mid"].shift(-1) - df["mid"]
                mask = df["l1_obi"].abs() > 0.05
                size = (df["l1_obi"].abs() * size_max).clip(upper=size_max).round()
                pnl = np.sign(df["l1_obi"][mask]) * fwd[mask] * size[mask]
                pnl = pnl.dropna()
                tot += float(pnl.sum())
                n_signals += int(mask.sum())
            capture[f"size_max_{size_max}"] = {
                "total_3d_mid_tick_points": float(tot),
                "n_signals_3d": int(n_signals),
            }
        out[sym] = {
            "per_day_stats": per_day_stats,
            "per_day_obi_drift": per_day_obi,
            "obi_skew_capture_upper_bound": capture,
        }
    return out


# -------------------- 3. Time-of-day patterns --------------------
def intraday_patterns(prices_dict: dict[str, dict[int, pd.DataFrame]]) -> dict:
    """For each asset and each day-quarter, compute OBI tier 1 H=1 Sharpe."""
    out = {}
    for sym, prices in prices_dict.items():
        per_quarter = {}
        for q, (lo, hi) in enumerate([(0, 250000), (250000, 500000),
                                       (500000, 750000), (750000, 1000000)]):
            sharpes = []
            means = []
            n_per_day = []
            for d, df in prices.items():
                df = add_features(df)
                m = (df["timestamp"] >= lo) & (df["timestamp"] < hi)
                sub = df[m].copy()
                if len(sub) < 100:
                    continue
                fwd = sub["mid"].shift(-1) - sub["mid"]
                # signed payoff = sign(OBI) * fwd
                strong = sub["l1_obi"].abs() > 0.05
                pnl = (np.sign(sub["l1_obi"]) * fwd)[strong].dropna()
                n_per_day.append(int(len(pnl)))
                if len(pnl) > 5 and pnl.std() > 0:
                    sharpes.append(float(pnl.mean() / pnl.std()))
                    means.append(float(pnl.mean()))
            per_quarter[f"q{q}"] = {
                "mean_sharpe_per_sig": float(np.mean(sharpes)) if sharpes else 0.0,
                "mean_pnl_per_sig": float(np.mean(means)) if means else 0.0,
                "n_signals_per_day": n_per_day,
            }
        out[sym] = per_quarter
    return out


# -------------------- 4. Spread-condition gating --------------------
def spread_gating(prices: dict[int, pd.DataFrame], sym: str) -> dict:
    out = {"per_spread_obi_drift": {}, "per_spread_revz_drift": {}}
    spread_buckets = [(0, 8), (8, 14), (14, 18), (18, 30)]
    for d, df in prices.items():
        df = add_features(df)
        fwd = df["mid"].shift(-1) - df["mid"]
        for lo, hi in spread_buckets:
            m = (df["spread"] >= lo) & (df["spread"] < hi)
            if m.sum() < 50:
                continue
            sub_obi = df["l1_obi"][m]
            sub_fwd = fwd[m]
            strong = sub_obi.abs() > 0.05
            pnl = (np.sign(sub_obi) * sub_fwd)[strong].dropna()
            key = f"day{d}_spread_{lo}_{hi}"
            if len(pnl) > 5 and pnl.std() > 0:
                out["per_spread_obi_drift"][key] = {
                    "n": int(len(pnl)),
                    "mean_pnl": float(pnl.mean()),
                    "sharpe": float(pnl.mean() / pnl.std()),
                }
    return out


# -------------------- 5. Inventory autocorrelation (proxy via flow) --------------------
def signed_flow_autocorr(trades: dict[int, pd.DataFrame], sym: str) -> dict:
    """Use trade-direction proxy (price vs prior mid) and compute autocorr at lags."""
    out = {}
    for d, df in trades.items():
        if len(df) < 50:
            continue
        # Use simple signed quantity sequence: alternating implies stable, persistent implies flow
        # We approximate by sign of price-change
        prices = df["price"].astype(float).values
        if len(prices) < 50:
            continue
        diffs = np.diff(prices)
        signs = np.sign(diffs)
        # Autocorr of signs at lags 1, 5, 20
        ac = {}
        for L in (1, 5, 20):
            if len(signs) > L + 5:
                a = signs[:-L]
                b = signs[L:]
                if a.std() > 0 and b.std() > 0:
                    ac[f"lag{L}"] = float(np.corrcoef(a, b)[0, 1])
                else:
                    ac[f"lag{L}"] = 0.0
        out[f"day{d}"] = {"n_trades": int(len(df)), "autocorr": ac}
    return out


# -------------------- 7. Cross-strike vert-spread MR replay --------------------
def bs_call(S: float, K: float, sigma: float, T: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    N = NormalDist().cdf
    return S * N(d1) - K * N(d2)


def smile_iv(K: float, S: float) -> float:
    if S <= 0:
        return SMILE_A
    m = math.log(K / S)
    return SMILE_A + SMILE_B * m + SMILE_C * m * m


def smile_fair(K: float, S: float) -> float:
    iv = max(0.05, smile_iv(K, S))
    return bs_call(S, K, iv, SMILE_T)


def cross_strike_replay(low_sym: str, high_sym: str, target_size: int,
                         k_sigma: float = 2.0, hold_ticks: int = 30) -> dict:
    """Simulate Rothschild-style entry/exit on the 5300/5400 (or other) vert
    using mid prices. Strict: per-day non-overlapping, count round-trip PnL
    realized at exit (mid-to-mid)."""
    out = {"per_day": {}, "agg": {}}
    Klow = STRIKES[low_sym]
    Khigh = STRIKES[high_sym]

    total_pnl = 0.0
    total_trades = 0
    daily_pnls = []
    for d in DAYS:
        df_low_full = pd.read_parquet(DATA / f"prices_round_3_day_{d}.parquet")
        df_low = df_low_full[df_low_full["product"] == low_sym].sort_values("timestamp").reset_index(drop=True)
        df_high = df_low_full[df_low_full["product"] == high_sym].sort_values("timestamp").reset_index(drop=True)
        df_velvet = df_low_full[df_low_full["product"] == "VELVETFRUIT_EXTRACT"].sort_values("timestamp").reset_index(drop=True)

        # Align on timestamp
        merged = df_low[["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].rename(
            columns={"mid_price": "mid_low", "bid_price_1": "bid_low", "ask_price_1": "ask_low"})
        merged = merged.merge(
            df_high[["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].rename(
                columns={"mid_price": "mid_high", "bid_price_1": "bid_high", "ask_price_1": "ask_high"}),
            on="timestamp", how="inner")
        merged = merged.merge(
            df_velvet[["timestamp", "mid_price"]].rename(columns={"mid_price": "S"}),
            on="timestamp", how="inner")

        # Compute dev = market_spread - theo_spread
        merged["mkt_spread"] = merged["mid_low"] - merged["mid_high"]
        merged["theo_spread"] = merged.apply(
            lambda r: smile_fair(Klow, r["S"]) - smile_fair(Khigh, r["S"]), axis=1)
        merged["dev"] = merged["mkt_spread"] - merged["theo_spread"]
        # EWMA std (simulate live)
        ew_mean = merged["dev"].ewm(alpha=0.01, adjust=False).mean()
        ew_var = ((merged["dev"] - ew_mean) ** 2).ewm(alpha=0.02, adjust=False).mean()
        merged["dev_std"] = ew_var.clip(lower=0.25) ** 0.5
        merged["z"] = (merged["dev"] - ew_mean) / merged["dev_std"]

        # Strict: simulate sequentially with hold_ticks bar
        position = 0  # +N = long spread (long low, short high), -N = short spread
        entry_idx = -10**9
        entry_mkt_spread = 0.0
        day_pnl = 0.0
        trades = 0
        # Skip warmup of 200 ticks for EWMA
        for i, row in merged.iloc[200:].reset_index(drop=True).iterrows():
            real_i = i + 200
            if position == 0:
                if row["z"] > k_sigma:
                    # spread rich -> SHORT spread (sell low, buy high)
                    position = -target_size
                    entry_idx = real_i
                    entry_mkt_spread = row["mkt_spread"]
                elif row["z"] < -k_sigma:
                    position = +target_size
                    entry_idx = real_i
                    entry_mkt_spread = row["mkt_spread"]
            else:
                # Exit conditions: z reverts past 0 or hold_ticks elapsed
                if (real_i - entry_idx) >= hold_ticks or \
                   (position > 0 and row["z"] >= 0) or \
                   (position < 0 and row["z"] <= 0):
                    # Realized PnL: long spread profits if mkt_spread went up
                    # short spread profits if mkt_spread went down
                    pnl = position * (row["mkt_spread"] - entry_mkt_spread)
                    day_pnl += pnl
                    trades += 1
                    position = 0

        out["per_day"][f"day{d}"] = {
            "pnl": float(day_pnl),
            "trades": int(trades),
            "mean_per_trade": float(day_pnl / trades) if trades else 0.0,
        }
        total_pnl += day_pnl
        total_trades += trades
        daily_pnls.append(day_pnl)

    out["agg"] = {
        "total_3d_pnl": float(total_pnl),
        "mean_per_day": float(np.mean(daily_pnls)),
        "std_per_day": float(np.std(daily_pnls)),
        "total_trades": int(total_trades),
        "all_days_positive": all(p > 0 for p in daily_pnls),
    }
    return out


# -------------------- 8. Quote saturation --------------------
def quote_saturation(prices_dict: dict, trades_dict: dict) -> dict:
    """Compare typical traded volume per asset vs our nominal quote sizes."""
    out = {}
    for sym in PRODUCTS:
        prices = prices_dict[sym]
        trades = trades_dict[sym]
        per_day = {}
        for d in DAYS:
            t = trades[d]
            n_trades = len(t)
            total_vol = float(t["quantity"].sum()) if n_trades else 0.0
            n_ticks = len(prices[d])
            vol_per_tick = total_vol / max(1, n_ticks)
            per_day[f"day{d}"] = {
                "n_trades": int(n_trades),
                "total_vol": float(total_vol),
                "vol_per_tick": float(vol_per_tick),
                "trades_per_tick": float(n_trades / max(1, n_ticks)),
            }
        out[sym] = per_day
    return out


# -------------------- 9. Microprice / stale-quote signals --------------------
def stale_quote_signals(prices_dict: dict) -> dict:
    """Look for ticks where spread widens and check next-tick reversion."""
    out = {}
    for sym in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5000",
                "VEV_5100", "VEV_5200", "VEV_5300"):
        prices = prices_dict[sym]
        per_day = {}
        for d in DAYS:
            df = add_features(prices[d])
            spread_q90 = df["spread"].quantile(0.9)
            wide = df["spread"] >= spread_q90
            fwd = df["mid"].shift(-3) - df["mid"]
            # Compute drift conditional on spread-widening
            wide_pnl = fwd[wide].dropna()
            normal_pnl = fwd[~wide].dropna()
            per_day[f"day{d}"] = {
                "spread_q90": float(spread_q90),
                "n_wide": int(len(wide_pnl)),
                "wide_mean_drift_h3": float(wide_pnl.mean()) if len(wide_pnl) > 5 else 0.0,
                "wide_std": float(wide_pnl.std()) if len(wide_pnl) > 5 else 0.0,
                "normal_mean_drift": float(normal_pnl.mean()),
            }
        out[sym] = per_day
    return out


# -------------------- main --------------------
def main():
    print("Loading data...")
    prices_dict = {sym: load_prices(sym) for sym in PRODUCTS}
    trades_dict = {sym: load_trades(sym) for sym in PRODUCTS}

    result = {}

    print("[1/9] VELVETFRUIT deep dive...")
    result["1_velvet_deep"] = velvet_deep(prices_dict["VELVETFRUIT_EXTRACT"])

    print("[2/9] Deep ITM voucher analysis...")
    result["2_deep_itm"] = deep_itm_analysis(prices_dict["VEV_4000"], prices_dict["VEV_4500"])

    print("[3/9] Time-of-day patterns...")
    result["3_intraday"] = intraday_patterns({
        sym: prices_dict[sym] for sym in
        ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5000", "VEV_5300")
    })

    print("[4/9] Spread-condition gating (HYDROGEL)...")
    result["4_spread_gating_hydrogel"] = spread_gating(prices_dict["HYDROGEL_PACK"], "HYDROGEL_PACK")

    print("[5/9] Signed-flow autocorr (proxy for inventory dynamics)...")
    result["5_flow_autocorr"] = {
        sym: signed_flow_autocorr(trades_dict[sym], sym)
        for sym in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_4000")
    }

    print("[6/9] MAF guidance (recap from R2)...")
    result["6_maf_guidance"] = {
        "r2_uplift_per_eval_xirecs": 1474,
        "r2_winner_mean_pnl": 100116,
        "r2_loser_mean_pnl": 98642,
        "recommended_r3_bid_xirecs": 500,
        "rationale": "R3 quote-fraction uplift mechanic likely identical. "
                     "Bid 500 = ~33% of expected R2 uplift, safe ceiling. "
                     "Submit only if portal supports MAF in R3.",
    }

    print("[7/9] Cross-strike spread MR replay (3-day)...")
    cs_results = {}
    for low, high, sz in [
        ("VEV_5300", "VEV_5400", 40),
        ("VEV_5300", "VEV_5500", 20),
        ("VEV_5200", "VEV_5400", 30),
        ("VEV_5300", "VEV_5400", 100),  # full size variant
    ]:
        key = f"{low}_{high}_size{sz}"
        cs_results[key] = cross_strike_replay(low, high, sz)
    result["7_cross_strike_replay"] = cs_results

    print("[8/9] Quote saturation...")
    result["8_quote_saturation"] = quote_saturation(prices_dict, trades_dict)

    print("[9/9] Stale-quote / wide-spread signals...")
    result["9_stale_quote"] = stale_quote_signals(prices_dict)

    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"Wrote {OUT_JSON}")
    print("Headline:")
    print(f"  VELVET top rev_z signal: {result['1_velvet_deep']['signals']['rev_z_sweep_top10'][0]}")
    print(f"  CS replay 5300/5400 sz=100: total {cs_results['VEV_5300_VEV_5400_size100']['agg']}")


if __name__ == "__main__":
    main()
