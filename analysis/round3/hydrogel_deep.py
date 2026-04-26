"""HYDROGEL_PACK deep-dive analysis (Round 3).

Reads the 3-day R3 prices/trades CSVs, restricted to HYDROGEL_PACK, and runs
seven targeted analyses to figure out what actually makes money on HYDROGEL
specifically (the asset that consistently loses in MC for our R3 trader).

Outputs:
  analysis/round3/hydrogel_deep.json  (headline numbers)
  analysis/round3/hydrogel_deep.md    (report -- written by hand based on json)

Run: py -3.13 analysis/round3/hydrogel_deep.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "prosperity4" / "round3"
OUT_DIR = ROOT / "analysis" / "round3"
OUT_JSON = OUT_DIR / "hydrogel_deep.json"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200
HALF_SPREAD = 8  # median spread = 16 ticks (penny-jump leaves us 7 ticks from mid)


# ------------------------- IO -------------------------
def load_prices() -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for d in (0, 1, 2):
        pq = DATA / f"prices_round_3_day_{d}.parquet"
        if pq.exists():
            df = pd.read_parquet(pq)
        else:
            df = pd.read_csv(DATA / f"prices_round_3_day_{d}.csv", sep=";")
        df = df[df["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
        out[d] = df
    return out


def load_trades() -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for d in (0, 1, 2):
        pq = DATA / f"trades_round_3_day_{d}.parquet"
        if pq.exists():
            df = pd.read_parquet(pq)
        else:
            df = pd.read_csv(DATA / f"trades_round_3_day_{d}.csv", sep=";")
        df = df[df["symbol"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
        out[d] = df
    return out


# ------------------------- helpers -------------------------
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Mid, L1-OBI, microprice, spread."""
    df = df.copy()
    bv1 = df["bid_volume_1"].fillna(0).astype(float)
    av1 = df["ask_volume_1"].fillna(0).astype(float)
    bp1 = df["bid_price_1"].astype(float)
    ap1 = df["ask_price_1"].astype(float)
    mid = df["mid_price"].astype(float)
    df["mid"] = mid
    df["spread"] = ap1 - bp1
    denom = bv1 + av1
    df["l1_obi"] = np.where(denom > 0, (bv1 - av1) / denom, 0.0)
    df["microprice"] = np.where(denom > 0, (bp1 * av1 + ap1 * bv1) / denom, mid)
    df["micro_dev"] = df["microprice"] - mid
    return df


def rev_z(mid: pd.Series, window: int) -> pd.Series:
    """z = (mid - SMA_w) / std_w; SHORT when z>0, LONG when z<0 -> sign convention.
    Returns z (caller flips sign for the trade direction)."""
    ma = mid.rolling(window, min_periods=window).mean()
    sd = mid.rolling(window, min_periods=window).std(ddof=0)
    return (mid - ma) / sd.replace(0, np.nan)


def per_signal_stats(returns: np.ndarray) -> dict:
    r = returns[~np.isnan(returns)]
    if len(r) == 0:
        return {"n": 0, "mean": float("nan"), "std": float("nan"),
                "sharpe": float("nan"), "win_rate": float("nan")}
    mean = float(r.mean())
    std = float(r.std(ddof=1)) if len(r) > 1 else float("nan")
    sharpe = mean / std if std and std > 0 else float("nan")
    win = float((r > 0).mean())
    return {"n": int(len(r)), "mean": mean, "std": std,
            "sharpe": sharpe, "win_rate": win}


# ===================== 1. rev_z window x horizon sweep =====================
def revz_sweep(prices: dict[int, pd.DataFrame],
               windows=(10, 25, 50, 100, 200, 500),
               horizons=(50, 100, 200, 500, 1000),
               z_thresh: float = 1.0) -> dict:
    """For each (window, horizon, day), compute mean PnL/sig, Sharpe, n, EV/sig
    of the rev_z signal (enter when |z| > z_thresh, hold H ticks, exit at mid).
    Also a pooled-3-day stat per (window, horizon).

    PnL_per_sig = sign * (mid_{t+H} - mid_t)  where sign = -sign(z_t).
    """
    results = []
    pooled = {}
    for w in windows:
        for h in horizons:
            per_day = {}
            r_pooled = []
            for d, df in prices.items():
                mid = df["mid"].to_numpy()
                z = rev_z(df["mid"], w).to_numpy()
                fut = np.concatenate([mid[h:], np.full(h, np.nan)])
                r = np.where(np.abs(z) > z_thresh,
                             -np.sign(z) * (fut - mid),
                             np.nan)
                stats = per_signal_stats(r)
                per_day[d] = stats
                r_pooled.append(r[~np.isnan(r)])
            r_pool_arr = np.concatenate(r_pooled) if r_pooled else np.array([])
            pool_stats = per_signal_stats(r_pool_arr)
            # per-day signs (consistency check)
            day_means = [per_day[d]["mean"] for d in (0, 1, 2)]
            consistent = all(np.sign(m) == np.sign(pool_stats["mean"])
                             and not np.isnan(m) for m in day_means)
            results.append({
                "window": w, "horizon": h,
                "pooled": pool_stats,
                "per_day": per_day,
                "consistent_sign_3d": bool(consistent),
            })
            pooled[(w, h)] = pool_stats
    # rank by Sharpe x sqrt(n) to surface daily-Sharpe-equivalent
    ranked = sorted(
        results,
        key=lambda r: (-(r["pooled"]["sharpe"] or 0)
                       * np.sqrt(r["pooled"]["n"] or 0)),
    )
    return {"all": results, "best5": ranked[:5]}


# ===================== 2. OBI vs rev_z race =====================
def obi_revz_race(prices: dict[int, pd.DataFrame],
                  rev_window: int = 50,
                  z_thresh: float = 2.4,
                  horizon: int = 100) -> dict:
    """When both rev_z (|z|>thresh) AND |L1-OBI|>0.05 fire on the same tick,
    do they agree (both predict the same future direction)?

    rev_z direction: -sign(z) (mean-revert -> trade opposite the recent move)
    OBI direction: +sign(l1_obi) (mid drifts toward the heavier side)
    """
    rows = []
    for d, df in prices.items():
        z = rev_z(df["mid"], rev_window).to_numpy()
        obi = df["l1_obi"].to_numpy()
        mid = df["mid"].to_numpy()
        revz_dir = -np.sign(z)
        obi_dir = np.sign(obi)
        revz_fire = np.abs(z) > z_thresh
        obi_fire = np.abs(obi) > 0.05
        both = revz_fire & obi_fire & ~np.isnan(z)
        if both.sum() == 0:
            continue
        agree = (revz_dir[both] == obi_dir[both])
        agree_rate = float(agree.mean())
        # PnL when both fire and agree -> use revz direction
        fut = np.concatenate([mid[horizon:], np.full(horizon, np.nan)])
        # Both-fire-agree
        idx_agree = np.where(both & (revz_dir == obi_dir))[0]
        idx_disagree = np.where(both & (revz_dir != obi_dir))[0]
        # For "disagree" trades, score them as (revz direction wins?)
        ret_revz_wins = revz_dir * (fut - mid)  # positive if revz right
        ret_obi_wins = obi_dir * (fut - mid)
        rows.append({
            "day": d,
            "n_both_fire": int(both.sum()),
            "agree_rate": agree_rate,
            "n_agree": int(len(idx_agree)),
            "n_disagree": int(len(idx_disagree)),
            "agree_revz_pnl_mean": float(np.nanmean(ret_revz_wins[idx_agree]))
                if len(idx_agree) else float("nan"),
            "disagree_revz_pnl_mean": float(np.nanmean(ret_revz_wins[idx_disagree]))
                if len(idx_disagree) else float("nan"),
            "disagree_obi_pnl_mean": float(np.nanmean(ret_obi_wins[idx_disagree]))
                if len(idx_disagree) else float("nan"),
        })
    # Pooled correlation cor(L1_OBI, rev_z) using non-nan ticks
    cors = []
    for d, df in prices.items():
        z = rev_z(df["mid"], rev_window).to_numpy()
        obi = df["l1_obi"].to_numpy()
        mask = ~np.isnan(z)
        if mask.sum() > 100:
            cors.append(float(np.corrcoef(z[mask], obi[mask])[0, 1]))
    return {"per_day": rows, "cor_obi_revz_per_day": cors,
            "cor_obi_revz_mean": float(np.mean(cors)) if cors else float("nan")}


# ===================== 3. Aggressive-BUY cluster reproduction =====================
def buy_cluster_signal(prices: dict[int, pd.DataFrame],
                       trades: dict[int, pd.DataFrame],
                       window_ticks: int = 50,
                       k_min: int = 3,
                       horizons=(50, 100, 200, 500, 1000)) -> dict:
    """Reproduce the trades_signals.md finding: HYDROGEL aggressive-BUY clusters
    -> FADE +7 ticks at H=500. Per-day breakdown plus pooled.

    Aggressor inferred by: trade_price >= ask_1 -> BUY; <= bid_1 -> SELL.
    Cluster trigger: at least k_min BUY trades within window_ticks ticks.

    Signal: at the cluster-trigger tick, FADE (i.e. our PnL = -1 * (mid_{t+H} - mid_t)).
    """
    out = {"per_day": {}, "pooled": {}}
    # Build per-day price/trade joined timeline
    for h in horizons:
        out["pooled"][h] = {"means": [], "n_per_day": []}
    for d in (0, 1, 2):
        pdf = prices[d]
        tdf = trades[d]
        # Map trade timestamp -> nearest price row (timestamps align by 100)
        # Annotate aggressor side
        if tdf.empty:
            continue
        # Merge trade with the price snapshot at the SAME timestamp
        merged = tdf.merge(
            pdf[["timestamp", "bid_price_1", "ask_price_1", "mid"]],
            on="timestamp", how="left"
        )
        side = np.where(merged["price"] >= merged["ask_price_1"], 1,
                        np.where(merged["price"] <= merged["bid_price_1"], -1, 0))
        merged["side"] = side
        # For each cluster trigger tick, find: the LAST trade in the cluster window
        # is the trigger.  We sweep through trades, track BUY-trade timestamps in
        # a sliding-deque of width window_ticks * 100 (timestamp units).
        buy_ts = merged.loc[merged["side"] == 1, "timestamp"].to_numpy()
        # window_ticks ticks = window_ticks * 100 timestamp units
        ts_window = window_ticks * 100
        triggers = []
        # Sliding window — count BUYs within (t - ts_window, t]
        from collections import deque
        dq: deque = deque()
        last_trigger = -10**18
        for t in buy_ts:
            t = int(t)
            dq.append(t)
            while dq and dq[0] < t - ts_window:
                dq.popleft()
            if len(dq) >= k_min:
                # require min spacing so we don't double count overlapping
                if t - last_trigger >= ts_window:
                    triggers.append(t)
                    last_trigger = t
        if not triggers:
            continue
        # For each trigger ts, compute PnL = -(mid_{ts + H*100} - mid_{ts})
        ts2mid = pdf.set_index("timestamp")["mid"].to_dict()
        per_h = {}
        for h in horizons:
            pnls = []
            for ts in triggers:
                m0 = ts2mid.get(int(ts))
                m1 = ts2mid.get(int(ts) + h * 100)
                if m0 is None or m1 is None:
                    continue
                pnls.append(-(m1 - m0))  # FADE the buyer
            arr = np.array(pnls, dtype=float)
            stats = per_signal_stats(arr)
            per_h[h] = stats
            out["pooled"][h]["means"].append(stats["mean"] if stats["n"] else float("nan"))
            out["pooled"][h]["n_per_day"].append(stats["n"])
        out["per_day"][d] = {"n_triggers": len(triggers), "horizons": per_h}
    # Aggregate pooled
    for h in horizons:
        n_total = sum(out["pooled"][h]["n_per_day"])
        # weighted mean by n
        means = out["pooled"][h]["means"]
        ns = out["pooled"][h]["n_per_day"]
        if n_total:
            wm = sum(m * n for m, n in zip(means, ns) if not np.isnan(m)) / n_total
        else:
            wm = float("nan")
        out["pooled"][h]["weighted_mean"] = wm
        out["pooled"][h]["n_total"] = n_total
        # Per-day sign consistency
        signs_pos = sum(1 for m in means if not np.isnan(m) and m > 0)
        out["pooled"][h]["days_positive"] = signs_pos
    return out


# ===================== 4. Wide-spread MM quote-placement EV =====================
def wide_spread_mm(prices: dict[int, pd.DataFrame],
                   horizon_exit: int = 5) -> dict:
    """Compute the implied PnL/fill of quoting at different relative spread
    positions on HYDROGEL (median spread = 16).

    For each tick, if we post a buy at price P_b = best_bid + skew_b (and an ask
    similarly), the *ideal* edge is (mid - P_b) at fill, and adverse selection
    cost is (mid_{t+H_exit} - mid).  We approximate fill probability as 1.0 when
    we're inside best bid/ask (we assume bot takers will hit our quote with the
    same rate).

    Return mean per-fill edge per (skew_from_best_bid, side).
    skew=1 = penny-jump (best+1).  skew=8 = at-mid.
    """
    rows = []
    for skew in (1, 2, 4, 6, 8):
        # Pool across days
        edges_buy = []
        edges_sell = []
        for d, df in prices.items():
            mid = df["mid"].to_numpy()
            bp = df["bid_price_1"].to_numpy()
            ap = df["ask_price_1"].to_numpy()
            sp = df["spread"].to_numpy()
            valid = (sp >= 2 * skew) & ~np.isnan(mid)
            our_bid = bp + skew
            our_ask = ap - skew
            fut = np.concatenate([mid[horizon_exit:], np.full(horizon_exit, np.nan)])
            # Buy fill: edge = mid - our_bid (immediate) - (fut - mid) (adverse)
            # Net  = mid - our_bid - (fut - mid) = 2*mid - our_bid - fut
            edge_buy = (mid - our_bid) - (fut - mid)
            edge_sell = (our_ask - mid) - (mid - fut)
            edges_buy.append(edge_buy[valid & ~np.isnan(fut)])
            edges_sell.append(edge_sell[valid & ~np.isnan(fut)])
        eb = np.concatenate(edges_buy)
        es = np.concatenate(edges_sell)
        rows.append({
            "skew_from_best": skew,
            "n_valid_buy": int(len(eb)),
            "buy_edge_mean": float(eb.mean()) if len(eb) else float("nan"),
            "buy_edge_std": float(eb.std(ddof=1)) if len(eb) > 1 else float("nan"),
            "sell_edge_mean": float(es.mean()) if len(es) else float("nan"),
            "sell_edge_std": float(es.std(ddof=1)) if len(es) > 1 else float("nan"),
        })
    return {"horizon_exit": horizon_exit, "rows": rows}


# ===================== 5. OBI tier sizing =====================
def obi_tier_pnl(prices: dict[int, pd.DataFrame],
                 horizon: int = 1) -> dict:
    """For HYDROGEL, bucket each tick by L1-OBI into 5 buckets and report
    pe-bucket mean future mid drift. Then compute the PnL of a CONFIDENCE-SCALED
    position size: size = ceil(LIMIT * |OBI|) capped by LIMIT, traded in OBI
    direction at the mid (simulating a passive skew that captures mid drift)."""
    out = {"buckets": [], "size_strategies": []}
    bins = [-1.0001, -0.3, -0.05, 0.05, 0.3, 1.0001]
    labels = ["q0(<-0.3)", "q1(-0.3,-0.05)", "q2(|.|<=0.05)", "q3(0.05,0.3)", "q4(>0.3)"]
    bucket_means = {l: [] for l in labels}
    bucket_ns = {l: [] for l in labels}
    for d, df in prices.items():
        mid = df["mid"].to_numpy()
        obi = df["l1_obi"].to_numpy()
        fut = np.concatenate([mid[horizon:], np.full(horizon, np.nan)])
        ret = fut - mid
        for i, lab in enumerate(labels):
            mask = (obi >= bins[i]) & (obi < bins[i+1]) & ~np.isnan(ret)
            if mask.sum():
                bucket_means[lab].append(float(np.nanmean(ret[mask])))
                bucket_ns[lab].append(int(mask.sum()))
    for lab in labels:
        out["buckets"].append({
            "bucket": lab,
            "per_day_mean": bucket_means[lab],
            "per_day_n": bucket_ns[lab],
        })
    # Strategies: full-size (LIMIT) when |OBI|>thresh, vs confidence-scaled
    for size_max in (50, 100, 150, 200):
        per_day_pnl = []
        per_day_fills = []
        for d, df in prices.items():
            mid = df["mid"].to_numpy()
            obi = df["l1_obi"].to_numpy()
            fut = np.concatenate([mid[horizon:], np.full(horizon, np.nan)])
            ret = fut - mid
            mask = (np.abs(obi) > 0.05) & ~np.isnan(ret)
            sz = np.minimum(size_max, np.ceil(np.abs(obi) * size_max).astype(int))
            pnl = np.where(mask, np.sign(obi) * ret * sz, 0.0)
            per_day_pnl.append(float(np.nansum(pnl)))
            per_day_fills.append(int(mask.sum()))
        out["size_strategies"].append({
            "size_max": size_max,
            "per_day_pnl": per_day_pnl,
            "per_day_fills": per_day_fills,
            "total_pnl": float(np.sum(per_day_pnl)),
        })
    return out


# ===================== 6. v3 rev_z replay on historical CSV =====================
def replay_rev_z_v3(prices: dict[int, pd.DataFrame],
                    window: int = 50,
                    z_thresh: float = 2.4,
                    take_size: int = 140,
                    hold_ticks: int = 359) -> dict:
    """Simulate the v3 rev_z parameters on historical HYDROGEL data.

    Trade policy:
      - When |z| > z_thresh AND no open trade -> enter at the OPPOSITE side
        of the book (cross spread): if z>0 (overpriced) -> SELL at best_bid;
        if z<0 (underpriced) -> BUY at best_ask.
      - Hold for hold_ticks ticks then exit at MID (best estimate).

    This is intentionally faithful to the v3 trader semantics (aggressive
    take). Outputs total PnL per day and signal-level stats.
    """
    rows = []
    for d, df in prices.items():
        mid = df["mid"].to_numpy()
        bp = df["bid_price_1"].to_numpy()
        ap = df["ask_price_1"].to_numpy()
        z = rev_z(df["mid"], window).to_numpy()
        # Walk forward; respect cooldown
        n = len(mid)
        i = 0
        trades = []
        while i < n:
            if not np.isnan(z[i]) and abs(z[i]) > z_thresh:
                exit_i = i + hold_ticks
                if exit_i >= n:
                    break
                if z[i] > 0:
                    # Sell at best_bid, buy back at mid
                    entry = bp[i]
                    exit_p = mid[exit_i]
                    pnl_per_unit = entry - exit_p
                else:
                    # Buy at best_ask, sell at mid
                    entry = ap[i]
                    exit_p = mid[exit_i]
                    pnl_per_unit = exit_p - entry
                trades.append({
                    "i": i, "side": int(np.sign(z[i])), "z": float(z[i]),
                    "pnl_per_unit": float(pnl_per_unit),
                    "pnl_total": float(pnl_per_unit) * take_size,
                })
                i = exit_i + 1  # cooldown until exit
            else:
                i += 1
        ppt = np.array([t["pnl_per_unit"] for t in trades])
        ppt_total = np.array([t["pnl_total"] for t in trades])
        rows.append({
            "day": d,
            "n_trades": len(trades),
            "mean_pnl_per_unit": float(ppt.mean()) if len(ppt) else float("nan"),
            "win_rate": float((ppt > 0).mean()) if len(ppt) else float("nan"),
            "total_pnl_size140": float(ppt_total.sum()) if len(ppt_total) else 0.0,
            "median_pnl_per_unit": float(np.median(ppt)) if len(ppt) else float("nan"),
        })
    return {"rows": rows,
            "params": {"window": window, "z_thresh": z_thresh,
                       "take_size": take_size, "hold_ticks": hold_ticks}}


# ===================== 7. Strategy candidate scoring =====================
def passive_obi_skew_pnl(prices: dict[int, pd.DataFrame],
                         horizon: int = 1,
                         thresh: float = 0.05,
                         skew_size: int = 200) -> dict:
    """The 'do-nothing-but-skew' upper bound: at every tick where |OBI|>thresh,
    assume our quote in the favoured direction captures (mid_{t+H} - mid_t).
    skew_size = how many lots/fill our quote moves."""
    rows = []
    for d, df in prices.items():
        mid = df["mid"].to_numpy()
        obi = df["l1_obi"].to_numpy()
        fut = np.concatenate([mid[horizon:], np.full(horizon, np.nan)])
        ret = fut - mid
        mask = (np.abs(obi) > thresh) & ~np.isnan(ret)
        signed = np.sign(obi) * ret
        rows.append({
            "day": d,
            "n_signals": int(mask.sum()),
            "mean_per_sig_ticks": float(np.nanmean(signed[mask])) if mask.sum() else float("nan"),
            "win_rate": float(np.nanmean(signed[mask] > 0)) if mask.sum() else float("nan"),
            "total_ticks": float(np.nansum(signed[mask])),
            "implied_pnl_size_one": float(np.nansum(signed[mask])),
            "implied_pnl_skew_size": float(np.nansum(signed[mask]) * skew_size),
        })
    return {"rows": rows, "horizon": horizon, "thresh": thresh, "skew_size": skew_size}


# ===================== Driver =====================
def main():
    prices = load_prices()
    trades = load_trades()

    # Add features per day
    for d in prices:
        prices[d] = add_features(prices[d])

    # Sanity-check basics
    sanity = {}
    for d, df in prices.items():
        sanity[f"day{d}"] = {
            "n_rows": int(len(df)),
            "median_spread": float(df["spread"].median()),
            "mid_min": float(df["mid"].min()),
            "mid_max": float(df["mid"].max()),
            "mid_std": float(df["mid"].std()),
            "obi_nonzero_frac": float((df["l1_obi"].abs() > 0.05).mean()),
        }

    out: dict = {"product": PRODUCT, "limit": LIMIT, "sanity": sanity}

    print("[1/7] rev_z window x horizon sweep ...")
    out["revz_sweep"] = revz_sweep(prices)

    print("[2/7] OBI vs rev_z race condition ...")
    out["obi_revz_race_z2_4_h100"] = obi_revz_race(prices, rev_window=50,
                                                    z_thresh=2.4, horizon=100)
    out["obi_revz_race_z1_h200"] = obi_revz_race(prices, rev_window=50,
                                                  z_thresh=1.0, horizon=200)

    print("[3/7] Aggressive-BUY cluster signal reproduction ...")
    out["buy_cluster_k3_w50"] = buy_cluster_signal(prices, trades,
                                                    window_ticks=50, k_min=3)
    out["buy_cluster_k4_w50"] = buy_cluster_signal(prices, trades,
                                                    window_ticks=50, k_min=4)
    out["buy_cluster_k3_w25"] = buy_cluster_signal(prices, trades,
                                                    window_ticks=25, k_min=3)

    print("[4/7] Wide-spread MM quote-placement EV ...")
    out["wide_spread_mm"] = wide_spread_mm(prices, horizon_exit=5)
    out["wide_spread_mm_h20"] = wide_spread_mm(prices, horizon_exit=20)

    print("[5/7] OBI tier sizing ...")
    out["obi_tiers_h1"] = obi_tier_pnl(prices, horizon=1)
    out["obi_tiers_h5"] = obi_tier_pnl(prices, horizon=5)

    print("[6/7] v3 rev_z replay on historical CSV ...")
    out["v3_revz_replay"] = replay_rev_z_v3(prices)
    # Also: lighter parameterizations to see what would have worked
    out["v3_revz_replay_w200_z2"] = replay_rev_z_v3(prices, window=200, z_thresh=2.0,
                                                     take_size=100, hold_ticks=200)
    out["v3_revz_replay_w50_z1_5"] = replay_rev_z_v3(prices, window=50, z_thresh=1.5,
                                                      take_size=50, hold_ticks=200)

    print("[7/7] Passive-OBI-skew upper bound ...")
    out["passive_obi_skew_h1"] = passive_obi_skew_pnl(prices, horizon=1, skew_size=200)
    out["passive_obi_skew_h5"] = passive_obi_skew_pnl(prices, horizon=5, skew_size=200)

    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nWrote {OUT_JSON}")
    # Print a few headlines
    print("\n=== HEADLINES ===")
    print("Top 5 (window, horizon) by daily-Sharpe:")
    for r in out["revz_sweep"]["best5"]:
        ps = r["pooled"]
        print(f"  w={r['window']:4d} H={r['horizon']:5d}  mean={ps['mean']:+.3f} "
              f"sharpe={ps['sharpe']:+.3f} n={ps['n']}  "
              f"3day_consistent={r['consistent_sign_3d']}")
    print("\nv3 rev_z replay (w=50 z=2.4 size=140 hold=359):")
    for row in out["v3_revz_replay"]["rows"]:
        print(f"  day{row['day']}: n={row['n_trades']} mean/unit={row['mean_pnl_per_unit']:+.3f} "
              f"win={row['win_rate']:.2f} total={row['total_pnl_size140']:+,.0f}")
    print("\nPassive-OBI-skew upper bound (size=200):")
    for row in out["passive_obi_skew_h1"]["rows"]:
        print(f"  day{row['day']}: n_sig={row['n_signals']} "
              f"mean_ticks={row['mean_per_sig_ticks']:+.3f} "
              f"total_size_one={row['implied_pnl_size_one']:+,.0f} "
              f"size200={row['implied_pnl_skew_size']:+,.0f}")
    print("\nWide-spread MM quote-placement (H_exit=5):")
    for row in out["wide_spread_mm"]["rows"]:
        print(f"  skew={row['skew_from_best']}  buy_edge={row['buy_edge_mean']:+.3f}  "
              f"sell_edge={row['sell_edge_mean']:+.3f}  n={row['n_valid_buy']}")
    print("\nBUY cluster fade (k=3, w=50 ticks):")
    for h, agg in out["buy_cluster_k3_w50"]["pooled"].items():
        print(f"  H={h}: weighted_mean={agg['weighted_mean']:+.3f} ticks  "
              f"n_total={agg['n_total']}  days_positive={agg['days_positive']}/3")


if __name__ == "__main__":
    main()
