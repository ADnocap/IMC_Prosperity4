"""Bot3 timing analysis for ASH_COATED_OSMIUM (ACO) in Round 1."""
import csv
import statistics
from collections import Counter

DAYS = [-2, -1, 0]
DATA_DIR = "data/prosperity4/round1"
PRODUCT = "ASH_COATED_OSMIUM"

# ---------- Load trades ----------
all_trades = []  # (day, timestamp, price, quantity)
for day in DAYS:
    with open(f"{DATA_DIR}/trades_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["symbol"] == PRODUCT:
                all_trades.append((day, int(row["timestamp"]), float(row["price"]), int(row["quantity"])))

# ---------- Load prices (book snapshots) ----------
# Build lookup: (day, timestamp) -> (best_bid, best_ask, spread)
book = {}
for day in DAYS:
    with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] == PRODUCT:
                ts = int(row["timestamp"])
                bp1 = float(row["bid_price_1"]) if row["bid_price_1"] else None
                ap1 = float(row["ask_price_1"]) if row["ask_price_1"] else None
                mid = float(row["mid_price"]) if row["mid_price"] else None
                book[(day, ts)] = (bp1, ap1, mid)

print(f"Total ACO trades across 3 days: {len(all_trades)}")
print(f"Volume distribution: {Counter(t[3] for t in all_trades).most_common()}")

# ---------- Q1: Inter-trade gaps ----------
print("\n=== Q1: Inter-trade gaps (per day) ===")
all_gaps = []
for day in DAYS:
    day_trades = sorted([t for t in all_trades if t[0] == day], key=lambda x: x[1])
    timestamps = [t[1] for t in day_trades]
    gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    all_gaps.extend(gaps)
    print(f"  Day {day}: {len(day_trades)} trades, gap mean={statistics.mean(gaps):.0f}, "
          f"median={statistics.median(gaps):.0f}, stdev={statistics.stdev(gaps):.0f}, "
          f"min={min(gaps)}, max={max(gaps)}")

print(f"  ALL:   gap mean={statistics.mean(all_gaps):.0f}, median={statistics.median(all_gaps):.0f}, "
      f"stdev={statistics.stdev(all_gaps):.0f}")

# Gap distribution (histogram)
gap_buckets = Counter()
for g in all_gaps:
    bucket = (g // 500) * 500
    gap_buckets[bucket] += 1
print("\n  Gap histogram (bucket_start: count):")
for b in sorted(gap_buckets.keys()):
    bar = "#" * (gap_buckets[b])
    print(f"    {b:5d}-{b+499:5d}: {gap_buckets[b]:4d} {bar}")

# ---------- Q2: Spread at time of trade ----------
print("\n=== Q2: Spread at time of Bot3 trade ===")
spreads_at_trade = []
spreads_all = []
for day in DAYS:
    for (d, ts), (bp, ap, mid) in book.items():
        if d == day and bp is not None and ap is not None:
            spreads_all.append(ap - bp)
    day_trades = [t for t in all_trades if t[0] == day]
    for _, ts, price, qty in day_trades:
        # Look at book at this timestamp or the one just before
        entry = book.get((day, ts))
        if entry is None:
            # try previous tick
            entry = book.get((day, ts - 100))
        if entry and entry[0] is not None and entry[1] is not None:
            spread = entry[1] - entry[0]
            spreads_at_trade.append(spread)

print(f"  Spread at trade time: mean={statistics.mean(spreads_at_trade):.1f}, "
      f"median={statistics.median(spreads_at_trade):.1f}, stdev={statistics.stdev(spreads_at_trade):.1f}")
print(f"  Overall book spread:  mean={statistics.mean(spreads_all):.1f}, "
      f"median={statistics.median(spreads_all):.1f}, stdev={statistics.stdev(spreads_all):.1f}")

spread_at_trade_dist = Counter(int(s) for s in spreads_at_trade)
print(f"  Spread-at-trade distribution: {sorted(spread_at_trade_dist.items())}")

# ---------- Q3: Timestamp periodicity ----------
print("\n=== Q3: Timestamp-based periodicity ===")
# Check if timestamps mod N cluster
for period in [500, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 2000, 2500, 3000, 3500, 4000, 5000]:
    residues = [t[1] % period for t in all_trades]
    res_counter = Counter(residues)
    # Measure concentration: if periodic, a few residues dominate
    top5 = sum(c for _, c in res_counter.most_common(5))
    frac = top5 / len(residues)
    if frac > 0.25 or period in [1000, 2000, 3000, 5000]:
        print(f"  period={period}: top5 residues capture {frac:.1%} of trades "
              f"(top: {res_counter.most_common(3)})")

# Autocorrelation of inter-trade gaps
print("\n  Autocorrelation of gaps (lag 1-5):")
gap_mean = statistics.mean(all_gaps)
gap_var = statistics.variance(all_gaps)
for lag in range(1, 6):
    if lag < len(all_gaps):
        cov = sum((all_gaps[i] - gap_mean) * (all_gaps[i+lag] - gap_mean)
                  for i in range(len(all_gaps) - lag)) / (len(all_gaps) - lag)
        acf = cov / gap_var if gap_var > 0 else 0
        print(f"    lag {lag}: {acf:.3f}")

# ---------- Q4: Buy vs Sell fraction ----------
print("\n=== Q4: Buy vs Sell direction ===")
buys = 0
sells = 0
unknown = 0
for day, ts, price, qty in all_trades:
    entry = book.get((day, ts))
    if entry is None:
        entry = book.get((day, ts - 100))
    if entry:
        bp, ap, mid = entry
        if ap is not None and price >= ap - 0.5:
            buys += 1
        elif bp is not None and price <= bp + 0.5:
            sells += 1
        else:
            unknown += 1
    else:
        unknown += 1

total = buys + sells + unknown
print(f"  Buys (hit ask): {buys} ({buys/total:.1%})")
print(f"  Sells (hit bid): {sells} ({sells/total:.1%})")
print(f"  Ambiguous: {unknown} ({unknown/total:.1%})")

buy_vol, sell_vol = 0, 0
for day, ts, price, qty in all_trades:
    entry = book.get((day, ts)) or book.get((day, ts - 100))
    if entry:
        bp, ap, mid = entry
        if ap is not None and price >= ap - 0.5:
            buy_vol += qty
        elif bp is not None and price <= bp + 0.5:
            sell_vol += qty
print(f"  Buy volume: {buy_vol}, Sell volume: {sell_vol}")

# Per-day breakdown
print("\n  Per-day buy/sell counts:")
for day in DAYS:
    day_trades = [t for t in all_trades if t[0] == day]
    b = s = 0
    for _, ts, price, qty in day_trades:
        entry = book.get((day, ts)) or book.get((day, ts - 100))
        if entry:
            bp, ap, mid = entry
            if ap is not None and price >= ap - 0.5:
                b += 1
            elif bp is not None and price <= bp + 0.5:
                s += 1
    print(f"    Day {day}: buys={b}, sells={s}")
