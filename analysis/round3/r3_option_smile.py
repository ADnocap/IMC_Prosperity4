"""R3 data analysis — volatility smile + microstructure for VEV vouchers.

Goals:
  1. Per-voucher summary: mid stats, spread, depth, realized vol of mid
  2. Underlying (VELVETFRUIT_EXTRACT) realized vol, correlation with each voucher
  3. Black-Scholes IV inversion per tick per voucher -> smile curve
     (check whether a quadratic fit in log-moneyness explains cross-sectional IV)
  4. Residuals of IV vs fitted smile -> autocorrelation (mean reversion signal?)
  5. HYDROGEL basic stats (random-walk confirmation + spread distribution)

Conventions:
  - 1 round = 1 day. TTE in days from round 1: day 0 = tutorial (TTE=8d),
    day 1 = R1 (TTE=7d), day 2 = R2 (TTE=6d), R3 final = TTE=5d.
  - Historical CSVs data/prosperity4/round3/ are days 0,1,2.
  - 10000 ticks/day at portal final eval; one tick = 100 timestamp units.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "prosperity4" / "round3"
OUT_DIR = ROOT / "analysis" / "round3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VEV_STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000, "VEV_5100": 5100,
    "VEV_5200": 5200, "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
    "VEV_6000": 6000, "VEV_6500": 6500,
}
SPOT = "VELVETFRUIT_EXTRACT"
HYDRO = "HYDROGEL_PACK"


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(S, K, T, sigma):
    """Black-Scholes call (r=0). Returns intrinsic if T or sigma tiny."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def bs_vega(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return S * norm_pdf(d1) * math.sqrt(T)


def bs_delta(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1)


def implied_vol(C, S, K, T, sigma0=0.30, tol=1e-6, max_iter=80):
    """Newton-Raphson IV solver. Returns None if no convergence or undefined."""
    intrinsic = max(S - K, 0.0)
    if C < intrinsic - 1e-9 or C <= 0:
        return None
    sigma = sigma0
    for _ in range(max_iter):
        price = bs_call(S, K, T, sigma)
        vega = bs_vega(S, K, T, sigma)
        if vega < 1e-9:
            return None
        diff = price - C
        if abs(diff) < tol:
            return sigma
        sigma = sigma - diff / vega
        if sigma < 1e-4:
            sigma = 1e-4
        elif sigma > 5.0:
            sigma = 5.0
    return sigma if abs(bs_call(S, K, T, sigma) - C) < 1e-3 else None


def load_prices(days=(0, 1, 2)):
    parts = []
    for d in days:
        f = DATA_DIR / f"prices_round_3_day_{d}.csv"
        df = pd.read_csv(f, sep=";")
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def load_trades(days=(0, 1, 2)):
    parts = []
    for d in days:
        f = DATA_DIR / f"trades_round_3_day_{d}.csv"
        df = pd.read_csv(f, sep=";")
        df["day"] = d
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def asset_summary(df):
    rows = []
    for prod, sub in df.groupby("product"):
        mid = sub["mid_price"].dropna()
        bid = sub["bid_price_1"].dropna()
        ask = sub["ask_price_1"].dropna()
        spread = (ask - bid)
        dmid = mid.diff().dropna()
        rows.append({
            "product": prod,
            "n": len(sub),
            "mid_mean": mid.mean(),
            "mid_std": mid.std(),
            "mid_min": mid.min(),
            "mid_max": mid.max(),
            "spread_mean": spread.mean(),
            "spread_median": spread.median(),
            "tick_vol": dmid.std(),   # sigma per tick
            "bid_depth_top": sub["bid_volume_1"].mean(),
            "ask_depth_top": sub["ask_volume_1"].mean(),
        })
    return pd.DataFrame(rows).set_index("product")


def resample_mids(df, step=100):
    """Pivot to wide mid-price table keyed by (day, timestamp)."""
    df = df.copy()
    df["t"] = df["day"].astype(int) * 1_000_000 + df["timestamp"].astype(int)
    w = df.pivot_table(index="t", columns="product", values="mid_price", aggfunc="mean")
    return w.sort_index()


def smile_per_day(wide, day, tte_days_by_day):
    """For each tick on a given day, compute (moneyness, IV) for each voucher."""
    tte_days = tte_days_by_day[day]
    T_years = tte_days / 365.0  # convention; smile is invariant to unit of T up to rescaling
    # Use a calendar-day scale where 1 tick = 1 / 10000 day.
    # We'll parametrize with tte in *ticks-equivalent*, but since our per-tick sigma
    # is in price units, we can use T expressed in ticks and sigma in per-tick units.
    # To keep things standard, use T in years and compute IV annualised.
    sub = wide.loc[wide.index // 1_000_000 == day]
    rows = []
    strikes = [(k, VEV_STRIKES[k]) for k in VEV_STRIKES]
    for t, row in sub.iterrows():
        S = row.get(SPOT)
        if pd.isna(S):
            continue
        for col, K in strikes:
            C = row.get(col)
            if pd.isna(C):
                continue
            iv = implied_vol(C, S, K, T_years)
            if iv is None:
                continue
            m = math.log(K / S)
            rows.append({"t": t, "day": day, "product": col, "S": S, "K": K,
                         "C": C, "moneyness": m, "iv": iv})
    return pd.DataFrame(rows)


def fit_smile(df_iv):
    """Quadratic fit of IV = a + b*m + c*m^2, returning coefs and residuals."""
    m = df_iv["moneyness"].values
    iv = df_iv["iv"].values
    X = np.column_stack([np.ones_like(m), m, m * m])
    coefs, *_ = np.linalg.lstsq(X, iv, rcond=None)
    pred = X @ coefs
    resid = iv - pred
    return coefs, resid


def autocorr(series, lag=1):
    s = pd.Series(series).dropna()
    if len(s) <= lag:
        return np.nan
    return s.autocorr(lag=lag)


def main():
    px = load_prices()
    print(f"Loaded {len(px):,} price rows across {px['product'].nunique()} products")

    summary = asset_summary(px)
    summary_out = OUT_DIR / "summary_stats.csv"
    summary.to_csv(summary_out)
    print("\n== Per-asset summary ==")
    print(summary.round(3).to_string())

    wide = resample_mids(px)
    print(f"\nPivot shape: {wide.shape} (timesteps x products)")

    # Per-day realized vol of spot
    spot_by_day = {}
    for d in (0, 1, 2):
        sub = wide.loc[wide.index // 1_000_000 == d, SPOT].dropna()
        if len(sub) > 1:
            spot_by_day[d] = sub.diff().dropna().std()
    print(f"\nVELVET tick-sigma by day: {spot_by_day}")

    tte_days_by_day = {0: 8, 1: 7, 2: 6}
    all_iv = []
    for d in (0, 1, 2):
        iv_df = smile_per_day(wide, d, tte_days_by_day)
        print(f"day {d}: {len(iv_df):,} (tick, strike) IV points")
        if len(iv_df):
            coefs, resid = fit_smile(iv_df)
            print(f"  quadratic fit coefs (const, m, m^2): "
                  f"{coefs[0]:.4f}, {coefs[1]:.4f}, {coefs[2]:.4f}")
            print(f"  residual std: {resid.std():.4f}, max |resid|: "
                  f"{np.abs(resid).max():.4f}")
            iv_df["resid"] = resid
            all_iv.append(iv_df)

            # Per-strike IV summary
            print("  per-strike mean IV:")
            per = iv_df.groupby("product")["iv"].agg(["mean", "std", "count"])
            print(per.round(4).to_string())
    if all_iv:
        iv_all = pd.concat(all_iv, ignore_index=True)
        iv_all.to_csv(OUT_DIR / "iv_ticks.csv", index=False)
        print(f"\nSaved {len(iv_all):,} IV rows to analysis/round3/iv_ticks.csv")

        # Residual autocorrelation per strike (mean reversion signal?)
        print("\n== Residual autocorrelation (lag 1, 10, 100) ==")
        for prod in sorted(iv_all["product"].unique()):
            r = iv_all.loc[iv_all["product"] == prod, "resid"]
            print(f"  {prod}: ac1={autocorr(r, 1):.3f}, "
                  f"ac10={autocorr(r, 10):.3f}, ac100={autocorr(r, 100):.3f}, "
                  f"std={r.std():.4f}")

    # Correlation of voucher mid-changes with spot mid-change (delta probe)
    print("\n== Mid-change correlation voucher vs VELVET (per day 2) ==")
    d2 = wide.loc[wide.index // 1_000_000 == 2].diff().dropna()
    if SPOT in d2.columns:
        for col in sorted(VEV_STRIKES.keys()):
            if col in d2.columns:
                corr = d2[col].corr(d2[SPOT])
                # OLS slope of d_voucher on d_spot is empirical delta
                x = d2[SPOT].values
                y = d2[col].values
                mask = ~(np.isnan(x) | np.isnan(y))
                if mask.sum() > 10:
                    slope = np.cov(x[mask], y[mask])[0, 1] / np.var(x[mask])
                else:
                    slope = np.nan
                print(f"  {col}: corr={corr:.3f}  empirical_delta={slope:.3f}")

    # HYDROGEL basic behaviour
    print("\n== HYDROGEL per-day tick-sigma ==")
    for d in (0, 1, 2):
        s = wide.loc[wide.index // 1_000_000 == d, HYDRO].dropna()
        if len(s) > 1:
            dv = s.diff().dropna()
            print(f"  day {d}: sigma={dv.std():.3f}, mean_mid={s.mean():.1f}, "
                  f"drift={dv.mean():.3f}")


if __name__ == "__main__":
    main()
