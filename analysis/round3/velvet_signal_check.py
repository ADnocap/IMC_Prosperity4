"""Does VELVET have a short-horizon microstructure signal?

Tests whether OBI (order-book imbalance), microprice skew, and signed
trade-flow imbalance predict the NEXT tick's mid-price change. If corr ≈ 0
on historical data, a directional strategy on VELVET will churn spread.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "prosperity4" / "round3"
SPOT = "VELVETFRUIT_EXTRACT"


def load_velvet(day: int) -> pd.DataFrame:
    px = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
    return px.loc[px["product"] == SPOT].sort_values("timestamp").reset_index(drop=True)


def load_trades(day: int) -> pd.DataFrame:
    tr = pd.read_csv(DATA / f"trades_round_3_day_{day}.csv", sep=";")
    return tr.loc[tr["symbol"] == SPOT].copy()


def add_signals(df: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    # OBI using top-of-book volume
    bv = df["bid_volume_1"].fillna(0)
    av = df["ask_volume_1"].fillna(0)
    tot = bv + av
    df["obi"] = np.where(tot > 0, (bv - av) / tot, 0.0)

    # Microprice: (ask*bv + bid*av) / (bv+av)
    bb = df["bid_price_1"]
    ba = df["ask_price_1"]
    mid = 0.5 * (bb + ba)
    micro = np.where(tot > 0, (ba * bv + bb * av) / tot, mid)
    df["micro_skew"] = micro - mid
    df["spread"] = ba - bb

    # Signed trade flow (buyer aggressor = buyer has bot name, seller empty = taker buy, etc.)
    # Simplest: compare trade price to mid at that tick
    df.set_index("timestamp", inplace=True)
    mid_series = df["mid_price"]
    trades["side"] = np.where(trades["price"] > trades["timestamp"].map(mid_series),
                              1, np.where(trades["price"] < trades["timestamp"].map(mid_series),
                                          -1, 0))
    signed = trades.groupby("timestamp")["quantity"].sum()  # placeholder
    signed_net = (trades.assign(sq=trades["side"] * trades["quantity"])
                  .groupby("timestamp")["sq"].sum())
    df["tf_signed"] = signed_net.reindex(df.index).fillna(0)

    df.reset_index(inplace=True)
    return df


def evaluate(df: pd.DataFrame, horizon: int = 1) -> dict:
    d = df["mid_price"].diff().shift(-horizon)  # future Δmid over `horizon` ticks
    res = {}
    for sig in ("obi", "micro_skew", "tf_signed"):
        s = df[sig]
        mask = d.notna() & s.notna()
        if mask.sum() < 100:
            continue
        # Correlation
        corr = s[mask].corr(d[mask])
        # OLS slope (one-step regression intercept-free)
        xx = s[mask].values
        yy = d[mask].values
        denom = (xx * xx).sum()
        slope = (xx * yy).sum() / denom if denom > 0 else np.nan
        # Hit rate: sign(signal) == sign(Δmid)
        hit = ((np.sign(xx) == np.sign(yy)) & (xx != 0) & (yy != 0)).sum()
        active = ((xx != 0) & (yy != 0)).sum()
        hit_rate = hit / active if active else np.nan
        res[sig] = {"corr": corr, "slope": slope, "hit_rate": hit_rate,
                    "n": int(mask.sum()), "active": int(active)}
    return res


def main():
    for day in (0, 1, 2):
        px = load_velvet(day)
        tr = load_trades(day)
        px = add_signals(px, tr)
        print(f"\n=== Day {day}, n={len(px)} ticks, {len(tr)} trades ===")
        for H in (1, 2, 5, 10):
            r = evaluate(px, horizon=H)
            print(f"  horizon +{H} tick:")
            for sig, v in r.items():
                print(f"    {sig:12s}  corr={v['corr']:+.4f}  "
                      f"slope={v['slope']:+.3f}  hit_rate={v['hit_rate']:.3f}  "
                      f"n={v['n']:,}")


if __name__ == "__main__":
    main()
