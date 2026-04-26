"""Per-Mark counterparty profiling for Round 4.

Reads R4 trades + prices CSVs (3 days), classifies each trade as aggressive/passive
on each side using the contemporaneous mid, computes post-trade mid drift at multiple
horizons, builds counterparty pair frequencies, and emits:

  - mark_profiles.json   per-Mark, per-product, per-side stats
  - mark_profiles.md     human-readable report
  - signals.json         machine-readable actionable signals

Run:  py -3.13 calibration/marks/profile_marks.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "prosperity4" / "round4"
OUT_DIR = ROOT / "calibration" / "marks"

DAYS = [1, 2, 3]
PRODUCTS = [
    "HYDROGEL_PACK",
    "VELVETFRUIT_EXTRACT",
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]
HORIZONS = [1, 50, 200, 1000]  # in ticks (1 tick = 100 timestamp units)
TICK = 100


# ---------------------------------------------------------------------------
# Data loading & enrichment
# ---------------------------------------------------------------------------
def load_day(day: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = pd.read_csv(DATA_DIR / f"trades_round_4_day_{day}.csv", sep=";")
    prices = pd.read_csv(DATA_DIR / f"prices_round_4_day_{day}.csv", sep=";")
    trades["day"] = day
    prices["day"] = day
    return trades, prices


def build_mid_lookup(prices: pd.DataFrame) -> dict[str, pd.Series]:
    """Return {product: Series indexed by timestamp -> mid_price}."""
    mids: dict[str, pd.Series] = {}
    for product, grp in prices.groupby("product", sort=False):
        s = grp.set_index("timestamp")["mid_price"].sort_index()
        # Some rows may have NaN mids (no quotes on a side); ffill is safe for drift calc.
        s = s.ffill().bfill()
        mids[product] = s
    return mids


def classify_and_drift(
    trades: pd.DataFrame, mids: dict[str, pd.Series]
) -> pd.DataFrame:
    """Add mid_at_trade, side_class (bid/ask/mid), and post-trade drifts at horizons."""
    out_rows = []
    for product, grp in trades.groupby("symbol", sort=False):
        if product not in mids:
            continue
        mid_series = mids[product]
        ts_idx = mid_series.index.values
        mid_vals = mid_series.values

        # For each trade, look up contemporaneous mid + future mids at each horizon
        for row in grp.itertuples(index=False):
            t = int(row.timestamp)
            price = float(row.price)
            # contemporaneous mid (left-aligned: most recent observation at or before t)
            pos = np.searchsorted(ts_idx, t, side="right") - 1
            if pos < 0:
                continue
            mid_now = float(mid_vals[pos])
            # Classify
            if price <= mid_now - 0.5:
                side_class = "at_bid"  # someone sold at bid → buyer is passive, seller is aggressive
            elif price >= mid_now + 0.5:
                side_class = "at_ask"  # someone bought at ask → buyer aggressive, seller passive
            else:
                side_class = "at_mid"
            # Future drifts
            drifts = {}
            for H in HORIZONS:
                target_t = t + H * TICK
                fpos = np.searchsorted(ts_idx, target_t, side="right") - 1
                if fpos < 0 or fpos >= len(mid_vals):
                    drifts[f"drift_{H}"] = np.nan
                else:
                    drifts[f"drift_{H}"] = float(mid_vals[fpos]) - price
            out_rows.append(
                {
                    "day": row.day,
                    "timestamp": t,
                    "buyer": row.buyer,
                    "seller": row.seller,
                    "symbol": product,
                    "price": price,
                    "quantity": int(row.quantity),
                    "mid_now": mid_now,
                    "side_class": side_class,
                    **drifts,
                }
            )
    return pd.DataFrame(out_rows)


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------
def per_mark_per_product_per_side(enr: pd.DataFrame) -> dict:
    """Build the per-Mark / per-product / per-side stats dict."""
    marks = sorted(set(enr["buyer"].dropna().unique()) | set(enr["seller"].dropna().unique()))
    profile: dict = {}
    for mark in marks:
        profile[mark] = {"products": {}}
        for product in PRODUCTS:
            sub = enr[enr["symbol"] == product]
            if sub.empty:
                continue
            cell = {}
            for side in ("buyer", "seller"):
                rows = sub[sub[side] == mark]
                if rows.empty:
                    continue
                # Aggressive / passive classification depends on side
                if side == "buyer":
                    n_aggr = int((rows["side_class"] == "at_ask").sum())
                    n_pass = int((rows["side_class"] == "at_bid").sum())
                else:
                    n_aggr = int((rows["side_class"] == "at_bid").sum())
                    n_pass = int((rows["side_class"] == "at_ask").sum())
                n_mid = int((rows["side_class"] == "at_mid").sum())
                n = len(rows)
                vol = int(rows["quantity"].sum())

                # Drifts: signed so that "informed" is always positive.
                # Buyer informed → mid goes up after they buy → drift_H > 0
                # Seller informed → mid goes down after they sell → drift_H < 0,
                # so flip sign for sellers to make positive=informed.
                sign = 1 if side == "buyer" else -1
                drift_stats = {}
                per_day_stats = {}
                for H in HORIZONS:
                    col = f"drift_{H}"
                    vals = rows[col].dropna().values * sign
                    drift_stats[f"H{H}_mean"] = float(np.mean(vals)) if len(vals) else None
                    drift_stats[f"H{H}_median"] = float(np.median(vals)) if len(vals) else None
                    drift_stats[f"H{H}_std"] = float(np.std(vals)) if len(vals) else None
                    drift_stats[f"H{H}_n"] = int(len(vals))
                # Per-day breakdown for honesty (H=200 only)
                for d in DAYS:
                    d_rows = rows[rows["day"] == d]
                    vals = d_rows["drift_200"].dropna().values * sign
                    per_day_stats[f"day{d}_H200_mean"] = (
                        float(np.mean(vals)) if len(vals) else None
                    )
                    per_day_stats[f"day{d}_n"] = int(len(d_rows))

                cell[side] = {
                    "n_trades": n,
                    "volume": vol,
                    "agg_pct": round(100 * n_aggr / n, 1) if n else None,
                    "pass_pct": round(100 * n_pass / n, 1) if n else None,
                    "mid_pct": round(100 * n_mid / n, 1) if n else None,
                    "drift": drift_stats,
                    "per_day": per_day_stats,
                }
            if cell:
                profile[mark]["products"][product] = cell
    return profile


def overall_summary(enr: pd.DataFrame, profile: dict) -> dict:
    summary = {}
    for mark, mp in profile.items():
        total_vol = 0
        total_n = 0
        n_aggr = 0
        n_pass = 0
        # Mean H200 informed drift weighted by n
        weighted_drift = 0.0
        weight = 0
        # Per-day day1/2/3 H=200 drift (weighted)
        per_day = {d: {"sum": 0.0, "w": 0} for d in DAYS}
        for prod, cell in mp["products"].items():
            for side, s in cell.items():
                total_vol += s["volume"]
                total_n += s["n_trades"]
                # aggressive count
                ap = s.get("agg_pct") or 0.0
                pp = s.get("pass_pct") or 0.0
                n_aggr += s["n_trades"] * ap / 100.0
                n_pass += s["n_trades"] * pp / 100.0
                # drift
                d_mean = s["drift"].get("H200_mean")
                d_n = s["drift"].get("H200_n", 0)
                if d_mean is not None and d_n:
                    weighted_drift += d_mean * d_n
                    weight += d_n
                for d in DAYS:
                    v = s["per_day"].get(f"day{d}_H200_mean")
                    n = s["per_day"].get(f"day{d}_n", 0)
                    if v is not None and n:
                        per_day[d]["sum"] += v * n
                        per_day[d]["w"] += n
        summary[mark] = {
            "total_trades": total_n,
            "total_volume": total_vol,
            "agg_pct": round(100 * n_aggr / total_n, 1) if total_n else None,
            "pass_pct": round(100 * n_pass / total_n, 1) if total_n else None,
            "informed_drift_H200": round(weighted_drift / weight, 3) if weight else None,
            "informed_drift_H200_per_day": {
                f"day{d}": (round(per_day[d]["sum"] / per_day[d]["w"], 3) if per_day[d]["w"] else None)
                for d in DAYS
            },
        }
    return summary


def pair_frequencies(enr: pd.DataFrame) -> dict:
    """All-day, all-product (buyer, seller) pair counts and per-day breakdowns."""
    pairs = (
        enr.groupby(["buyer", "seller"])
        .agg(n_trades=("quantity", "size"), volume=("quantity", "sum"))
        .reset_index()
        .sort_values("n_trades", ascending=False)
    )
    per_day_pairs = {}
    for d in DAYS:
        sub = enr[enr["day"] == d]
        per_day_pairs[f"day{d}"] = (
            sub.groupby(["buyer", "seller"])
            .size()
            .reset_index(name="n_trades")
            .sort_values("n_trades", ascending=False)
            .head(15)
            .to_dict(orient="records")
        )
    return {
        "all_days_top": pairs.head(25).to_dict(orient="records"),
        "per_day_top": per_day_pairs,
    }


# ---------------------------------------------------------------------------
# Classification & signal extraction
# ---------------------------------------------------------------------------
def classify_cell(side_stats: dict) -> str:
    """Classify a (Mark, product, side) cell as informed/dumb/passive/neutral."""
    if not side_stats:
        return "—"
    n = side_stats["n_trades"]
    if n < 8:
        return "n/a"
    agg = side_stats.get("agg_pct") or 0.0
    drift = side_stats["drift"].get("H200_mean")
    if drift is None:
        return "n/a"
    # passive if very low aggression
    if agg < 15:
        # passive - is it adversely selected? (drift > 0 means side wins)
        if drift > 0.5:
            return "passive_lucky"
        if drift < -0.5:
            return "passive_dumb"  # consistently wrong-side passive = adverse selection target
        return "passive_neutral"
    # active
    if drift > 0.5:
        return "informed"
    if drift < -0.5:
        return "dumb"
    return "neutral"


def actionable_signals(profile: dict, summary: dict) -> list[dict]:
    """Pull out concrete trade signals: which Mark, which product, what action."""
    signals = []
    for mark, mp in profile.items():
        for product, cell in mp["products"].items():
            for side, s in cell.items():
                n = s["n_trades"]
                if n < 25:  # minimum sample
                    continue
                drift = s["drift"].get("H200_mean")
                if drift is None or abs(drift) < 0.5:
                    continue
                agg = s.get("agg_pct") or 0.0
                # Per-day stratification for confidence
                d_means = [s["per_day"].get(f"day{d}_H200_mean") for d in DAYS]
                d_counts = [s["per_day"].get(f"day{d}_n", 0) for d in DAYS]
                # Day-1 and day-2 are same FV path → treat as one sample. Day 3 independent.
                d12_means = [m for m, c in zip(d_means[:2], d_counts[:2]) if m is not None and c >= 5]
                d3_mean = d_means[2] if d_counts[2] >= 5 else None
                avg_d12 = float(np.mean(d12_means)) if d12_means else None
                signs_consistent = None
                if avg_d12 is not None and d3_mean is not None:
                    signs_consistent = (avg_d12 * drift > 0) and (d3_mean * drift > 0)
                elif avg_d12 is not None:
                    signs_consistent = avg_d12 * drift > 0
                # Action
                if drift > 0:
                    # mark's side outperforms → "follow" them
                    action_side = "BUY" if side == "buyer" else "SELL"
                    note = f"follow {mark}: when they {action_side}, mid moves +{drift:.2f} over 200 ticks"
                else:
                    # mark's side underperforms → "fade" them (take opposite side)
                    action_side = "SELL" if side == "buyer" else "BUY"
                    note = f"fade {mark}: when they {('BUY' if side=='buyer' else 'SELL')}, mid drops {drift:.2f}/200t → we {action_side} the print"
                confidence = (
                    "high" if signs_consistent and n >= 60
                    else "med" if signs_consistent
                    else "low"
                )
                signals.append(
                    {
                        "mark": mark,
                        "product": product,
                        "mark_side": side,
                        "n_trades": n,
                        "agg_pct": agg,
                        "drift_H200_mean": round(drift, 3),
                        "per_day_H200": {f"day{d}": d_means[i] for i, d in enumerate(DAYS)},
                        "per_day_n": {f"day{d}": d_counts[i] for i, d in enumerate(DAYS)},
                        "action_side_for_us": action_side,
                        "horizon_ticks": 200,
                        "confidence": confidence,
                        "note": note,
                    }
                )
    # Sort by abs(drift) * sqrt(n) so big-edge, big-sample signals come first
    signals.sort(key=lambda x: -abs(x["drift_H200_mean"]) * np.sqrt(x["n_trades"]))
    return signals


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def build_md(summary: dict, profile: dict, pairs: dict, signals: list[dict]) -> str:
    lines = ["# Round 4 — Per-Mark Counterparty Profiles", ""]
    lines.append(
        "Source: `data/prosperity4/round4/{trades,prices}_round_4_day_{1,2,3}.csv`. "
        "R4 days 1–2 reproduce R3 days 1–2 (same FV path); day 3 is fresh data. "
        "Per-day stratification of every effect is in `mark_profiles.json`."
    )
    lines.append("")
    lines.append("## 7-Mark summary (all products, all days)")
    lines.append("")
    lines.append(
        "| Mark | Trades | Volume | Aggressive % | Passive % | Mean informed drift @H=200 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for mark, s in sorted(summary.items()):
        lines.append(
            f"| {mark} | {s['total_trades']} | {s['total_volume']} | "
            f"{s['agg_pct']} | {s['pass_pct']} | {s['informed_drift_H200']} |"
        )
    lines.append("")
    lines.append(
        "*Informed drift sign convention*: positive = the Mark's trades print on the "
        "side that wins over the next 200 ticks (buyer drift = future mid − price; "
        "seller drift sign-flipped). Positive ⇒ informed; negative ⇒ adversely-selected / dumb."
    )
    lines.append("")
    lines.append("### Same metric, per day (H=200)")
    lines.append("")
    lines.append("| Mark | Day 1 | Day 2 | Day 3 |")
    lines.append("|---|---:|---:|---:|")
    for mark, s in sorted(summary.items()):
        pd_ = s["informed_drift_H200_per_day"]
        lines.append(f"| {mark} | {pd_['day1']} | {pd_['day2']} | {pd_['day3']} |")
    lines.append("")

    # Per-product classification grid
    lines.append("## Per-product classification grid")
    lines.append("")
    lines.append(
        "Each cell shows the Mark's role on that product, computed from BOTH sides "
        "(buyer, seller). Format: `buyer-side / seller-side`. "
        "Codes: `inf` informed (drift>+0.5), `dumb` adverse (drift<−0.5), "
        "`neu` neutral (|drift|≤0.5), `passΛ` passive lucky, `passN` passive neutral, "
        "`passD` passive dumb (passive but adverse), `n/a` <8 trades."
    )
    lines.append("")
    header = "| Mark | " + " | ".join(p.replace("VELVETFRUIT_EXTRACT", "VELVET").replace("HYDROGEL_PACK", "HYDRO") for p in PRODUCTS) + " |"
    lines.append(header)
    lines.append("|---" * (len(PRODUCTS) + 1) + "|")
    code_map = {
        "informed": "inf",
        "dumb": "dumb",
        "neutral": "neu",
        "passive_lucky": "passΛ",
        "passive_neutral": "passN",
        "passive_dumb": "passD",
        "n/a": "n/a",
        "—": "—",
    }
    for mark in sorted(profile.keys()):
        row = [mark]
        for prod in PRODUCTS:
            cell = profile[mark]["products"].get(prod, {})
            buyer_c = code_map[classify_cell(cell.get("buyer", {}))]
            seller_c = code_map[classify_cell(cell.get("seller", {}))]
            row.append(f"{buyer_c}/{seller_c}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Pair frequencies
    lines.append("## Counterparty pair frequencies (all 3 days, all products)")
    lines.append("")
    lines.append("| Buyer → Seller | Trades | Volume |")
    lines.append("|---|---:|---:|")
    for r in pairs["all_days_top"][:20]:
        lines.append(f"| {r['buyer']} → {r['seller']} | {r['n_trades']} | {r['volume']} |")
    lines.append("")
    for d, plist in pairs["per_day_top"].items():
        lines.append(f"### Top pairs — {d}")
        lines.append("")
        lines.append("| Buyer → Seller | Trades |")
        lines.append("|---|---:|")
        for r in plist[:10]:
            lines.append(f"| {r['buyer']} → {r['seller']} | {r['n_trades']} |")
        lines.append("")

    # Top actionable signals
    lines.append("## Top actionable signals (drift @ H=200 ticks, sample-weighted)")
    lines.append("")
    lines.append(
        "Only signals with |drift|≥0.5 XIRECs and n≥25 trades are listed. "
        "Confidence: `high` = signs agree on day1+2 *and* day3, n≥60. "
        "`med` = signs agree across our two FV samples but lighter sample. "
        "`low` = single-sample (likely day3 alone or sign disagrees)."
    )
    lines.append("")
    lines.append(
        "| # | Mark | Side | Product | n | Aggr% | Drift@200 | Per-day [d1,d2,d3] | Conf | Action |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---|---|---|")
    for i, sig in enumerate(signals[:30], 1):
        pd_ = sig["per_day_H200"]
        per_day_str = (
            f"[{pd_['day1']}, {pd_['day2']}, {pd_['day3']}]"
        )
        action = (
            f"{sig['action_side_for_us']} on {sig['product']} "
            f"when we see {sig['mark']} {('BUY' if sig['mark_side']=='buyer' else 'SELL')} in last 50t"
        )
        lines.append(
            f"| {i} | {sig['mark']} | {sig['mark_side']} | {sig['product']} | "
            f"{sig['n_trades']} | {sig['agg_pct']} | {sig['drift_H200_mean']} | "
            f"{per_day_str} | {sig['confidence']} | {action} |"
        )
    lines.append("")

    # Curated top-5 recommended signals + thesis
    lines.append("## Top 5 recommended signals (to layer on stratton baseline)")
    lines.append("")
    high = [s for s in signals if s["confidence"] == "high"]
    med = [s for s in signals if s["confidence"] == "med"]
    pool = high + med  # full pool, ranked
    if not pool:
        pool = signals
    # Ensure product-family diversity: at most 1 pick per (product family).
    # Family = HYDROGEL_PACK / VELVETFRUIT_EXTRACT / VEV_<strike>
    def fam(p: str) -> str:
        return p if not p.startswith("VEV_") else p  # each strike its own family
    seen_fams = set()
    picked = []
    for s in pool:
        f = fam(s["product"])
        if f in seen_fams:
            continue
        seen_fams.add(f)
        picked.append(s)
        if len(picked) == 5:
            break
    # Backfill if we didn't reach 5
    if len(picked) < 5:
        for s in pool:
            if s not in picked:
                picked.append(s)
                if len(picked) == 5:
                    break
    for i, sig in enumerate(picked, 1):
        verb = "informed (follow)" if sig["drift_H200_mean"] > 0 else "adverse (fade)"
        side_word = "BUY" if sig["mark_side"] == "buyer" else "SELL"
        opp_side = "SELL" if side_word == "BUY" else "BUY"
        suggested_size = min(15, max(3, int(round(abs(sig["drift_H200_mean"]) * 4))))
        if sig["drift_H200_mean"] > 0:
            action = (
                f"When `state.market_trades['{sig['product']}']` shows a {sig['mark']} "
                f"{side_word} within last 50 ticks → place an aggressive {side_word} "
                f"of up to {suggested_size} lots at the {('ask' if side_word=='BUY' else 'bid')} "
                f"(or join the queue 1 tick inside)."
            )
        else:
            action = (
                f"When `state.market_trades['{sig['product']}']` shows a {sig['mark']} "
                f"{side_word} within last 50 ticks → place a {opp_side} of up to "
                f"{suggested_size} lots; expect mid to move {sig['drift_H200_mean']:.2f} "
                f"over the next 200 ticks."
            )
        lines.append(
            f"**S{i}. {sig['mark']} on {sig['product']} ({verb})** — n={sig['n_trades']}, "
            f"drift@200={sig['drift_H200_mean']:+.2f}, conf={sig['confidence']}. {action}"
        )
        lines.append("")

    # Mark-vs-stratton thoughts
    lines.append("## Layering on top of `traders/round4/submission.py` (stratton)")
    lines.append("")
    lines.append(
        "- **Compatible additions** (no structural change): a thin `counterparty_signal()` "
        "method that scans `state.market_trades[product]` for the last 50 ticks of trades "
        "and, when it finds a high-conf signal above, *biases* one of stratton's existing "
        "knobs — e.g. shifts the inventory-target or quote-skew on that product by a small "
        "amount. This avoids fighting the IV-scalp logic on vouchers and the OBI-skew MM on "
        "HYDROGEL/far-strike vouchers."
    )
    lines.append("")
    lines.append(
        "- **Structural changes (riskier)**: re-enabling takes guarded by a Mark filter. "
        "Stratton has takes disabled because of toxic flow; if a clear `informed = follow` "
        "signal exists for one product, we could re-enable taking *only when* the signal "
        "fires, sized small. Test offline first because re-enabling takes interacts with "
        "position limits and can cancel passive quotes."
    )
    lines.append("")
    lines.append(
        "- **Adverse-selection avoidance**: any Mark classified `inf` on a product means we "
        "should *avoid being on the other side of their trades*. For passive MM that means "
        "widening the quote on the side that mark is hitting (e.g. if Mark X aggressively "
        "buys, widen our ask). This is a 1-line skew tweak inside stratton's quote builder."
    )
    lines.append("")
    lines.append(
        "- **Caveats**: N=2 independent FV samples is *very* small. Only the `high`-confidence "
        "signals above are safe to ship; `med` should go behind a feature flag, `low` is "
        "research-only. Do not stack more than 2-3 signals on one product without re-testing "
        "in MC, or you risk eating into the IV-scalp edge."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"[marks] loading {len(DAYS)} days from {DATA_DIR}")
    enriched_frames = []
    for d in DAYS:
        trades, prices = load_day(d)
        mids = build_mid_lookup(prices)
        enr = classify_and_drift(trades, mids)
        print(f"  day{d}: {len(trades):>5} trades, {len(enr):>5} enriched")
        enriched_frames.append(enr)
    enr_all = pd.concat(enriched_frames, ignore_index=True)

    # Drop trades with empty buyer/seller (shouldn't happen in R4 but be safe)
    enr_all = enr_all.dropna(subset=["buyer", "seller"])
    print(f"[marks] total enriched trades: {len(enr_all)}")

    profile = per_mark_per_product_per_side(enr_all)
    summary = overall_summary(enr_all, profile)
    pairs = pair_frequencies(enr_all)
    signals = actionable_signals(profile, summary)

    # ---- write outputs ----
    full_json = {
        "summary_per_mark": summary,
        "per_mark_per_product": profile,
        "pair_frequencies": pairs,
    }
    (OUT_DIR / "mark_profiles.json").write_text(
        json.dumps(full_json, indent=2, default=str), encoding="utf-8"
    )
    print(f"[marks] wrote {OUT_DIR / 'mark_profiles.json'}")

    md = build_md(summary, profile, pairs, signals)
    (OUT_DIR / "mark_profiles.md").write_text(md, encoding="utf-8")
    print(f"[marks] wrote {OUT_DIR / 'mark_profiles.md'}")

    (OUT_DIR / "signals.json").write_text(
        json.dumps({"signals": signals}, indent=2, default=str), encoding="utf-8"
    )
    print(f"[marks] wrote {OUT_DIR / 'signals.json'} ({len(signals)} signals)")


if __name__ == "__main__":
    main()
