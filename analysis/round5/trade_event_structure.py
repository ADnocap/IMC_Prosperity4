"""Characterize bot trade-event structure across the 50-asset universe.

Hypothesis: trades cluster into shared "pulses" — at certain ticks many vanilla
products trade simultaneously, while pebbles + microchips have their own
independent pulse processes. This shapes how the MC sim must generate
trade events (not 50 independent Poissons but a shared multi-asset pulse).

For each tick where any trade occurs, record:
  - which assets traded
  - whether the pulse is "all-vanilla", "all-pebbles", "mixed", etc.
  - direction (buy / sell from market-maker perspective)

Then characterize:
  - inter-pulse arrival distribution
  - pulse-size distribution (how many assets fire per pulse)
  - within-pulse correlation across categories
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
    raise ValueError(f"unknown {symbol}")


def load_trades() -> pd.DataFrame:
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"trades_round_5_day_{d}.csv", sep=";")
        f["day"] = d
        f["cat"] = f["symbol"].apply(cat_of)
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def load_prices() -> pd.DataFrame:
    """Wide DataFrame of mid prices indexed by (day, timestamp)."""
    frames = []
    for d in (2, 3, 4):
        f = pd.read_csv(DATA_DIR / f"prices_round_5_day_{d}.csv", sep=";")
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def main():
    trades = load_trades()
    prices = load_prices()
    print(f"trades: {len(trades)}  prices: {len(prices)}")

    # Per-tick pulse characterization
    pulses = trades.groupby(["day", "timestamp"]).agg(
        n_assets=("symbol", "nunique"),
        n_pebble=("cat", lambda s: (s == "pebbles").sum()),
        n_micro=("cat", lambda s: (s == "microchips").sum()),
        n_vanilla=("cat", lambda s: (~s.isin(["pebbles", "microchips"])).sum()),
    )
    print(f"\npulse count (unique trade ticks across 3 days): {len(pulses)}")
    print("\npulse n_assets distribution:")
    print(pulses["n_assets"].describe())
    print("\npulse n_assets value_counts:")
    print(pulses["n_assets"].value_counts().sort_index().head(20))

    # Are the pulses "all vanilla" or "all pebble" or mixed?
    print("\npulse type breakdown (n_pebble + n_micro + n_vanilla):")
    pulses["type"] = pulses.apply(
        lambda r: f"P{r.n_pebble}_M{r.n_micro}_V{r.n_vanilla}", axis=1
    )
    print(pulses["type"].value_counts().head(20))

    # Inter-pulse arrival
    print("\nINTER-PULSE arrival times (within day):")
    for d in (2, 3, 4):
        ticks = trades[trades.day == d]["timestamp"].drop_duplicates().sort_values().values
        gaps = np.diff(ticks) // 100  # convert to tick-units
        print(f"  day {d}: n_pulses={len(ticks)}, gap mean={gaps.mean():.2f}, "
              f"gap p50={int(np.median(gaps))}, p90={int(np.percentile(gaps, 90))}, "
              f"p99={int(np.percentile(gaps, 99))}, max={int(gaps.max())}")

    # Per-category fire rate
    print("\nPER-CATEGORY pulse rate (avg ticks between same-cat trades):")
    for c in CATEGORIES.values():
        sub = trades[trades.cat == c]
        if not len(sub):
            continue
        ticks = sub.groupby("day")["timestamp"].apply(lambda s: s.drop_duplicates().sort_values().diff().dropna() // 100)
        all_gaps = ticks.values
        print(f"  {c:14s}  n_pulses_per_day={int(round(len(sub) / 3 / 5))}  "
              f"gap_mean={all_gaps.mean():.1f}  gap_p50={int(np.median(all_gaps))}  "
              f"gap_max={int(all_gaps.max())}")

    # Within-pulse asset coverage: when a vanilla pulse happens, how many of the 40 fire?
    vanilla_pulses = pulses[(pulses.n_vanilla > 0) & (pulses.n_pebble == 0)]
    print(f"\n'pure vanilla' pulses: {len(vanilla_pulses)} pulses, n_vanilla distribution:")
    print(vanilla_pulses["n_vanilla"].describe())

    pebble_pulses = pulses[(pulses.n_pebble > 0)]
    print(f"\n'pebble-fires' pulses: {len(pebble_pulses)}, n_pebble distribution:")
    print(pebble_pulses["n_pebble"].value_counts())

    # Inferred trade direction (if buyer/seller empty, derive from price vs prior mid)
    # Compare trade price to prior-tick mid for that product
    print("\n\nTRADE DIRECTION (from price vs prior mid):")
    # Build lookup of prior mid per (day, ts, product)
    prices_w = prices.pivot_table(
        index=["day", "timestamp"], columns="product", values="mid_price"
    )
    # forward-fill in case some tick rows are missing for some products
    prices_w = prices_w.sort_index()
    # for each trade, get prior mid (lag 1 tick = -100 timestamp)
    trades_dir = trades.copy()
    trades_dir["prev_ts"] = trades_dir["timestamp"]  # will lookup at SAME ts (the book pre-trade)
    # simplest: trade.price > mid_at_trade_tick → buy initiated (taker hit ask)
    #          trade.price < mid_at_trade_tick → sell initiated
    # Get mid at trade tick
    mid_at = []
    for _, r in trades_dir.head(30).iterrows():
        try:
            mid_at.append(prices_w.loc[(r.day, r.timestamp), r.symbol])
        except KeyError:
            mid_at.append(np.nan)
    print(f"  sample: trade prices vs same-tick mids (first 30 trades):")
    for (_, r), m in zip(trades_dir.head(30).iterrows(), mid_at):
        if pd.notna(m):
            d = r.price - m
            tag = "BUY" if d > 0 else "SELL" if d < 0 else "MID"
            print(f"    t={r.timestamp:>6d} {r.symbol[:30]:30s} px={r.price:8.1f} mid={m:8.1f} "
                  f"d={d:+6.1f} qty={r.quantity} {tag}")


if __name__ == "__main__":
    main()
