"""Test whether passive-only CS execution could harvest the spread instead of paying it.

Idea: when z>2 (spread rich → want to SHORT spread), POST a passive bid on the high leg
and a passive ask on the low leg. Get filled by counterparties → we capture spread/2 per leg.
Exit symmetrically when z reverts.

This is fundamentally different from the audit's mid-to-mid because we only "execute"
when the counterparty crosses our quote.

Approximation: assume passive fill probability per tick = base_rate. We'll try
several rates and see at what level CS becomes profitable.

Run: py -3.13 analysis/round4/cs_passive_only.py
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
OUT_JSON = OUT_DIR / "cs_passive_only.json"

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


def cs_passive(low_sym, high_sym, target_size, k_sigma, hold_ticks,
                fill_prob_per_tick, days, data_dir, day_pattern):
    """Passive-only fills: when signal active, we get random fills at our
    penny-jumped quote. We pay 1 tick haircut (penny-jump) per leg.

    Specifically: when |z|>k_sigma, post penny-jumped quotes on the desired
    side of each leg. Each tick, with probability fill_prob_per_tick, get
    1 unit filled per leg (rate-limited). When position reaches target_size
    OR z reverts to 0 (exit signal), reverse-post passive quotes to unwind.
    """
    Klow = STRIKES[low_sym]
    Khigh = STRIKES[high_sym]
    daily_pnls = []
    daily_trades = []
    rng = np.random.default_rng(42)
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

        pos_low = 0
        pos_high = 0
        # We track entry pxs on a per-unit basis (running cost basis)
        cost_low = 0.0
        cost_high = 0.0
        day_pnl = 0.0
        trades = 0
        for i, row in merged.iloc[200:].reset_index(drop=True).iterrows():
            z = row["z"]
            # Determine desired position (perfect-execution target)
            if z > k_sigma:
                desired = -target_size  # short spread
            elif z < -k_sigma:
                desired = +target_size  # long spread
            else:
                desired = 0
            tgt_low = desired
            tgt_high = -desired

            # Try to move toward target with passive fills
            # For each leg, if we want to BUY, post bid at best_bid+1 (penny jump);
            # the penny-jump means we pay (best_bid+1) which is mid - spread/2 + 1
            # Approximate: passive fill at best_bid+1 if we're buying, best_ask-1 if selling
            for leg, sym, mid_col, bid_col, ask_col, pos_var, cost_var, tgt in [
                ("low", low_sym, "mid_low", "bid_low", "ask_low", "pos_low", "cost_low", tgt_low),
                ("high", high_sym, "mid_high", "bid_high", "ask_high", "pos_high", "cost_high", tgt_high),
            ]:
                pos = locals()[pos_var]
                cost = locals()[cost_var]
                diff = tgt - pos
                if diff > 0:
                    # buy → passive bid at best_bid+1
                    fill_qty = 1 if rng.random() < fill_prob_per_tick else 0
                    fill_qty = min(fill_qty, diff)
                    if fill_qty > 0:
                        px = row[bid_col] + 1
                        new_pos = pos + fill_qty
                        if new_pos != 0:
                            cost = (cost * pos + px * fill_qty) / new_pos if abs(new_pos) > 0.5 else 0
                        else:
                            day_pnl += (cost - px) * pos  # closing crossing
                            cost = 0
                        pos = new_pos
                elif diff < 0:
                    # sell → passive ask at best_ask-1
                    fill_qty = 1 if rng.random() < fill_prob_per_tick else 0
                    fill_qty = min(fill_qty, -diff)
                    if fill_qty > 0:
                        px = row[ask_col] - 1
                        new_pos = pos - fill_qty
                        if new_pos != 0:
                            cost = (cost * pos - px * fill_qty) / new_pos if abs(new_pos) > 0.5 else 0
                        else:
                            day_pnl += (px - cost) * pos
                            cost = 0
                        pos = new_pos
                if leg == "low":
                    pos_low = pos
                    cost_low = cost
                else:
                    pos_high = pos
                    cost_high = cost

        # Mark to mid at end of day
        last = merged.iloc[-1]
        day_pnl += pos_low * (last["mid_low"] - cost_low)
        day_pnl += pos_high * (last["mid_high"] - cost_high)
        daily_pnls.append(day_pnl)
        daily_trades.append(trades)
    return {"per_day_pnl": [float(p) for p in daily_pnls],
            "total_pnl": float(sum(daily_pnls))}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    pairs = [
        ("VEV_5200", "VEV_5400", 30),
        ("VEV_5300", "VEV_5400", 40),
        ("VEV_5300", "VEV_5500", 20),
    ]
    print(f"{'pair':25s} {'sz':>3s} {'p_fill':>7s}  d1   d2   d3  total")
    for low, high, sz in pairs:
        for fp in (0.05, 0.1, 0.2, 0.5):
            res = cs_passive(low, high, sz, 2.0, 30, fp,
                              (1, 2, 3), DATA_R4, "prices_round_4_day_{d}.parquet")
            key = f"{low}_{high}_size{sz}_p{fp}"
            out[key] = res
            d1, d2, d3 = res["per_day_pnl"]
            print(f"{low}/{high:8s} {sz:3d} {fp:7.2f}  {d1:+5.0f} {d2:+5.0f} {d3:+5.0f}  {res['total_pnl']:+7.0f}")
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
