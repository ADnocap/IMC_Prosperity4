#!/usr/bin/env python3
"""
Comprehensive OSMIUM (ASH_COATED_OSMIUM) trade analysis.
Analyzes trade data from CSV files and submission logs.
"""

import csv
import json
import math
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path(r"C:\Users\alexa\OneDrive\Documents\IMC_trading_hack")
DATA = BASE / "data" / "prosperity4" / "round1"

TRADE_FILES = {
    -2: DATA / "trades_round_1_day_-2.csv",
    -1: DATA / "trades_round_1_day_-1.csv",
    0:  DATA / "trades_round_1_day_0.csv",
}

PRICE_FILES = {
    -2: DATA / "prices_round_1_day_-2.csv",
    -1: DATA / "prices_round_1_day_-1.csv",
    0:  DATA / "prices_round_1_day_0.csv",
}

LOG_FILE = BASE / "tmp" / "sub_151318" / "151318.log"

SYMBOL = "ASH_COATED_OSMIUM"
SPREAD = 16  # known spread for FV extraction


def load_prices(day):
    """Load price data for a given day, return dict: timestamp -> {bid1, ask1, mid, fv}"""
    prices = {}
    with open(PRICE_FILES[day], 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] != SYMBOL:
                continue
            ts = int(row['timestamp'])
            bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
            ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
            mid = float(row['mid_price']) if row['mid_price'] else None

            # FV from spread=16 ticks
            if bid1 is not None and ask1 is not None:
                fv = (bid1 + ask1) / 2.0
            elif bid1 is not None:
                fv = bid1 + SPREAD / 2
            elif ask1 is not None:
                fv = ask1 - SPREAD / 2
            else:
                fv = mid  # fallback

            prices[ts] = {
                'bid1': bid1, 'ask1': ask1, 'mid': mid, 'fv': fv
            }
    return prices


def load_trades(day):
    """Load trade data for a given day, return list of OSMIUM trades."""
    trades = []
    with open(TRADE_FILES[day], 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['symbol'] != SYMBOL:
                continue
            trades.append({
                'timestamp': int(row['timestamp']),
                'buyer': row.get('buyer', ''),
                'seller': row.get('seller', ''),
                'price': float(row['price']),
                'quantity': int(row['quantity']),
                'day': day,
            })
    return trades


def find_fv_at_ts(prices, ts):
    """Find FV at or just before timestamp ts."""
    if ts in prices:
        return prices[ts]['fv']
    # Find closest earlier timestamp
    valid = [t for t in prices if t <= ts]
    if valid:
        return prices[max(valid)]['fv']
    # Find closest later timestamp
    valid = [t for t in prices if t > ts]
    if valid:
        return prices[min(valid)]['fv']
    return None


def get_fv_at_offset(prices, ts, offset_ticks):
    """Get FV at ts + offset_ticks * 100."""
    target = ts + offset_ticks * 100
    return find_fv_at_ts(prices, target)


def print_separator(title):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def section_a(all_trades, all_prices):
    """Trade basics."""
    print_separator("A. TRADE BASICS")

    # Trades per day
    for day in sorted(TRADE_FILES.keys()):
        day_trades = [t for t in all_trades if t['day'] == day]
        print(f"\n  Day {day}: {len(day_trades)} OSMIUM trades")
        if day_trades:
            prices_list = [t['price'] for t in day_trades]
            qtys = [t['quantity'] for t in day_trades]
            print(f"    Price range: {min(prices_list):.0f} - {max(prices_list):.0f}")
            print(f"    Quantity range: {min(qtys)} - {max(qtys)}, mean: {sum(qtys)/len(qtys):.1f}")

    print(f"\n  Total OSMIUM trades across all days: {len(all_trades)}")

    # Buyer/seller fields
    buyers = set(t['buyer'] for t in all_trades)
    sellers = set(t['seller'] for t in all_trades)
    print(f"\n  Unique buyer values: {buyers}")
    print(f"  Unique seller values: {sellers}")

    # Trade price vs FV
    print("\n  --- Trade Price vs FV ---")
    offsets = []
    for t in all_trades:
        prices = all_prices[t['day']]
        fv = find_fv_at_ts(prices, t['timestamp'])
        if fv is not None:
            offset = t['price'] - fv
            offsets.append(offset)
            t['fv'] = fv
            t['offset'] = offset
            t['direction'] = 'buy' if t['price'] >= fv else 'sell'
        else:
            t['fv'] = None
            t['offset'] = None
            t['direction'] = None

    valid = [o for o in offsets if o is not None]
    if valid:
        print(f"  Price - FV distribution (N={len(valid)}):")
        print(f"    Mean offset: {sum(valid)/len(valid):.2f}")
        print(f"    Min: {min(valid):.1f}, Max: {max(valid):.1f}")

        # Histogram of offsets
        offset_counts = Counter(round(o) for o in valid)
        print(f"\n  Offset histogram (rounded to int):")
        for off in sorted(offset_counts.keys()):
            count = offset_counts[off]
            bar = '#' * count
            print(f"    {off:+5.0f}: {count:3d} {bar}")

    # Quantity distribution
    print("\n  --- Quantity Distribution ---")
    qtys = [t['quantity'] for t in all_trades]
    qty_counts = Counter(qtys)
    print(f"  Quantity histogram:")
    for q in sorted(qty_counts.keys()):
        count = qty_counts[q]
        bar = '#' * count
        print(f"    {q:3d}: {count:3d} {bar}")

    # Direction classification
    buys = sum(1 for t in all_trades if t['direction'] == 'buy')
    sells = sum(1 for t in all_trades if t['direction'] == 'sell')
    at_fv = sum(1 for t in all_trades if t['offset'] is not None and t['offset'] == 0)
    print(f"\n  Direction: buy-initiated={buys}, sell-initiated={sells}, at-FV={at_fv}")


def section_b(all_trades, all_prices):
    """Trade timing vs FV changes."""
    print_separator("B. TRADE TIMING vs FV CHANGES")

    for horizon_name, horizons in [("NEXT 1,2,5,10,20 ticks", [1, 2, 5, 10, 20])]:
        print(f"\n  --- FV Change After Trades ({horizon_name}) ---")
        for h in horizons:
            fv_changes_after_trade = []
            for t in all_trades:
                if t['fv'] is None:
                    continue
                prices = all_prices[t['day']]
                future_fv = get_fv_at_offset(prices, t['timestamp'], h)
                if future_fv is not None:
                    change = future_fv - t['fv']
                    fv_changes_after_trade.append(change)

            if fv_changes_after_trade:
                mean_change = sum(fv_changes_after_trade) / len(fv_changes_after_trade)
                abs_changes = [abs(c) for c in fv_changes_after_trade]
                mean_abs = sum(abs_changes) / len(abs_changes)
                nonzero = sum(1 for c in fv_changes_after_trade if c != 0)
                print(f"    +{h:2d} ticks: mean_change={mean_change:+.3f}, mean_abs={mean_abs:.3f}, "
                      f"nonzero={nonzero}/{len(fv_changes_after_trade)} ({100*nonzero/len(fv_changes_after_trade):.1f}%)")

    # FV changes BEFORE trades
    print(f"\n  --- FV Change BEFORE Trades (lookback 1,2,5,10 ticks) ---")
    for h in [1, 2, 5, 10]:
        fv_changes_before = []
        for t in all_trades:
            if t['fv'] is None:
                continue
            prices = all_prices[t['day']]
            past_fv = get_fv_at_offset(prices, t['timestamp'], -h)
            if past_fv is not None:
                change = t['fv'] - past_fv
                fv_changes_before.append(change)

        if fv_changes_before:
            mean_change = sum(fv_changes_before) / len(fv_changes_before)
            mean_abs = sum(abs(c) for c in fv_changes_before) / len(fv_changes_before)
            nonzero = sum(1 for c in fv_changes_before if c != 0)
            print(f"    -{h:2d} ticks: mean_change={mean_change:+.3f}, mean_abs={mean_abs:.3f}, "
                  f"nonzero={nonzero}/{len(fv_changes_before)} ({100*nonzero/len(fv_changes_before):.1f}%)")

    # Compare: at trade timestamps vs ALL timestamps
    print(f"\n  --- Baseline: FV Change at ALL timestamps (not just trade timestamps) ---")
    for day in sorted(all_prices.keys()):
        prices = all_prices[day]
        ts_list = sorted(prices.keys())
        for h in [1, 5, 10]:
            changes = []
            for ts in ts_list:
                target = ts + h * 100
                if target in prices:
                    changes.append(prices[target]['fv'] - prices[ts]['fv'])
            if changes:
                mean_abs = sum(abs(c) for c in changes) / len(changes)
                nonzero = sum(1 for c in changes if c != 0)
                print(f"    Day {day}, +{h:2d} ticks: mean_abs={mean_abs:.3f}, "
                      f"nonzero={nonzero}/{len(changes)} ({100*nonzero/len(changes):.1f}%)")


def section_c(all_trades, all_prices):
    """Trade flow as FV predictor."""
    print_separator("C. TRADE FLOW AS FV PREDICTOR")

    for h in [1, 2, 5, 10, 20]:
        buy_up = buy_dn = buy_flat = 0
        sell_up = sell_dn = sell_flat = 0

        for t in all_trades:
            if t['fv'] is None or t['direction'] is None:
                continue
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], h)
            if future_fv is None:
                continue

            change = future_fv - t['fv']
            if t['direction'] == 'buy':
                if change > 0: buy_up += 1
                elif change < 0: buy_dn += 1
                else: buy_flat += 1
            else:
                if change > 0: sell_up += 1
                elif change < 0: sell_dn += 1
                else: sell_flat += 1

        buy_total = buy_up + buy_dn + buy_flat
        sell_total = sell_up + sell_dn + sell_flat

        print(f"\n  Horizon +{h} ticks:")
        if buy_total > 0:
            print(f"    After BUY trade (N={buy_total}): "
                  f"P(FV_up)={buy_up/buy_total:.3f}, P(FV_dn)={buy_dn/buy_total:.3f}, P(flat)={buy_flat/buy_total:.3f}")
        if sell_total > 0:
            print(f"    After SELL trade (N={sell_total}): "
                  f"P(FV_up)={sell_up/sell_total:.3f}, P(FV_dn)={sell_dn/sell_total:.3f}, P(flat)={sell_flat/sell_total:.3f}")

        # Baseline: ALL timestamps
        all_up = all_dn = all_flat = 0
        for day in sorted(all_prices.keys()):
            prices = all_prices[day]
            ts_list = sorted(prices.keys())
            for ts in ts_list:
                target = ts + h * 100
                if target in prices:
                    change = prices[target]['fv'] - prices[ts]['fv']
                    if change > 0: all_up += 1
                    elif change < 0: all_dn += 1
                    else: all_flat += 1
        all_total = all_up + all_dn + all_flat
        if all_total > 0:
            print(f"    BASELINE all ticks (N={all_total}): "
                  f"P(FV_up)={all_up/all_total:.3f}, P(FV_dn)={all_dn/all_total:.3f}, P(flat)={all_flat/all_total:.3f}")

    # Conditional: FV change magnitude after buy vs sell trades
    print(f"\n  --- Mean FV Change (signed) After Buy vs Sell Trades ---")
    for h in [1, 2, 5, 10, 20]:
        buy_changes = []
        sell_changes = []
        for t in all_trades:
            if t['fv'] is None or t['direction'] is None:
                continue
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], h)
            if future_fv is None:
                continue
            change = future_fv - t['fv']
            if t['direction'] == 'buy':
                buy_changes.append(change)
            else:
                sell_changes.append(change)

        if buy_changes and sell_changes:
            mean_buy = sum(buy_changes) / len(buy_changes)
            mean_sell = sum(sell_changes) / len(sell_changes)
            print(f"    +{h:2d} ticks: after_buy={mean_buy:+.3f}, after_sell={mean_sell:+.3f}, "
                  f"spread={mean_buy - mean_sell:+.3f}")


def section_d(all_trades, all_prices):
    """Trade price patterns."""
    print_separator("D. TRADE PRICE PATTERNS (Offsets from FV)")

    # Group by offset
    offset_trades = defaultdict(list)
    for t in all_trades:
        if t['offset'] is not None:
            key = round(t['offset'])
            offset_trades[key].append(t)

    print(f"\n  --- Offset Distribution ---")
    for off in sorted(offset_trades.keys()):
        trades = offset_trades[off]
        print(f"    Offset {off:+3.0f}: {len(trades):3d} trades, "
              f"avg_qty={sum(t['quantity'] for t in trades)/len(trades):.1f}")

    # Predictive power by offset
    print(f"\n  --- Predictive Power by Offset (FV change at +5 ticks) ---")
    for off in sorted(offset_trades.keys()):
        trades = offset_trades[off]
        changes = []
        for t in trades:
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], 5)
            if future_fv is not None and t['fv'] is not None:
                changes.append(future_fv - t['fv'])
        if changes:
            mean_change = sum(changes) / len(changes)
            pos = sum(1 for c in changes if c > 0)
            neg = sum(1 for c in changes if c < 0)
            print(f"    Offset {off:+3.0f} (N={len(changes):3d}): mean_fv_change_5={mean_change:+.3f}, "
                  f"up={pos}, dn={neg}")

    # Predictive power by offset at +10 ticks
    print(f"\n  --- Predictive Power by Offset (FV change at +10 ticks) ---")
    for off in sorted(offset_trades.keys()):
        trades = offset_trades[off]
        changes = []
        for t in trades:
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], 10)
            if future_fv is not None and t['fv'] is not None:
                changes.append(future_fv - t['fv'])
        if changes:
            mean_change = sum(changes) / len(changes)
            pos = sum(1 for c in changes if c > 0)
            neg = sum(1 for c in changes if c < 0)
            print(f"    Offset {off:+3.0f} (N={len(changes):3d}): mean_fv_change_10={mean_change:+.3f}, "
                  f"up={pos}, dn={neg}")

    # Which offsets correspond to which book levels?
    print(f"\n  --- Trade Offsets Mapped to Book Structure ---")
    print(f"    Spread = {SPREAD}, so half-spread = {SPREAD/2}")
    print(f"    Best bid = FV - {SPREAD/2}, Best ask = FV + {SPREAD/2}")
    print(f"    Trades AT best bid (offset -{SPREAD/2}): likely seller-initiated (hitting bid)")
    print(f"    Trades AT best ask (offset +{SPREAD/2}): likely buyer-initiated (lifting ask)")
    print(f"    Trades INSIDE spread: likely aggressive orders from a bot")
    print(f"    Trades BEYOND best bid/ask: hitting deeper levels")

    for off in sorted(offset_trades.keys()):
        n = len(offset_trades[off])
        if off == -SPREAD // 2:
            label = "AT BEST BID"
        elif off == SPREAD // 2:
            label = "AT BEST ASK"
        elif -SPREAD // 2 < off < SPREAD // 2:
            label = "INSIDE SPREAD"
        elif off < -SPREAD // 2:
            label = "BELOW BEST BID (deeper sell)"
        else:
            label = "ABOVE BEST ASK (deeper buy)"
        print(f"    Offset {off:+3.0f}: {n:3d} trades -> {label}")


def section_e(all_trades, all_prices):
    """Trade clusters."""
    print_separator("E. TRADE CLUSTERS")

    # Group by (day, timestamp)
    clusters = defaultdict(list)
    for t in all_trades:
        clusters[(t['day'], t['timestamp'])].append(t)

    # Cluster size distribution
    cluster_sizes = Counter(len(v) for v in clusters.values())
    print(f"\n  Total unique (day, timestamp) with trades: {len(clusters)}")
    print(f"  Cluster size distribution:")
    for sz in sorted(cluster_sizes.keys()):
        print(f"    Size {sz}: {cluster_sizes[sz]} occurrences")

    # Multi-trade clusters
    multi = {k: v for k, v in clusters.items() if len(v) > 1}
    print(f"\n  Multi-trade clusters: {len(multi)}")

    # For multi-trade clusters: are they same direction?
    print(f"\n  --- Multi-Trade Cluster Direction Consistency ---")
    same_dir = 0
    mixed_dir = 0
    for (day, ts), trades in multi.items():
        dirs = set(t['direction'] for t in trades if t['direction'] is not None)
        if len(dirs) == 1:
            same_dir += 1
        else:
            mixed_dir += 1
    print(f"    Same direction: {same_dir}")
    print(f"    Mixed direction: {mixed_dir}")

    # Predictive power of clusters
    print(f"\n  --- Cluster Prediction (FV at +5 ticks) ---")
    for label, filter_fn in [
        ("Single trade (buy)", lambda cl: len(cl) == 1 and cl[0]['direction'] == 'buy'),
        ("Single trade (sell)", lambda cl: len(cl) == 1 and cl[0]['direction'] == 'sell'),
        ("Multi-trade (all buy)", lambda cl: len(cl) > 1 and all(t['direction'] == 'buy' for t in cl)),
        ("Multi-trade (all sell)", lambda cl: len(cl) > 1 and all(t['direction'] == 'sell' for t in cl)),
        ("Multi-trade (mixed)", lambda cl: len(cl) > 1 and len(set(t['direction'] for t in cl if t['direction'])) > 1),
    ]:
        changes = []
        for (day, ts), cl in clusters.items():
            if not filter_fn(cl):
                continue
            fv = cl[0]['fv']
            if fv is None:
                continue
            prices = all_prices[day]
            future_fv = get_fv_at_offset(prices, ts, 5)
            if future_fv is not None:
                changes.append(future_fv - fv)
        if changes:
            mean_change = sum(changes) / len(changes)
            print(f"    {label:30s} (N={len(changes):3d}): mean_fv_change_5={mean_change:+.3f}")

    # Consecutive same-direction trades
    print(f"\n  --- Consecutive Same-Direction Trades ---")
    for day in sorted(TRADE_FILES.keys()):
        day_trades = sorted([t for t in all_trades if t['day'] == day and t['direction'] is not None],
                           key=lambda t: t['timestamp'])
        if not day_trades:
            continue

        # Find runs of same direction
        runs = []
        current_dir = day_trades[0]['direction']
        current_run = [day_trades[0]]
        for t in day_trades[1:]:
            if t['direction'] == current_dir:
                current_run.append(t)
            else:
                runs.append((current_dir, current_run))
                current_dir = t['direction']
                current_run = [t]
        runs.append((current_dir, current_run))

        run_lengths = [len(r[1]) for r in runs]
        print(f"\n    Day {day}: {len(runs)} runs")
        print(f"    Run length distribution: {Counter(run_lengths)}")

        # Does a run of 2+ same direction predict continuation?
        for min_run in [2, 3]:
            long_runs = [(d, r) for d, r in runs if len(r) >= min_run]
            if long_runs:
                continuations = 0
                reversals = 0
                for direction, run in long_runs:
                    last_ts = run[-1]['timestamp']
                    last_fv = run[-1]['fv']
                    if last_fv is None:
                        continue
                    prices = all_prices[day]
                    future_fv = get_fv_at_offset(prices, last_ts, 5)
                    if future_fv is None:
                        continue
                    change = future_fv - last_fv
                    if direction == 'buy' and change > 0:
                        continuations += 1
                    elif direction == 'sell' and change < 0:
                        continuations += 1
                    elif change != 0:
                        reversals += 1
                total = continuations + reversals
                if total > 0:
                    print(f"    Run >= {min_run} same dir: continuation={continuations}/{total} "
                          f"({100*continuations/total:.1f}%)")


def section_f(all_trades, all_prices):
    """Trade volume as signal."""
    print_separator("F. TRADE VOLUME AS SIGNAL")

    # Split by quantity
    print(f"\n  --- FV Prediction by Trade Quantity ---")
    for h in [5, 10]:
        print(f"\n  Horizon +{h} ticks:")
        # Bucket trades by quantity
        small = [t for t in all_trades if t['quantity'] <= 3 and t['direction'] is not None]
        medium = [t for t in all_trades if 4 <= t['quantity'] <= 6 and t['direction'] is not None]
        large = [t for t in all_trades if t['quantity'] >= 7 and t['direction'] is not None]

        for label, bucket in [("Small (<=3)", small), ("Medium (4-6)", medium), ("Large (>=7)", large)]:
            correct = 0
            wrong = 0
            flat = 0
            signed_changes = []
            for t in bucket:
                if t['fv'] is None:
                    continue
                prices = all_prices[t['day']]
                future_fv = get_fv_at_offset(prices, t['timestamp'], h)
                if future_fv is None:
                    continue
                change = future_fv - t['fv']
                signed_changes.append(change)
                if t['direction'] == 'buy':
                    if change > 0: correct += 1
                    elif change < 0: wrong += 1
                    else: flat += 1
                else:
                    if change < 0: correct += 1
                    elif change > 0: wrong += 1
                    else: flat += 1

            total = correct + wrong
            if total > 0:
                mean_change = sum(signed_changes) / len(signed_changes) if signed_changes else 0
                print(f"    {label:15s} (N={len(bucket):3d}): correct_dir={correct}/{total} "
                      f"({100*correct/total:.1f}%), mean_change={mean_change:+.3f}")

    # Volume-weighted signal
    print(f"\n  --- Volume-Weighted Direction Signal ---")
    for h in [1, 5, 10, 20]:
        vol_weighted_correct = 0
        vol_weighted_wrong = 0
        for t in all_trades:
            if t['fv'] is None or t['direction'] is None:
                continue
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], h)
            if future_fv is None:
                continue
            change = future_fv - t['fv']
            qty = t['quantity']
            if t['direction'] == 'buy':
                if change > 0: vol_weighted_correct += qty
                elif change < 0: vol_weighted_wrong += qty
            else:
                if change < 0: vol_weighted_correct += qty
                elif change > 0: vol_weighted_wrong += qty

        total = vol_weighted_correct + vol_weighted_wrong
        if total > 0:
            print(f"    +{h:2d} ticks: vol_correct={vol_weighted_correct}, vol_wrong={vol_weighted_wrong}, "
                  f"accuracy={100*vol_weighted_correct/total:.1f}%")


def section_g(log_file):
    """Submission log analysis."""
    print_separator("G. SUBMISSION LOG ANALYSIS")

    with open(log_file, 'r') as f:
        data = json.load(f)

    # Load activities log (prices from submission)
    activities = data['activitiesLog']
    lines = activities.strip().split('\n')
    print(f"\n  activitiesLog: {len(lines)} lines (price data)")

    # Trade history
    trades = data['tradeHistory']
    osm_trades = [t for t in trades if t['symbol'] == SYMBOL]
    print(f"  tradeHistory: {len(trades)} total trades, {len(osm_trades)} OSMIUM trades")

    # Analyze buyer/seller in submission trades
    print(f"\n  --- OSMIUM Trades from Submission Log ---")
    print(f"  (These are trades involving OUR submission)")
    buyers = Counter(t['buyer'] for t in osm_trades)
    sellers = Counter(t['seller'] for t in osm_trades)
    print(f"  Buyer field values: {dict(buyers)}")
    print(f"  Seller field values: {dict(sellers)}")

    # Our buys vs sells
    our_buys = [t for t in osm_trades if t['buyer'] == 'SUBMISSION']
    our_sells = [t for t in osm_trades if t['seller'] == 'SUBMISSION']
    print(f"\n  Our buys: {len(our_buys)}, total qty: {sum(t['quantity'] for t in our_buys)}")
    print(f"  Our sells: {len(our_sells)}, total qty: {sum(t['quantity'] for t in our_sells)}")

    # Parse activities log for FV at submission trade timestamps
    price_data = {}
    reader = csv.DictReader(lines, delimiter=';')
    for row in reader:
        if row['product'] != SYMBOL:
            continue
        ts = int(row['timestamp'])
        bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
        ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
        if bid1 is not None and ask1 is not None:
            fv = (bid1 + ask1) / 2.0
        elif bid1 is not None:
            fv = bid1 + SPREAD / 2
        elif ask1 is not None:
            fv = ask1 - SPREAD / 2
        else:
            fv = float(row['mid_price']) if row['mid_price'] else None
        price_data[ts] = fv

    # Analyze our trades vs FV
    print(f"\n  --- Our OSMIUM Trades vs FV ---")
    total_pnl = 0
    for t in osm_trades:
        ts = t['timestamp']
        fv = price_data.get(ts)
        side = "BUY" if t['buyer'] == 'SUBMISSION' else "SELL"
        if fv is not None:
            edge = (t['price'] - fv) * (-1 if side == 'BUY' else 1)
            pnl = edge * t['quantity']
            total_pnl += pnl
            if ts <= 20000 or ts >= 190000:  # Show first and last
                print(f"    ts={ts:6d} {side:4s} {t['quantity']:2d}@{t['price']:.0f} FV={fv:.1f} edge={edge:+.1f} pnl={pnl:+.1f}")

    print(f"\n  Total edge PnL estimate: {total_pnl:+.1f}")

    # Check logs for market_trades
    logs = data.get('logs', [])
    print(f"\n  Logs entries: {len(logs)}")
    has_content = sum(1 for l in logs if l.get('sandboxLog', '') or l.get('lambdaLog', ''))
    print(f"  Logs with content: {has_content}")

    # Check a few logs with content
    shown = 0
    for l in logs:
        sandbox = l.get('sandboxLog', '')
        lambda_log = l.get('lambdaLog', '')
        if sandbox or lambda_log:
            print(f"    ts={l['timestamp']}: sandbox='{sandbox[:200]}' lambda='{lambda_log[:200]}'")
            shown += 1
            if shown >= 5:
                break

    if has_content == 0:
        print("  NOTE: No sandbox/lambda logs found. market_trades data not available in this submission.")
        print("  To get market_trades, add print(state.market_trades) to your trader and resubmit.")


def compute_trade_imbalance_signal(all_trades, all_prices):
    """Compute cumulative trade imbalance as a signal."""
    print_separator("BONUS: CUMULATIVE TRADE IMBALANCE SIGNAL")

    for day in sorted(TRADE_FILES.keys()):
        day_trades = sorted([t for t in all_trades if t['day'] == day],
                           key=lambda t: t['timestamp'])
        prices = all_prices[day]
        ts_list = sorted(prices.keys())

        if not day_trades:
            continue

        print(f"\n  Day {day}:")

        # Build imbalance at each timestamp
        # Imbalance = cumulative (buy_volume - sell_volume) in recent window
        for window in [5, 10, 20]:
            correct = 0
            wrong = 0
            flat = 0

            for i, ts in enumerate(ts_list):
                # Compute imbalance from trades in [ts - window*100, ts]
                window_start = ts - window * 100
                recent = [t for t in day_trades if window_start < t['timestamp'] <= ts]
                if not recent:
                    continue

                buy_vol = sum(t['quantity'] for t in recent if t.get('direction') == 'buy')
                sell_vol = sum(t['quantity'] for t in recent if t.get('direction') == 'sell')
                imbalance = buy_vol - sell_vol

                if imbalance == 0:
                    continue

                # Check FV change at +5
                future_fv = get_fv_at_offset(prices, ts, 5)
                current_fv = prices[ts]['fv']
                if future_fv is None:
                    continue

                change = future_fv - current_fv
                if imbalance > 0 and change > 0:
                    correct += 1
                elif imbalance < 0 and change < 0:
                    correct += 1
                elif change != 0:
                    wrong += 1
                else:
                    flat += 1

            total = correct + wrong
            if total > 0:
                print(f"    Window={window:2d} ticks: correct={correct}/{total} ({100*correct/total:.1f}%)")


def summary(all_trades, all_prices):
    """Print actionable summary."""
    print_separator("SUMMARY OF ACTIONABLE FINDINGS")

    # Compute key stats for summary
    buy_trades = [t for t in all_trades if t['direction'] == 'buy']
    sell_trades = [t for t in all_trades if t['direction'] == 'sell']

    for h in [5, 10]:
        buy_correct = 0
        buy_wrong = 0
        sell_correct = 0
        sell_wrong = 0

        for t in buy_trades:
            if t['fv'] is None: continue
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], h)
            if future_fv is None: continue
            change = future_fv - t['fv']
            if change > 0: buy_correct += 1
            elif change < 0: buy_wrong += 1

        for t in sell_trades:
            if t['fv'] is None: continue
            prices = all_prices[t['day']]
            future_fv = get_fv_at_offset(prices, t['timestamp'], h)
            if future_fv is None: continue
            change = future_fv - t['fv']
            if change < 0: sell_correct += 1
            elif change > 0: sell_wrong += 1

        bt = buy_correct + buy_wrong
        st = sell_correct + sell_wrong
        print(f"\n  At +{h} ticks:")
        if bt > 0:
            print(f"    Buy trades predict FV up: {buy_correct}/{bt} = {100*buy_correct/bt:.1f}%")
        if st > 0:
            print(f"    Sell trades predict FV down: {sell_correct}/{st} = {100*sell_correct/st:.1f}%")

    # Most common offsets
    offsets = [round(t['offset']) for t in all_trades if t['offset'] is not None]
    offset_counts = Counter(offsets)
    top3 = offset_counts.most_common(5)
    print(f"\n  Top 5 trade offsets from FV: {top3}")

    print(f"""
  ============================================================
  KEY TAKEAWAYS FOR STRATEGY:
  ============================================================

  1. TRADE DATA IN CSV: buyer/seller fields are EMPTY in public CSV files.
     Only submission logs show 'SUBMISSION' vs '' (counterparty unknown).

  2. TRADE DIRECTION CLASSIFICATION: Since we know spread=16 and FV,
     trades at price >= FV are buy-initiated, < FV are sell-initiated.

  3. PREDICTIVE POWER: Check the numbers above. If buy trades predict
     FV going up at +5/+10 ticks with >55% accuracy, this is a usable signal.

  4. OFFSET ANALYSIS: Trades at extreme offsets (near +-8 from FV, i.e.,
     at the best bid/ask) may be less informative (just bots trading).
     Trades INSIDE the spread (offsets like -3, +3) could indicate
     aggressive informed trading.

  5. RECOMMENDED STRATEGY ENHANCEMENT:
     - Track recent trades in traderData (last N market_trades)
     - Compute buy/sell imbalance
     - Skew FV estimate: if recent trades are buy-heavy, shift FV UP
       by a small amount (e.g., 0.5-2.0)
     - This lets you quote asymmetrically to capture direction
  """)


def main():
    print("Loading data...")

    # Load all prices
    all_prices = {}
    for day in PRICE_FILES:
        all_prices[day] = load_prices(day)
        print(f"  Day {day}: {len(all_prices[day])} OSMIUM price ticks")

    # Load all trades
    all_trades = []
    for day in TRADE_FILES:
        trades = load_trades(day)
        all_trades.extend(trades)
        print(f"  Day {day}: {len(trades)} OSMIUM trades")

    print(f"\n  Total OSMIUM trades: {len(all_trades)}")

    # Run all analyses
    section_a(all_trades, all_prices)
    section_b(all_trades, all_prices)
    section_c(all_trades, all_prices)
    section_d(all_trades, all_prices)
    section_e(all_trades, all_prices)
    section_f(all_trades, all_prices)

    # Submission log analysis
    if LOG_FILE.exists():
        section_g(LOG_FILE)
    else:
        print(f"\n  Log file not found: {LOG_FILE}")

    # Bonus: imbalance signal
    compute_trade_imbalance_signal(all_trades, all_prices)

    # Summary
    summary(all_trades, all_prices)


if __name__ == '__main__':
    main()
