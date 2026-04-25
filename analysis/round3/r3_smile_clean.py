"""Deeper look: fit the smile using only 'clean' near-ATM vouchers
(VEV_5000..VEV_5500), check per-tick residual dynamics, and compute
theoretical FV for the ITM strikes from the fitted curve.

Also: measures effective bot 'take rate' / depth asymmetry near best quote
to gauge how aggressive MM quoting can be on each voucher.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "prosperity4" / "round3"
OUT = ROOT / "analysis" / "round3"

SPOT = "VELVETFRUIT_EXTRACT"
STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
           "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
           "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
           "VEV_6500": 6500}
CLEAN = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]


def norm_cdf(x): return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
def norm_pdf(x): return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call(S, K, T, sigma):
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


def iv_newton(C, S, K, T, sigma0=0.23, max_iter=80, tol=1e-7):
    intrinsic = max(S - K, 0.0)
    if C < intrinsic - 1e-9 or C <= 0 or T <= 0:
        return None
    sigma = sigma0
    for _ in range(max_iter):
        p = bs_call(S, K, T, sigma)
        v = bs_vega(S, K, T, sigma)
        if v < 1e-9:
            return None
        diff = p - C
        if abs(diff) < tol:
            return sigma
        sigma -= diff / v
        sigma = min(max(sigma, 1e-4), 5.0)
    return sigma if abs(bs_call(S, K, T, sigma) - C) < 1e-3 else None


def main():
    # Use day-2 historical data (closest to R3 conditions: TTE=6 → 5 at final).
    df = pd.read_csv(DATA / "prices_round_3_day_2.csv", sep=";")
    wide = df.pivot_table(index="timestamp", columns="product",
                          values="mid_price", aggfunc="mean").sort_index()

    T = 6 / 365.0  # TTE in years (historical day 2)

    # Build per-tick (moneyness, IV) only for CLEAN strikes
    rows = []
    for t, row in wide.iterrows():
        S = row.get(SPOT)
        if pd.isna(S):
            continue
        for col in CLEAN:
            C = row.get(col)
            if pd.isna(C):
                continue
            K = STRIKES[col]
            iv = iv_newton(C, S, K, T)
            if iv is None:
                continue
            m = math.log(K / S)
            delta = bs_delta(S, K, T, iv)
            rows.append({"t": t, "product": col, "S": S, "K": K, "C": C,
                         "m": m, "iv": iv, "delta": delta})
    iv_df = pd.DataFrame(rows)
    print(f"Clean IV rows: {len(iv_df):,}")
    print("\n=== Per-strike IV stats (clean set) ===")
    per = iv_df.groupby("product")["iv"].agg(["mean", "std", "min", "max"])
    print(per.round(5).to_string())

    # Fit quadratic smile on the clean set
    m = iv_df["m"].values
    iv = iv_df["iv"].values
    X = np.column_stack([np.ones_like(m), m, m * m])
    coefs, *_ = np.linalg.lstsq(X, iv, rcond=None)
    a, b, c = coefs
    pred = a + b * m + c * m * m
    resid = iv - pred
    print(f"\nQuadratic smile: IV = {a:.5f} + {b:.5f}*m + {c:.5f}*m^2")
    print(f"Residual std: {resid.std():.5f}, max |r|: {np.abs(resid).max():.5f}")

    # Cross-sectional IV per tick (how much does the smile fit vary over time?)
    print("\n=== Cross-sectional smile coefs per 1000-tick window ===")
    iv_df["window"] = (iv_df["t"] // 100_000).astype(int)
    for w, sub in iv_df.groupby("window"):
        if len(sub) < 60:
            continue
        mm = sub["m"].values
        vv = sub["iv"].values
        XX = np.column_stack([np.ones_like(mm), mm, mm * mm])
        cc, *_ = np.linalg.lstsq(XX, vv, rcond=None)
        print(f"  window {w}: a={cc[0]:.4f} b={cc[1]:.4f} c={cc[2]:.4f} n={len(sub)}")

    # Apply clean-set smile to estimate theoretical FV for VEV_4000 / VEV_4500
    # (these are deep ITM, so outside moneyness range but we can check fit)
    print("\n=== Theoretical vs observed mid for ITM vouchers ===")
    for col in ("VEV_4000", "VEV_4500"):
        K = STRIKES[col]
        S_mean = wide[SPOT].dropna().mean()
        m0 = math.log(K / S_mean)
        iv0 = a + b * m0 + c * m0 * m0
        iv0 = max(iv0, 0.05)
        theo = bs_call(S_mean, K, T, iv0)
        obs = wide[col].dropna().mean()
        print(f"  {col}: theo={theo:.2f} (using IV={iv0:.3f}), "
              f"obs_mean={obs:.2f}, diff={obs-theo:.2f}")

    # Mean ATM IV (a single scalar suitable for live pricing)
    atm_rows = iv_df.loc[iv_df["product"].isin(["VEV_5100", "VEV_5200", "VEV_5300"])]
    atm_iv = atm_rows["iv"].mean()
    print(f"\nATM IV (VEV_5100..5300 tick average): {atm_iv:.5f}")

    # Save per-strike avg IV + smile coefs for the trader
    out = {
        "atm_iv": float(atm_iv),
        "smile_a": float(a),
        "smile_b": float(b),
        "smile_c": float(c),
        "resid_std": float(resid.std()),
        "per_strike_iv_mean": {p: float(v["mean"])
                               for p, v in per.iterrows()
                               for _ in [()]},
        "T_years_day_2": T,
    }
    import json
    # per_strike_iv_mean comprehension above is goofy; do cleanly
    out["per_strike_iv_mean"] = {p: float(per.loc[p, "mean"]) for p in per.index}
    (OUT / "smile_coefs_day2.json").write_text(json.dumps(out, indent=2))
    print("\nSaved smile coefs -> analysis/round3/smile_coefs_day2.json")

    # Spread + depth asymmetry per voucher (MM edge map)
    print("\n=== MM edge map (spread + top-of-book depth) ===")
    for col in list(STRIKES.keys()) + [SPOT, "HYDROGEL_PACK"]:
        if col not in df["product"].unique():
            continue
        sub = df.loc[df["product"] == col]
        sp = (sub["ask_price_1"] - sub["bid_price_1"])
        bd = sub["bid_volume_1"]
        ad = sub["ask_volume_1"]
        mid = sub["mid_price"]
        # "room": how many ticks we can tighten (spread - 2 means penny-jump both sides)
        room = (sp - 2).clip(lower=0)
        print(f"  {col}: spread_med={sp.median():.0f}  "
              f"pct_spread>=2={100*(sp>=2).mean():.1f}%  "
              f"pct_spread>=3={100*(sp>=3).mean():.1f}%  "
              f"room_mean={room.mean():.2f}  "
              f"mid_mean={mid.mean():.1f}  depth(b/a)={bd.mean():.1f}/{ad.mean():.1f}")


if __name__ == "__main__":
    main()
