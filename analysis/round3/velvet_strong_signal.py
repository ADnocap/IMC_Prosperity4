"""Find 'high-conviction' signal regimes on VELVET.

Baseline OBI: corr +0.28 with next-tick Δmid, 68.5% hit rate.
  Goal: isolate regimes where hit rate climbs to 80%+ and/or
  magnitude |Δmid| conditional on signal is large. Those are where
  we should deploy max leverage.

Tests:
  1. OBI magnitude vs hit rate: does |OBI|>0.8 have stronger edge?
  2. Full-depth OBI (3 levels) vs top-of-book OBI
  3. Cumulative OBI (EMA / sum over last K ticks)
  4. OBI persistence (same-sign streak)
  5. Multi-tick return confirmation (OBI × recent_mid_return sign)
  6. Interaction: strong OBI + confirming price momentum
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "prosperity4" / "round3"
SPOT = "VELVETFRUIT_EXTRACT"


def load_velvet(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"prices_round_3_day_{day}.csv", sep=";")
    df = df.loc[df["product"] == SPOT].sort_values("timestamp").reset_index(drop=True)
    return df


def top_obi(df):
    bv = df["bid_volume_1"].fillna(0).astype(float)
    av = df["ask_volume_1"].fillna(0).astype(float)
    tot = bv + av
    return np.where(tot > 0, (bv - av) / tot, 0.0)


def depth_obi(df, levels=3):
    bv = sum(df[f"bid_volume_{i}"].fillna(0).astype(float) for i in range(1, levels + 1))
    av = sum(df[f"ask_volume_{i}"].fillna(0).astype(float) for i in range(1, levels + 1))
    tot = bv + av
    return np.where(tot > 0, (bv - av) / tot, 0.0)


def microprice_skew_norm(df):
    bb = df["bid_price_1"].astype(float)
    ba = df["ask_price_1"].astype(float)
    bv = df["bid_volume_1"].fillna(0).astype(float)
    av = df["ask_volume_1"].fillna(0).astype(float)
    tot = bv + av
    mid = 0.5 * (bb + ba)
    micro = np.where(tot > 0, (ba * bv + bb * av) / tot, mid)
    sp = ba - bb
    return np.where(sp > 0, (micro - mid) / sp, 0.0)


def signed_trade_flow(trades_df, ts_index, mid_series):
    """Per-tick signed trade flow: sum of qty*sign(price - mid at t)."""
    if trades_df.empty:
        return np.zeros(len(ts_index))
    tfm = trades_df.copy()
    tfm["mid_at_ts"] = tfm["timestamp"].map(mid_series)
    tfm["side"] = np.where(tfm["price"] > tfm["mid_at_ts"], 1,
                           np.where(tfm["price"] < tfm["mid_at_ts"], -1, 0))
    tfm["signed_qty"] = tfm["side"] * tfm["quantity"]
    grouped = tfm.groupby("timestamp")["signed_qty"].sum()
    return grouped.reindex(ts_index).fillna(0).values


def evaluate_signal(signal, future_dmid, name="signal", buckets=None):
    """Corr, hit rate, conditional magnitudes at various |signal| thresholds."""
    mask = ~(np.isnan(signal) | np.isnan(future_dmid))
    s = signal[mask]
    d = future_dmid[mask]
    out = {"name": name, "n": len(s), "corr": float(np.corrcoef(s, d)[0, 1])}
    # Overall hit rate (ignoring zeros)
    nz = (s != 0) & (d != 0)
    hit = float(((np.sign(s) == np.sign(d)) & nz).sum() / max(nz.sum(), 1))
    out["hit_rate_all"] = hit
    out["active_all"] = int(nz.sum())

    # Per-|signal| bucket
    if buckets is None:
        buckets = [(0.05, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
    bucket_rows = []
    for lo, hi in buckets:
        m = (np.abs(s) >= lo) & (np.abs(s) < hi)
        if m.sum() < 20:
            continue
        sub_s = s[m]; sub_d = d[m]
        nz2 = (sub_s != 0) & (sub_d != 0)
        hr = float(((np.sign(sub_s) == np.sign(sub_d)) & nz2).sum() / max(nz2.sum(), 1))
        exp_dmid = float(np.mean(np.sign(sub_s) * sub_d))  # expected return in signal direction
        bucket_rows.append({"lo": lo, "hi": hi, "n": int(m.sum()),
                            "hit_rate": hr, "exp_dmid": exp_dmid})
    out["buckets"] = bucket_rows
    return out


def print_eval(res, indent="  "):
    print(f"{indent}{res['name']:32s} corr={res['corr']:+.4f}  "
          f"hit_all={res['hit_rate_all']:.3f}  n_active={res['active_all']}")
    for b in res["buckets"]:
        print(f"{indent}  |s|∈[{b['lo']:.2f},{b['hi']:.2f}]  "
              f"n={b['n']:6d}  hit={b['hit_rate']:.3f}  "
              f"E[Δmid|dir]={b['exp_dmid']:+.3f}")


def main():
    frames = []
    for d in (0, 1, 2):
        df = load_velvet(d)
        df["_day"] = d
        frames.append(df)
    all_px = pd.concat(frames, ignore_index=True)

    # Next-tick Δmid within each day
    dmid_1 = []
    dmid_5 = []
    dmid_10 = []
    for d, sub in all_px.groupby("_day"):
        m = sub["mid_price"].values.astype(float)
        d1 = np.append(np.diff(m), np.nan)
        d5 = np.append(m[5:] - m[:-5], [np.nan]*5)
        d10 = np.append(m[10:] - m[:-10], [np.nan]*10)
        dmid_1.append(d1); dmid_5.append(d5); dmid_10.append(d10)
    all_px["dmid_1"] = np.concatenate(dmid_1)
    all_px["dmid_5"] = np.concatenate(dmid_5)
    all_px["dmid_10"] = np.concatenate(dmid_10)

    # Signal A: top-of-book OBI
    obi1 = top_obi(all_px)
    # Signal B: depth-3 OBI
    obi3 = depth_obi(all_px, 3)
    # Signal C: microprice skew
    mp = microprice_skew_norm(all_px) * 2.0
    # Signal D: EMA-smoothed OBI (rolling mean, horizon 5)
    obi_series = pd.Series(obi1)
    ema_alpha = 0.3
    ema_obi = obi_series.ewm(alpha=ema_alpha, adjust=False).mean().values
    # Signal E: rolling sum of OBI (last 5 ticks)
    rolling_obi = obi_series.rolling(5, min_periods=1).sum().values / 5.0
    # Signal F: OBI * recent return (momentum confirmation)
    recent_ret = pd.Series(dmid_1[0]).shift(1).values if len(dmid_1) == 1 else \
                 all_px["dmid_1"].shift(1).fillna(0).values
    # simpler: use previous-tick Δmid sign times OBI magnitude
    prev_dmid = all_px.groupby("_day")["dmid_1"].shift(1).fillna(0).values
    mom_sign = np.sign(prev_dmid)
    obi_times_mom = obi1 * np.where(mom_sign == np.sign(obi1), 1.5, 0.7)  # boost when aligned

    # Signal G: combined composite — weighted sum of obi1, obi3, mp
    combined = 0.4 * obi1 + 0.3 * obi3 + 0.3 * mp

    # Signal H: combined * persistence (require EMA same sign as raw)
    persistence = (np.sign(ema_obi) == np.sign(obi1)).astype(float)
    combined_pers = combined * persistence

    print("=" * 72)
    print("HORIZON = 1 tick")
    print("=" * 72)
    for name, sig in [
        ("OBI (top-of-book)", obi1),
        ("OBI (depth-3)", obi3),
        ("Microprice skew (×2)", mp),
        ("OBI EMA (α=0.3)", ema_obi),
        ("OBI rolling mean (5)", rolling_obi),
        ("OBI × momentum confirm", obi_times_mom),
        ("Composite (0.4/0.3/0.3)", combined),
        ("Composite × persistence", combined_pers),
    ]:
        res = evaluate_signal(sig, all_px["dmid_1"].values, name=name)
        print_eval(res)

    print("\n" + "=" * 72)
    print("HORIZON = 5 ticks (cumulative Δmid)")
    print("=" * 72)
    for name, sig in [
        ("OBI (top)", obi1),
        ("OBI EMA (α=0.3)", ema_obi),
        ("OBI rolling sum (5)", rolling_obi * 5),
        ("Composite", combined),
    ]:
        res = evaluate_signal(sig, all_px["dmid_5"].values, name=name)
        print_eval(res)

    print("\n" + "=" * 72)
    print("HORIZON = 10 ticks")
    print("=" * 72)
    for name, sig in [
        ("OBI (top)", obi1),
        ("OBI rolling sum (10)",
         pd.Series(obi1).rolling(10, min_periods=1).sum().values / 10.0),
        ("Composite", combined),
    ]:
        res = evaluate_signal(sig, all_px["dmid_10"].values, name=name)
        print_eval(res)


if __name__ == "__main__":
    main()
