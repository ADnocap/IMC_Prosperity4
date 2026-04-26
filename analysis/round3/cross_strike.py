"""Cross-strike options analysis for R3 VELVETFRUIT_EXTRACT vouchers.

Goal: identify cross-strike structures (butterflies, vertical spreads, risk
reversals) whose combined position is approximately delta-neutral by
construction so we can size up without spot hedge cost.

Inputs: prices_round_3_day_{0,1,2}.csv (semicolon-delimited).
Outputs: cross_strike.md, cross_strike.json
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
OUT = ROOT / "analysis" / "round3"

SPOT = "VELVETFRUIT_EXTRACT"
STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
SYMS = [f"VEV_{k}" for k in STRIKES]
T_DAYS = 6.0
T = T_DAYS / 365.0
N = NormalDist().cdf
PDF = NormalDist().pdf


def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * N(d1) - K * N(d2)


def bs_vega(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return S * PDF(d1) * math.sqrt(T)


def bs_delta(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return N(d1)


def bs_theta(S, K, T, sigma):
    """Theta per unit time (years). Daily theta = bs_theta / 365."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return -(S * PDF(d1) * sigma) / (2.0 * math.sqrt(T))


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


def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
    wide = df.pivot_table(index="timestamp", columns="product",
                          values="mid_price", aggfunc="mean").sort_index()
    return wide


def fit_smile(wide: pd.DataFrame, T_use: float) -> tuple:
    rows = []
    for t, row in wide.iterrows():
        S = row.get(SPOT)
        if pd.isna(S):
            continue
        sqrtT = math.sqrt(T_use)
        for sym, K in zip(SYMS, STRIKES):
            C = row.get(sym)
            if pd.isna(C):
                continue
            iv = iv_newton(C, S, K, T_use)
            if iv is None:
                continue
            m = math.log(K / S) / sqrtT
            rows.append({"t": t, "sym": sym, "S": S, "K": K, "C": C, "m": m, "iv": iv})
    iv_df = pd.DataFrame(rows)
    if len(iv_df) < 30:
        return None, iv_df
    m_arr = iv_df["m"].values
    iv_arr = iv_df["iv"].values
    X = np.column_stack([np.ones_like(m_arr), m_arr, m_arr * m_arr])
    coefs, *_ = np.linalg.lstsq(X, iv_arr, rcond=None)
    a, b, c = coefs
    pred = a + b * m_arr + c * m_arr * m_arr
    resid = iv_arr - pred
    return (float(a), float(b), float(c), float(resid.std())), iv_df


def smile_iv(a, b, c, S, K, T_use):
    m = math.log(K / S) / math.sqrt(T_use)
    iv = a + b * m + c * m * m
    return max(iv, 0.05)


def smile_call(a, b, c, S, K, T_use):
    iv = smile_iv(a, b, c, S, K, T_use)
    return bs_call(S, K, T_use, iv)


def half_life(series: np.ndarray) -> float:
    """AR(1) half-life: x_{t+1} = phi*x_t. HL = -ln(2)/ln(phi). Returns NaN if no MR."""
    s = pd.Series(series).dropna().values
    if len(s) < 50:
        return float("nan")
    x = s[:-1]
    y = s[1:]
    if x.var() < 1e-12:
        return float("nan")
    phi = float(np.cov(x, y, ddof=0)[0, 1] / x.var())
    if phi <= 0 or phi >= 1:
        return float("nan")
    return -math.log(2) / math.log(phi)


def main():
    print("Loading days 0,1,2...")
    days = {d: load_day(d) for d in (0, 1, 2)}
    # Combine all 3 days for pooled stats; tag day for stability checks
    parts = []
    for d, w in days.items():
        w = w.copy()
        w["day"] = d
        parts.append(w)
    all_wide = pd.concat(parts).reset_index()  # keeps timestamp as a col

    out = {}

    # ----- Q4: Per-day smile fit (stability check) -----
    print("\n== Q4: Per-day smile fit ==")
    per_day_smile = {}
    for d in (0, 1, 2):
        coefs, _ = fit_smile(days[d], T)
        if coefs is None:
            continue
        a, b, c, rs = coefs
        per_day_smile[d] = {"a": a, "b": b, "c": c, "resid_std": rs}
        print(f"  day {d}: a={a:.4f} b={b:.4f} c={c:.4f} resid_std={rs:.4f}")
    out["per_day_smile"] = per_day_smile
    # Pooled smile (all 3 days) — used as the "static fair smile"
    pooled_coefs, pooled_iv_df = fit_smile(pd.concat([days[d] for d in (0, 1, 2)]), T)
    a_p, b_p, c_p, rs_p = pooled_coefs
    out["pooled_smile"] = {"a": a_p, "b": b_p, "c": c_p, "resid_std": rs_p}
    print(f"  pooled: a={a_p:.4f} b={b_p:.4f} c={c_p:.4f} resid_std={rs_p:.4f}")

    # ----- Q1: Butterfly arbitrage check -----
    print("\n== Q1: Butterfly arbitrage check ==")
    bf_results = []
    triples = [(5000, 5100, 5200), (5100, 5200, 5300), (5200, 5300, 5400),
               (5300, 5400, 5500)]
    for k1, k2, k3 in triples:
        s1, s2, s3 = f"VEV_{k1}", f"VEV_{k2}", f"VEV_{k3}"
        # Compute butterfly mid per day
        all_neg_count = 0
        all_total = 0
        all_bf_means = []
        all_bf_stds = []
        per_day = {}
        for d in (0, 1, 2):
            w = days[d]
            sub = w[[s1, s2, s3, SPOT]].dropna()
            bf = sub[s1] - 2 * sub[s2] + sub[s3]
            # Theoretical butterfly under pooled smile
            theo = sub[SPOT].apply(lambda S: smile_call(a_p, b_p, c_p, S, k1, T)
                                   - 2 * smile_call(a_p, b_p, c_p, S, k2, T)
                                   + smile_call(a_p, b_p, c_p, S, k3, T))
            dev = bf.values - theo.values
            n_neg = int((bf < 0).sum())
            per_day[d] = {
                "n": int(len(bf)),
                "bf_mean": float(bf.mean()),
                "bf_std": float(bf.std()),
                "bf_min": float(bf.min()),
                "n_neg": n_neg,
                "theo_mean": float(theo.mean()),
                "dev_mean": float(dev.mean()),
                "dev_std": float(dev.std()),
            }
            all_neg_count += n_neg
            all_total += len(bf)
            all_bf_means.append(bf.mean())
            all_bf_stds.append(bf.std())
        bf_results.append({
            "triple": [k1, k2, k3],
            "per_day": per_day,
            "pooled_bf_mean": float(np.mean(all_bf_means)),
            "pooled_bf_std": float(np.mean(all_bf_stds)),
            "n_neg_total": all_neg_count,
            "n_total": all_total,
        })
        print(f"  {k1}/{k2}/{k3}: bf_mean={np.mean(all_bf_means):.2f} "
              f"bf_std={np.mean(all_bf_stds):.2f} "
              f"n_neg={all_neg_count}/{all_total} "
              f"day0_dev={per_day[0]['dev_mean']:+.2f}±{per_day[0]['dev_std']:.2f} "
              f"day2_dev={per_day[2]['dev_mean']:+.2f}±{per_day[2]['dev_std']:.2f}")
    out["butterflies"] = bf_results

    # ----- Q2: Risk reversal / vertical spread deviations -----
    print("\n== Q2: Vertical-spread deviation series ==")
    rr_results = []
    pairs = [(5100, 5300), (5100, 5400), (5200, 5300), (5200, 5400),
             (5300, 5400), (5300, 5500), (5200, 5500), (5100, 5500),
             (5000, 5500)]
    for klow, khigh in pairs:
        slow, shigh = f"VEV_{klow}", f"VEV_{khigh}"
        per_day = {}
        all_dev = []
        all_dev_per_day_mean = []
        all_dev_per_day_std = []
        all_hl = []
        for d in (0, 1, 2):
            w = days[d]
            sub = w[[slow, shigh, SPOT]].dropna()
            mkt = (sub[slow] - sub[shigh]).values
            theo = sub[SPOT].apply(
                lambda S: smile_call(a_p, b_p, c_p, S, klow, T)
                - smile_call(a_p, b_p, c_p, S, khigh, T)
            ).values
            dev = mkt - theo
            hl = half_life(dev)
            per_day[d] = {
                "n": int(len(dev)),
                "mkt_mean": float(mkt.mean()),
                "theo_mean": float(theo.mean()),
                "dev_mean": float(dev.mean()),
                "dev_std": float(dev.std()),
                "half_life": float(hl) if not math.isnan(hl) else None,
            }
            all_dev.append(dev)
            all_dev_per_day_mean.append(dev.mean())
            all_dev_per_day_std.append(dev.std())
            if not math.isnan(hl):
                all_hl.append(hl)
        # Sharpe of trade-the-deviation: assume we trade when |dev| > 1 std,
        # capture (dev) per round-trip. Daily reversion → daily Sharpe.
        # Quick proxy: signal = -dev/dev.std; PnL per tick ≈ -dev * (next dev change).
        # Use the simplest: how big is signal-to-noise = mean(|dev|)/std(dev)
        full_dev = np.concatenate(all_dev)
        snr = float(np.mean(np.abs(full_dev)) / (np.std(full_dev) + 1e-9))
        # Estimate Sharpe of mean-reversion: an OU PnL ~ (dev**2)/HL per timeframe
        pooled_hl = float(np.mean(all_hl)) if all_hl else float("nan")
        # If HL exists, expected PnL per tick from holding -dev = dev**2 / (2*HL)
        if not math.isnan(pooled_hl) and pooled_hl > 0:
            mean_dev2 = float(np.mean(full_dev ** 2))
            ev_per_tick = mean_dev2 / (2 * pooled_hl)
            # Daily PnL ≈ ev_per_tick * 10000
            ev_per_day = ev_per_tick * 10000
            # Variance ≈ var(dev**2 - mean_dev2) per tick (very approximate)
            var_per_tick = float(np.var(full_dev ** 2)) / (4 * pooled_hl ** 2)
            daily_sharpe = ev_per_day / (math.sqrt(var_per_tick * 10000) + 1e-9)
        else:
            ev_per_day = float("nan")
            daily_sharpe = float("nan")
        rr_results.append({
            "pair": [klow, khigh],
            "per_day": per_day,
            "pooled_dev_mean": float(np.mean(all_dev_per_day_mean)),
            "pooled_dev_std": float(np.mean(all_dev_per_day_std)),
            "pooled_half_life": pooled_hl,
            "snr": snr,
            "ev_per_day_mr": ev_per_day,
            "daily_sharpe_mr": daily_sharpe,
        })
        print(f"  {klow}/{khigh}: dev_mean={np.mean(all_dev_per_day_mean):+.2f} "
              f"dev_std={np.mean(all_dev_per_day_std):.2f} HL={pooled_hl:.0f} "
              f"snr={snr:.2f} ev/day={ev_per_day:.0f} sharpe={daily_sharpe:.2f}")
    out["vertical_spreads"] = rr_results

    # ----- Q3: Vertical spread theta carry -----
    print("\n== Q3: Vertical-spread theta carry ==")
    theta_results = []
    short_long_pairs = [(5300, 5400), (5200, 5300), (5400, 5500), (5300, 5500)]
    for kshort, klong in short_long_pairs:
        sshort, slong = f"VEV_{kshort}", f"VEV_{klong}"
        per_day_credit = []
        per_day_theta = []
        for d in (0, 1, 2):
            w = days[d]
            sub = w[[sshort, slong, SPOT]].dropna()
            credit = (sub[sshort] - sub[slong]).mean()
            S_mean = sub[SPOT].mean()
            iv_short = smile_iv(a_p, b_p, c_p, S_mean, kshort, T)
            iv_long = smile_iv(a_p, b_p, c_p, S_mean, klong, T)
            theta_short = bs_theta(S_mean, kshort, T, iv_short)
            theta_long = bs_theta(S_mean, klong, T, iv_long)
            # We are short kshort, long klong. PnL/year = -theta_short + theta_long.
            # But theta is negative (option decays), so being short captures that.
            net_theta_year = -theta_short + theta_long
            net_theta_day = net_theta_year / 365.0
            per_day_credit.append(float(credit))
            per_day_theta.append(float(net_theta_day))
        avg_credit = float(np.mean(per_day_credit))
        avg_theta = float(np.mean(per_day_theta))
        theta_results.append({
            "pair_short_long": [kshort, klong],
            "credit_avg": avg_credit,
            "daily_theta_per_unit": avg_theta,
            "ev_per_round_at_pos300_to_expiry": avg_credit * 300,
            "ev_per_3_days_at_pos300_decay": avg_theta * 3 * 300,
        })
        print(f"  short {kshort}/long {klong}: credit={avg_credit:.2f} "
              f"theta_day={avg_theta:.3f} "
              f"ev_pos300_3d={avg_theta*3*300:.0f} "
              f"ev_pos300_expiry={avg_credit*300:.0f}")
    out["theta_spreads"] = theta_results

    # ----- Q5: Rolling smile slope b(t) -----
    print("\n== Q5: Rolling smile slope b(t) ==")
    # Per-day windowed fit with 1000-tick windows
    bt_series_all = []
    for d in (0, 1, 2):
        w = days[d].copy().reset_index()
        # Build per-tick (m, iv) rows
        rows = []
        for _, r in w.iterrows():
            S = r.get(SPOT)
            if pd.isna(S):
                continue
            sqrtT = math.sqrt(T)
            for sym, K in zip(SYMS, STRIKES):
                C = r.get(sym)
                if pd.isna(C):
                    continue
                iv = iv_newton(C, S, K, T)
                if iv is None:
                    continue
                m = math.log(K / S) / sqrtT
                rows.append({"t": r["timestamp"], "m": m, "iv": iv})
        ivd = pd.DataFrame(rows)
        # 1000-tick windows: 100 ticks/sample × 10 = 1000... but timestamp increments are 100,
        # so 1000 ticks = 100k timestamps. Use 10 windows per day.
        ivd["window"] = (ivd["t"] // 100_000).astype(int)
        for w_id, g in ivd.groupby("window"):
            if len(g) < 30:
                continue
            mm = g["m"].values
            vv = g["iv"].values
            X = np.column_stack([np.ones_like(mm), mm, mm * mm])
            cc, *_ = np.linalg.lstsq(X, vv, rcond=None)
            bt_series_all.append({"day": d, "window": int(w_id),
                                  "a": float(cc[0]), "b": float(cc[1]), "c": float(cc[2])})
    bt_df = pd.DataFrame(bt_series_all)
    b_mean = float(bt_df["b"].mean())
    b_std = float(bt_df["b"].std())
    hl_b = half_life(bt_df["b"].values)
    print(f"  b mean={b_mean:.4f} std={b_std:.4f} HL_windows={hl_b:.2f}")
    print(f"  c mean={bt_df['c'].mean():.4f} std={bt_df['c'].std():.4f}")
    out["smile_slope_dynamics"] = {
        "b_mean": b_mean, "b_std": b_std, "b_half_life_windows": float(hl_b) if not math.isnan(hl_b) else None,
        "c_mean": float(bt_df["c"].mean()), "c_std": float(bt_df["c"].std()),
        "n_windows": int(len(bt_df)),
    }

    # ----- Q6: Vega-neutral pair -----
    print("\n== Q6: Vega-neutral delta-neutral pair ==")
    # Compute average vega and delta per strike under pooled smile
    S_mean_all = pd.concat([days[d][SPOT] for d in (0, 1, 2)]).dropna().mean()
    greeks = {}
    for sym, K in zip(SYMS, STRIKES):
        iv = smile_iv(a_p, b_p, c_p, S_mean_all, K, T)
        delta = bs_delta(S_mean_all, K, T, iv)
        vega = bs_vega(S_mean_all, K, T, iv)
        greeks[sym] = {"K": K, "iv": iv, "delta": delta, "vega": vega}
        print(f"  {sym}: iv={iv:.3f} delta={delta:.3f} vega={vega:.2f}")
    out["greeks_at_S_mean"] = greeks

    # ----- Q7: Static rich list -----
    print("\n== Q7: Static rich list ==")
    rich = []
    for sym, K in zip(SYMS, STRIKES):
        residuals = []
        for d in (0, 1, 2):
            w = days[d]
            sub = w[[sym, SPOT]].dropna()
            theo = sub[SPOT].apply(lambda S: smile_call(a_p, b_p, c_p, S, K, T))
            res = sub[sym].values - theo.values
            residuals.append(res)
        full = np.concatenate(residuals)
        mean_res = float(full.mean())
        std_res = float(full.std())
        z = mean_res / (std_res + 1e-9)
        rich.append({"sym": sym, "K": K, "mean_residual": mean_res,
                     "std_residual": std_res, "z_richness": z})
        print(f"  {sym}: mean_res={mean_res:+.3f} std={std_res:.3f} z={z:+.2f}")
    out["rich_list"] = rich

    # ----- Q8: Cross-strike OBI signal -----
    print("\n== Q8: Cross-strike OBI signal ==")
    # OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol) at top of book
    # Need bid_volume_1, ask_volume_1 per strike per tick
    obi_results = []
    for klow, khigh in [(5300, 5400), (5200, 5300), (5200, 5400)]:
        slow, shigh = f"VEV_{klow}", f"VEV_{khigh}"
        # Build per-day OBI series and call-spread changes
        per_day_corr = []
        per_day_cond_drift = []
        for d in (0, 1, 2):
            df = pd.read_csv(DATA / f"prices_round_3_day_{d}.csv", sep=";")
            sub_low = df[df["product"] == slow].set_index("timestamp")
            sub_high = df[df["product"] == shigh].set_index("timestamp")
            # OBI
            obi_low = (sub_low["bid_volume_1"] - sub_low["ask_volume_1"]) / \
                      (sub_low["bid_volume_1"] + sub_low["ask_volume_1"]).replace(0, np.nan)
            obi_high = (sub_high["bid_volume_1"] - sub_high["ask_volume_1"]) / \
                       (sub_high["bid_volume_1"] + sub_high["ask_volume_1"]).replace(0, np.nan)
            spread = sub_low["mid_price"] - sub_high["mid_price"]
            d_spread = spread.diff().shift(-1)  # next-tick change
            # Combined signal: aggressive buyers at low (obi_low > 0) AND aggressive sellers at high (obi_high < 0)
            combo = obi_low - obi_high
            joined = pd.concat([combo, d_spread], axis=1, keys=["combo", "ds"]).dropna()
            if len(joined) < 50:
                continue
            corr = float(joined["combo"].corr(joined["ds"]))
            # Conditional: when combo > +0.5 (strong asymmetry), what's avg ds?
            cond_pos = joined.loc[joined["combo"] > 0.5, "ds"].mean()
            cond_neg = joined.loc[joined["combo"] < -0.5, "ds"].mean()
            per_day_corr.append(corr)
            per_day_cond_drift.append((float(cond_pos), float(cond_neg)))
        obi_results.append({
            "pair": [klow, khigh],
            "corr_avg": float(np.mean(per_day_corr)) if per_day_corr else None,
            "per_day_corr": per_day_corr,
            "cond_drift_pos_neg_avg": (
                float(np.mean([x[0] for x in per_day_cond_drift])) if per_day_cond_drift else None,
                float(np.mean([x[1] for x in per_day_cond_drift])) if per_day_cond_drift else None,
            ),
        })
        print(f"  {klow}/{khigh}: corr(combo,d_spread)_avg="
              f"{(np.mean(per_day_corr) if per_day_corr else float('nan')):+.4f} "
              f"cond_drift+/-= "
              f"{(np.mean([x[0] for x in per_day_cond_drift])):+.3f}/"
              f"{(np.mean([x[1] for x in per_day_cond_drift])):+.3f}")
    out["cross_strike_obi"] = obi_results

    # ----- Save -----
    (OUT / "cross_strike.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved cross_strike.json")
    return out


if __name__ == "__main__":
    main()
