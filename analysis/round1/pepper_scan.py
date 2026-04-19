"""PEPPER signal scan across all 3 R1 days.

What we already believe (to verify or refute):
  - Deterministic drift +0.1/tick
  - Bot1 at proportional offset K=3/4000, Bot2 at K=1/2000
  - Strategy maxes out position=80 via sweeping asks < 15 vol

What we probe (new):
  1. Drift stability — constant across ticks/days? timed modulation?
  2. L2 gap patterns (analog of OSMIUM finding)
  3. Trade-price-vs-book: any tradable mispricings we miss?
  4. Trade clustering / burst patterns
  5. Book-state transition → move timing
  6. MM edge on top of hold-and-drift: can we quote asks cheap + rebuy cheap?
"""
from __future__ import annotations
import csv
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "prosperity4" / "round1"
DAYS = [0, -1, -2]


def load_prices(day, symbol):
    rows = []
    path = DATA / f"prices_round_1_day_{day}.csv"
    with path.open() as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != symbol:
                continue
            rows.append(row)
    return rows


def load_trades(day, symbol):
    out = []
    with (DATA / f"trades_round_1_day_{day}.csv").open() as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["symbol"] != symbol:
                continue
            out.append((int(row["timestamp"]), float(row["price"]), int(row["quantity"])))
    return out


def parse_book(row):
    def i(k):
        v = row[k]
        return int(v) if v else None

    return {
        "ts": int(row["timestamp"]),
        "bp1": i("bid_price_1"), "bv1": i("bid_volume_1") or 0,
        "bp2": i("bid_price_2"), "bv2": i("bid_volume_2") or 0,
        "ap1": i("ask_price_1"), "av1": i("ask_volume_1") or 0,
        "ap2": i("ask_price_2"), "av2": i("ask_volume_2") or 0,
    }


def analyze_day(day):
    print(f"\n{'='*70}\n   PEPPER — R1 day {day}\n{'='*70}")
    books = [parse_book(r) for r in load_prices(day, "INTARIAN_PEPPER_ROOT")]
    by_ts = {b["ts"]: b for b in books}
    trades = load_trades(day, "INTARIAN_PEPPER_ROOT")

    # ── 1. Drift: fit FV = a + b*ts from symmetric ticks ──
    # For PEPPER K1=3/4000, K2=1/2000. Bot2 spread = 2*ceil(FV*K2) ≈ 12-14 depending on FV.
    # Use L1 mid as proxy for FV.
    mids = []
    for b in books:
        if b["bp1"] and b["ap1"]:
            mids.append((b["ts"], (b["bp1"] + b["ap1"]) / 2))
    if mids:
        n = len(mids)
        sx = sum(t for t, _ in mids)
        sy = sum(m for _, m in mids)
        sxx = sum(t*t for t, _ in mids)
        sxy = sum(t*m for t, m in mids)
        slope = (n*sxy - sx*sy) / (n*sxx - sx*sx)
        intercept = (sy - slope*sx) / n
        # Residual std from linear fit
        resid = [m - (intercept + slope*t) for t, m in mids]
        rstd = statistics.pstdev(resid) if len(resid) > 1 else 0
        print(f"L1-mid linear fit: slope={slope*1000:.4f}/1000ts  intercept={intercept:.2f}  n={n}  resid_std={rstd:.3f}")
        # PEPPER drift should be 0.1/tick = 0.001/ts (since ts=100 per tick)
        print(f"  drift per tick: {slope*100:+.4f} (target: +0.1000)")
        # drift stability: split into halves
        half = n // 2
        def slope_of(data):
            m = len(data)
            if m < 2: return None
            sx = sum(t for t,_ in data)
            sy = sum(m_ for _,m_ in data)
            sxx = sum(t*t for t,_ in data)
            sxy = sum(t*m_ for t,m_ in data)
            d = m*sxx - sx*sx
            return (m*sxy - sx*sy)/d if d else None
        s1 = slope_of(mids[:half])
        s2 = slope_of(mids[half:])
        if s1 and s2:
            print(f"  first-half drift: {s1*100:+.4f}/tick   second-half: {s2*100:+.4f}/tick")

    # ── 2. L2 gap patterns ──
    gap_counts = defaultdict(int)
    for b in books:
        if not (b["bp1"] and b["ap1"] and b["bp2"] and b["ap2"]):
            continue
        bg = b["bp1"] - b["bp2"]
        ag = b["ap2"] - b["ap1"]
        gap_counts[(bg, ag)] += 1
    top = sorted(gap_counts.items(), key=lambda x: -x[1])[:8]
    print(f"\nL2 gap patterns (top): {top}")

    # ── 3. Trade prices vs book (mispricings we miss) ──
    buy_agg = 0
    sell_agg = 0
    mid_trade = 0
    inside_spread = 0
    above_ask = 0
    below_bid = 0
    for tt, pr, q in trades:
        b = by_ts.get(tt)
        if not b or not (b["bp1"] and b["ap1"]):
            continue
        if pr >= b["ap1"] and pr <= b["ap1"]+0.001:
            buy_agg += 1
        elif pr <= b["bp1"] and pr >= b["bp1"]-0.001:
            sell_agg += 1
        elif b["bp1"] < pr < b["ap1"]:
            inside_spread += 1
        elif pr > b["ap1"]:
            above_ask += 1
        elif pr < b["bp1"]:
            below_bid += 1
    print(f"\ntrade classification: buy_agg={buy_agg}  sell_agg={sell_agg}  inside={inside_spread}  above_ask={above_ask}  below_bid={below_bid}")

    # ── 4. Clustering / volume bursts ──
    sizes = [q for _, _, q in trades]
    print(f"trade count: {len(trades)}  total_vol: {sum(sizes)}  mean_size: {statistics.mean(sizes):.2f} median: {statistics.median(sizes)}")
    tt_list = sorted(set(tt for tt,_,_ in trades))
    if len(tt_list) > 1:
        gaps = [tt_list[i]-tt_list[i-1] for i in range(1,len(tt_list))]
        print(f"inter-trade gaps: mean={statistics.mean(gaps):.0f}  median={statistics.median(gaps):.0f}")

    # ── 5. Taker volume breakdown ──
    buy_vol = sum(q for tt, pr, q in trades if by_ts.get(tt) and by_ts[tt]["ap1"] and pr >= by_ts[tt]["ap1"])
    sell_vol = sum(q for tt, pr, q in trades if by_ts.get(tt) and by_ts[tt]["bp1"] and pr <= by_ts[tt]["bp1"])
    print(f"taker volume: buy={buy_vol}  sell={sell_vol}  (drift +0.1/tick should see more buys)")

    # ── 6. Book imbalance + ask-volume trend (does ask side run dry near drift jumps?)
    # For each L1 level, compute Bot2-ask stability. Key question: does Bot2 ask get
    # eaten more than Bot2 bid? If so, our sweep strategy is capturing edge; the
    # residual ask side is interesting.
    av_bv_ratio = []
    for b in books:
        if b["bv1"] and b["av1"]:
            av_bv_ratio.append(b["av1"] / b["bv1"])
    if av_bv_ratio:
        print(f"av1/bv1 ratio: mean={statistics.mean(av_bv_ratio):.3f}  median={statistics.median(av_bv_ratio):.3f}")

    # ── 7. Bot1 & Bot2 price identification from book ──
    # At each tick, measure Bot1 offset (vol 15-25) and Bot2 offset (vol 8-12)
    # Sanity check that the bot model holds throughout the day.
    b1_offsets = []
    b2_offsets = []
    for b in books:
        if not (b["bp1"] and b["ap1"]):
            continue
        # FV proxy from L1 mid
        fv = (b["bp1"] + b["ap1"]) / 2
        # Check L1 vol to identify bot
        if 8 <= b["bv1"] <= 12:
            b2_offsets.append(fv - b["bp1"])
        elif 15 <= b["bv1"] <= 25:
            b1_offsets.append(fv - b["bp1"])
        if 8 <= b["av1"] <= 12:
            b2_offsets.append(b["ap1"] - fv)
        elif 15 <= b["av1"] <= 25:
            b1_offsets.append(b["ap1"] - fv)
    if b1_offsets:
        print(f"Bot1 offsets: n={len(b1_offsets)}  mean={statistics.mean(b1_offsets):.2f}")
    if b2_offsets:
        print(f"Bot2 offsets: n={len(b2_offsets)}  mean={statistics.mean(b2_offsets):.2f}")


if __name__ == "__main__":
    for day in DAYS:
        analyze_day(day)
