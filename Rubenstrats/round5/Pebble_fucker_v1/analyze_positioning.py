"""Replay Pebble_fucker_v1 against the day-4 portal data and report positioning.

The portal sub 557974 made +1,976 on 1K-tick day-4 backtest with all final
positions at +2 (a slight long basket bias). This script reconstructs the
position trajectory tick by tick to answer:

  - How often were we at the +/-10 limit?
  - Average |position|?
  - How long did we sit flat (position == 0)?
  - Per-pebble distribution of position?

Used to decide whether quote sizes can safely be increased.
"""
from __future__ import annotations

import sys, csv, importlib.util
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "traders"))

from datamodel import (  # noqa: E402
    Listing, Observation, Order, OrderDepth, Trade, TradingState,
)


PEBBLES = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")
LIMIT = 10
TRADER_PATH = Path(__file__).parent / "Pebble_fucker_v1.py"


def load_trader():
    spec = importlib.util.spec_from_file_location("pebble_fucker_v1", TRADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pebble_fucker_v1"] = mod
    spec.loader.exec_module(mod)
    return mod.Trader()


def build_order_depth(row: pd.Series) -> OrderDepth:
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


def cross_at_l1(od: OrderDepth, side: str, qty_remaining: int):
    """Naive fill model: take available L1 first, then L2, etc."""
    fills = []
    if side == "buy":
        levels = sorted(od.sell_orders.items())  # ascending price
    else:
        levels = sorted(od.buy_orders.items(), reverse=True)
    for px, sz in levels:
        avail = abs(sz)
        take = min(avail, qty_remaining)
        if take <= 0:
            continue
        fills.append((px, take))
        qty_remaining -= take
        if qty_remaining <= 0:
            break
    return fills


def run() -> None:
    day_csv = REPO_ROOT / "data" / "prosperity4" / "round5" / "prices_round_5_day_4.csv"
    df = pd.read_csv(day_csv, sep=";")
    # Restrict to first 1K ticks to mirror portal-UI backtest.
    df_1k = df[df["timestamp"] <= 99_900].copy()
    pebbles_only = df_1k[df_1k["product"].isin(PEBBLES)].copy()
    timestamps = sorted(pebbles_only["timestamp"].unique())
    print(f"Replaying day 4, {len(timestamps)} ticks (timestamps 0..{max(timestamps)}). 5 pebbles.")

    trader = load_trader()
    listings = {p: Listing(symbol=p, product=p, denomination=1) for p in PEBBLES}
    position = {p: 0 for p in PEBBLES}
    cash = {p: 0.0 for p in PEBBLES}
    trader_data = ""
    own_trades: Dict[str, List[Trade]] = {p: [] for p in PEBBLES}

    pos_hist = {p: [] for p in PEBBLES}  # position after each tick
    fills_hist = {p: 0 for p in PEBBLES}  # cumulative fill count
    side_fills = {p: {"buy": 0, "sell": 0} for p in PEBBLES}
    residual_hist = []  # basket residual per tick
    quote_size_used = {p: [] for p in PEBBLES}  # qty actually quoted (bid+ask)

    by_ts = pebbles_only.set_index(["timestamp", "product"])

    for ts in timestamps:
        order_depths = {}
        for p in PEBBLES:
            row = by_ts.loc[(ts, p)]
            order_depths[p] = build_order_depth(row)

        ts_state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings=listings,
            order_depths=order_depths,
            own_trades={p: own_trades[p][-50:] for p in PEBBLES},
            market_trades={p: [] for p in PEBBLES},
            position={p: position[p] for p in PEBBLES if position[p] != 0},
            observations=Observation({}, {}),
        )

        result, _, trader_data = trader.run(ts_state)

        # Compute residual for diagnostics.
        mids = {}
        for p in PEBBLES:
            od = order_depths[p]
            if od.buy_orders and od.sell_orders:
                mids[p] = (max(od.buy_orders) + min(od.sell_orders)) / 2.0
        residual_hist.append(sum(mids.values()) - 50_000 if len(mids) == 5 else float("nan"))

        # Match orders against the *static* book (no after-strategy bot activity
        # modeled — this is just a CSV replay sanity check, not the full sim).
        for p, orders in result.items():
            if p not in PEBBLES:
                continue
            total_quoted = sum(abs(o.quantity) for o in orders)
            quote_size_used[p].append(total_quoted)
            for o in orders:
                od = order_depths[p]
                if o.quantity > 0:
                    fills = cross_at_l1(od, "buy", o.quantity) if any(
                        ap <= o.price for ap in od.sell_orders
                    ) else []
                    for px, qty in fills:
                        position[p] += qty
                        cash[p] -= px * qty
                        fills_hist[p] += 1
                        side_fills[p]["buy"] += qty
                        own_trades[p].append(Trade(p, px, qty, "SUBMISSION", "", ts))
                elif o.quantity < 0:
                    qty = -o.quantity
                    fills = cross_at_l1(od, "sell", qty) if any(
                        bp >= o.price for bp in od.buy_orders
                    ) else []
                    for px, q in fills:
                        position[p] -= q
                        cash[p] += px * q
                        fills_hist[p] += 1
                        side_fills[p]["sell"] += q
                        own_trades[p].append(Trade(p, px, q, "", "SUBMISSION", ts))

        for p in PEBBLES:
            pos_hist[p].append(position[p])

    # Mark-to-market PnL for sanity check
    last_mids = {}
    for p in PEBBLES:
        row = by_ts.loc[(timestamps[-1], p)]
        last_mids[p] = float(row["mid_price"])
    pnl_per = {p: cash[p] + position[p] * last_mids[p] for p in PEBBLES}
    total_pnl = sum(pnl_per.values())

    # Reports
    print(f"\n=== PnL reconstruction (mid-mark) ===")
    print(f"Total: {total_pnl:>10,.0f}  (portal reported +1,976 on day 4 1K ticks)")
    for p in PEBBLES:
        print(f"  {p:14s}  {pnl_per[p]:>10,.0f}  fills={fills_hist[p]:4d}  "
              f"buy={side_fills[p]['buy']} sell={side_fills[p]['sell']}  "
              f"final_pos={position[p]:+d}")

    print(f"\n=== Position usage (per-pebble) ===")
    print(f"{'pebble':14s}  {'mean_|p|':>9s} {'std':>7s} {'p50_|p|':>8s} {'p90_|p|':>8s} {'p99_|p|':>8s} "
          f"{'pct_at_lim':>11s} {'pct_zero':>9s} {'max_pos':>8s} {'min_pos':>8s}")
    for p in PEBBLES:
        arr = np.array(pos_hist[p])
        absp = np.abs(arr)
        pct_at_lim = (absp >= LIMIT).mean() * 100
        pct_zero = (arr == 0).mean() * 100
        print(f"{p:14s}  {absp.mean():>9.2f} {absp.std():>7.2f} "
              f"{np.percentile(absp,50):>8.0f} {np.percentile(absp,90):>8.0f} "
              f"{np.percentile(absp,99):>8.0f} {pct_at_lim:>10.1f}% "
              f"{pct_zero:>8.1f}% {arr.max():>+8d} {arr.min():>+8d}")

    print(f"\n=== Aggregate basket position (sum of pebble positions) ===")
    basket = np.array([sum(pos_hist[p][i] for p in PEBBLES) for i in range(len(timestamps))])
    print(f"mean={basket.mean():+.2f} std={basket.std():.2f} "
          f"p05={np.percentile(basket,5):+.0f} p95={np.percentile(basket,95):+.0f} "
          f"min={basket.min():+d} max={basket.max():+d}")
    print(f"pct_at_basket_lim_+50={((basket >= 50).mean() * 100):.1f}%  "
          f"pct_at_basket_lim_-50={((basket <= -50).mean() * 100):.1f}%")

    print(f"\n=== Basket residual (signal that drives gating) ===")
    arr = np.array(residual_hist)
    arr = arr[~np.isnan(arr)]
    print(f"mean={arr.mean():+.2f} std={arr.std():.2f} "
          f"p05={np.percentile(arr,5):+.1f} p95={np.percentile(arr,95):+.1f} "
          f"min={arr.min():+.1f} max={arr.max():+.1f}")
    n = len(arr)
    print(f"|r|<=1.0 (no signal): {(np.abs(arr)<=1.0).mean()*100:.1f}%")
    print(f"|r|>1.0  (gated):     {(np.abs(arr)>1.0).mean()*100:.1f}%")
    print(f"|r|>5    (strong):    {(np.abs(arr)>5).mean()*100:.1f}%")
    print(f"|r|>10   (extreme):   {(np.abs(arr)>10).mean()*100:.1f}%")

    print(f"\n=== Quote size used per tick (sum of |bid|+|ask| qty per leg) ===")
    print(f"{'pebble':14s}  {'mean':>6s} {'p50':>5s} {'p90':>5s} {'p99':>5s} {'max':>5s}")
    for p in PEBBLES:
        arr = np.array(quote_size_used[p])
        print(f"{p:14s}  {arr.mean():>6.1f} {np.percentile(arr,50):>5.0f} "
              f"{np.percentile(arr,90):>5.0f} {np.percentile(arr,99):>5.0f} {arr.max():>5d}")


if __name__ == "__main__":
    run()
