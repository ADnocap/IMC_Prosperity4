"""Per-asset post-pulse mid drift (1-tick horizon).

For each (sym, trade_event), measure (mid_{t+1} - mid_t) * side, where
  side = +1 if trade.price >= ask_price_1 (BUY), -1 if <= bid_price_1 (SELL).
Average over all events and over 3 days. Output:
  - JSON file {symbol: mean_signed_dmid_p1} for all 50 assets
  - Console table sorted

Positive = continuation (mid moves with the pulse direction); negative =
reversion (mid moves opposite). For pulse_v2 we want a per-asset target shift:
  target_shift = -k * mean_signed_dmid_p1  (fade continuation, ride reversion)
... no wait, opposite:
  target_shift =  k * mean_signed_dmid_p1
because a positive number means after a BUY pulse mid keeps going up — so we
want to BE LONG (target +) into the next tick. After a SELL pulse with
negative drift (continuation), we want to BE SHORT.

Reversion is the other case: mean_signed_dmid < 0 means after a BUY pulse mid
falls — we want to be SHORT into the next tick = negative target = sign(side)
* mean_signed_dmid. Same formula.
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"
OUT  = REPO / "analysis" / "round5" / "post_pulse_drift.json"

DAYS = [2, 3, 4]


def per_day(day: int) -> pd.DataFrame:
    px = pd.read_csv(DATA / f"prices_round_5_day_{day}.csv", sep=";")
    tr = pd.read_csv(DATA / f"trades_round_5_day_{day}.csv", sep=";")
    px = px.sort_values(["product", "timestamp"]).copy()
    px["mid"] = (px["bid_price_1"] + px["ask_price_1"]) / 2.0

    merged = tr.merge(
        px[["product", "timestamp", "bid_price_1", "ask_price_1", "mid"]]
            .rename(columns={"product": "symbol"}),
        on=["symbol", "timestamp"], how="left",
    )
    side = np.where(merged["price"] >= merged["ask_price_1"], 1,
                    np.where(merged["price"] <= merged["bid_price_1"], -1, 0))
    merged["side"] = side

    # mid lookup: index by (product, timestamp)
    px_ix = px.set_index(["product", "timestamp"])["mid"]

    def lookup(symbol, ts_arr):
        try:
            return px_ix.loc[symbol].reindex(ts_arr).values
        except KeyError:
            return np.full(len(ts_arr), np.nan)

    rows = []
    for sym, g in merged.groupby("symbol"):
        ts = g["timestamp"].values
        sd = g["side"].values
        if (sd != 0).sum() < 30:
            continue
        mid_now = lookup(sym, ts)
        # Multiple horizons: the strategy sees the pulse at +1 tick lag, so
        # it can only act on the move from +1 onward. p1_to_p2 = mid drift
        # from tick after pulse to two-after; this is the actionable horizon.
        mid_p1 = lookup(sym, ts + 100)
        mid_p2 = lookup(sym, ts + 200)
        mid_p3 = lookup(sym, ts + 300)
        mid_p5 = lookup(sym, ts + 500)
        valid = (~np.isnan(mid_now) & ~np.isnan(mid_p1) & ~np.isnan(mid_p2) & (sd != 0))
        if valid.sum() < 30:
            continue
        # Per-horizon signed drift from t=0
        dm_p1 = (mid_p1 - mid_now) * sd
        dm_p2 = (mid_p2 - mid_now) * sd
        dm_p3 = (mid_p3 - mid_now) * sd
        dm_p5 = (mid_p5 - mid_now) * sd
        # Actionable: drift from p1 (when we detect) to p2/p3/p5
        dm_p1_to_p2 = (mid_p2 - mid_p1) * sd
        dm_p1_to_p3 = (mid_p3 - mid_p1) * sd
        dm_p1_to_p5 = (mid_p5 - mid_p1) * sd
        rows.append({
            "day": day, "symbol": sym,
            "n": int(valid.sum()),
            "mean_p1": float(np.nanmean(dm_p1[valid])),
            "mean_p2": float(np.nanmean(dm_p2[valid])),
            "mean_p3": float(np.nanmean(dm_p3[valid])),
            "mean_p5": float(np.nanmean(dm_p5[valid])),
            "mean_p1_to_p2": float(np.nanmean(dm_p1_to_p2[valid])),
            "mean_p1_to_p3": float(np.nanmean(dm_p1_to_p3[valid])),
            "mean_p1_to_p5": float(np.nanmean(dm_p1_to_p5[valid])),
            "std_p1_to_p2": float(np.nanstd(dm_p1_to_p2[valid], ddof=1)),
        })
    return pd.DataFrame(rows)


def main():
    frames = [per_day(d) for d in DAYS]
    all_rows = pd.concat(frames, ignore_index=True)
    avg = all_rows.groupby("symbol").agg(
        n=("n", "sum"),
        mean_p1=("mean_p1", "mean"),
        mean_p2=("mean_p2", "mean"),
        mean_p1_to_p2=("mean_p1_to_p2", "mean"),
        mean_p1_to_p3=("mean_p1_to_p3", "mean"),
        mean_p1_to_p5=("mean_p1_to_p5", "mean"),
        std_p1_to_p2=("std_p1_to_p2", "mean"),
        sign_p1_3d=("mean_p1", lambda s: int(np.sign(s).sum())),
        sign_p1_to_p2_3d=("mean_p1_to_p2", lambda s: int(np.sign(s).sum())),
    ).reset_index().sort_values("mean_p1_to_p2")

    avg["se_p1_to_p2"] = avg["std_p1_to_p2"] / np.sqrt(avg["n"])
    avg["t_p1_to_p2"] = avg["mean_p1_to_p2"] / avg["se_p1_to_p2"]

    print("Per-asset post-pulse drift, 3-day avg.  Actionable horizon = p1_to_p2")
    print("(strategy sees pulse at +1 tick lag -> can only act on drift from +1 onward)")
    print(f"{'symbol':40s}{'n':>6s}{'p1':>9s}{'p1->p2':>9s}{'p1->p3':>9s}{'p1->p5':>9s}{'t':>7s}{'sgn':>5s}")
    for _, r in avg.iterrows():
        print(f"{r['symbol']:40s}{int(r['n']):>6d}{r['mean_p1']:>9.3f}"
              f"{r['mean_p1_to_p2']:>9.3f}{r['mean_p1_to_p3']:>9.3f}"
              f"{r['mean_p1_to_p5']:>9.3f}{r['t_p1_to_p2']:>7.2f}"
              f"{int(r['sign_p1_to_p2_3d']):>5d}")

    out = {}
    for _, r in avg.iterrows():
        out[r["symbol"]] = {
            "mean_p1": float(r["mean_p1"]),
            "mean_p1_to_p2": float(r["mean_p1_to_p2"]),
            "mean_p1_to_p3": float(r["mean_p1_to_p3"]),
            "mean_p1_to_p5": float(r["mean_p1_to_p5"]),
            "t_p1_to_p2": float(r["t_p1_to_p2"]),
            "n": int(r["n"]),
            "sign_p1_to_p2_3d": int(r["sign_p1_to_p2_3d"]),
        }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
