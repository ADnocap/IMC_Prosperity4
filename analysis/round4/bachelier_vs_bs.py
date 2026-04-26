"""Bachelier vs Black-Scholes smile fit on R3 voucher data.

Goal: settle whether the underlying-is-arithmetic Bachelier model (used in
analysis/round3/options_analysis.py) or the standard log-normal Black-Scholes
(used by Timo/Chris/Carter/Eric in P3) gives tighter smile residuals on the
R3 VEV voucher chain.

Per spec:
  1. Per tick where we have S = mid(VELVETFRUIT_EXTRACT) and all 10 voucher mids,
     invert IV under both models.
  2. Fit a per-tick parabolic smile (3 coefs) in the natural moneyness for each
     model:
       BS:        iv = a + b*m + c*m^2,  m = log(K/S) / sqrt(T_years)   (Timo)
       Bachelier: iv = a + b*m + c*m^2,  m = (K-S) / sqrt(T_ticks)
  3. Compute residual statistics in IV space AND price space (vega-weighted).
  4. Decide whether deep ITM (4000/4500) and deep OTM wings (5500-6500) need
     to be excluded.
  5. Persist coefs + per-strike residuals to JSON.

Outputs:
  analysis/round4/bachelier_vs_bs.json  -- numerical results
  analysis/round4/bachelier_vs_bs.md    -- written separately
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "prosperity4" / "round3"
OUT_DIR = REPO / "analysis" / "round4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNDERLYING = "VELVETFRUIT_EXTRACT"
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV = {k: f"VEV_{k}" for k in STRIKES}

# TTE convention (defensible choice, document in MD):
#   - Round 3 = 3 trading days * 10_000 ticks = 30_000 ticks total horizon.
#   - At round open (day-0 t=0), TTE = 30_000 ticks = 3 / 365 yr.
#   - At any (day, tick) we have T_ticks_remaining = 30_000 - (day*10_000 + tick).
#   - Both R3 days 1-2 of the historical CSV cover days 0,1,2 of a synthetic
#     3-day session. We therefore treat day-d row at timestamp ts as
#         T_ticks = 30_000 - d * 10_000 - ts // 100
#   - Black-Scholes uses T_years = T_ticks / (365 * 10_000) so that vol
#     numbers come out at the conventional annualised scale. Bachelier uses
#     T_ticks directly so sigma is in units of "price / sqrt(tick)".
TICKS_PER_DAY = 10_000
DAYS_PER_YEAR = 365.0
TICKS_PER_YEAR = TICKS_PER_DAY * DAYS_PER_YEAR
TOTAL_TICKS = 3 * TICKS_PER_DAY

# Wings to exclude from the smile fit: deep OTM has bid pinned at minimum tick
# and deep ITM is essentially intrinsic (IV is unstable / undefined).
WING_EXCLUDE = {6000, 6500}              # always exclude (dead/frozen)
DEEP_ITM_EXCLUDE = {4000, 4500}          # often pinned at intrinsic; eval both
CORE_STRIKES = [k for k in STRIKES
                if k not in WING_EXCLUDE and k not in DEEP_ITM_EXCLUDE]

# ---------- Math helpers ---------- #
def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _n(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# Black-Scholes (r=0)
def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    d2 = d1 - sd
    return S * _N(d1) - K * _N(d2)


def bs_vega(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 0.0
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    return S * _n(d1) * math.sqrt(T)


# Bachelier (r=0)
def bach_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    sd = sigma * math.sqrt(T)
    d = (S - K) / sd
    return (S - K) * _N(d) + sd * _n(d)


def bach_vega(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 0.0
    sd = sigma * math.sqrt(T)
    d = (S - K) / sd
    return math.sqrt(T) * _n(d)


def implied_vol(price, S, K, T, model="bs", lo=1e-6, hi=None):
    """Bisection IV solver for either model. Returns None if no root."""
    intrinsic = max(S - K, 0.0)
    if T <= 0 or price < intrinsic - 1e-9:
        return None
    if price > S + 1e-6:
        return None
    if hi is None:
        hi = 5.0 if model == "bs" else 50.0  # BS in vol units; Bachelier in price/sqrt(t)
    pricer = bs_call if model == "bs" else bach_call
    plo = pricer(S, K, T, lo) - price
    phi = pricer(S, K, T, hi) - price
    if plo * phi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        pm = pricer(S, K, T, mid) - price
        if abs(pm) < 1e-9:
            return mid
        if plo * pm < 0:
            hi, phi = mid, pm
        else:
            lo, plo = mid, pm
        if hi - lo < 1e-12:
            break
    return 0.5 * (lo + hi)


# ---------- Data ---------- #
def load_prices() -> pd.DataFrame:
    parts = []
    for d in (0, 1, 2):
        df = pd.read_csv(DATA_DIR / f"prices_round_3_day_{d}.csv", sep=";")
        df["day"] = d
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def build_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Wide table: rows = (day, timestamp), cols = each product's mid + S."""
    df = df.copy()
    df["t_global"] = df["day"] * TICKS_PER_DAY + df["timestamp"] // 100
    pv = df.pivot_table(index="t_global", columns="product",
                        values="mid_price", aggfunc="first").sort_index()
    return pv


# ---------- IV inversion + per-tick smile fit ---------- #
def per_tick_iv_table(panel: pd.DataFrame, model: str) -> pd.DataFrame:
    """For every tick where S and *all 10* voucher mids exist, invert IV
    under the chosen model. Returns a long DataFrame indexed by (t, strike)
    with columns [S, K, C, T_ticks, T_years, iv, m_bs, m_bach, vega_<model>].
    """
    rows = []
    needed = [UNDERLYING] + [VEV[k] for k in STRIKES]
    panel = panel.dropna(subset=needed)
    print(f"[{model}] panel rows after dropna({len(needed)} cols): {len(panel)}")
    for t, row in panel.iterrows():
        S = float(row[UNDERLYING])
        T_ticks = max(1.0, TOTAL_TICKS - t)
        T_years = T_ticks / TICKS_PER_YEAR
        for K in STRIKES:
            C = float(row[VEV[K]])
            if model == "bs":
                T = T_years
                iv = implied_vol(C, S, K, T, model="bs")
                vega = bs_vega(S, K, T, iv) if iv else 0.0
            else:
                T = T_ticks
                iv = implied_vol(C, S, K, T, model="bach")
                vega = bach_vega(S, K, T, iv) if iv else 0.0
            if iv is None or not math.isfinite(iv):
                continue
            m_bs = math.log(K / S) / math.sqrt(T_years)
            m_bach = (K - S) / math.sqrt(T_ticks)
            rows.append({
                "t": int(t), "day": int(t // TICKS_PER_DAY),
                "S": S, "K": K, "C": C,
                "T_ticks": T_ticks, "T_years": T_years,
                "iv": iv, "m_bs": m_bs, "m_bach": m_bach,
                "vega": vega,
            })
    return pd.DataFrame(rows)


def per_tick_smile(iv_df: pd.DataFrame, model: str,
                   strikes: list[int]) -> pd.DataFrame:
    """Fit iv = a + b*m + c*m^2 separately per tick using only `strikes`,
    return per-(t, strike) residual frame including ALL strikes (so we can
    score the wings even if they were excluded from the fit)."""
    m_col = "m_bs" if model == "bs" else "m_bach"
    out_rows = []
    for t, sub in iv_df.groupby("t"):
        fit = sub[sub["K"].isin(strikes)]
        if len(fit) < 3:
            continue
        X = np.column_stack([np.ones(len(fit)), fit[m_col].values,
                             fit[m_col].values ** 2])
        try:
            coefs, *_ = np.linalg.lstsq(X, fit["iv"].values, rcond=None)
        except np.linalg.LinAlgError:
            continue
        a, b, c = coefs
        for _, r in sub.iterrows():
            mm = r[m_col]
            iv_hat = a + b * mm + c * mm * mm
            iv_resid = r["iv"] - iv_hat
            price_resid = iv_resid * r["vega"]   # 1st-order price diff
            out_rows.append({
                "t": int(t), "K": int(r["K"]),
                "iv": r["iv"], "iv_hat": iv_hat, "iv_resid": iv_resid,
                "price_resid": price_resid, "vega": r["vega"],
                "a": a, "b": b, "c": c,
            })
    return pd.DataFrame(out_rows)


def per_strike_summary(resid_df: pd.DataFrame) -> pd.DataFrame:
    g = resid_df.groupby("K")
    out = pd.DataFrame({
        "n":              g["iv_resid"].count(),
        "iv_resid_mean":  g["iv_resid"].mean(),
        "iv_resid_std":   g["iv_resid"].std(),
        "price_resid_mean": g["price_resid"].mean(),
        "price_resid_std":  g["price_resid"].std(),
        "iv_mean":        g["iv"].mean(),
        "vega_mean":      g["vega"].mean(),
    })
    out["abs_price_resid_mean"] = g["price_resid"].apply(lambda s: s.abs().mean())
    return out


def pooled_smile_coefs(iv_df: pd.DataFrame, model: str,
                       strikes: list[int]) -> tuple[float, float, float, int]:
    """Single quadratic across all ticks (Timo-style hardcoded constants)."""
    m_col = "m_bs" if model == "bs" else "m_bach"
    sub = iv_df[iv_df["K"].isin(strikes)]
    X = np.column_stack([np.ones(len(sub)), sub[m_col].values,
                         sub[m_col].values ** 2])
    coefs, *_ = np.linalg.lstsq(X, sub["iv"].values, rcond=None)
    return float(coefs[0]), float(coefs[1]), float(coefs[2]), len(sub)


# ---------- Main ---------- #
def main():
    print("Loading R3 prices...")
    df = load_prices()
    panel = build_panel(df)
    print(f"  panel shape (ticks x products): {panel.shape}")

    results: dict = {
        "meta": {
            "tte_convention": (
                "T_ticks = 30000 - (day*10000 + ts//100); "
                "T_years = T_ticks / (365 * 10000). "
                "Round = 3 days * 10K ticks; vouchers expire at the end of day 2."
            ),
            "ticks_per_day": TICKS_PER_DAY,
            "total_ticks": TOTAL_TICKS,
            "strikes_full": STRIKES,
            "strikes_wing_excluded": sorted(WING_EXCLUDE),
            "strikes_deep_itm": sorted(DEEP_ITM_EXCLUDE),
            "strikes_core_for_fit": CORE_STRIKES,
        },
        "models": {},
    }

    # We fit the smile two ways for each model:
    #   (A) core 6 strikes [5000..5500] only  <- recommended
    #   (B) full ten strikes (so we can SHOW the deep ITM/OTM blow up)
    fit_sets = {"core": CORE_STRIKES, "full": STRIKES}

    iv_tables = {}
    for model in ("bs", "bach"):
        iv_df = per_tick_iv_table(panel, model)
        iv_tables[model] = iv_df
        m_per_strike = (iv_df.groupby("K")["iv"]
                        .agg(["count", "mean", "std", "min", "max"])
                        .round(6))
        print(f"\n[{model}] IV stats per strike:\n{m_per_strike.to_string()}")

        results["models"][model] = {"per_strike_iv": m_per_strike.to_dict("index")}

        for set_name, set_strikes in fit_sets.items():
            resid = per_tick_smile(iv_df, model, set_strikes)
            if resid.empty:
                continue
            summary = per_strike_summary(resid)

            # Aggregate fit metrics over the strikes that were INCLUDED in the fit.
            in_fit = resid[resid["K"].isin(set_strikes)]
            iv_rmse = float(np.sqrt(np.mean(in_fit["iv_resid"] ** 2)))
            price_rmse = float(np.sqrt(np.mean(in_fit["price_resid"] ** 2)))
            mean_abs_price = float(in_fit["price_resid"].abs().mean())

            a, b, c, n_used = pooled_smile_coefs(iv_df, model, set_strikes)
            print(f"\n[{model}/{set_name}] pooled coefs a={a:.6f} b={b:.6f} c={c:.6f} (n={n_used})")
            print(f"  in-fit IV RMSE: {iv_rmse:.6f}, price RMSE: {price_rmse:.4f}, "
                  f"mean |price_resid|: {mean_abs_price:.4f}")
            print(f"  per-strike summary:\n{summary.round(4).to_string()}")

            results["models"][model][f"fit_{set_name}"] = {
                "strikes_used": set_strikes,
                "pooled_coefs": {"a": a, "b": b, "c": c, "n": n_used},
                "iv_rmse_in_fit": iv_rmse,
                "price_rmse_in_fit": price_rmse,
                "mean_abs_price_resid_in_fit": mean_abs_price,
                "per_strike": {int(k): {kk: (None if pd.isna(vv) else float(vv))
                                        for kk, vv in row.items()}
                               for k, row in summary.iterrows()},
            }

    # Comparison: BS vs Bachelier on CORE fit (the apples-to-apples version)
    bs_core = results["models"]["bs"]["fit_core"]
    bach_core = results["models"]["bach"]["fit_core"]
    results["comparison_core"] = {
        "bs_iv_rmse": bs_core["iv_rmse_in_fit"],
        "bach_iv_rmse": bach_core["iv_rmse_in_fit"],
        "bs_price_rmse": bs_core["price_rmse_in_fit"],
        "bach_price_rmse": bach_core["price_rmse_in_fit"],
        "bs_mean_abs_price_resid": bs_core["mean_abs_price_resid_in_fit"],
        "bach_mean_abs_price_resid": bach_core["mean_abs_price_resid_in_fit"],
        "bs_minus_bach_price_rmse": (bs_core["price_rmse_in_fit"]
                                     - bach_core["price_rmse_in_fit"]),
        "winner_by_price_rmse": ("bs" if bs_core["price_rmse_in_fit"]
                                 < bach_core["price_rmse_in_fit"] else "bach"),
    }
    print("\n=== HEAD-TO-HEAD (core 6 strikes) ===")
    print(json.dumps(results["comparison_core"], indent=2))

    # Per-day pooled coefs for the better model (so we can sanity check stability)
    winner = results["comparison_core"]["winner_by_price_rmse"]
    iv_df = iv_tables[winner]
    daily = []
    for d in (0, 1, 2):
        sub = iv_df[(iv_df["day"] == d) & iv_df["K"].isin(CORE_STRIKES)]
        if len(sub) < 30:
            continue
        a, b, c, n = pooled_smile_coefs(sub, winner, CORE_STRIKES)
        daily.append({"day": d, "a": a, "b": b, "c": c, "n": n})
    results["winner_daily_coefs"] = daily
    print(f"\n[{winner}] per-day pooled coefs:\n{json.dumps(daily, indent=2)}")

    # ===== 5400 cheap-vs-smile recheck =====
    # FINDINGS_v2 said VEV_5400 has mean residual -2.22 (price), z=-0.73
    # under the BS smile fit on the clean set. Let's recompute under both
    # models, restricted to the CORE fit, and see whether the sign holds.
    cheapness = {}
    for model in ("bs", "bach"):
        resid = per_tick_smile(iv_tables[model], model, CORE_STRIKES)
        for K in (5300, 5400, 5500):
            sub = resid[resid["K"] == K]
            if sub.empty:
                continue
            mean_p = float(sub["price_resid"].mean())
            std_p  = float(sub["price_resid"].std())
            cheapness.setdefault(model, {})[int(K)] = {
                "price_resid_mean": mean_p,
                "price_resid_std":  std_p,
                "z": mean_p / std_p if std_p > 0 else None,
                "n": int(len(sub)),
            }
    results["cheapness_recheck"] = cheapness
    print("\n=== 5300/5400/5500 cheapness (price-resid z) ===")
    print(json.dumps(cheapness, indent=2))

    out_json = OUT_DIR / "bachelier_vs_bs.json"
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
