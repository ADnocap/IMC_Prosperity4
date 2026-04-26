"""Cross-strike replay — audit's logic, but with three execution modes:

  1. mid-to-mid     (audit's original — claimed +11,265 for 5200/5400 sz=30)
  2. realistic      (entry pays spread/2 per leg; exit pays spread/2 per leg)
  3. cross-spread   (entry buys at ask + sells at bid; exit reverses)

The realistic mode is what prosperity3bt approximates: an "aggressive take" of
target size = 30 sweeps the top-of-book ask of the leg you want to buy and
the top-of-book bid of the leg you want to sell. So entry costs (ask_low - mid_low)
+ (mid_high - bid_high) on a long-spread; exit pays the symmetric amount.

Run on R4 day 1/2/3 (= R3 day 0/1/2 plus a fresh day 3).

py -3.13 analysis/round4/cs_replay_with_spread.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_R3 = ROOT / "data" / "prosperity4" / "round3"
DATA_R4 = ROOT / "data" / "prosperity4" / "round4"
OUT_DIR = ROOT / "analysis" / "round4"
OUT_JSON = OUT_DIR / "cs_replay_with_spread.json"

# Audit's exact constants
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
    iv = max(0.05, smile_iv(K, S))
    return bs_call(S, K, iv, SMILE_T)


def cs_replay(low_sym, high_sym, target_size, k_sigma, hold_ticks,
              days, data_dir, day_pattern, mode):
    """
    mode in {"mid", "realistic", "cross"}:
       mid:       mark P&L at mids on entry & exit (audit's mode)
       realistic: pay spread/2 per leg on entry & exit (one-tick haircut typical)
       cross:     buy at ask, sell at bid on entry; reverse on exit (full spread)
    """
    Klow = STRIKES[low_sym]
    Khigh = STRIKES[high_sym]
    daily_pnls = []
    daily_trades = []
    for d in days:
        path = data_dir / day_pattern.format(d=d)
        full = pd.read_parquet(path)
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
        # Track per-leg entry prices (separated by execution mode)
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
                    direction = -1   # SHORT spread = sell low, buy high
                    fired = True
                elif row["z"] < -k_sigma:
                    direction = +1   # LONG spread = buy low, sell high
                    fired = True
                if fired:
                    position = direction * target_size
                    entry_idx = real_i
                    if mode == "mid":
                        entry_low_px = row["mid_low"]
                        entry_high_px = row["mid_high"]
                    elif mode == "realistic":
                        # spread/2 haircut per leg on entry
                        if direction > 0:
                            # buy low, sell high
                            entry_low_px = row["mid_low"] + (row["ask_low"] - row["mid_low"]) * 0.5
                            entry_high_px = row["mid_high"] - (row["mid_high"] - row["bid_high"]) * 0.5
                        else:
                            entry_low_px = row["mid_low"] - (row["mid_low"] - row["bid_low"]) * 0.5
                            entry_high_px = row["mid_high"] + (row["ask_high"] - row["mid_high"]) * 0.5
                    elif mode == "cross":
                        if direction > 0:
                            entry_low_px = row["ask_low"]
                            entry_high_px = row["bid_high"]
                        else:
                            entry_low_px = row["bid_low"]
                            entry_high_px = row["ask_high"]
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
                        # exit reverses sides: long-spread sells low, buys high (so sells low at bid_low haircut, buys high at ask_high haircut)
                        if direction > 0:
                            exit_low_px = row["mid_low"] - (row["mid_low"] - row["bid_low"]) * 0.5
                            exit_high_px = row["mid_high"] + (row["ask_high"] - row["mid_high"]) * 0.5
                        else:
                            exit_low_px = row["mid_low"] + (row["ask_low"] - row["mid_low"]) * 0.5
                            exit_high_px = row["mid_high"] - (row["mid_high"] - row["bid_high"]) * 0.5
                    elif mode == "cross":
                        if direction > 0:
                            exit_low_px = row["bid_low"]
                            exit_high_px = row["ask_high"]
                        else:
                            exit_low_px = row["ask_low"]
                            exit_high_px = row["bid_high"]
                    # PnL = direction * size * (mkt_spread_change)
                    # = direction * size * ((exit_low - entry_low) - (exit_high - entry_high))
                    # But each leg has its own price.
                    # Long spread (dir=+1): bought low at entry_low_px, sold low at exit_low_px → gain (exit_low - entry_low) * size; sold high at entry_high_px, bought high at exit_high_px → gain (entry_high - exit_high) * size.
                    pnl_low = (exit_low_px - entry_low_px) * (direction * target_size)
                    pnl_high = (entry_high_px - exit_high_px) * (direction * target_size)
                    day_pnl += pnl_low + pnl_high
                    trades += 1
                    position = 0
        daily_pnls.append(day_pnl)
        daily_trades.append(trades)
    return {"per_day_pnl": [float(p) for p in daily_pnls],
            "per_day_trades": [int(t) for t in daily_trades],
            "total_pnl": float(sum(daily_pnls)),
            "total_trades": int(sum(daily_trades))}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs = [
        ("VEV_5200", "VEV_5400", 30),
        ("VEV_5300", "VEV_5400", 40),
        ("VEV_5300", "VEV_5500", 20),
        ("VEV_5300", "VEV_5400", 100),
    ]
    out = {"r3_days_0_2": {}, "r4_days_1_3": {}}
    print("=== R3 days 0,1,2 (audit's data) ===")
    for low, high, sz in pairs:
        out["r3_days_0_2"][f"{low}_{high}_size{sz}"] = {}
        for mode in ("mid", "realistic", "cross"):
            res = cs_replay(low, high, sz, 2.0, 30, (0, 1, 2),
                            DATA_R3, "prices_round_3_day_{d}.parquet", mode)
            out["r3_days_0_2"][f"{low}_{high}_size{sz}"][mode] = res
            print(f"  {low}/{high} sz={sz:3d} mode={mode:9s}  total={res['total_pnl']:+9.0f} trades={res['total_trades']}")
    print()
    print("=== R4 days 1,2,3 ===")
    for low, high, sz in pairs:
        out["r4_days_1_3"][f"{low}_{high}_size{sz}"] = {}
        for mode in ("mid", "realistic", "cross"):
            res = cs_replay(low, high, sz, 2.0, 30, (1, 2, 3),
                            DATA_R4, "prices_round_4_day_{d}.parquet", mode)
            out["r4_days_1_3"][f"{low}_{high}_size{sz}"][mode] = res
            print(f"  {low}/{high} sz={sz:3d} mode={mode:9s}  total={res['total_pnl']:+9.0f} trades={res['total_trades']}")
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
