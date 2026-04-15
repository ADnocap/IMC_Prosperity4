"""
Deep analysis of Round 1 data: OSMIUM and PEPPER
Goal: understand microstructure, bot behavior, and find unexploited edges
"""
import csv
import statistics
import json
from collections import defaultdict, Counter

DATA_DIR = "data/prosperity4/round1"
DAYS = [-2, -1, 0]

def load_prices(day):
    rows = []
    with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def load_trades(day):
    rows = []
    with open(f"{DATA_DIR}/trades_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def parse_book(row):
    """Parse order book from a price row"""
    bids = []
    asks = []
    for i in range(1, 4):
        bp = row.get(f'bid_price_{i}', '')
        bv = row.get(f'bid_volume_{i}', '')
        if bp and bv:
            bids.append((float(bp), int(bv)))
        ap = row.get(f'ask_price_{i}', '')
        av = row.get(f'ask_volume_{i}', '')
        if ap and av:
            asks.append((float(ap), int(av)))
    return bids, asks

# ============================================================
# SECTION 1: Basic statistics per product per day
# ============================================================
print("=" * 80)
print("SECTION 1: BASIC STATISTICS")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    trades = load_trades(day)

    # Group by product
    by_product = defaultdict(list)
    for row in prices:
        by_product[row['product']].append(row)

    trade_by_product = defaultdict(list)
    for row in trades:
        trade_by_product[row['symbol']].append(row)

    print(f"\n--- Day {day} ---")
    for product, rows in sorted(by_product.items()):
        mids = [float(r['mid_price']) for r in rows if r['mid_price']]
        print(f"\n  {product}: {len(rows)} ticks")
        if mids:
            print(f"    Mid: min={min(mids):.1f}, max={max(mids):.1f}, mean={statistics.mean(mids):.1f}, std={statistics.stdev(mids):.2f}")
            print(f"    Range: {max(mids) - min(mids):.1f}")
            # First and last mid
            print(f"    Start mid: {mids[0]:.1f}, End mid: {mids[-1]:.1f}, Drift: {mids[-1] - mids[0]:.1f}")

        # Spread analysis
        spreads = []
        for r in rows:
            bids, asks = parse_book(r)
            if bids and asks:
                spread = asks[0][0] - bids[0][0]
                spreads.append(spread)
        if spreads:
            print(f"    Spread: min={min(spreads):.0f}, max={max(spreads):.0f}, mean={statistics.mean(spreads):.1f}, median={statistics.median(spreads):.0f}")

        # Count ticks with various levels
        n_bids = Counter()
        n_asks = Counter()
        for r in rows:
            bids, asks = parse_book(r)
            n_bids[len(bids)] += 1
            n_asks[len(asks)] += 1
        print(f"    Bid levels: {dict(sorted(n_bids.items()))}")
        print(f"    Ask levels: {dict(sorted(n_asks.items()))}")

        # Trades
        trs = trade_by_product.get(product, [])
        if trs:
            print(f"    Trades: {len(trs)} total, qty sum={sum(int(t['quantity']) for t in trs)}")

# ============================================================
# SECTION 2: OSMIUM - Deep microstructure analysis
# ============================================================
print("\n" + "=" * 80)
print("SECTION 2: OSMIUM MICROSTRUCTURE")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # Analyze order book patterns
    # What are the typical bid/ask configurations?
    book_patterns = Counter()
    bid_spreads_from_mid = []
    ask_spreads_from_mid = []

    # Track individual levels
    bid1_vols = []
    bid2_vols = []
    ask1_vols = []
    ask2_vols = []

    bid1_dist = []  # distance from mid
    ask1_dist = []

    empty_bids = 0
    empty_asks = 0

    # Bot identification: look at volume patterns
    all_bid_volumes = Counter()
    all_ask_volumes = Counter()
    all_bid_prices_rel = Counter()  # relative to mid
    all_ask_prices_rel = Counter()

    # Track book states
    one_sided_bid = 0
    one_sided_ask = 0
    both_sides = 0

    prev_mid = None
    mid_changes = []

    for r in osmium:
        bids, asks = parse_book(r)
        mid = float(r['mid_price']) if r['mid_price'] else None

        if mid and prev_mid:
            mid_changes.append(mid - prev_mid)
        prev_mid = mid

        if not bids and not asks:
            continue

        if bids and not asks:
            one_sided_bid += 1
        elif asks and not bids:
            one_sided_ask += 1
        else:
            both_sides += 1

        if not bids:
            empty_bids += 1
        if not asks:
            empty_asks += 1

        for bp, bv in bids:
            all_bid_volumes[bv] += 1
            if mid:
                dist = round(mid - bp, 1)
                all_bid_prices_rel[dist] += 1

        for ap, av in asks:
            all_ask_volumes[av] += 1
            if mid:
                dist = round(ap - mid, 1)
                all_ask_prices_rel[dist] += 1

        n_bids = len(bids)
        n_asks = len(asks)
        book_patterns[(n_bids, n_asks)] += 1

        if bids:
            bid1_vols.append(bids[0][1])
            if mid:
                bid1_dist.append(round(mid - bids[0][0], 1))
        if asks:
            ask1_vols.append(asks[0][1])
            if mid:
                ask1_dist.append(round(asks[0][0] - mid, 1))

    print(f"  Book patterns (n_bids, n_asks): {dict(book_patterns.most_common(10))}")
    print(f"  One-sided bid: {one_sided_bid}, One-sided ask: {one_sided_ask}, Both: {both_sides}")
    print(f"  Empty bids: {empty_bids}, Empty asks: {empty_asks}")

    print(f"\n  Bid volumes (count): {dict(all_bid_volumes.most_common(15))}")
    print(f"  Ask volumes (count): {dict(all_ask_volumes.most_common(15))}")

    print(f"\n  Bid distance from mid (count): {dict(sorted(all_bid_prices_rel.most_common(20)))}")
    print(f"  Ask distance from mid (count): {dict(sorted(all_ask_prices_rel.most_common(20)))}")

    if bid1_dist:
        print(f"\n  Best bid distance from mid: min={min(bid1_dist)}, max={max(bid1_dist)}, mean={statistics.mean(bid1_dist):.2f}")
    if ask1_dist:
        print(f"  Best ask distance from mid: min={min(ask1_dist)}, max={max(ask1_dist)}, mean={statistics.mean(ask1_dist):.2f}")

    if mid_changes:
        nonzero = [c for c in mid_changes if c != 0]
        print(f"\n  Mid-price changes: total={len(mid_changes)}, nonzero={len(nonzero)}")
        if nonzero:
            print(f"    Mean change: {statistics.mean(nonzero):.4f}, Std: {statistics.stdev(nonzero):.4f}")
            up = sum(1 for c in nonzero if c > 0)
            down = sum(1 for c in nonzero if c < 0)
            print(f"    Up: {up}, Down: {down}")
            # Distribution of changes
            change_dist = Counter(round(c, 1) for c in nonzero)
            print(f"    Change distribution: {dict(sorted(change_dist.items()))}")

# ============================================================
# SECTION 3: PEPPER - Deep microstructure analysis
# ============================================================
print("\n" + "=" * 80)
print("SECTION 3: PEPPER MICROSTRUCTURE")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    pepper = [r for r in prices if 'PEPPER' in r['product']]

    print(f"\n--- Day {day} ---")

    book_patterns = Counter()
    all_bid_volumes = Counter()
    all_ask_volumes = Counter()
    all_bid_prices_rel = Counter()
    all_ask_prices_rel = Counter()

    prev_mid = None
    mid_changes = []

    bid1_dist = []
    ask1_dist = []

    for r in pepper:
        bids, asks = parse_book(r)
        mid = float(r['mid_price']) if r['mid_price'] else None

        if mid and prev_mid:
            mid_changes.append(mid - prev_mid)
        prev_mid = mid

        n_bids = len(bids)
        n_asks = len(asks)
        book_patterns[(n_bids, n_asks)] += 1

        for bp, bv in bids:
            all_bid_volumes[bv] += 1
            if mid:
                dist = round(mid - bp, 1)
                all_bid_prices_rel[dist] += 1

        for ap, av in asks:
            all_ask_volumes[av] += 1
            if mid:
                dist = round(ap - mid, 1)
                all_ask_prices_rel[dist] += 1

        if bids and mid:
            bid1_dist.append(round(mid - bids[0][0], 1))
        if asks and mid:
            ask1_dist.append(round(asks[0][0] - mid, 1))

    print(f"  Book patterns (n_bids, n_asks): {dict(book_patterns.most_common(10))}")

    print(f"\n  Bid volumes (count): {dict(all_bid_volumes.most_common(15))}")
    print(f"  Ask volumes (count): {dict(all_ask_volumes.most_common(15))}")

    print(f"\n  Bid distance from mid (count): {dict(sorted(all_bid_prices_rel.most_common(20)))}")
    print(f"  Ask distance from mid (count): {dict(sorted(all_ask_prices_rel.most_common(20)))}")

    if bid1_dist:
        print(f"\n  Best bid dist: min={min(bid1_dist)}, max={max(bid1_dist)}, mean={statistics.mean(bid1_dist):.2f}")
    if ask1_dist:
        print(f"  Best ask dist: min={min(ask1_dist)}, max={max(ask1_dist)}, mean={statistics.mean(ask1_dist):.2f}")

    if mid_changes:
        nonzero = [c for c in mid_changes if c != 0]
        print(f"\n  Mid-price changes: total={len(mid_changes)}, nonzero={len(nonzero)}")
        if nonzero:
            print(f"    Mean change: {statistics.mean(nonzero):.4f}")
            up = sum(1 for c in nonzero if c > 0)
            down = sum(1 for c in nonzero if c < 0)
            print(f"    Up: {up}, Down: {down}")
            change_dist = Counter(round(c, 1) for c in nonzero)
            print(f"    Change distribution: {dict(sorted(change_dist.items()))}")

# ============================================================
# SECTION 4: Trade analysis - who trades, when, patterns
# ============================================================
print("\n" + "=" * 80)
print("SECTION 4: TRADE ANALYSIS")
print("=" * 80)

for day in DAYS:
    trades = load_trades(day)
    prices = load_prices(day)

    print(f"\n--- Day {day} ---")

    for product_key in ['OSMIUM', 'PEPPER']:
        trs = [t for t in trades if product_key in t['symbol']]
        prs = [r for r in prices if product_key in r['product']]

        if not trs:
            print(f"\n  {product_key}: No trades")
            continue

        # Build mid-price lookup
        mid_lookup = {}
        for r in prs:
            ts = int(r['timestamp'])
            mid = float(r['mid_price']) if r['mid_price'] else None
            mid_lookup[ts] = mid

        print(f"\n  {product_key}: {len(trs)} trades")

        # Trade timing
        timestamps = [int(t['timestamp']) for t in trs]
        print(f"    Timestamp range: {min(timestamps)} to {max(timestamps)}")

        # Trade prices vs mid
        trade_vs_mid = []
        for t in trs:
            ts = int(t['timestamp'])
            price = float(t['price'])
            qty = int(t['quantity'])
            mid = mid_lookup.get(ts)
            if mid:
                trade_vs_mid.append((price - mid, qty))

        if trade_vs_mid:
            buy_trades = [(d, q) for d, q in trade_vs_mid if d > 0]
            sell_trades = [(d, q) for d, q in trade_vs_mid if d < 0]
            at_mid = [(d, q) for d, q in trade_vs_mid if d == 0]
            print(f"    Above mid (buys): {len(buy_trades)}, Below mid (sells): {len(sell_trades)}, At mid: {len(at_mid)}")

            if buy_trades:
                dists = [d for d, q in buy_trades]
                print(f"    Buy distance from mid: mean={statistics.mean(dists):.2f}, min={min(dists):.1f}, max={max(dists):.1f}")
            if sell_trades:
                dists = [d for d, q in sell_trades]
                print(f"    Sell distance from mid: mean={statistics.mean(dists):.2f}, min={min(dists):.1f}, max={max(dists):.1f}")

        # Volume per trade
        qtys = [int(t['quantity']) for t in trs]
        print(f"    Trade qty: min={min(qtys)}, max={max(qtys)}, mean={statistics.mean(qtys):.1f}")
        qty_dist = Counter(qtys)
        print(f"    Qty distribution: {dict(sorted(qty_dist.items()))}")

        # Buyer/seller patterns
        buyers = Counter(t['buyer'] for t in trs if t['buyer'])
        sellers = Counter(t['seller'] for t in trs if t['seller'])
        print(f"    Buyers: {dict(buyers.most_common(10))}")
        print(f"    Sellers: {dict(sellers.most_common(10))}")

        # Inter-trade timing
        if len(timestamps) > 1:
            gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            print(f"    Inter-trade gap: min={min(gaps)}, max={max(gaps)}, mean={statistics.mean(gaps):.0f}, median={statistics.median(gaps):.0f}")

# ============================================================
# SECTION 5: OSMIUM - Sequential book analysis (bot behavior)
# ============================================================
print("\n" + "=" * 80)
print("SECTION 5: OSMIUM SEQUENTIAL BOOK ANALYSIS")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} (first 50 ticks) ---")
    for i, r in enumerate(osmium[:50]):
        bids, asks = parse_book(r)
        ts = r['timestamp']
        mid = r['mid_price']
        bid_str = " | ".join(f"{p}x{v}" for p, v in bids)
        ask_str = " | ".join(f"{p}x{v}" for p, v in asks)
        print(f"  t={ts:>5}: [{bid_str:>40}] {mid:>10} [{ask_str:<40}]")

# ============================================================
# SECTION 6: PEPPER - Sequential book analysis
# ============================================================
print("\n" + "=" * 80)
print("SECTION 6: PEPPER SEQUENTIAL BOOK ANALYSIS (first 50 ticks)")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    pepper = [r for r in prices if 'PEPPER' in r['product']]

    print(f"\n--- Day {day} ---")
    for i, r in enumerate(pepper[:50]):
        bids, asks = parse_book(r)
        ts = r['timestamp']
        mid = r['mid_price']
        bid_str = " | ".join(f"{p}x{v}" for p, v in bids)
        ask_str = " | ".join(f"{p}x{v}" for p, v in asks)
        print(f"  t={ts:>5}: [{bid_str:>40}] {mid:>10} [{ask_str:<40}]")

# ============================================================
# SECTION 7: OSMIUM - Tick-by-tick volume/level transitions
# ============================================================
print("\n" + "=" * 80)
print("SECTION 7: OSMIUM BOOK STATE TRANSITIONS")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # Track how the book changes tick to tick
    prev_bids = None
    prev_asks = None

    transitions = Counter()

    # Volume at each level when both sides present
    bid_vol_when_both = []
    ask_vol_when_both = []

    # When one-sided, what happened on the next tick?
    one_sided_transitions = {"bid_only": Counter(), "ask_only": Counter()}

    for i, r in enumerate(osmium):
        bids, asks = parse_book(r)

        if bids and asks:
            total_bid_vol = sum(v for _, v in bids)
            total_ask_vol = sum(v for _, v in asks)
            bid_vol_when_both.append(total_bid_vol)
            ask_vol_when_both.append(total_ask_vol)

        state = ("B" if bids else "-") + ("A" if asks else "-")

        if prev_bids is not None:
            prev_state = ("B" if prev_bids else "-") + ("A" if prev_asks else "-")
            transitions[(prev_state, state)] += 1

            if prev_bids and not prev_asks:
                one_sided_transitions["bid_only"][state] += 1
            elif prev_asks and not prev_bids:
                one_sided_transitions["ask_only"][state] += 1

        prev_bids = bids
        prev_asks = asks

    print(f"  State transitions: {dict(transitions.most_common(10))}")
    print(f"  After bid-only: {dict(one_sided_transitions['bid_only'].most_common(5))}")
    print(f"  After ask-only: {dict(one_sided_transitions['ask_only'].most_common(5))}")

    if bid_vol_when_both:
        print(f"  Total bid vol (both sides): mean={statistics.mean(bid_vol_when_both):.1f}, std={statistics.stdev(bid_vol_when_both):.1f}")
    if ask_vol_when_both:
        print(f"  Total ask vol (both sides): mean={statistics.mean(ask_vol_when_both):.1f}, std={statistics.stdev(ask_vol_when_both):.1f}")

# ============================================================
# SECTION 8: PEPPER drift analysis - precise drift rate
# ============================================================
print("\n" + "=" * 80)
print("SECTION 8: PEPPER DRIFT ANALYSIS")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    pepper = [r for r in prices if 'PEPPER' in r['product']]

    print(f"\n--- Day {day} ---")

    mids = [(int(r['timestamp']), float(r['mid_price'])) for r in pepper if r['mid_price']]

    if len(mids) < 2:
        continue

    # Compute drift rate
    total_drift = mids[-1][1] - mids[0][1]
    total_ticks = (mids[-1][0] - mids[0][0]) / 100
    drift_per_tick = total_drift / total_ticks if total_ticks else 0

    print(f"  Total drift: {total_drift:.1f} over {total_ticks:.0f} ticks = {drift_per_tick:.4f} per tick")

    # Rolling drift (every 100 ticks)
    window = 100
    drifts = []
    for i in range(0, len(mids) - window, window):
        d = mids[i + window][1] - mids[i][1]
        dt = (mids[i + window][0] - mids[i][0]) / 100
        drifts.append(d / dt if dt else 0)

    if drifts:
        print(f"  Rolling drift (100-tick windows): mean={statistics.mean(drifts):.4f}, std={statistics.stdev(drifts):.4f}")
        print(f"    Min window drift: {min(drifts):.4f}, Max: {max(drifts):.4f}")

    # Check if drift is constant or varies
    # Also: is there volatility around the drift?
    returns = [mids[i+1][1] - mids[i][1] for i in range(len(mids)-1)]
    if returns:
        print(f"  Per-tick returns: mean={statistics.mean(returns):.4f}, std={statistics.stdev(returns):.4f}")
        print(f"    Positive: {sum(1 for r in returns if r > 0)}, Zero: {sum(1 for r in returns if r == 0)}, Negative: {sum(1 for r in returns if r < 0)}")

# ============================================================
# SECTION 9: OSMIUM autocorrelation and predictability
# ============================================================
print("\n" + "=" * 80)
print("SECTION 9: OSMIUM RETURN PREDICTABILITY")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    mids = [float(r['mid_price']) for r in osmium if r['mid_price']]

    if len(mids) < 100:
        continue

    print(f"\n--- Day {day} ---")

    # Returns
    returns = [mids[i+1] - mids[i] for i in range(len(mids)-1)]

    # Autocorrelation at various lags
    n = len(returns)
    mean_r = statistics.mean(returns)
    var_r = statistics.variance(returns)

    if var_r > 0:
        for lag in [1, 2, 3, 5, 10]:
            if lag < n:
                cov = sum((returns[i] - mean_r) * (returns[i + lag] - mean_r) for i in range(n - lag)) / (n - lag)
                acf = cov / var_r
                print(f"  Autocorrelation lag {lag}: {acf:.4f}")

    # Is mid-price change predictable from book state?
    # When bids heavy vs asks heavy, what happens next?
    book_imbalance_next_return = []
    for i, r in enumerate(osmium[:-1]):
        bids, asks = parse_book(r)
        if bids and asks and i < len(returns):
            bid_vol = sum(v for _, v in bids)
            ask_vol = sum(v for _, v in asks)
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
            book_imbalance_next_return.append((imbalance, returns[i]))

    if book_imbalance_next_return:
        # Split into quintiles
        sorted_by_imb = sorted(book_imbalance_next_return, key=lambda x: x[0])
        n = len(sorted_by_imb)
        q_size = n // 5
        for q in range(5):
            start = q * q_size
            end = start + q_size if q < 4 else n
            chunk = sorted_by_imb[start:end]
            mean_imb = statistics.mean([x[0] for x in chunk])
            mean_ret = statistics.mean([x[1] for x in chunk])
            print(f"  OBI quintile {q+1}: avg_imb={mean_imb:.3f}, avg_next_return={mean_ret:.4f}")

    # When one side is empty (only bids or only asks), what happens?
    one_sided_returns = {"bid_only": [], "ask_only": []}
    for i, r in enumerate(osmium[:-1]):
        bids, asks = parse_book(r)
        if bids and not asks and i < len(returns):
            one_sided_returns["bid_only"].append(returns[i])
        elif asks and not bids and i < len(returns):
            one_sided_returns["ask_only"].append(returns[i])

    for side, rets in one_sided_returns.items():
        if rets:
            print(f"  After {side}: n={len(rets)}, mean_return={statistics.mean(rets):.4f}, positive={sum(1 for r in rets if r > 0)}, negative={sum(1 for r in rets if r < 0)}")

# ============================================================
# SECTION 10: OSMIUM - Volume patterns and bot classification
# ============================================================
print("\n" + "=" * 80)
print("SECTION 10: OSMIUM BOT IDENTIFICATION")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # Analyze each order level: (volume, distance from mid) pairs
    level_data = []  # (distance, volume, side)

    for r in osmium:
        bids, asks = parse_book(r)
        mid = float(r['mid_price']) if r['mid_price'] else None
        if not mid:
            continue

        for bp, bv in bids:
            dist = round(mid - bp, 1)
            level_data.append((dist, bv, 'bid'))
        for ap, av in asks:
            dist = round(ap - mid, 1)
            level_data.append((dist, av, 'ask'))

    # Cluster by (distance, volume) to identify bot types
    vol_dist_pairs = Counter()
    for dist, vol, side in level_data:
        vol_dist_pairs[(dist, vol, side)] += 1

    print("  Top 30 (distance, volume, side) patterns:")
    for (dist, vol, side), count in vol_dist_pairs.most_common(30):
        print(f"    dist={dist:>5.1f}, vol={vol:>3}, side={side:>3}: {count:>5} times")

# ============================================================
# SECTION 11: PEPPER - Volume patterns and bot classification
# ============================================================
print("\n" + "=" * 80)
print("SECTION 11: PEPPER BOT IDENTIFICATION")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    pepper = [r for r in prices if 'PEPPER' in r['product']]

    print(f"\n--- Day {day} ---")

    level_data = []

    for r in pepper:
        bids, asks = parse_book(r)
        mid = float(r['mid_price']) if r['mid_price'] else None
        if not mid:
            continue

        for bp, bv in bids:
            dist = round(mid - bp, 1)
            level_data.append((dist, bv, 'bid'))
        for ap, av in asks:
            dist = round(ap - mid, 1)
            level_data.append((dist, av, 'ask'))

    vol_dist_pairs = Counter()
    for dist, vol, side in level_data:
        vol_dist_pairs[(dist, vol, side)] += 1

    print("  Top 30 (distance, volume, side) patterns:")
    for (dist, vol, side), count in vol_dist_pairs.most_common(30):
        print(f"    dist={dist:>5.1f}, vol={vol:>3}, side={side:>3}: {count:>5} times")

# ============================================================
# SECTION 12: How much edge is left on the table?
# ============================================================
print("\n" + "=" * 80)
print("SECTION 12: THEORETICAL EDGE ANALYSIS")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)

    for product_key in ['OSMIUM', 'PEPPER']:
        rows = [r for r in prices if product_key in r['product']]

        print(f"\n  {product_key} Day {day}:")

        # Perfect foresight: if we knew next mid, how much could we make?
        mids = [(int(r['timestamp']), float(r['mid_price'])) for r in rows if r['mid_price']]

        if len(mids) < 2:
            continue

        # Strategy 1: Perfect taking - buy below future mid, sell above
        # We scan the book and see if any orders are mispriced relative to next mid
        perfect_pnl = 0
        for i, r in enumerate(rows[:-1]):
            bids, asks = parse_book(r)
            next_mid = float(rows[i+1]['mid_price']) if rows[i+1]['mid_price'] else None
            if not next_mid:
                continue

            # Could buy asks below next mid
            for ap, av in asks:
                if ap < next_mid:
                    perfect_pnl += (next_mid - ap) * av

            # Could sell to bids above next mid
            for bp, bv in bids:
                if bp > next_mid:
                    perfect_pnl += (bp - next_mid) * bv

        print(f"    Perfect 1-tick foresight PnL (no pos limit): {perfect_pnl:.0f}")

        # Strategy 2: Perfect MM - always quote at fair and collect spread
        # Approximate: sum of half-spreads collected
        spread_pnl = 0
        for r in rows:
            bids, asks = parse_book(r)
            mid = float(r['mid_price']) if r['mid_price'] else None
            if not mid or not bids or not asks:
                continue
            # If we could buy at best bid and sell at best ask every tick
            spread_pnl += (asks[0][0] - bids[0][0]) * min(bids[0][1], asks[0][1])

        print(f"    Max spread capture (buy bid, sell ask, min vol): {spread_pnl:.0f}")

        # PEPPER: total drift PnL if perfectly positioned
        if product_key == 'PEPPER':
            total_drift = mids[-1][1] - mids[0][1]
            print(f"    Max drift PnL (80 units * drift): {80 * total_drift:.0f}")
            print(f"    Drift per tick: {total_drift / ((mids[-1][0] - mids[0][0])/100):.4f}")

print("\nDone!")
