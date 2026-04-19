"""OSMIUM signal scan across all 3 R1 days.

Angles probed (not previously covered):
  1. FV move reversal rates conditioned on various states
  2. OBI at non-symmetric spread ticks (what the user hinted at)
  3. L1 volume patterns when spread == 16
  4. Trade-clustering (multi-trades within a short window)
  5. Trade-aggressor direction as a leading signal (vs concurrent)
  6. Inter-trade timing (gap since last trade)
  7. L2 price-gap as a signal
  8. Cross-asset: does PEPPER activity carry any OSMIUM signal?
  9. Book-transition states
"""
from __future__ import annotations
import csv
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "prosperity4" / "round1"
DAYS = [0, -1, -2]


def load_prices(day: int, symbol: str):
    rows = []
    path = DATA / f"prices_round_1_day_{day}.csv"
    with path.open() as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != symbol:
                continue
            rows.append(row)
    return rows


def load_trades(day: int, symbol: str):
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


# ─────────────────────────── Analysis functions ───────────────────────────

def analyze_day(day: int):
    print(f"\n{'='*70}\n   OSMIUM — R1 day {day}\n{'='*70}")
    books = [parse_book(r) for r in load_prices(day, "ASH_COATED_OSMIUM")]
    by_ts = {b["ts"]: b for b in books}
    trades = load_trades(day, "ASH_COATED_OSMIUM")

    # Symmetric-FV series (spread=16, both L1 present)
    sym_fv = {}
    for b in books:
        if b["bp1"] and b["ap1"] and (b["ap1"] - b["bp1"]) == 16:
            sym_fv[b["ts"]] = (b["bp1"] + b["ap1"]) / 2
    sorted_sym = sorted(sym_fv)
    print(f"ticks total={len(books)}, symmetric(spread=16)={len(sym_fv)} ({len(sym_fv)/len(books):.1%})")

    # ── 1. Conditional reversal rates ──
    moves = []
    for i, t in enumerate(sorted_sym):
        if i == 0:
            continue
        prev = sym_fv[sorted_sym[i-1]]
        cur = sym_fv[t]
        if cur != prev:
            moves.append((t, 1 if cur > prev else -1))
    print(f"\nFV-moves at symmetric ticks: {len(moves)}")
    cons = rev = 0
    for i in range(1, len(moves)):
        if moves[i][1] == moves[i-1][1]:
            cons += 1
        else:
            rev += 1
    print(f"  next-move reversal rate: {rev/(rev+cons):.3f}  (cons={cons}, rev={rev})")

    # Conditional on non-zero next move at NEXT symmetric tick (not next move!)
    # i.e., immediate next-tick-move direction
    nz_after_up = [0, 0]  # [up, down]
    nz_after_down = [0, 0]
    for i, (t, dir_) in enumerate(moves):
        # Find the next symmetric tick after t
        idx = sorted_sym.index(t)
        if idx + 1 >= len(sorted_sym):
            continue
        nxt_t = sorted_sym[idx + 1]
        nxt_move = sym_fv[nxt_t] - sym_fv[t]
        if nxt_move == 0:
            continue
        if dir_ > 0:
            if nxt_move > 0:
                nz_after_up[0] += 1
            else:
                nz_after_up[1] += 1
        else:
            if nxt_move > 0:
                nz_after_down[0] += 1
            else:
                nz_after_down[1] += 1
    total_up = sum(nz_after_up)
    total_down = sum(nz_after_down)
    if total_up:
        print(f"  after UP | non-zero next: P(down)={nz_after_up[1]/total_up:.3f}  n={total_up}")
    if total_down:
        print(f"  after DOWN | non-zero next: P(up)={nz_after_down[0]/total_down:.3f}  n={total_down}")

    # ── 2. OBI at non-16 spread ──
    print("\nOBI signal at non-16 spread ticks:")
    obi_bucket = defaultdict(lambda: {"next_up": 0, "next_down": 0, "n": 0})
    for i, b in enumerate(books):
        if not (b["bp1"] and b["ap1"]):
            continue
        sp = b["ap1"] - b["bp1"]
        if sp == 16:
            continue
        tot = b["bv1"] + b["av1"]
        if tot <= 0:
            continue
        obi = (b["bv1"] - b["av1"]) / tot
        # Find prev and next symmetric FV
        prev_fv = None
        for t in reversed(sorted_sym):
            if t < b["ts"]:
                prev_fv = sym_fv[t]
                break
        next_fv = None
        for t in sorted_sym:
            if t > b["ts"] and t <= b["ts"] + 2000:
                next_fv = sym_fv[t]
                break
        if prev_fv is None or next_fv is None:
            continue
        mv = next_fv - prev_fv
        if obi > 0.3:
            k = "obi_pos"
        elif obi < -0.3:
            k = "obi_neg"
        else:
            k = "obi_flat"
        if mv > 0:
            obi_bucket[k]["next_up"] += 1
        elif mv < 0:
            obi_bucket[k]["next_down"] += 1
        obi_bucket[k]["n"] += 1
    for k, v in obi_bucket.items():
        n = v["n"]
        if n < 30:
            continue
        nz = v["next_up"] + v["next_down"]
        if nz == 0:
            continue
        print(f"  {k}: n={n}  P(up|nz)={v['next_up']/nz:.3f}  P(down|nz)={v['next_down']/nz:.3f}")

    # ── 3. L1 volume patterns at symmetric ticks ──
    # Prior analysis claimed BV1=AV1 always at spread=16. Verify + check if
    # volume *magnitude* predicts next move.
    print("\nL1 volume magnitude at symmetric ticks → next move (spread=16):")
    by_vol = defaultdict(lambda: {"up": 0, "down": 0, "flat": 0})
    for i, t in enumerate(sorted_sym[:-1]):
        b = by_ts[t]
        if b["bv1"] != b["av1"]:
            continue  # already filtered by sym but double-check
        v = b["bv1"]
        next_t = sorted_sym[i+1]
        mv = sym_fv[next_t] - sym_fv[t]
        if mv > 0:
            by_vol[v]["up"] += 1
        elif mv < 0:
            by_vol[v]["down"] += 1
        else:
            by_vol[v]["flat"] += 1
    for v in sorted(by_vol):
        d = by_vol[v]
        n = d["up"] + d["down"] + d["flat"]
        if n < 50:
            continue
        nz = d["up"] + d["down"]
        if nz == 0:
            continue
        print(f"  bv1=av1={v}: n={n}  P(up|nz)={d['up']/nz:.3f}  flat_frac={d['flat']/n:.3f}")

    # ── 4. Trade-leading-move: does a trade signal incoming FV move? ──
    print("\nTrade → FV-move within next N ticks:")
    # At each symmetric tick, is there a trade in the next 0-300ts? Does next FV move more often?
    ts_with_trade = defaultdict(list)
    for tt, pr, q in trades:
        ts_with_trade[tt].append((pr, q))
    for window in [100, 300, 500]:
        has_trade = {"moves": 0, "n": 0}
        no_trade = {"moves": 0, "n": 0}
        for i, t in enumerate(sorted_sym[:-1]):
            next_t = sorted_sym[i+1]
            mv = sym_fv[next_t] - sym_fv[t]
            bucket = None
            # Was there a trade in [t, t+window]?
            trade_in_window = any(tt >= t and tt <= t + window for tt in ts_with_trade)
            bucket = has_trade if trade_in_window else no_trade
            bucket["n"] += 1
            if mv != 0:
                bucket["moves"] += 1
        print(f"  window={window}: trade→{has_trade['moves']}/{has_trade['n']}={has_trade['moves']/max(1,has_trade['n']):.3f}  "
              f"no-trade→{no_trade['moves']}/{no_trade['n']}={no_trade['moves']/max(1,no_trade['n']):.3f}")

    # ── 5. Trade-aggressor direction → next FV move ──
    print("\nTrade aggressor → next sym-tick FV move:")
    agg_counts = {"buy": defaultdict(int), "sell": defaultdict(int)}
    for tt, pr, q in trades:
        book = by_ts.get(tt)
        if not book or not (book["bp1"] and book["ap1"]):
            continue
        if pr >= book["ap1"]:
            label = "buy"
        elif pr <= book["bp1"]:
            label = "sell"
        else:
            continue
        # Find next symmetric FV after trade
        prev_fv = None
        for t in reversed(sorted_sym):
            if t < tt:
                prev_fv = sym_fv[t]
                break
        next_fv = None
        for t in sorted_sym:
            if t > tt and t <= tt + 1000:
                next_fv = sym_fv[t]
                break
        if prev_fv is None or next_fv is None:
            continue
        mv = next_fv - prev_fv
        if mv > 0:
            agg_counts[label]["up"] += 1
        elif mv < 0:
            agg_counts[label]["down"] += 1
        agg_counts[label]["n"] += 1
    for label, d in agg_counts.items():
        n = d["n"]
        if n < 20:
            continue
        print(f"  {label}_agg: n={n}  P(up)={d['up']/n:.3f}  P(down)={d['down']/n:.3f}")

    # ── 6. L2 price gap vs L1 as a signal ──
    print("\nL2 gap (bp1-bp2, ap2-ap1) at symmetric ticks → next move:")
    gap_bucket = defaultdict(lambda: {"up": 0, "down": 0, "flat": 0})
    for i, t in enumerate(sorted_sym[:-1]):
        b = by_ts[t]
        if not (b["bp2"] and b["ap2"]):
            continue
        bg = b["bp1"] - b["bp2"]
        ag = b["ap2"] - b["ap1"]
        key = (bg, ag)
        next_t = sorted_sym[i+1]
        mv = sym_fv[next_t] - sym_fv[t]
        if mv > 0:
            gap_bucket[key]["up"] += 1
        elif mv < 0:
            gap_bucket[key]["down"] += 1
        else:
            gap_bucket[key]["flat"] += 1
    for key, d in sorted(gap_bucket.items()):
        n = d["up"] + d["down"] + d["flat"]
        if n < 100:
            continue
        nz = d["up"] + d["down"]
        if nz == 0:
            continue
        print(f"  L2gap bid={key[0]} ask={key[1]}: n={n}  P(up|nz)={d['up']/nz:.3f}  flat={d['flat']/n:.3f}")

    # ── 7. Clustering: multi-trades at same / close ts ──
    print("\nTrade clustering (trades within 100ts window):")
    sorted_tt = sorted(set(tt for tt, _, _ in trades))
    trades_by_ts = defaultdict(list)
    for tt, pr, q in trades:
        trades_by_ts[tt].append((pr, q))
    cluster_sizes = defaultdict(int)
    for tt in sorted_tt:
        cluster_sizes[len(trades_by_ts[tt])] += 1
    print(f"  same-ts cluster size distribution: {dict(cluster_sizes)}")

    # ── 8. Inter-trade timing ──
    gaps = []
    for i in range(1, len(sorted_tt)):
        gaps.append(sorted_tt[i] - sorted_tt[i-1])
    if gaps:
        print(f"  inter-trade gap: n={len(gaps)}  mean={statistics.mean(gaps):.0f}  median={statistics.median(gaps):.0f}  min={min(gaps)}  max={max(gaps)}")
        # Short gaps signal what?
        short_gap_moves = {"up": 0, "down": 0, "flat": 0}
        for i in range(1, len(sorted_tt)):
            gap = sorted_tt[i] - sorted_tt[i-1]
            if gap > 200:
                continue
            tt = sorted_tt[i]
            prev_fv = None
            next_fv = None
            for t in reversed(sorted_sym):
                if t < tt:
                    prev_fv = sym_fv[t]
                    break
            for t in sorted_sym:
                if t > tt and t <= tt + 1000:
                    next_fv = sym_fv[t]
                    break
            if prev_fv is None or next_fv is None:
                continue
            mv = next_fv - prev_fv
            if mv > 0:
                short_gap_moves["up"] += 1
            elif mv < 0:
                short_gap_moves["down"] += 1
            else:
                short_gap_moves["flat"] += 1
        n = sum(short_gap_moves.values())
        if n:
            print(f"  after short-gap (<=200ts): n={n}  up={short_gap_moves['up']/n:.3f}  "
                  f"down={short_gap_moves['down']/n:.3f}  flat={short_gap_moves['flat']/n:.3f}")


if __name__ == "__main__":
    for day in DAYS:
        analyze_day(day)
