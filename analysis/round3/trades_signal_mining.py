"""R3 trades data signal mining.

Counterparty IDs are stripped in P4 trades data (buyer/seller cols all empty),
so we infer *trade side* from price-vs-mid and look for:

  - Trade-burst regimes (volume windows -> subsequent move)
  - Same-side cluster signal (n consecutive buy-side or sell-side trades)
  - Post-trade alpha by inferred side
  - Cross-product directional correlation (VELVET vs VEV options)
  - Volume turnover vs resting book size

Output: trades_signals.md
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "prosperity4" / "round3"
OUT_DIR = ROOT / "analysis" / "round3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Forward-look horizons (in ticks) for post-trade alpha
HORIZONS = [10, 50, 100, 500]
# Window for "same-side cluster" signal (in ticks)
CLUSTER_WINDOW = 50
CLUSTER_MIN = 3
# Trade-burst window (ticks) and percentile for "high vol"
BURST_WINDOW = 1000
BURST_PCT = 0.9
# Cross-product lead horizon (ticks)
CROSS_LEAD = 30


def load_day(day: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = pd.read_csv(DATA_DIR / f"trades_round_3_day_{day}.csv", sep=";")
    prices = pd.read_csv(DATA_DIR / f"prices_round_3_day_{day}.csv", sep=";")
    trades["day"] = day
    return trades, prices


def merge_trade_side(trades: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Tag each trade with the resting mid at that timestamp and infer side.

    side = +1 if trade.price >= mid (aggressive buy hitting ask side / above mid)
           -1 if trade.price < mid  (aggressive sell hitting bid side / below mid)
    Tie at mid -> 0 (ambiguous, dropped from side-conditional stats).
    """
    p = prices[["timestamp", "product", "mid_price", "bid_price_1", "ask_price_1",
                "bid_volume_1", "ask_volume_1"]].rename(columns={"product": "symbol"})
    t = trades.merge(p, on=["timestamp", "symbol"], how="left")
    # Side inference vs best bid/ask if available, else vs mid
    bb = t["bid_price_1"]
    aa = t["ask_price_1"]
    side = np.where(t["price"] >= aa, +1,
            np.where(t["price"] <= bb, -1, 0))
    # Fall back to vs-mid for ties
    fallback = np.where(t["price"] > t["mid_price"], +1,
                np.where(t["price"] < t["mid_price"], -1, 0))
    t["side"] = np.where(side == 0, fallback, side)
    t["signed_qty"] = t["side"] * t["quantity"]
    t["spread"] = aa - bb
    t["edge_vs_mid"] = (t["price"] - t["mid_price"]) * t["side"]
    return t


def add_future_mid(prices: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """For each (timestamp, product) row in prices, compute mid_t+H per horizon."""
    p = prices[["timestamp", "product", "mid_price"]].copy()
    p = p.sort_values(["product", "timestamp"]).reset_index(drop=True)
    for H in horizons:
        # Each tick is +100 ts; H ticks = H*100 ts shift
        p[f"mid_p{H}"] = p.groupby("product")["mid_price"].shift(-H)
    return p


def per_symbol_summary(trades: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Total trade-vol per symbol vs resting book size at trade times."""
    rows = []
    for sym, g in trades.groupby("symbol"):
        n_trades = len(g)
        total_qty = g["quantity"].sum()
        signed = g["signed_qty"].sum()
        buy_n = int((g["side"] == +1).sum())
        sell_n = int((g["side"] == -1).sum())
        amb_n = int((g["side"] == 0).sum())
        avg_qty = g["quantity"].mean()
        # Resting book at trade times
        bb_vol = g["bid_volume_1"].mean()
        aa_vol = g["ask_volume_1"].mean()
        # Book-resting average across whole day
        sym_prices = prices[prices["product"] == sym]
        avg_book = (sym_prices["bid_volume_1"].mean() + sym_prices["ask_volume_1"].mean()) / 2
        # Per-tick turnover proxy
        n_ticks = sym_prices["timestamp"].nunique()
        per_tick_vol = total_qty / max(n_ticks, 1)
        rows.append({
            "symbol": sym,
            "n_trades": n_trades,
            "total_qty": int(total_qty),
            "signed_qty_net": int(signed),
            "buy_trades": buy_n,
            "sell_trades": sell_n,
            "ambig_trades": amb_n,
            "buy_pct": round(buy_n / max(buy_n + sell_n, 1) * 100, 1),
            "avg_trade_qty": round(avg_qty, 2),
            "avg_book_qty": round(avg_book, 1),
            "per_tick_vol": round(per_tick_vol, 3),
            "turnover_pct_book": round(per_tick_vol / max(avg_book, 1) * 100, 2),
        })
    return pd.DataFrame(rows).sort_values("n_trades", ascending=False)


def post_trade_alpha(trades: pd.DataFrame, prices_fut: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, side), compute mean post-trade move per horizon."""
    pf = prices_fut.rename(columns={"product": "symbol"}).drop(columns=["day"], errors="ignore")
    t = trades.merge(pf, on=["timestamp", "symbol", "mid_price"], how="left")
    rows = []
    for (sym, side), g in t.groupby(["symbol", "side"]):
        if side == 0 or len(g) < 5:
            continue
        row = {"symbol": sym, "side": "BUY" if side == +1 else "SELL", "n": len(g)}
        for H in HORIZONS:
            future = g[f"mid_p{H}"]
            move = (future - g["price"])  # +ve = price went UP after trade
            # Alpha from the perspective of the aggressor: side * (mid_future - trade_price)
            alpha = side * (future - g["price"])
            row[f"H{H}_mean_move"] = round(move.mean(), 2)
            row[f"H{H}_alpha"] = round(alpha.mean(), 2)
            row[f"H{H}_alpha_t"] = round(alpha.mean() / max(alpha.std() / np.sqrt(len(alpha.dropna())), 1e-9), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def cluster_signal(trades: pd.DataFrame, prices_fut: pd.DataFrame) -> pd.DataFrame:
    """When >=CLUSTER_MIN same-side trades hit within CLUSTER_WINDOW, study the post move."""
    pf = prices_fut.rename(columns={"product": "symbol"})
    # Drop dup 'day' col from trades before merge (pf also has day)
    pf_keep = pf.drop(columns=["day"], errors="ignore")
    t = trades.merge(pf_keep, on=["timestamp", "symbol", "mid_price"], how="left")
    t = t.sort_values(["day", "symbol", "timestamp"]).reset_index(drop=True)

    rows = []
    for (day, sym), g in t.groupby(["day", "symbol"]):
        if len(g) < CLUSTER_MIN:
            continue
        g = g.reset_index(drop=True)
        for side_val, side_lbl in [(+1, "BUY"), (-1, "SELL")]:
            mask = g["side"] == side_val
            idx = np.where(mask.values)[0]
            cluster_signals = []
            for i in range(len(idx) - CLUSTER_MIN + 1):
                ts0 = g.loc[idx[i], "timestamp"]
                ts_end = g.loc[idx[i + CLUSTER_MIN - 1], "timestamp"]
                if ts_end - ts0 <= CLUSTER_WINDOW * 100:  # 100 ts per tick
                    cluster_signals.append(idx[i + CLUSTER_MIN - 1])
            if not cluster_signals:
                continue
            anchor = g.iloc[cluster_signals]
            row = {"day": day, "symbol": sym, "side": side_lbl, "n_clusters": len(anchor)}
            for H in HORIZONS:
                future = anchor[f"mid_p{H}"]
                price = anchor["price"]
                alpha = side_val * (future - price)
                row[f"H{H}_alpha"] = round(alpha.mean(), 2) if len(alpha.dropna()) else float("nan")
            rows.append(row)
    return pd.DataFrame(rows)


def burst_regime(trades: pd.DataFrame, prices_fut: pd.DataFrame) -> pd.DataFrame:
    """Trade-vol bursts: rolling sum of trade qty per symbol, threshold at BURST_PCT."""
    rows = []
    for (day, sym), g in trades.groupby(["day", "symbol"]):
        if len(g) < 5:
            continue
        g = g.sort_values("timestamp").reset_index(drop=True)
        # Bin trades into BURST_WINDOW ticks and sum qty
        g["bin"] = (g["timestamp"] // (BURST_WINDOW * 100)).astype(int)
        binned = g.groupby("bin").agg(qty=("quantity", "sum"),
                                       signed=("signed_qty", "sum"),
                                       n=("quantity", "size"),
                                       ts_mid=("timestamp", "mean")).reset_index()
        if len(binned) < 5:
            continue
        thresh = binned["qty"].quantile(BURST_PCT)
        hi = binned[binned["qty"] >= thresh]
        if hi.empty:
            continue
        # Compare avg signed-bin-qty vs subsequent move in mid
        sym_p = prices_fut[(prices_fut["product"] == sym) & (prices_fut["day"] == day)].set_index("timestamp").sort_index()
        moves_h100 = []
        for _, b in hi.iterrows():
            # Anchor at end of bin
            ts_end = (b["bin"] + 1) * BURST_WINDOW * 100
            # Find nearest available timestamp
            try:
                ts_avail = sym_p.index[sym_p.index >= ts_end][0]
            except IndexError:
                continue
            row_now = sym_p.loc[ts_avail]
            mid_now = float(row_now["mid_price"])
            mid_fut_raw = row_now.get("mid_p100", np.nan)
            mid_fut = float(mid_fut_raw) if pd.notna(mid_fut_raw) else np.nan
            if not np.isnan(mid_fut):
                # Direction-conditional move (use sign of net signed flow)
                signed_dir = np.sign(b["signed"]) if b["signed"] != 0 else 0
                moves_h100.append({
                    "signed_flow": b["signed"],
                    "dir_alpha": signed_dir * (mid_fut - mid_now),
                    "abs_move": abs(mid_fut - mid_now),
                })
        if not moves_h100:
            continue
        mdf = pd.DataFrame(moves_h100)
        rows.append({
            "day": day,
            "symbol": sym,
            "n_bursts": len(mdf),
            "mean_signed_flow": round(mdf["signed_flow"].mean(), 1),
            "burst_dir_alpha_H100": round(mdf["dir_alpha"].mean(), 2),
            "burst_abs_move_H100": round(mdf["abs_move"].mean(), 2),
        })
    return pd.DataFrame(rows)


def cross_product_correlation(trades: pd.DataFrame) -> pd.DataFrame:
    """For each pair (VELVET, VEV_strike), check if signed flow leads/lags."""
    # Aggregate signed flow into per-(day, ts_bin) per-symbol buckets
    bin_size = CROSS_LEAD * 100  # ts per bin
    t = trades.copy()
    t["bin"] = t["timestamp"] // bin_size
    flow = t.groupby(["day", "symbol", "bin"])["signed_qty"].sum().unstack("symbol", fill_value=0)
    # Build a full grid of bins
    rows = []
    syms = list(flow.columns)
    if "VELVETFRUIT_EXTRACT" not in syms:
        return pd.DataFrame(rows)
    velvet = flow["VELVETFRUIT_EXTRACT"]
    for sym in syms:
        if sym == "VELVETFRUIT_EXTRACT":
            continue
        s = flow[sym]
        if s.std() < 1e-6:
            continue
        # Lead/contemp/lag
        rho_contemp = velvet.corr(s)
        rho_lead = velvet.corr(s.groupby(level="day").shift(-1))  # velvet leads sym by one bin
        rho_lag = velvet.corr(s.groupby(level="day").shift(+1))   # velvet lags sym by one bin
        rows.append({
            "pair": f"VELVET <-> {sym}",
            "rho_contemp": round(rho_contemp, 3),
            "rho_velvet_leads": round(rho_lead, 3),
            "rho_velvet_lags": round(rho_lag, 3),
        })
    return pd.DataFrame(rows).sort_values("rho_contemp", ascending=False, key=abs)


def main():
    all_trades, all_prices, all_fut = [], [], []
    for d in (0, 1, 2):
        tr, pr = load_day(d)
        tr_tagged = merge_trade_side(tr, pr)
        pr_fut = add_future_mid(pr, HORIZONS)
        all_trades.append(tr_tagged)
        all_prices.append(pr.assign(day=d))
        all_fut.append(pr_fut.assign(day=d))
    trades = pd.concat(all_trades, ignore_index=True)
    prices = pd.concat(all_prices, ignore_index=True)
    prices_fut = pd.concat(all_fut, ignore_index=True)

    print(f"Loaded {len(trades)} trades over 3 days, {len(prices)} price rows.")
    print(f"Trade side dist: BUY={(trades['side']==1).sum()} SELL={(trades['side']==-1).sum()} AMBIG={(trades['side']==0).sum()}")

    summary = per_symbol_summary(trades, prices)
    alpha = post_trade_alpha(trades, prices_fut)
    clusters = cluster_signal(trades, prices_fut)
    bursts = burst_regime(trades, prices_fut)
    cross = cross_product_correlation(trades)

    summary.to_csv(OUT_DIR / "trades_summary.csv", index=False)
    alpha.to_csv(OUT_DIR / "trades_post_trade_alpha.csv", index=False)
    clusters.to_csv(OUT_DIR / "trades_clusters.csv", index=False)
    bursts.to_csv(OUT_DIR / "trades_bursts.csv", index=False)
    cross.to_csv(OUT_DIR / "trades_cross_product.csv", index=False)

    # Aggregate cluster signal across days for each (symbol, side)
    cluster_agg = (clusters.groupby(["symbol", "side"])
                   .agg(n_clusters=("n_clusters", "sum"),
                        H10=("H10_alpha", "mean"),
                        H50=("H50_alpha", "mean"),
                        H100=("H100_alpha", "mean"),
                        H500=("H500_alpha", "mean"))
                   .reset_index()
                   .sort_values("n_clusters", ascending=False))
    cluster_agg.to_csv(OUT_DIR / "trades_clusters_agg.csv", index=False)

    burst_agg = (bursts.groupby("symbol")
                 .agg(n_bursts=("n_bursts", "sum"),
                      mean_signed_flow=("mean_signed_flow", "mean"),
                      dir_alpha_H100=("burst_dir_alpha_H100", "mean"),
                      abs_move_H100=("burst_abs_move_H100", "mean"))
                 .reset_index()
                 .sort_values("n_bursts", ascending=False))
    burst_agg.to_csv(OUT_DIR / "trades_bursts_agg.csv", index=False)

    print("\nWrote:")
    for fn in ("trades_summary", "trades_post_trade_alpha", "trades_clusters",
               "trades_clusters_agg", "trades_bursts", "trades_bursts_agg",
               "trades_cross_product"):
        print(f"  analysis/round3/{fn}.csv")

    # Return dataframes for inspection
    return summary, alpha, cluster_agg, burst_agg, cross


if __name__ == "__main__":
    s, a, c, b, x = main()
    print("\n=== SUMMARY ===")
    print(s.to_string(index=False))
    print("\n=== POST-TRADE ALPHA (3-day pooled) ===")
    print(a.to_string(index=False))
    print("\n=== CLUSTER AGG ===")
    print(c.to_string(index=False))
    print("\n=== BURST AGG ===")
    print(b.to_string(index=False))
    print("\n=== CROSS-PRODUCT CORRELATION ===")
    print(x.to_string(index=False))
