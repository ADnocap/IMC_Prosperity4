"""IPR bot behavior analysis for Round 1."""
import csv
import statistics
from collections import defaultdict

DATA_DIR = "data/prosperity4/round1"
PRODUCT = "INTARIAN_PEPPER_ROOT"
DRIFT = 0.1  # per tick

def load_prices():
    rows = []
    for day in [-2, -1, 0]:
        with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                if r["product"] == PRODUCT:
                    r["_day"] = day
                    rows.append(r)
    return rows

def load_trades():
    rows = []
    for day in [-2, -1, 0]:
        with open(f"{DATA_DIR}/trades_round_1_day_{day}.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                if r["symbol"] == PRODUCT:
                    r["_day"] = day
                    rows.append(r)
    return rows

def analyze_book(prices):
    print("=" * 60)
    print("1. BID/ASK VOLUMES BY LEVEL")
    print("=" * 60)

    for level in [1, 2, 3]:
        bvols = [int(r[f"bid_volume_{level}"]) for r in prices if r.get(f"bid_volume_{level}") and r[f"bid_volume_{level}"] != ""]
        avols = [int(r[f"ask_volume_{level}"]) for r in prices if r.get(f"ask_volume_{level}") and r[f"ask_volume_{level}"] != ""]
        bprices_raw = [float(r[f"bid_price_{level}"]) for r in prices if r.get(f"bid_price_{level}") and r[f"bid_price_{level}"] != ""]
        aprices_raw = [float(r[f"ask_price_{level}"]) for r in prices if r.get(f"ask_price_{level}") and r[f"ask_price_{level}"] != ""]

        pct_bid = len(bvols) / len(prices) * 100
        pct_ask = len(avols) / len(prices) * 100

        print(f"\n  Level {level}:")
        print(f"    Bid present: {pct_bid:.1f}% of ticks | Ask present: {pct_ask:.1f}% of ticks")
        if bvols:
            print(f"    Bid vol: mean={statistics.mean(bvols):.1f}, median={statistics.median(bvols):.0f}, min={min(bvols)}, max={max(bvols)}")
        if avols:
            print(f"    Ask vol: mean={statistics.mean(avols):.1f}, median={statistics.median(avols):.0f}, min={min(avols)}, max={max(avols)}")

def analyze_spread(prices):
    print("\n" + "=" * 60)
    print("2. SPREAD ANALYSIS")
    print("=" * 60)

    spreads_by_segment = defaultdict(list)
    all_spreads = []

    for r in prices:
        bp1 = r.get("bid_price_1", "")
        ap1 = r.get("ask_price_1", "")
        if bp1 and ap1 and bp1 != "" and ap1 != "":
            spread = float(ap1) - float(bp1)
            ts = int(r["timestamp"])
            all_spreads.append((ts, spread))
            # segment into quarters of the day (10000 ticks = 1M timestamps)
            quarter = ts // 250000
            spreads_by_segment[quarter].append(spread)

    if all_spreads:
        vals = [s for _, s in all_spreads]
        print(f"\n  Overall: mean={statistics.mean(vals):.2f}, median={statistics.median(vals):.0f}, "
              f"std={statistics.stdev(vals):.2f}, min={min(vals):.0f}, max={max(vals):.0f}")

        print("\n  By time segment (quarter of day):")
        for q in sorted(spreads_by_segment.keys()):
            v = spreads_by_segment[q]
            print(f"    Q{q} (ts {q*250000}-{(q+1)*250000}): mean={statistics.mean(v):.2f}, n={len(v)}")

    # Also check: how often is only bid or only ask present?
    bid_only = sum(1 for r in prices if r.get("bid_price_1","") != "" and (r.get("ask_price_1","") == ""))
    ask_only = sum(1 for r in prices if r.get("ask_price_1","") != "" and (r.get("bid_price_1","") == ""))
    both = sum(1 for r in prices if r.get("bid_price_1","") != "" and r.get("ask_price_1","") != "")
    neither = sum(1 for r in prices if r.get("bid_price_1","") == "" and r.get("ask_price_1","") == "")
    print(f"\n  Both sides present: {both}/{len(prices)} ({both/len(prices)*100:.1f}%)")
    print(f"  Bid only: {bid_only}, Ask only: {ask_only}, Neither: {neither}")

def analyze_trades(trades):
    print("\n" + "=" * 60)
    print("3. TRADE ANALYSIS (buyer/seller names)")
    print("=" * 60)

    buyers = defaultdict(int)
    sellers = defaultdict(int)

    for t in trades:
        b = t.get("buyer", "").strip()
        s = t.get("seller", "").strip()
        buyers[b if b else "(empty)"] += 1
        sellers[s if s else "(empty)"] += 1

    print(f"\n  Total trades: {len(trades)}")
    print(f"  Buyers: {dict(buyers)}")
    print(f"  Sellers: {dict(sellers)}")

    # Trade size distribution
    sizes = [int(t["quantity"]) for t in trades]
    print(f"\n  Trade sizes: mean={statistics.mean(sizes):.1f}, median={statistics.median(sizes):.0f}, "
          f"min={min(sizes)}, max={max(sizes)}")

    # Trade frequency
    by_day = defaultdict(list)
    for t in trades:
        by_day[t["_day"]].append(t)
    for d in sorted(by_day):
        print(f"  Day {d}: {len(by_day[d])} trades")

def analyze_mean_reversion(prices):
    print("\n" + "=" * 60)
    print("4. MEAN REVERSION AROUND DRIFT")
    print("=" * 60)

    by_day = defaultdict(list)
    for r in prices:
        mp = r.get("mid_price", "")
        if mp and mp != "":
            by_day[r["_day"]].append((int(r["timestamp"]), float(mp)))

    all_deviations = []

    for day in sorted(by_day):
        pts = sorted(by_day[day])
        if not pts:
            continue

        # Fit trend: first mid price + 0.1/tick
        t0, p0 = pts[0]

        deviations = []
        for ts, mp in pts:
            ticks = (ts - t0) / 100
            expected = p0 + DRIFT * ticks
            dev = mp - expected
            deviations.append(dev)
            all_deviations.append(dev)

        print(f"\n  Day {day}: {len(pts)} ticks with mid_price")
        print(f"    Deviation from trend: mean={statistics.mean(deviations):.2f}, "
              f"std={statistics.stdev(deviations):.2f}, min={min(deviations):.1f}, max={max(deviations):.1f}")

        # Autocorrelation of deviations (lag-1)
        if len(deviations) > 1:
            mean_d = statistics.mean(deviations)
            var_d = statistics.variance(deviations)
            if var_d > 0:
                ac = sum((deviations[i] - mean_d) * (deviations[i+1] - mean_d)
                         for i in range(len(deviations)-1)) / ((len(deviations)-1) * var_d)
                print(f"    Lag-1 autocorrelation: {ac:.4f}")

    if all_deviations:
        print(f"\n  Overall deviation std: {statistics.stdev(all_deviations):.2f}")

def analyze_accumulation_cost(prices):
    print("\n" + "=" * 60)
    print("5. ACCUMULATION COST & TRADING STRATEGY ANALYSIS")
    print("=" * 60)

    by_day = defaultdict(list)
    for r in prices:
        by_day[r["_day"]].append(r)

    for day in sorted(by_day):
        rows = sorted(by_day[day], key=lambda x: int(x["timestamp"]))

        # Cost to buy at ask vs mid
        ask_costs = []
        mid_prices = []
        bid_prices_list = []

        for r in rows:
            ap1 = r.get("ask_price_1", "")
            bp1 = r.get("bid_price_1", "")
            mp = r.get("mid_price", "")
            if ap1 and ap1 != "" and mp and mp != "":
                ask_costs.append(float(ap1) - float(mp))
            if mp and mp != "":
                mid_prices.append((int(r["timestamp"]), float(mp)))
            if bp1 and bp1 != "":
                bid_prices_list.append((int(r["timestamp"]), float(bp1)))

        if ask_costs:
            print(f"\n  Day {day}:")
            print(f"    Ask premium over mid: mean={statistics.mean(ask_costs):.2f}")

        # Simulate: buy at first available ask, accumulate 80 units ASAP
        # vs buy 1 per tick
        first_ask_rows = [(int(r["timestamp"]), float(r["ask_price_1"]), int(r["ask_volume_1"]))
                          for r in rows if r.get("ask_price_1","") != "" and r.get("ask_volume_1","") != ""]

        if first_ask_rows and mid_prices:
            # Strategy 1: buy ASAP at ask
            pos = 0
            total_cost = 0
            for ts, ap, av in first_ask_rows:
                can_buy = min(av, 80 - pos)
                if can_buy > 0:
                    total_cost += ap * can_buy
                    pos += can_buy
                if pos >= 80:
                    break

            # End-of-day value
            final_mid = mid_prices[-1][1]
            pnl_asap = final_mid * 80 - total_cost if pos >= 80 else 0

            # Strategy 2: buy 1 unit per tick at ask
            pos2 = 0
            total_cost2 = 0
            for ts, ap, av in first_ask_rows:
                if pos2 < 80:
                    total_cost2 += ap
                    pos2 += 1
            pnl_slow = final_mid * pos2 - total_cost2

            ticks_to_fill = first_ask_rows[min(79, len(first_ask_rows)-1)][0] if len(first_ask_rows) >= 80 else -1

            print(f"    ASAP fill cost: {total_cost:.0f} for {pos} units ({total_cost/max(pos,1):.1f}/unit avg)")
            print(f"    End mid: {final_mid:.1f}, ASAP PnL: {pnl_asap:.0f}")
            print(f"    Slow fill (1/tick) cost: {total_cost2:.0f} for {pos2} units ({total_cost2/max(pos2,1):.1f}/unit avg)")
            print(f"    Slow PnL: {pnl_slow:.0f}")

            # Drift value: 80 units * avg ticks held * 0.1
            if mid_prices:
                total_ticks = (mid_prices[-1][0] - mid_prices[0][0]) / 100
                print(f"    Total ticks in day: {total_ticks:.0f}")
                print(f"    Pure drift value (80 units, full day): {80 * total_ticks * DRIFT:.0f}")

def analyze_bid_ask_depth_vs_level(prices):
    print("\n" + "=" * 60)
    print("6. BID/ASK PRICE OFFSETS FROM MID")
    print("=" * 60)

    for level in [1, 2, 3]:
        bid_offsets = []
        ask_offsets = []
        for r in prices:
            mp = r.get("mid_price", "")
            bp = r.get(f"bid_price_{level}", "")
            ap = r.get(f"ask_price_{level}", "")
            if mp and mp != "":
                mid = float(mp)
                if bp and bp != "":
                    bid_offsets.append(float(bp) - mid)
                if ap and ap != "":
                    ask_offsets.append(float(ap) - mid)

        if bid_offsets:
            print(f"\n  Level {level} bid offset from mid: mean={statistics.mean(bid_offsets):.2f}, "
                  f"std={statistics.stdev(bid_offsets):.2f}")
        if ask_offsets:
            print(f"  Level {level} ask offset from mid: mean={statistics.mean(ask_offsets):.2f}, "
                  f"std={statistics.stdev(ask_offsets):.2f}")

if __name__ == "__main__":
    prices = load_prices()
    trades = load_trades()

    print(f"Loaded {len(prices)} price rows, {len(trades)} trades for {PRODUCT}")

    analyze_book(prices)
    analyze_spread(prices)
    analyze_trades(trades)
    analyze_mean_reversion(prices)
    analyze_accumulation_cost(prices)
    analyze_bid_ask_depth_vs_level(prices)
