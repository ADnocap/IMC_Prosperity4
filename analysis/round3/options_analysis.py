"""R3 VELVETFRUIT_EXTRACT options analysis.

Loads the 3-day R3 prices CSVs, computes per-tick mids/spreads, and runs:
 1. Underlying distribution (range, drift, sigma per tick)
 2. Strike-monotonicity / bull-spread / butterfly arbitrages
 3. Implied volatility surface (Black-Scholes solve, vol smile + term shape)
 4. Numerical delta (regression of dC vs dS)
 5. Spread vs option-mid std (MM edge potential)
 6. Dead-strike (6000/6500) audit — non-zero quote frequency
 7. PnL upper bound for a static delta-hedged short straddle on rich strikes

Writes ALL findings to tmp/r3_options/ as parquet/json + a markdown report at
analysis/round3/options_analysis.md.

Uses the assumption that vouchers expire at end of round (i.e. at the end of
day 2 of R3). Per-tick sigma of the underlying is calibrated at 0.96, and we
have 3*10000 = 30000 ticks of life when the round opens.

Run with:
    py -3.13 analysis/round3/options_analysis.py
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "prosperity4" / "round3"
OUT_DIR = REPO / "tmp" / "r3_options"
REPORT_DIR = REPO / "analysis" / "round3"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

UNDERLYING = "VELVETFRUIT_EXTRACT"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV = {k: f"VEV_{k}" for k in STRIKES}
SIGMA_PER_TICK = 0.96  # calibrated underlying volatility (per tick)
HYDROGEL = "HYDROGEL_PACK"


# ----------------------- Black-Scholes helpers ----------------------- #
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(S: float, K: float, sigma: float, T: float) -> float:
    """Bachelier-style call (arithmetic Brownian, r=0).

    Underlying is a random walk with per-tick std sigma; T is in ticks.
    Bachelier price: C = (S-K) * N(d) + sigma*sqrt(T) * phi(d), d = (S-K)/(sigma*sqrt(T)).
    Why Bachelier: the underlying is an absolute random walk (drift 0, additive
    sigma in price units), not log-normal. Bachelier is the matching model.
    """
    if T <= 0:
        return max(0.0, S - K)
    sd = sigma * math.sqrt(T)
    if sd <= 0:
        return max(0.0, S - K)
    d = (S - K) / sd
    return (S - K) * _norm_cdf(d) + sd * _norm_pdf(d)


def bs_call_delta(S: float, K: float, sigma: float, T: float) -> float:
    if T <= 0:
        return 1.0 if S > K else (0.5 if S == K else 0.0)
    sd = sigma * math.sqrt(T)
    d = (S - K) / sd
    return _norm_cdf(d)


def implied_sigma(price: float, S: float, K: float, T: float) -> float | None:
    """Solve Bachelier for sigma given a market price. Bisection on [1e-6, 50]."""
    if T <= 0 or price < max(0.0, S - K) - 1e-9 or price > S + 1e-6:
        return None
    lo, hi = 1e-6, 50.0
    plo = bs_call(S, K, lo, T) - price
    phi = bs_call(S, K, hi, T) - price
    if plo * phi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        pm = bs_call(S, K, mid, T) - price
        if pm == 0:
            return mid
        if plo * pm < 0:
            hi, phi = mid, pm
        else:
            lo, plo = mid, pm
        if hi - lo < 1e-9:
            break
    return 0.5 * (lo + hi)


# ----------------------- Data loading ----------------------- #
def load_prices() -> pd.DataFrame:
    parts = []
    for d in (0, 1, 2):
        p = DATA_DIR / f"prices_round_3_day_{d}.csv"
        df = pd.read_csv(p, sep=";")
        df["day"] = d
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def pivot_mid(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["t"] = df["day"] * 10000 + df["timestamp"] // 100
    pv = df.pivot_table(index="t", columns="product", values="mid_price", aggfunc="first")
    return pv.sort_index()


def pivot_field(df: pd.DataFrame, field: str) -> pd.DataFrame:
    df = df.copy()
    df["t"] = df["day"] * 10000 + df["timestamp"] // 100
    pv = df.pivot_table(index="t", columns="product", values=field, aggfunc="first")
    return pv.sort_index()


# ----------------------- Analyses ----------------------- #
def underlying_stats(mid: pd.DataFrame) -> dict:
    s = mid[UNDERLYING].dropna()
    diffs = s.diff().dropna()
    out = {
        "n_ticks": int(len(s)),
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
        "std": float(s.std()),
        "tick_sigma_obs": float(diffs.std()),
        "tick_drift_obs": float(diffs.mean()),
        "p01": float(s.quantile(0.01)),
        "p50": float(s.quantile(0.5)),
        "p99": float(s.quantile(0.99)),
    }
    crossings = {}
    for k in STRIKES:
        crossings[k] = {
            "frac_above": float((s > k).mean()),
            "frac_below": float((s < k).mean()),
            "ever_above": bool((s > k).any()),
            "ever_below": bool((s < k).any()),
        }
    out["strike_crossings"] = crossings
    out["hydrogel_min"] = float(mid[HYDROGEL].min())
    out["hydrogel_max"] = float(mid[HYDROGEL].max())
    out["hydrogel_drift"] = float(mid[HYDROGEL].diff().mean())
    out["hydrogel_sigma"] = float(mid[HYDROGEL].diff().std())
    return out


def strike_arbitrage(bid: pd.DataFrame, ask: pd.DataFrame) -> dict:
    """Detect:
       - Direct strike inversions: best ask of LOW strike < best bid of HIGH strike
         (=> buy lower-K cheap from ask, sell higher-K rich at its bid; bull-spread free money)
       - Negative-cost bull spreads in mids
       - Negative-cost butterflies in mids
    """
    rows = []
    sks = STRIKES
    inv_count = 0
    inv_edge_total = 0.0
    inv_examples = []
    for i, k1 in enumerate(sks):
        for k2 in sks[i + 1 :]:
            a, b = VEV[k1], VEV[k2]
            if a not in ask.columns or b not in bid.columns:
                continue
            la, lb = ask[a], bid[b]  # ask of k1, bid of k2
            mask = la.notna() & lb.notna() & (la < lb)
            n = int(mask.sum())
            if n > 0:
                edge = float((lb[mask] - la[mask]).sum())
                inv_count += n
                inv_edge_total += edge
                # take a few examples
                idxs = list(mask[mask].index[:3])
                for tt in idxs:
                    inv_examples.append({
                        "t": int(tt), "k_long": k1, "k_short": k2,
                        "ask_long": float(la[tt]), "bid_short": float(lb[tt]),
                        "edge_per_unit": float(lb[tt] - la[tt]),
                    })
            rows.append({"k_long": k1, "k_short": k2, "n_inversions": n})

    # Mid-based bull spreads (educational, not directly tradeable) — but tells us
    # if the QUOTED MIDS are non-monotone.
    return {
        "inversion_pairs": rows,
        "total_inversion_ticks": inv_count,
        "total_inversion_edge_xirec": inv_edge_total,
        "examples": inv_examples,
    }


def butterflies(mid: pd.DataFrame) -> dict:
    """Butterfly: long C(K-h), short 2*C(K), long C(K+h). Convexity demands
    the COST be non-negative. If mid butterfly cost is negative, the mid quote
    structure is wrong.

    We look at each consecutive triple of strikes that are equally spaced.
    """
    out = []
    for i in range(1, len(STRIKES) - 1):
        kl, kc, kr = STRIKES[i - 1], STRIKES[i], STRIKES[i + 1]
        if kc - kl != kr - kc:
            continue
        cl = mid.get(VEV[kl])
        cc = mid.get(VEV[kc])
        cr = mid.get(VEV[kr])
        if cl is None or cc is None or cr is None:
            continue
        cost = cl + cr - 2 * cc
        cost = cost.dropna()
        out.append({
            "kl": kl, "kc": kc, "kr": kr,
            "n": int(len(cost)),
            "min_cost": float(cost.min()),
            "mean_cost": float(cost.mean()),
            "frac_negative": float((cost < 0).mean()),
            "frac_below_minus_0p5": float((cost < -0.5).mean()),
        })
    return {"butterflies": out}


def imp_vol_surface(mid: pd.DataFrame) -> dict:
    """For each strike, compute IV per tick assuming the round started at t=0
    and expires at t=30000 (end of day 2). T_remaining = 30000 - t.

    Returns per-strike mean IV and the avg residual (option mid − model price
    at sigma=0.96).
    """
    s_und = mid[UNDERLYING].astype(float)
    rows = []
    res_arrays = {}
    for k in STRIKES:
        col = VEV[k]
        if col not in mid.columns:
            continue
        c = mid[col].astype(float)
        joint = pd.concat([s_und, c], axis=1, keys=["S", "C"]).dropna()
        if joint.empty:
            continue
        ts = joint.index.to_numpy()
        T_rem = 30000 - ts  # ticks remaining
        ivs = []
        residuals = []  # market - model(sigma=0.96)
        intrinsic_residual = []  # market - intrinsic
        for ti, sv, cv in zip(T_rem, joint["S"].to_numpy(), joint["C"].to_numpy()):
            iv = implied_sigma(cv, sv, k, max(1, ti))
            ivs.append(iv if iv is not None else np.nan)
            mod = bs_call(sv, k, SIGMA_PER_TICK, max(1, ti))
            residuals.append(cv - mod)
            intrinsic_residual.append(cv - max(0.0, sv - k))
        ivs = np.array(ivs, dtype=float)
        residuals = np.array(residuals, dtype=float)
        intr_r = np.array(intrinsic_residual, dtype=float)
        res_arrays[k] = residuals
        rows.append({
            "strike": k,
            "n": int(len(ivs)),
            "iv_mean": float(np.nanmean(ivs)),
            "iv_median": float(np.nanmedian(ivs)),
            "iv_p10": float(np.nanpercentile(ivs, 10)),
            "iv_p90": float(np.nanpercentile(ivs, 90)),
            "vs_model_mean_residual": float(np.nanmean(residuals)),
            "vs_model_residual_std": float(np.nanstd(residuals)),
            "vs_intrinsic_mean": float(np.nanmean(intr_r)),
            "vs_intrinsic_min": float(np.nanmin(intr_r)),  # negative => option < intrinsic, free $
            "model_price_at_mean_S": float(bs_call(float(s_und.mean()), k, SIGMA_PER_TICK, 30000 - 15000)),
            "obs_price_at_mid": float(c.mean()),
        })
    return {"per_strike": rows, "_residuals_keys": list(res_arrays.keys())}


def numerical_delta(mid: pd.DataFrame) -> dict:
    s = mid[UNDERLYING].astype(float)
    ds = s.diff()
    rows = []
    for k in STRIKES:
        col = VEV[k]
        if col not in mid.columns:
            continue
        c = mid[col].astype(float)
        dc = c.diff()
        joint = pd.concat([ds, dc], axis=1, keys=["dS", "dC"]).dropna()
        joint = joint[joint["dS"].abs() > 0]
        if len(joint) < 30:
            continue
        # OLS: dC = beta * dS
        x = joint["dS"].to_numpy()
        y = joint["dC"].to_numpy()
        beta = float((x @ y) / (x @ x))
        resid = y - beta * x
        # naive r-squared
        ss_tot = float(((y - y.mean()) ** 2).sum())
        ss_res = float((resid ** 2).sum())
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        # bs delta at mean S, mid-of-round T=15000
        bs_d = bs_call_delta(float(s.mean()), k, SIGMA_PER_TICK, 15000)
        rows.append({
            "strike": k,
            "n_obs": int(len(joint)),
            "delta_regressed": beta,
            "delta_bs_at_meanS_midT": float(bs_d),
            "r2": r2,
        })
    return {"per_strike": rows}


def spread_vs_volatility(mid: pd.DataFrame, bid: pd.DataFrame, ask: pd.DataFrame) -> dict:
    rows = []
    for k in STRIKES:
        col = VEV[k]
        if col not in mid.columns:
            continue
        b = bid[col].astype(float)
        a = ask[col].astype(float)
        spr = (a - b)
        sd = mid[col].diff().std()
        rows.append({
            "strike": k,
            "n": int(spr.notna().sum()),
            "spread_mean": float(spr.mean()),
            "spread_median": float(spr.median()),
            "spread_p90": float(spr.quantile(0.9)),
            "mid_per_tick_std": float(sd),
            "mid_total_std": float(mid[col].std()),
            "mean_mid": float(mid[col].mean()),
            "bid_zero_frac": float((b == 0).mean()),
            "spread_one_frac": float((spr == 1).mean()),
        })
    return {"per_strike": rows}


def dead_strike_audit(mid: pd.DataFrame, bid: pd.DataFrame, ask: pd.DataFrame) -> dict:
    out = {}
    for k in (6000, 6500):
        col = VEV[k]
        if col not in mid.columns:
            continue
        b = bid[col]
        a = ask[col]
        info = {
            "n": int(b.notna().sum()),
            "bid_unique": [float(x) for x in sorted(b.dropna().unique())[:20]],
            "ask_unique": [float(x) for x in sorted(a.dropna().unique())[:20]],
            "max_bid": float(b.max()),
            "max_ask": float(a.max()),
            "frac_bid_gt_0": float((b > 0).mean()),
            "frac_ask_gt_1": float((a > 1).mean()),
            "frac_bid_gt_1": float((b > 1).mean()),
        }
        out[col] = info
    return out


def rich_strike_quote_short_pnl(mid: pd.DataFrame, sigma_per_tick: float) -> dict:
    """For each strike, suppose we sell the option mid and buy back at expiry
    intrinsic value, hedged delta-flat at constant delta = bs_delta(meanS, K, T_mid).

    PnL_per_unit = mid_short - intrinsic_at_expiry + delta * (S_expiry - S_now)
    With delta hedge at every tick we get pure vega/theta extraction.

    We do a static (non-rebalanced) approximation. Returns approximate edge per
    sold contract over the 3 days using observed underlying path and assuming we
    held to expiry T=30000.

    Caveat: this is rough. It mostly serves to flag richness magnitude.
    """
    s = mid[UNDERLYING].dropna()
    s_first, s_last = float(s.iloc[0]), float(s.iloc[-1])
    rows = []
    for k in STRIKES:
        col = VEV[k]
        if col not in mid.columns:
            continue
        c = mid[col].dropna()
        if c.empty:
            continue
        c0 = float(c.iloc[0])
        # model price at start, T=30000 ticks
        mod0 = bs_call(s_first, k, sigma_per_tick, 30000)
        intrinsic_end = max(0.0, s_last - k)
        # Static edge per unit: rich premium captured if we sold and held
        rich_premium = c0 - mod0
        # Pure short with no hedge: pnl = c0 - intrinsic_end
        unhedged_pnl = c0 - intrinsic_end
        # With static delta hedge at delta(S0, K, T=30000):
        d0 = bs_call_delta(s_first, k, sigma_per_tick, 30000)
        hedged_pnl_static = c0 - intrinsic_end + d0 * (s_last - s_first)
        rows.append({
            "strike": k,
            "obs_price_t0": c0,
            "model_price_t0": mod0,
            "rich_premium_t0": rich_premium,
            "delta_t0": d0,
            "intrinsic_at_expiry": intrinsic_end,
            "static_short_pnl_unhedged": unhedged_pnl,
            "static_short_pnl_delta_hedged": hedged_pnl_static,
        })
    return {"per_strike": rows, "S_first": s_first, "S_last": s_last}


# ----------------------- Main ----------------------- #
def main():
    print("Loading R3 prices...")
    df = load_prices()
    print(f"  rows: {len(df)}; products: {df['product'].nunique()}")
    mid = pivot_mid(df)
    bid = pivot_field(df, "bid_price_1")
    ask = pivot_field(df, "ask_price_1")
    print(f"  ticks: {len(mid)}")

    out = {}
    out["underlying"] = underlying_stats(mid)
    out["strike_arbitrage"] = strike_arbitrage(bid, ask)
    out["butterflies"] = butterflies(mid)
    out["iv_surface"] = imp_vol_surface(mid)
    out["delta"] = numerical_delta(mid)
    out["spread_vs_vol"] = spread_vs_volatility(mid, bid, ask)
    out["dead_strikes"] = dead_strike_audit(mid, bid, ask)
    out["short_pnl"] = rich_strike_quote_short_pnl(mid, SIGMA_PER_TICK)

    # Save raw json
    raw_path = OUT_DIR / "options_findings.json"
    with raw_path.open("w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  wrote {raw_path}")

    return out


if __name__ == "__main__":
    main()
