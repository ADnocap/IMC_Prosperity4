"""Book structure deep-dive: characterize the MM that posts the bids and asks
the pulse process hits. Per asset:
  - half-spread distribution (FV - bid_1, ask_1 - FV)
  - L2 offset (bid_1 - bid_2, ask_2 - ask_1)
  - L3 frequency (mostly empty per inspection)
  - depth distribution at each level
  - mid quantum (integer vs half-integer)
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
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        if "day" not in f.columns:
            f["day"] = d
        frames.append(f)
    p = pd.concat(frames, ignore_index=True)
    p["cat"] = p["product"].apply(cat_of)
    print(f"loaded prices: {len(p)}")

    # Half-spread analysis
    p["bid_offset_1"] = p["mid_price"] - p["bid_price_1"]
    p["ask_offset_1"] = p["ask_price_1"] - p["mid_price"]
    p["bid_offset_2"] = p["mid_price"] - p["bid_price_2"]
    p["ask_offset_2"] = p["ask_price_2"] - p["mid_price"]
    p["L1_spread"] = p["ask_price_1"] - p["bid_price_1"]
    p["L2_lift_bid"] = p["bid_price_1"] - p["bid_price_2"]   # always >0 in proper book
    p["L2_lift_ask"] = p["ask_price_2"] - p["ask_price_1"]

    print("\n=== Per-asset book structure ===")
    cols = ["bid_offset_1", "ask_offset_1", "L1_spread",
            "L2_lift_bid", "L2_lift_ask",
            "bid_volume_1", "bid_volume_2", "bid_volume_3",
            "ask_volume_1", "ask_volume_2", "ask_volume_3"]
    rows = []
    for sym, sub in p.groupby("product"):
        rec = {"product": sym, "category": sub.cat.iat[0]}
        for col in cols:
            v = sub[col].dropna()
            rec[f"{col}_med"] = float(v.median()) if len(v) else float("nan")
            rec[f"{col}_n"] = int(v.notna().sum())
            rec[f"{col}_unq"] = int(v.nunique()) if len(v) else 0
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("product")

    print(df[["category", "bid_offset_1_med", "ask_offset_1_med", "L1_spread_med",
              "L2_lift_bid_med", "L2_lift_ask_med",
              "bid_volume_1_med", "bid_volume_2_med", "bid_volume_3_med",
              "bid_volume_3_n"]].sort_values(["category", "bid_offset_1_med"]).to_string())

    # Per-category aggregation
    print("\n\n=== Per-category typical book ===")
    cat_summary = p.groupby("cat").agg({
        "bid_offset_1": ["median", "mean", "std", "min", "max"],
        "L1_spread": ["median", "mean"],
        "L2_lift_bid": ["median", "mean"],
        "L2_lift_ask": ["median", "mean"],
        "bid_volume_1": ["median", "mean"],
        "bid_volume_2": ["median", "mean"],
        "bid_volume_3": "count",   # how many ticks have L3
        "ask_volume_3": "count",
    })
    print(cat_summary.to_string())

    # mid quantum check
    print("\n\n=== Mid quantum (integer vs half-integer) ===")
    for sym in p["product"].unique():
        v = p.loc[p["product"] == sym, "mid_price"]
        fracs = (v - v.astype(int)).abs()
        unique_fracs = sorted(fracs.unique().tolist())
        print(f"  {sym:36s}  unique_fracs={unique_fracs[:5]}  L1_med={(p.loc[p['product']==sym,'L1_spread']).median()}")


if __name__ == "__main__":
    main()
