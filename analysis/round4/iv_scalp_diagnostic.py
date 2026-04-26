"""IV-scalping signal diagnostic.

Purpose: understand WHY traders/round4/timo.py loses ~33k on
VEV_5200/5300/5400 in R4 historical replay.

Replicates timo's IV-scalping signal exactly (same smile coefs,
same EMA windows, same triggers). For each fire, records the
post-fire mid drift over multiple horizons. If average drift
after a SELL-fire is positive (mid went up), the signal is
backwards. If average drift after SELL is negative (mid went
down), the signal is right but execution is the issue.

Outputs:
  analysis/round4/iv_scalp_diagnostic.md   -- summary
  analysis/round4/iv_scalp_diagnostic.json -- numbers per strike
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "prosperity4" / "round4"
OUT_DIR = REPO / "analysis" / "round4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNDERLYING = "VELVETFRUIT_EXTRACT"
SCALP_STRIKES = {5000: "VEV_5000", 5100: "VEV_5100", 5200: "VEV_5200",
                 5300: "VEV_5300", 5400: "VEV_5400", 5500: "VEV_5500"}

# --- Trader-matching constants ---
SMILE_A_INIT = 0.580261
SMILE_B = 0.033704
SMILE_C = 0.089775
SMILE_A_ALPHA = 0.01
THEO_NORM_WINDOW = 100
IV_SCALPING_WINDOW = 100
THR_OPEN = 0.5
THR_CLOSE = 0.0
IV_SCALPING_THR = 0.7
LOW_VEGA_THR_ADJ = 0.5
LOW_VEGA_CUTOFF = 1.0
SCALP_MAX_PER_TICK = 60
LIMIT = 300

SESSION_TICKS = 30_000
TICKS_PER_YEAR = 365 * 10_000
T_FLOOR = 1e-4

_N = NormalDist()
HORIZONS = [50, 200, 1000]


def bs_call(S, K, sigma, T):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    d2 = d1 - sd
    return S * _N.cdf(d1) - K * _N.cdf(d2)


def bs_vega(S, K, sigma, T):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    return S * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) * math.sqrt(T)


def implied_vol(price, S, K, T):
    if T <= 0:
        return None
    intrinsic = max(S - K, 0.0)
    if price < intrinsic - 1e-6 or price > S + 1e-6:
        return None
    lo, hi = 1e-3, 5.0
    plo = bs_call(S, K, lo, T) - price
    phi = bs_call(S, K, hi, T) - price
    if plo * phi > 0:
        return None
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        pm = bs_call(S, K, mid, T) - price
        if abs(pm) < 1e-4:
            return mid
        if plo * pm < 0:
            hi, phi = mid, pm
        else:
            lo, plo = mid, pm
    return 0.5 * (lo + hi)


def smile_iv(K, S, T_years, smile_a):
    if S <= 0 or T_years <= 0:
        return smile_a
    m = math.log(K / S) / math.sqrt(T_years)
    return smile_a + SMILE_B * m + SMILE_C * m * m


def smile_fair(K, S, T_years, smile_a):
    iv = max(0.05, smile_iv(K, S, T_years, smile_a))
    return bs_call(S, K, iv, T_years)


def t_years(ts: int) -> float:
    ticks_remaining = max(1000, SESSION_TICKS - ts // 100)
    return max(T_FLOOR, ticks_remaining / TICKS_PER_YEAR)


def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"prices_round_4_day_{day}.csv", sep=";")
    df = df[["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]]
    pv_mid = df.pivot_table(index="timestamp", columns="product",
                            values="mid_price", aggfunc="first").sort_index()
    pv_bid = df.pivot_table(index="timestamp", columns="product",
                            values="bid_price_1", aggfunc="first").sort_index()
    pv_ask = df.pivot_table(index="timestamp", columns="product",
                            values="ask_price_1", aggfunc="first").sort_index()
    return pv_mid, pv_bid, pv_ask


def diagnose_day(day: int) -> dict:
    pv_mid, pv_bid, pv_ask = load_day(day)
    needed = [UNDERLYING] + list(SCALP_STRIKES.values())
    panel = pv_mid.dropna(subset=needed)
    panel_bid = pv_bid.loc[panel.index]
    panel_ask = pv_ask.loc[panel.index]
    print(f"day {day}: panel rows {len(panel)}")

    # Online state per voucher (matching trader)
    smile_a = SMILE_A_INIT
    mean_dev = {sym: None for sym in SCALP_STRIKES.values()}
    switch_mean = {sym: 0.0 for sym in SCALP_STRIKES.values()}
    a_m = 2.0 / (THEO_NORM_WINDOW + 1)
    a_s = 2.0 / (IV_SCALPING_WINDOW + 1)

    # Track fires: rows of (ts, sym, side, mid_now, fair_now, mean_dev,
    #               switch_mean, vega, fired_due_to)
    fires: list[dict] = []

    timestamps = panel.index.to_list()
    mids_arr = {sym: panel[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    bids_arr = {sym: panel_bid[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    asks_arr = {sym: panel_ask[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    S_arr = panel[UNDERLYING].to_numpy()

    for i, ts in enumerate(timestamps):
        S = float(S_arr[i])
        T = t_years(ts)

        # Refit smile_a from observed IVs (same as trader)
        observed_ivs = {}
        for K, sym in SCALP_STRIKES.items():
            mid = float(mids_arr[sym][i])
            iv = implied_vol(mid, S, K, T)
            if iv is not None and 0.05 < iv < 4.5:
                observed_ivs[K] = iv
        if observed_ivs:
            residuals = []
            for K, iv_obs in observed_ivs.items():
                residuals.append(iv_obs - smile_iv(K, S, T, smile_a))
            avg_res = sum(residuals) / len(residuals)
            smile_a = max(0.05, min(3.0, smile_a + SMILE_A_ALPHA * avg_res))

        for K, sym in SCALP_STRIKES.items():
            mid = float(mids_arr[sym][i])
            best_bid = float(bids_arr[sym][i])
            best_ask = float(asks_arr[sym][i])
            if math.isnan(mid) or math.isnan(best_bid) or math.isnan(best_ask):
                continue
            fair = smile_fair(K, S, T, smile_a)
            iv_use = max(0.05, smile_iv(K, S, T, smile_a))
            vega = bs_vega(S, K, iv_use, T)
            dev = mid - fair
            md_prev = mean_dev[sym] if mean_dev[sym] is not None else dev
            md_new = a_m * dev + (1 - a_m) * md_prev
            mean_dev[sym] = md_new
            sw_prev = switch_mean[sym]
            sw_new = a_s * abs(dev - md_new) + (1 - a_s) * sw_prev
            switch_mean[sym] = sw_new

            if sw_new < IV_SCALPING_THR:
                continue  # gated off

            thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
            sell_dev = (best_bid - fair) - md_new
            buy_dev = (best_ask - fair) - md_new

            if sell_dev >= thr:
                fires.append({"ts": int(ts), "i": i, "sym": sym, "K": int(K),
                              "side": "sell", "mid": mid, "best_bid": best_bid,
                              "best_ask": best_ask, "fair": fair,
                              "dev": dev, "mean_dev": md_new,
                              "switch_mean": sw_new, "vega": vega})
            elif buy_dev <= -thr:
                fires.append({"ts": int(ts), "i": i, "sym": sym, "K": int(K),
                              "side": "buy", "mid": mid, "best_bid": best_bid,
                              "best_ask": best_ask, "fair": fair,
                              "dev": dev, "mean_dev": md_new,
                              "switch_mean": sw_new, "vega": vega})

    # Compute post-fire drift over horizons
    n_panel = len(panel)
    for f in fires:
        i = f["i"]
        sym = f["sym"]
        for h in HORIZONS:
            j = min(i + h, n_panel - 1)
            mid_future = float(mids_arr[sym][j])
            f[f"drift_h{h}"] = mid_future - f["mid"]

    return {"day": day, "n_panel": n_panel, "fires": fires}


def summarize(diag_per_day: list[dict]) -> dict:
    rows = []
    by_sym_side: dict = {}
    for d in diag_per_day:
        for f in d["fires"]:
            rows.append({"day": d["day"], **f})
            key = (f["sym"], f["side"])
            by_sym_side.setdefault(key, []).append(f)
    df = pd.DataFrame(rows)

    summary = {"per_strike_side": {}, "totals": {}}
    for (sym, side), fs in by_sym_side.items():
        sub = pd.DataFrame(fs)
        rec = {
            "n_fires": int(len(sub)),
            "mean_sell_price_or_buy_price":
                float(sub["best_bid"].mean()) if side == "sell"
                else float(sub["best_ask"].mean()),
            "mean_fair":   float(sub["fair"].mean()),
            "mean_dev":    float(sub["dev"].mean()),
            "mean_mean_dev": float(sub["mean_dev"].mean()),
            "mean_switch": float(sub["switch_mean"].mean()),
            "mean_vega":   float(sub["vega"].mean()),
        }
        # Drift signs: for SELL we want NEGATIVE drift (mid goes down → win)
        # for BUY we want POSITIVE drift.
        for h in HORIZONS:
            d = sub[f"drift_h{h}"]
            rec[f"drift_h{h}_mean"] = float(d.mean())
            rec[f"drift_h{h}_std"] = float(d.std())
            rec[f"drift_h{h}_pct_favorable"] = float(
                (d < 0).mean() if side == "sell" else (d > 0).mean()
            )
            # PnL per fire: if SELL at best_bid then mid_future, PnL = best_bid - mid_future
            # If BUY at best_ask, PnL = mid_future - best_ask
            if side == "sell":
                pnl = sub["best_bid"] - (sub["mid"] + d)
            else:
                pnl = (sub["mid"] + d) - sub["best_ask"]
            rec[f"pnl_per_fire_h{h}"] = float(pnl.mean())
            rec[f"total_pnl_h{h}_unit_size"] = float(pnl.sum())
        summary["per_strike_side"][f"{sym}__{side}"] = rec

    return summary, df


def main():
    diags = []
    for day in (1, 2, 3):
        diags.append(diagnose_day(day))
    summary, df = summarize(diags)

    out_json = OUT_DIR / "iv_scalp_diagnostic.json"
    out_json.write_text(json.dumps({"summary": summary,
                                    "n_fires_per_day": [
                                        {"day": d["day"],
                                         "n_fires": len(d["fires"])}
                                        for d in diags
                                    ]}, indent=2))
    print(f"Wrote {out_json}")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary["per_strike_side"], indent=2))


if __name__ == "__main__":
    main()
