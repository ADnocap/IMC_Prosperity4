"""Sweep k_sigma and hold_ticks to see if a less-frequent / bigger-z CS strategy
can survive realistic execution costs.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_R4 = ROOT / "data" / "prosperity4" / "round4"
OUT_DIR = ROOT / "analysis" / "round4"
OUT_JSON = OUT_DIR / "cs_threshold_sweep.json"

SMILE_A = 0.24874922943238548
SMILE_B = 0.0033068871733395525
SMILE_C = 0.027240641751624436
SMILE_T = 6.0 / 365.0
STRIKES = {"VEV_5200": 5200, "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500}


def bs_call(S, K, sigma, T):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    N = NormalDist().cdf
    return S * N(d1) - K * N(d2)


def smile_iv(K, S):
    if S <= 0:
        return SMILE_A
    m = math.log(K / S)
    return SMILE_A + SMILE_B * m + SMILE_C * m * m


def smile_fair(K, S):
    return bs_call(S, K, max(0.05, smile_iv(K, S)), SMILE_T)


def cs_replay(low_sym, high_sym, target_size, k_sigma, hold_ticks, mode):
    Klow = STRIKES[low_sym]
    Khigh = STRIKES[high_sym]
    daily_pnls = []
    daily_trades = []
    for d in (1, 2, 3):
        full = pd.read_parquet(DATA_R4 / f"prices_round_4_day_{d}.parquet")
        df_low = full[full["product"] == low_sym].sort_values("timestamp").reset_index(drop=True)
        df_high = full[full["product"] == high_sym].sort_values("timestamp").reset_index(drop=True)
        df_velvet = full[full["product"] == "VELVETFRUIT_EXTRACT"].sort_values("timestamp").reset_index(drop=True)

        merged = df_low[["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].rename(
            columns={"mid_price": "mid_low", "bid_price_1": "bid_low", "ask_price_1": "ask_low"})
        merged = merged.merge(
            df_high[["timestamp", "mid_price", "bid_price_1", "ask_price_1"]].rename(
                columns={"mid_price": "mid_high", "bid_price_1": "bid_high", "ask_price_1": "ask_high"}),
            on="timestamp", how="inner")
        merged = merged.merge(
            df_velvet[["timestamp", "mid_price"]].rename(columns={"mid_price": "S"}),
            on="timestamp", how="inner")
        merged["mkt_spread"] = merged["mid_low"] - merged["mid_high"]
        merged["theo_spread"] = merged.apply(
            lambda r: smile_fair(Klow, r["S"]) - smile_fair(Khigh, r["S"]), axis=1)
        merged["dev"] = merged["mkt_spread"] - merged["theo_spread"]
        ew_mean = merged["dev"].ewm(alpha=0.01, adjust=False).mean()
        ew_var = ((merged["dev"] - ew_mean) ** 2).ewm(alpha=0.02, adjust=False).mean()
        merged["dev_std"] = ew_var.clip(lower=0.25) ** 0.5
        merged["z"] = (merged["dev"] - ew_mean) / merged["dev_std"]

        position = 0
        entry_idx = -10**9
        entry_low_px = 0.0
        entry_high_px = 0.0
        day_pnl = 0.0
        trades = 0
        for i, row in merged.iloc[200:].reset_index(drop=True).iterrows():
            real_i = i + 200
            if position == 0:
                fired = False
                direction = 0
                if row["z"] > k_sigma:
                    direction = -1
                    fired = True
                elif row["z"] < -k_sigma:
                    direction = +1
                    fired = True
                if fired:
                    position = direction * target_size
                    entry_idx = real_i
                    if mode == "mid":
                        entry_low_px = row["mid_low"]
                        entry_high_px = row["mid_high"]
                    elif mode == "realistic":
                        if direction > 0:
                            entry_low_px = (row["mid_low"] + row["ask_low"]) / 2
                            entry_high_px = (row["mid_high"] + row["bid_high"]) / 2
                        else:
                            entry_low_px = (row["mid_low"] + row["bid_low"]) / 2
                            entry_high_px = (row["mid_high"] + row["ask_high"]) / 2
            else:
                exit_now = (
                    (real_i - entry_idx) >= hold_ticks
                    or (position > 0 and row["z"] >= 0)
                    or (position < 0 and row["z"] <= 0)
                )
                if exit_now:
                    direction = 1 if position > 0 else -1
                    if mode == "mid":
                        exit_low_px = row["mid_low"]
                        exit_high_px = row["mid_high"]
                    elif mode == "realistic":
                        if direction > 0:
                            exit_low_px = (row["mid_low"] + row["bid_low"]) / 2
                            exit_high_px = (row["mid_high"] + row["ask_high"]) / 2
                        else:
                            exit_low_px = (row["mid_low"] + row["ask_low"]) / 2
                            exit_high_px = (row["mid_high"] + row["bid_high"]) / 2
                    pnl_low = (exit_low_px - entry_low_px) * (direction * target_size)
                    pnl_high = (entry_high_px - exit_high_px) * (direction * target_size)
                    day_pnl += pnl_low + pnl_high
                    trades += 1
                    position = 0
        daily_pnls.append(day_pnl)
        daily_trades.append(trades)
    return {"per_day": [float(p) for p in daily_pnls],
            "trades_per_day": [int(t) for t in daily_trades],
            "total": float(sum(daily_pnls)), "n_trades": int(sum(daily_trades))}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    print(f"{'pair':22s} {'sz':>3s} {'k':>4s} {'hold':>4s} {'mode':>10s} {'trades':>6s} {'total':>8s}")
    for low, high, sz in [
        ("VEV_5200", "VEV_5400", 30),
        ("VEV_5300", "VEV_5400", 40),
        ("VEV_5300", "VEV_5500", 20),
    ]:
        for k in (1.5, 2.0, 2.5, 3.0, 4.0):
            for hold in (30, 100, 300, 1000):
                for mode in ("mid", "realistic"):
                    res = cs_replay(low, high, sz, k, hold, mode)
                    key = f"{low}_{high}_sz{sz}_k{k}_h{hold}_{mode}"
                    out[key] = res
                    if res["n_trades"] > 0:
                        print(f"{low}/{high:8s} {sz:3d} {k:4.1f} {hold:4d} {mode:>10s} {res['n_trades']:6d} {res['total']:+8.0f}")
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
