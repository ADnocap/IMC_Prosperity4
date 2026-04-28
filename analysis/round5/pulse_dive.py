"""Within-pulse uniformity check: are direction and quantity shared across
all assets in a pulse? Is trade price always best_bid (sell) or best_ask (buy)?

If both hold, the bot model collapses to:
  for each pulse: pick a direction + quantity + which group fires,
  then for every member: trade at best_bid (sell) or best_ask (buy) with that qty.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"

CATEGORIES = {
    "GALAXY_": "galaxy_sounds", "SLEEP_": "sleep_pods",
    "MICROCHIP_": "microchips", "PEBBLES_": "pebbles",
    "ROBOT_": "robots", "UV_": "uv_visors",
    "TRANSLATOR_": "translators", "PANEL_": "panels",
    "OXYGEN_": "oxygen_shakes", "SNACKPACK_": "snackpacks",
}


def cat_of(symbol: str) -> str:
    for prefix, c in CATEGORIES.items():
        if symbol.startswith(prefix):
            return c
    raise ValueError(symbol)


def main():
    # load both prices (with full book) and trades
    pframes, tframes = [], []
    for d in (2, 3, 4):
        p = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        # ensure prices has 'day' column (some CSVs already have day, this is idempotent)
        if "day" not in p.columns:
            p["day"] = d
        t = pd.read_csv(DATA_DIR / f"trades_round_5_day_{d}.csv", sep=";")
        t["day"] = d  # trades CSVs DO NOT have a 'day' column
        pframes.append(p)
        tframes.append(t)
    prices = pd.concat(pframes, ignore_index=True)
    trades = pd.concat(tframes, ignore_index=True)
    trades["cat"] = trades["symbol"].apply(cat_of)

    # Build lookups: for each (day, ts, product) -> (bid_1, ask_1, mid)
    book = prices[["day", "timestamp", "product",
                   "bid_price_1", "ask_price_1", "mid_price"]].copy()
    book = book.set_index(["day", "timestamp", "product"])

    # Annotate each trade with same-tick book
    trades = trades.merge(
        book.reset_index(),
        left_on=["day", "timestamp", "symbol"],
        right_on=["day", "timestamp", "product"],
        how="left",
    )

    # Inferred direction: trade_price <= bid_1 → SELL (taker hit our bid),
    #                     trade_price >= ask_1 → BUY  (taker lifted our ask),
    #                     mid → ambiguous.
    def direction(row):
        if pd.notna(row["bid_price_1"]) and row["price"] <= row["bid_price_1"]:
            return "SELL"
        if pd.notna(row["ask_price_1"]) and row["price"] >= row["ask_price_1"]:
            return "BUY"
        return "MID"

    trades["dir"] = trades.apply(direction, axis=1)
    print("trade direction overall:")
    print(trades["dir"].value_counts())

    print("\ndirection x category:")
    print(pd.crosstab(trades["cat"], trades["dir"]))

    # Per-pulse uniformity check
    # Group by (day, timestamp) and check whether all rows share dir + qty
    print("\n=== pulse uniformity (within (day, timestamp)) ===")
    pulses = trades.groupby(["day", "timestamp"]).agg(
        n=("symbol", "size"),
        n_dirs=("dir", "nunique"),
        n_qtys=("quantity", "nunique"),
        dir_set=("dir", lambda s: tuple(sorted(s.unique()))),
        qty_set=("quantity", lambda s: tuple(sorted(s.unique()))),
        n_cat=("cat", "nunique"),
    )
    print(f"total pulses: {len(pulses)}")
    print(f"pulses with all same dir:  {(pulses.n_dirs == 1).sum()}  ({(pulses.n_dirs == 1).mean()*100:.1f}%)")
    print(f"pulses with all same qty:  {(pulses.n_qtys == 1).sum()}  ({(pulses.n_qtys == 1).mean()*100:.1f}%)")
    print(f"pulses with all same dir AND qty:  {((pulses.n_dirs == 1) & (pulses.n_qtys == 1)).sum()}")

    # Investigate non-uniform pulses
    mixed = pulses[(pulses.n_dirs > 1) | (pulses.n_qtys > 1)]
    print(f"\nMixed pulses ({len(mixed)}):")
    print(mixed.head(15))

    # Within a pulse, do different categories fire with different qty/dir?
    # Subset pulses where multiple categories fire
    multi_cat = pulses[pulses.n_cat > 1]
    print(f"\nMulti-category pulses: {len(multi_cat)}")
    # For these, are dir/qty uniform across categories within the pulse?
    if len(multi_cat) > 0:
        # for first few, show breakdown
        for (day, ts), row in multi_cat.head(5).iterrows():
            sub = trades[(trades.day == day) & (trades.timestamp == ts)]
            cat_summary = sub.groupby("cat").agg(
                dir=("dir", lambda s: tuple(s.unique())),
                qty=("quantity", lambda s: tuple(s.unique())),
            )
            print(f"\n  pulse (day={day}, ts={ts}):")
            print(cat_summary.to_string())

    # Confirm: trade price = best_bid (sell) or best_ask (buy)
    print("\n\n=== trade price == bid_1/ask_1 ? ===")
    # For SELL pulses, expect price == bid_price_1
    sell_t = trades[trades.dir == "SELL"]
    sell_match = (sell_t["price"] == sell_t["bid_price_1"]).sum()
    print(f"SELL trades: {len(sell_t)}, price == bid_1: {sell_match} ({sell_match/len(sell_t)*100:.2f}%)")
    # For BUY: price == ask_price_1
    buy_t = trades[trades.dir == "BUY"]
    buy_match = (buy_t["price"] == buy_t["ask_price_1"]).sum()
    print(f"BUY trades:  {len(buy_t)}, price == ask_1: {buy_match} ({buy_match/len(buy_t)*100:.2f}%)")

    # Where it doesn't match, what's the offset?
    sell_off = (sell_t["price"] - sell_t["bid_price_1"]).value_counts().head(10)
    buy_off = (buy_t["price"] - buy_t["ask_price_1"]).value_counts().head(10)
    print(f"\nSELL price - bid_1 distribution (top 10):")
    print(sell_off)
    print(f"\nBUY price - ask_1 distribution (top 10):")
    print(buy_off)

    # Per-category direction balance (BUY/SELL count)
    print("\n=== Per-pulse-group direction balance (full 3-day) ===")
    pulses["pulse_kind"] = pulses.apply(
        lambda r: "pebbles_only" if r.n == 5 and (r.qty_set[0] >= 2)
        else "microchips_only" if r.n == 5 and (r.qty_set[0] <= 3)
        else "vanilla_only" if r.n == 40
        else "pebbles+vanilla" if r.n == 45 and (r.qty_set[0] >= 2)
        else "microchips+vanilla" if r.n == 45
        else "mixed_other", axis=1
    )
    # we should derive pulse_kind by which category set fired, not by qty_set
    # better: re-derive from per-pulse cat composition
    sub = trades.groupby(["day", "timestamp"]).agg(
        n_pebble=("cat", lambda s: (s == "pebbles").sum()),
        n_micro=("cat", lambda s: (s == "microchips").sum()),
        n_vanilla=("cat", lambda s: (~s.isin(["pebbles", "microchips"])).sum()),
    )
    pulses = pulses.join(sub)

    def pulse_kind(r):
        kind = []
        if r.n_pebble > 0:
            kind.append("P")
        if r.n_micro > 0:
            kind.append("M")
        if r.n_vanilla > 0:
            kind.append("V")
        return "+".join(kind)

    pulses["kind"] = pulses.apply(pulse_kind, axis=1)
    # take per-pulse direction (assume uniform within)
    first_dir = trades.groupby(["day", "timestamp"])["dir"].first()
    pulses["dir"] = first_dir
    first_qty = trades.groupby(["day", "timestamp"])["quantity"].first()
    pulses["qty"] = first_qty

    print(pulses.groupby(["kind", "dir"]).size().unstack(fill_value=0))
    print()
    print("Per-kind quantity distribution:")
    print(pulses.groupby(["kind"])["qty"].value_counts().unstack(fill_value=0))


if __name__ == "__main__":
    main()
