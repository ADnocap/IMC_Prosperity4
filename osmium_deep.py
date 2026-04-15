"""
Deep OSMIUM analysis: find exploitable patterns for new strategies.
Focus on what we're NOT doing yet.
"""
import csv
import statistics
from collections import defaultdict, Counter
import math

DATA_DIR = "data/prosperity4/round1"

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
    bids = []
    asks = []
    for i in range(1, 4):
        bp = row.get(f'bid_price_{i}', '')
        bv = row.get(f'bid_volume_{i}', '')
        if bp and bv:
            bids.append((int(float(bp)), int(bv)))
        ap = row.get(f'ask_price_{i}', '')
        av = row.get(f'ask_volume_{i}', '')
        if ap and av:
            asks.append((int(float(ap)), int(av)))
    bids.sort(key=lambda x: -x[0])
    asks.sort(key=lambda x: x[0])
    return bids, asks


def classify_levels(bids, asks):
    """Classify each order level as Bot1, Bot2, or Bot3.
    Bot2: vol 10-15, always at a consistent offset from FV
    Bot1: vol 20-30, further from FV
    Bot3: vol < 10, very close to FV, rare
    """
    classified_bids = []
    classified_asks = []

    for p, v in bids:
        if 10 <= v <= 15:
            classified_bids.append((p, v, 'bot2'))
        elif v >= 20:
            classified_bids.append((p, v, 'bot1'))
        else:
            classified_bids.append((p, v, 'bot3'))

    for p, v in asks:
        if 10 <= v <= 15:
            classified_asks.append((p, v, 'bot2'))
        elif v >= 20:
            classified_asks.append((p, v, 'bot1'))
        else:
            classified_asks.append((p, v, 'bot3'))

    return classified_bids, classified_asks


def extract_fv_from_bots(classified_bids, classified_asks):
    """Try to extract true FV from bot quotes.
    Bot2 quotes at FV-8 (bid) and FV+8 (ask) per calibration.
    Bot1 quotes at FV-10 (bid) and FV+10 (ask) approximately.
    """
    estimates = []

    for p, v, bot in classified_bids:
        if bot == 'bot2':
            estimates.append(('bot2_bid', p + 8))
        elif bot == 'bot1':
            estimates.append(('bot1_bid', p + 10.5))

    for p, v, bot in classified_asks:
        if bot == 'bot2':
            estimates.append(('bot2_ask', p - 8))
        elif bot == 'bot1':
            estimates.append(('bot1_ask', p - 10.5))

    return estimates


# ============================================================
# ANALYSIS 1: How accurate is our FV estimation?
# ============================================================
print("=" * 80)
print("ANALYSIS 1: FV ESTIMATION ACCURACY")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # For each tick with both bot2 bid and ask, we can compute "true" FV
    fv_from_bot2_bid = []
    fv_from_bot2_ask = []
    fv_from_bot1_bid = []
    fv_from_bot1_ask = []
    fv_agreement = []  # when both bot2 bid and ask present

    for r in osmium:
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        estimates = extract_fv_from_bots(cb, ca)

        by_type = {}
        for etype, val in estimates:
            by_type.setdefault(etype, []).append(val)

        if 'bot2_bid' in by_type and 'bot2_ask' in by_type:
            fv_bid = by_type['bot2_bid'][0]
            fv_ask = by_type['bot2_ask'][0]
            fv_agreement.append(fv_ask - fv_bid)

        if 'bot2_bid' in by_type:
            fv_from_bot2_bid.append(by_type['bot2_bid'][0])
        if 'bot2_ask' in by_type:
            fv_from_bot2_ask.append(by_type['bot2_ask'][0])
        if 'bot1_bid' in by_type:
            fv_from_bot1_bid.append(by_type['bot1_bid'][0])
        if 'bot1_ask' in by_type:
            fv_from_bot1_ask.append(by_type['bot1_ask'][0])

    if fv_agreement:
        dist = Counter(fv_agreement)
        print(f"  Bot2 bid-vs-ask FV disagreement: {dict(sorted(dist.items()))}")
        print(f"    n={len(fv_agreement)}, mean={statistics.mean(fv_agreement):.3f}")

    # When Bot2 bid says FV=X and Bot2 ask says FV=Y, what does that tell us?
    # If disagree by 1, it means FV is between X and X+1 (fractional FV)

# ============================================================
# ANALYSIS 2: Bot2 offset calibration - is it exactly 8?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 2: BOT2 OFFSET CALIBRATION")
print("=" * 80)

# Use ticks where we see Bot2 on BOTH sides to pin down FV
# Then check what the offset actually is
for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # When both Bot2 bid and ask present, spread = ask - bid
    bot2_spreads = Counter()
    bot2_bid_offsets = []
    bot2_ask_offsets = []

    for r in osmium:
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)

        bot2_bids = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_asks = [(p, v) for p, v, t in ca if t == 'bot2']

        if bot2_bids and bot2_asks:
            spread = bot2_asks[0][0] - bot2_bids[0][0]
            bot2_spreads[spread] += 1

            # If spread is 16, FV = bid + 8 = ask - 8 (integer FV)
            # If spread is 17, FV is fractional: between bid+8 and ask-8
            # If spread is 15, FV is fractional: between bid+7.5 and ask-7.5
            mid = (bot2_bids[0][0] + bot2_asks[0][0]) / 2.0

    print(f"  Bot2 spread distribution: {dict(sorted(bot2_spreads.items()))}")


# ============================================================
# ANALYSIS 3: Bot3 deep analysis - when does it appear and what does it tell us?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 3: BOT3 BEHAVIOR")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    bot3_appearances = 0
    bot3_bid_count = 0
    bot3_ask_count = 0
    bot3_volumes = []
    bot3_distances_from_bot2_mid = []

    # Track what happens AFTER bot3 appears
    bot3_next_returns = []

    prev_mid = None

    for i, r in enumerate(osmium):
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)

        bot3_bids = [(p, v) for p, v, t in cb if t == 'bot3']
        bot3_asks = [(p, v) for p, v, t in ca if t == 'bot3']
        bot2_bids = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_asks = [(p, v) for p, v, t in ca if t == 'bot2']

        mid = float(r['mid_price']) if r['mid_price'] else None

        has_bot3 = bool(bot3_bids or bot3_asks)
        if has_bot3:
            bot3_appearances += 1
            for p, v in bot3_bids:
                bot3_bid_count += 1
                bot3_volumes.append(v)
                if bot2_bids and bot2_asks:
                    bot2_mid = (bot2_bids[0][0] + bot2_asks[0][0]) / 2
                    bot3_distances_from_bot2_mid.append(p - bot2_mid)
            for p, v in bot3_asks:
                bot3_ask_count += 1
                bot3_volumes.append(v)
                if bot2_bids and bot2_asks:
                    bot2_mid = (bot2_bids[0][0] + bot2_asks[0][0]) / 2
                    bot3_distances_from_bot2_mid.append(bot2_mid - p)

            # What happens on next tick?
            if i < len(osmium) - 1 and mid is not None:
                next_mid = float(osmium[i+1]['mid_price']) if osmium[i+1]['mid_price'] else None
                if next_mid and next_mid > 0 and mid > 0:
                    bot3_next_returns.append(next_mid - mid)

                    # Does bot3 predict direction?
                    if bot3_bids and not bot3_asks:
                        # Bot3 is buying → price should go up?
                        pass
                    elif bot3_asks and not bot3_bids:
                        # Bot3 is selling → price should go down?
                        pass

    print(f"  Bot3 appearances: {bot3_appearances}/{len(osmium)} = {bot3_appearances/len(osmium)*100:.1f}%")
    print(f"  Bot3 bid count: {bot3_bid_count}, ask count: {bot3_ask_count}")
    if bot3_volumes:
        print(f"  Bot3 volumes: {Counter(bot3_volumes).most_common(10)}")
    if bot3_distances_from_bot2_mid:
        print(f"  Bot3 distance from Bot2 mid: mean={statistics.mean(bot3_distances_from_bot2_mid):.2f}")
        dist_counter = Counter(round(d, 1) for d in bot3_distances_from_bot2_mid)
        print(f"    Distribution: {dict(sorted(dist_counter.items()))}")


# ============================================================
# ANALYSIS 4: One-sided book signal (more rigorous)
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 4: ONE-SIDED BOOK SIGNALS")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # When book goes one-sided, track returns over next 1,2,3,5,10 ticks
    for horizon in [1, 2, 3, 5, 10]:
        bid_only_returns = []
        ask_only_returns = []
        both_returns = []

        for i, r in enumerate(osmium):
            if i + horizon >= len(osmium):
                break
            bids, asks = parse_book(r)
            # Get FV-based return (use bot2 mid if available, else raw mid)
            cb, ca = classify_levels(bids, asks)
            bot2_bids = [(p, v) for p, v, t in cb if t == 'bot2']
            bot2_asks = [(p, v) for p, v, t in ca if t == 'bot2']

            # Current FV estimate
            if bot2_bids and bot2_asks:
                cur_fv = (bot2_bids[0][0] + bot2_asks[0][0]) / 2
            elif bot2_bids:
                cur_fv = bot2_bids[0][0] + 8
            elif bot2_asks:
                cur_fv = bot2_asks[0][0] - 8
            else:
                continue

            # Future FV
            future_r = osmium[i + horizon]
            future_bids, future_asks = parse_book(future_r)
            future_cb, future_ca = classify_levels(future_bids, future_asks)
            future_bot2_b = [(p, v) for p, v, t in future_cb if t == 'bot2']
            future_bot2_a = [(p, v) for p, v, t in future_ca if t == 'bot2']

            if future_bot2_b and future_bot2_a:
                future_fv = (future_bot2_b[0][0] + future_bot2_a[0][0]) / 2
            elif future_bot2_b:
                future_fv = future_bot2_b[0][0] + 8
            elif future_bot2_a:
                future_fv = future_bot2_a[0][0] - 8
            else:
                continue

            ret = future_fv - cur_fv

            if bids and not asks:
                bid_only_returns.append(ret)
            elif asks and not bids:
                ask_only_returns.append(ret)
            elif bids and asks:
                both_returns.append(ret)

        if horizon == 1:
            print(f"\n  Horizon {horizon}:")
        else:
            print(f"  Horizon {horizon}:")

        if bid_only_returns:
            print(f"    Bid-only → mean_ret={statistics.mean(bid_only_returns):+.3f}, n={len(bid_only_returns)}")
        if ask_only_returns:
            print(f"    Ask-only → mean_ret={statistics.mean(ask_only_returns):+.3f}, n={len(ask_only_returns)}")
        if both_returns and horizon == 1:
            print(f"    Both     → mean_ret={statistics.mean(both_returns):+.3f}, n={len(both_returns)}")


# ============================================================
# ANALYSIS 5: Trade data analysis - what happens around bot trades?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 5: TRADE IMPACT ANALYSIS")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    trades = load_trades(day)
    osmium_prices = [r for r in prices if 'OSMIUM' in r['product']]
    osmium_trades = [t for t in trades if 'OSMIUM' in t['symbol']]

    print(f"\n--- Day {day} ---")

    # Build tick → FV lookup
    tick_fv = {}
    for i, r in enumerate(osmium_prices):
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']
        if bot2_b and bot2_a:
            tick_fv[i] = (bot2_b[0][0] + bot2_a[0][0]) / 2
        elif bot2_b:
            tick_fv[i] = bot2_b[0][0] + 8
        elif bot2_a:
            tick_fv[i] = bot2_a[0][0] - 8

    # For each trade, look at FV before and after
    trade_impacts = []
    for t in osmium_trades:
        ts = int(t['timestamp'])
        tick_idx = ts // 100  # Convert timestamp to tick index

        price = float(t['price'])
        qty = int(t['quantity'])

        # FV before and after
        before_fv = tick_fv.get(tick_idx)
        after_fvs = [tick_fv.get(tick_idx + h) for h in [1, 2, 3, 5]]

        if before_fv:
            is_buy = price > before_fv
            trade_impacts.append({
                'price': price,
                'qty': qty,
                'fv_before': before_fv,
                'is_buy': is_buy,
                'fv_after': [f for f in after_fvs if f is not None],
            })

    buys = [t for t in trade_impacts if t['is_buy']]
    sells = [t for t in trade_impacts if not t['is_buy']]

    if buys:
        # After a buy trade, does FV go up or down?
        buy_impacts = []
        for t in buys:
            if t['fv_after']:
                buy_impacts.append(t['fv_after'][0] - t['fv_before'])
        if buy_impacts:
            print(f"  After bot BUY trade (n={len(buy_impacts)}): FV changes by mean={statistics.mean(buy_impacts):+.3f}")

    if sells:
        sell_impacts = []
        for t in sells:
            if t['fv_after']:
                sell_impacts.append(t['fv_after'][0] - t['fv_before'])
        if sell_impacts:
            print(f"  After bot SELL trade (n={len(sell_impacts)}): FV changes by mean={statistics.mean(sell_impacts):+.3f}")


# ============================================================
# ANALYSIS 6: Spread clustering - what makes spreads tighten/widen?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 6: SPREAD DYNAMICS")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    # Track what happens when Bot2 spread is 15 vs 16 vs 17
    spread_next_change = defaultdict(list)
    prev_bot2_spread = None
    prev_fv = None

    for i, r in enumerate(osmium):
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']

        if bot2_b and bot2_a:
            spread = bot2_a[0][0] - bot2_b[0][0]
            fv = (bot2_b[0][0] + bot2_a[0][0]) / 2

            if prev_bot2_spread is not None and prev_fv is not None:
                fv_change = fv - prev_fv
                spread_next_change[prev_bot2_spread].append(fv_change)

            prev_bot2_spread = spread
            prev_fv = fv

    for s in sorted(spread_next_change.keys()):
        changes = spread_next_change[s]
        if len(changes) > 10:
            print(f"  Spread={s}: n={len(changes)}, mean_next_fv_change={statistics.mean(changes):+.4f}, std={statistics.stdev(changes):.3f}")

    # What does a changing spread tell us about FV precision?
    # If spread goes 16→17→16, FV is oscillating around a half-integer
    # If spread stays 16, FV is near an integer
    transition_counts = Counter()
    prev_spread = None
    for r in osmium:
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']
        if bot2_b and bot2_a:
            spread = bot2_a[0][0] - bot2_b[0][0]
            if prev_spread is not None:
                transition_counts[(prev_spread, spread)] += 1
            prev_spread = spread
        else:
            prev_spread = None

    print(f"  Spread transitions: {dict(transition_counts.most_common(10))}")


# ============================================================
# ANALYSIS 7: Can we extract FV more precisely using Bot2 asymmetry?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 7: PRECISE FV FROM BOT2 ASYMMETRY")
print("=" * 80)

# From the calibration: Bot2 bid = floor(FV-0.5) - 7, Bot2 ask = floor(FV-0.5) + 9
# So: FV = Bot2_bid + 7 + frac, where frac = (FV - 0.5) mod 1
# And: FV = Bot2_ask - 9 + frac'
# Spread = ask - bid = (floor(FV-0.5) + 9) - (floor(FV-0.5) - 7) = 16
# BUT if FV-0.5 crosses an integer, spread can be 15 or 17

print("Deriving FV from Bot2 quotes using calibrated offsets:")
print("  Bot2 bid = floor(FV - 0.5) - 7")
print("  Bot2 ask = floor(FV - 0.5) + 9")
print("  When spread=16: FV = bid + 7.5 + 0.5 = bid + 8, or FV = ask - 8")
print("  When spread=17: FV-0.5 is between integers, so FV is near X.5")
print("  When spread=15: FV-0.5 is between integers (other direction)")

for day in [-2]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    # Verify calibration by checking consistency
    print(f"\n--- Day {day} (first 100 ticks with Bot2 on both sides) ---")
    count = 0
    for r in osmium:
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']
        bot1_b = [(p, v) for p, v, t in cb if t == 'bot1']
        bot1_a = [(p, v) for p, v, t in ca if t == 'bot1']

        if bot2_b and bot2_a:
            b2_bid = bot2_b[0][0]
            b2_ask = bot2_a[0][0]
            spread = b2_ask - b2_bid

            # Using calibration: bid = floor(FV-0.5) - 7
            # So floor(FV-0.5) = bid + 7
            floor_fv_minus_half = b2_bid + 7
            # FV is in range [floor_fv_minus_half + 0.5, floor_fv_minus_half + 1.5)
            fv_lower = floor_fv_minus_half + 0.5
            fv_upper = floor_fv_minus_half + 1.5

            # From ask: ask = floor(FV-0.5) + 9
            # floor(FV-0.5) = ask - 9
            floor_fv_minus_half_ask = b2_ask - 9

            # Check if Bot1 helps narrow FV
            b1_info = ""
            if bot1_b:
                # Bot1 bid = floor(FV) - 10
                b1_bid = bot1_b[0][0]
                floor_fv = b1_bid + 10
                b1_info += f" B1bid→floor(FV)={floor_fv}"
            if bot1_a:
                # Bot1 ask = ceil(FV) + 10
                b1_ask = bot1_a[0][0]
                ceil_fv = b1_ask - 10
                b1_info += f" B1ask→ceil(FV)={ceil_fv}"

            if count < 30:
                print(f"    B2: {b2_bid}/{b2_ask} (spread={spread}), floor(FV-0.5)_bid={floor_fv_minus_half}, _ask={floor_fv_minus_half_ask}, FV∈[{fv_lower},{fv_upper}){b1_info}")
            count += 1


# ============================================================
# ANALYSIS 8: Quantify edge from different quoting strategies
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 8: QUOTING STRATEGY COMPARISON")
print("=" * 80)

# For each tick, compute what our passive quotes would be under different strategies
# and whether they would have gotten filled (by comparing to Bot3 activity)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    trades = load_trades(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]
    osmium_trades = [t for t in trades if 'OSMIUM' in t['symbol']]

    print(f"\n--- Day {day} ---")

    # Build trade lookup
    trades_by_tick = defaultdict(list)
    for t in osmium_trades:
        tick = int(t['timestamp']) // 100
        trades_by_tick[tick].append({
            'price': float(t['price']),
            'qty': int(t['quantity']),
        })

    # For each tick, if a trade happened, could we have been the counterparty?
    fillable_ticks = 0
    total_ticks_with_trades = 0

    # Edge at different quote levels
    edge_by_level = defaultdict(lambda: {'fills': 0, 'edge_sum': 0, 'vol_sum': 0})

    for i, r in enumerate(osmium):
        tick_trades = trades_by_tick.get(i, [])
        if not tick_trades:
            continue

        total_ticks_with_trades += 1

        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']

        if not (bot2_b and bot2_a):
            continue

        fv = (bot2_b[0][0] + bot2_a[0][0]) / 2

        for trade in tick_trades:
            tp = trade['price']
            tq = trade['qty']

            # This trade crossed a bot level. If we had been quoting closer,
            # would the taker have hit us instead?
            if tp > fv:
                # Taker bought (lifted ask). If our ask was closer to FV, we'd get filled
                for offset in range(1, 9):
                    our_ask = int(round(fv)) + offset
                    if our_ask <= tp:
                        edge = our_ask - fv
                        edge_by_level[f'ask+{offset}']['fills'] += 1
                        edge_by_level[f'ask+{offset}']['edge_sum'] += edge * tq
                        edge_by_level[f'ask+{offset}']['vol_sum'] += tq
            elif tp < fv:
                # Taker sold (hit bid)
                for offset in range(1, 9):
                    our_bid = int(round(fv)) - offset
                    if our_bid >= tp:
                        edge = fv - our_bid
                        edge_by_level[f'bid-{offset}']['fills'] += 1
                        edge_by_level[f'bid-{offset}']['edge_sum'] += edge * tq
                        edge_by_level[f'bid-{offset}']['vol_sum'] += tq

    print(f"  Ticks with trades: {total_ticks_with_trades}")
    print(f"  Edge by quote level (per 10k ticks):")
    for level in sorted(edge_by_level.keys()):
        data = edge_by_level[level]
        print(f"    {level}: fills={data['fills']}, total_edge={data['edge_sum']:.0f}, avg_edge_per_fill={data['edge_sum']/max(data['fills'],1):.1f}")


# ============================================================
# ANALYSIS 9: FV volatility structure - how big are FV jumps?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 9: FV JUMP SIZE DISTRIBUTION")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]

    print(f"\n--- Day {day} ---")

    fv_series = []
    for r in osmium:
        bids, asks = parse_book(r)
        cb, ca = classify_levels(bids, asks)
        bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
        bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']

        if bot2_b and bot2_a:
            fv = (bot2_b[0][0] + bot2_a[0][0]) / 2
            fv_series.append(fv)
        else:
            fv_series.append(None)

    # Compute FV changes (skip None gaps)
    fv_changes = []
    prev = None
    for fv in fv_series:
        if fv is not None and prev is not None:
            fv_changes.append(fv - prev)
        prev = fv

    if fv_changes:
        nonzero = [c for c in fv_changes if c != 0]
        print(f"  FV changes: {len(fv_changes)} total, {len(nonzero)} nonzero ({100*len(nonzero)/len(fv_changes):.1f}%)")
        print(f"  FV change stats: mean={statistics.mean(fv_changes):.4f}, std={statistics.stdev(fv_changes):.3f}")
        if nonzero:
            print(f"  Nonzero FV changes: mean={statistics.mean(nonzero):.4f}, std={statistics.stdev(nonzero):.3f}")
            abs_changes = [abs(c) for c in nonzero]
            print(f"  Abs FV change: mean={statistics.mean(abs_changes):.3f}, median={statistics.median(abs_changes):.1f}")

            # Distribution
            change_dist = Counter(c for c in nonzero)
            print(f"  Distribution (top 15): {dict(sorted(change_dist.most_common(15), key=lambda x: x[0]))}")

        # How many ticks between FV changes?
        gaps = []
        last_change_tick = None
        for i, c in enumerate(fv_changes):
            if c != 0:
                if last_change_tick is not None:
                    gaps.append(i - last_change_tick)
                last_change_tick = i
        if gaps:
            print(f"  Ticks between FV changes: mean={statistics.mean(gaps):.1f}, median={statistics.median(gaps):.0f}")


# ============================================================
# ANALYSIS 10: Profit potential from different position limits
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 10: OSMIUM MM SIZING ANALYSIS")
print("=" * 80)

# Simulate simple MM: quote at FV±X, track PnL with position management
for day in [-2]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']][:1000]

    print(f"\n--- Day {day} (first 1000 ticks) ---")

    for spread_offset in [1, 2, 3, 4, 5, 6, 7]:
        pos = 0
        cash = 0
        fills = 0
        adverse_fills = 0

        fv_series = []
        for r in osmium:
            bids, asks = parse_book(r)
            cb, ca = classify_levels(bids, asks)
            bot2_b = [(p, v) for p, v, t in cb if t == 'bot2']
            bot2_a = [(p, v) for p, v, t in ca if t == 'bot2']
            if bot2_b and bot2_a:
                fv = (bot2_b[0][0] + bot2_a[0][0]) / 2
            elif bot2_b:
                fv = bot2_b[0][0] + 8
            elif bot2_a:
                fv = bot2_a[0][0] - 8
            else:
                fv = fv_series[-1] if fv_series else 10000
            fv_series.append(fv)

        for i, r in enumerate(osmium):
            bids, asks = parse_book(r)
            fv = fv_series[i]
            fv_r = int(round(fv))

            our_bid = fv_r - spread_offset
            our_ask = fv_r + spread_offset

            # Check if any ask <= our_bid (we'd buy) - only possible if spread_offset is large
            for p, v in asks:
                if p <= our_bid and pos < 80:
                    q = min(v, 80 - pos)
                    cash -= p * q
                    pos += q
                    fills += 1

            # Check if any bid >= our_ask (we'd sell)
            for p, v in bids:
                if p >= our_ask and pos > -80:
                    q = min(v, 80 + pos)
                    cash += p * q
                    pos -= q
                    fills += 1

        # Mark to market
        final_fv = fv_series[-1]
        pnl = cash + pos * final_fv
        print(f"  Spread ±{spread_offset}: PnL={pnl:>8.0f}, fills={fills:>4}, final_pos={pos:>4}")


print("\nDone!")
