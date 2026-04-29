"""Replay v4 against day-4 historical data and report:
- residual distribution
- per-leg velocity distribution
- take fire rate
- per-leg fill rate / final position
"""
from __future__ import annotations

import sys, importlib.util, json
from collections import Counter
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "traders"))

from datamodel import Listing, Observation, Order, OrderDepth, Trade, TradingState

PEBBLES = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")
LIMIT = 10
TRADER_PATH = Path(__file__).parent / "Pebble_fucker_v4.py"


def load_trader():
    spec = importlib.util.spec_from_file_location("pebble_fucker_v4", TRADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pebble_fucker_v4"] = mod
    spec.loader.exec_module(mod)
    return mod.Trader()


def build_od(row):
    od = OrderDepth()
    for i in (1, 2, 3):
        bp = row.get(f"bid_price_{i}")
        bv = row.get(f"bid_volume_{i}")
        if pd.notna(bp) and pd.notna(bv) and bv:
            od.buy_orders[int(bp)] = int(bv)
        ap = row.get(f"ask_price_{i}")
        av = row.get(f"ask_volume_{i}")
        if pd.notna(ap) and pd.notna(av) and av:
            od.sell_orders[int(ap)] = -int(av)
    return od


def main():
    df = pd.read_csv(REPO_ROOT / "data/prosperity4/round5/prices_round_5_day_4.csv", sep=";")
    df = df[df["product"].isin(PEBBLES)]
    timestamps = sorted(df["timestamp"].unique())
    by_ts = df.set_index(["timestamp", "product"])

    trader = load_trader()
    listings = {p: Listing(symbol=p, product=p, denomination=1) for p in PEBBLES}
    position = {p: 0 for p in PEBBLES}
    cash = {p: 0.0 for p in PEBBLES}
    own_trades = {p: [] for p in PEBBLES}
    trader_data = ""

    residuals = []
    velocities = {p: [] for p in PEBBLES}
    take_count = {"sell": 0, "buy": 0}
    quote_count = {p: {"bid": 0, "ask": 0} for p in PEBBLES}
    fill_count = {p: {"buy": 0, "sell": 0} for p in PEBBLES}
    side_qty = {p: {"buy": 0, "sell": 0} for p in PEBBLES}

    mid_history = {p: [] for p in PEBBLES}
    pos_hist = {p: [] for p in PEBBLES}

    for ts in timestamps:
        order_depths = {p: build_od(by_ts.loc[(ts, p)]) for p in PEBBLES}

        # Track external residual + velocity
        mids = {}
        for p in PEBBLES:
            od = order_depths[p]
            if od.buy_orders and od.sell_orders:
                mids[p] = (max(od.buy_orders) + min(od.sell_orders)) / 2.0
        if len(mids) == 5:
            residuals.append(sum(mids.values()) - 50_000)
        for p in PEBBLES:
            mid_history[p].append(mids.get(p, np.nan))
            if len(mid_history[p]) > 6:
                v = mid_history[p][-1] - mid_history[p][-6]
                velocities[p].append(v)

        ts_state = TradingState(
            traderData=trader_data, timestamp=ts, listings=listings,
            order_depths=order_depths,
            own_trades={p: own_trades[p][-50:] for p in PEBBLES},
            market_trades={p: [] for p in PEBBLES},
            position={p: position[p] for p in PEBBLES if position[p] != 0},
            observations=Observation({}, {}),
        )
        result, _, trader_data = trader.run(ts_state)

        for p in PEBBLES:
            od = order_depths[p]
            best_bid = max(od.buy_orders) if od.buy_orders else None
            best_ask = min(od.sell_orders) if od.sell_orders else None
            for o in result.get(p, []):
                # Classify: take (price >= best_ask if buy, <= best_bid if sell)
                # vs passive
                is_take = False
                if o.quantity > 0 and best_ask is not None and o.price >= best_ask:
                    is_take = True
                    take_count["buy"] += 1
                elif o.quantity < 0 and best_bid is not None and o.price <= best_bid:
                    is_take = True
                    take_count["sell"] += 1
                if o.quantity > 0:
                    quote_count[p]["bid"] += 1
                    side_qty[p]["buy"] += o.quantity
                    # Naive fill: did our price cross the ask?
                    if best_ask is not None and o.price >= best_ask:
                        fill_qty = min(abs(od.sell_orders[best_ask]), o.quantity)
                        position[p] += fill_qty
                        cash[p] -= best_ask * fill_qty
                        fill_count[p]["buy"] += fill_qty
                else:
                    quote_count[p]["ask"] += 1
                    side_qty[p]["sell"] += abs(o.quantity)
                    if best_bid is not None and o.price <= best_bid:
                        fill_qty = min(abs(od.buy_orders[best_bid]), abs(o.quantity))
                        position[p] -= fill_qty
                        cash[p] += best_bid * fill_qty
                        fill_count[p]["sell"] += fill_qty
            pos_hist[p].append(position[p])

    print("=== Residual distribution (10K ticks day 4) ===")
    r = np.array(residuals)
    print(f"  mean={r.mean():+.2f} std={r.std():.2f} ")
    print(f"  |r|<=1: {(np.abs(r)<=1).mean()*100:.1f}%")
    print(f"  |r|>1:  {(np.abs(r)>1).mean()*100:.1f}%")
    print(f"  |r|>3:  {(np.abs(r)>3).mean()*100:.1f}%")
    print(f"  |r|>5:  {(np.abs(r)>5).mean()*100:.1f}%")
    print(f"  |r|>10: {(np.abs(r)>10).mean()*100:.1f}%")
    print(f"  max |r|: {np.abs(r).max():.0f}")

    print("\n=== Per-leg lag-5 velocity (|dv|) ===")
    for p in PEBBLES:
        v = np.array(velocities[p])
        print(f"  {p:14s} mean|dv|={np.abs(v).mean():>5.2f} p50={np.percentile(np.abs(v),50):>4.1f} "
              f"p90={np.percentile(np.abs(v),90):>5.1f} p99={np.percentile(np.abs(v),99):>5.1f}")

    print("\n=== Take fire rate (orders that crossed) ===")
    print(f"  total take-buy:  {take_count['buy']}")
    print(f"  total take-sell: {take_count['sell']}")

    print("\n=== Per-leg orders / fills / final pos ===")
    for p in PEBBLES:
        bids, asks = quote_count[p]["bid"], quote_count[p]["ask"]
        bq, sq = side_qty[p]["buy"], side_qty[p]["sell"]
        bf, sf = fill_count[p]["buy"], fill_count[p]["sell"]
        print(f"  {p:14s} bid_orders={bids:5d} ask_orders={asks:5d}  "
              f"bid_qty_total={bq:5d} ask_qty_total={sq:5d}  "
              f"buy_fills={bf:4d} sell_fills={sf:4d}  final_pos={position[p]:+d}")


if __name__ == "__main__":
    main()
