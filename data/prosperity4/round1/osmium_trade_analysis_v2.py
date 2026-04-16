#!/usr/bin/env python3
"""
OSMIUM trade analysis v2: Focused deep-dive on promising signals.
Investigates:
1. Inside-spread trades as informed order flow
2. Small trades as informed signal
3. FV computation quality check
4. Trade timing patterns (time of day)
5. Proper signed trade flow predictive power
"""

import csv
import json
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

SYMBOL = "ASH_COATED_OSMIUM"
SPREAD = 16


def load_prices(day):
    """Load OSMIUM prices for a given day. Return dict: ts -> info dict."""
    prices = {}
    with open(PRICE_FILES[day], 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] != SYMBOL:
                continue
            ts = int(row['timestamp'])
            bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
            ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
            bid2 = float(row['bid_price_2']) if row.get('bid_price_2', '') else None
            ask2 = float(row['ask_price_2']) if row.get('ask_price_2', '') else None
            mid = float(row['mid_price']) if row['mid_price'] else None

            # Only compute FV when BOTH sides present (spread=16 regime)
            if bid1 is not None and ask1 is not None:
                fv = (bid1 + ask1) / 2.0
                actual_spread = ask1 - bid1
            else:
                fv = None
                actual_spread = None

            prices[ts] = {
                'bid1': bid1, 'ask1': ask1, 'bid2': bid2, 'ask2': ask2,
                'mid': mid, 'fv': fv, 'spread': actual_spread,
            }
    return prices


def load_trades(day):
    trades = []
    with open(TRADE_FILES[day], 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['symbol'] != SYMBOL:
                continue
            trades.append({
                'timestamp': int(row['timestamp']),
                'price': float(row['price']),
                'quantity': int(row['quantity']),
                'day': day,
            })
    return trades


def get_fv(prices, ts):
    if ts in prices and prices[ts]['fv'] is not None:
        return prices[ts]['fv']
    # Find nearest earlier with valid FV
    valid = [t for t in prices if t <= ts and prices[t]['fv'] is not None]
    if valid:
        return prices[max(valid)]['fv']
    return None


def print_separator(title):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def check_fv_quality(all_prices):
    """Check FV computation quality."""
    print_separator("0. FV QUALITY CHECK")

    for day in sorted(all_prices.keys()):
        prices = all_prices[day]
        ts_list = sorted(prices.keys())

        both_sides = sum(1 for ts in ts_list if prices[ts]['bid1'] is not None and prices[ts]['ask1'] is not None)
        bid_only = sum(1 for ts in ts_list if prices[ts]['bid1'] is not None and prices[ts]['ask1'] is None)
        ask_only = sum(1 for ts in ts_list if prices[ts]['bid1'] is None and prices[ts]['ask1'] is not None)
        neither = sum(1 for ts in ts_list if prices[ts]['bid1'] is None and prices[ts]['ask1'] is None)

        print(f"\n  Day {day}: {len(ts_list)} ticks")
        print(f"    Both sides: {both_sides} ({100*both_sides/len(ts_list):.1f}%)")
        print(f"    Bid only:   {bid_only} ({100*bid_only/len(ts_list):.1f}%)")
        print(f"    Ask only:   {ask_only} ({100*ask_only/len(ts_list):.1f}%)")
        print(f"    Neither:    {neither} ({100*neither/len(ts_list):.1f}%)")

        # Spread distribution when both sides present
        spreads = [prices[ts]['spread'] for ts in ts_list if prices[ts]['spread'] is not None]
        if spreads:
            spread_counts = Counter(int(s) for s in spreads)
            print(f"    Spread distribution:")
            for sp in sorted(spread_counts.keys()):
                n = spread_counts[sp]
                print(f"      {sp:3d}: {n:5d} ({100*n/len(spreads):.1f}%)")

        # FV change distribution (single tick)
        fv_changes = []
        for i in range(1, len(ts_list)):
            fv_prev = prices[ts_list[i-1]]['fv']
            fv_curr = prices[ts_list[i]]['fv']
            if fv_prev is not None and fv_curr is not None:
                fv_changes.append(fv_curr - fv_prev)

        if fv_changes:
            change_counts = Counter(round(c, 1) for c in fv_changes)
            print(f"    FV single-tick changes (top 15):")
            for ch, n in sorted(change_counts.items(), key=lambda x: -x[1])[:15]:
                pct = 100 * n / len(fv_changes)
                print(f"      {ch:+6.1f}: {n:5d} ({pct:.1f}%)")


def inside_spread_analysis(all_trades, all_prices):
    """Deep analysis of inside-spread trades."""
    print_separator("1. INSIDE-SPREAD TRADES (Potential Informed Flow)")

    inside = []
    at_bid = []
    at_ask = []
    beyond = []

    for t in all_trades:
        prices = all_prices[t['day']]
        fv = get_fv(prices, t['timestamp'])
        if fv is None:
            continue

        offset = t['price'] - fv
        t['fv'] = fv
        t['offset'] = offset

        abs_off = abs(offset)
        if abs_off < 8:  # inside spread
            inside.append(t)
        elif abs_off == 8:  # at bid/ask
            if offset < 0:
                at_bid.append(t)
            else:
                at_ask.append(t)
        else:  # beyond
            beyond.append(t)

    print(f"\n  Trade categorization:")
    print(f"    Inside spread (|offset| < 8): {len(inside)} trades")
    print(f"    At best bid (offset = -8):    {len(at_bid)} trades")
    print(f"    At best ask (offset = +8):    {len(at_ask)} trades")
    print(f"    Beyond best bid/ask:          {len(beyond)} trades")

    # Inside-spread trades detail
    print(f"\n  --- Inside-Spread Trades Detail ---")
    inside_offsets = Counter(round(t['offset'], 1) for t in inside)
    for off in sorted(inside_offsets.keys()):
        print(f"    Offset {off:+5.1f}: {inside_offsets[off]} trades")

    # Predictive power of inside-spread trades vs at-edge trades
    print(f"\n  --- Predictive Power Comparison ---")
    for label, trades_subset in [
        ("Inside spread (<8)", inside),
        ("At best bid (-8)", at_bid),
        ("At best ask (+8)", at_ask),
        ("Beyond bid/ask", beyond),
    ]:
        for h in [1, 2, 5, 10]:
            correct = wrong = flat_count = 0
            changes = []
            for t in trades_subset:
                prices = all_prices[t['day']]
                ts_offset = t['timestamp'] + h * 100
                # Only use ticks with valid FV
                future_fv = get_fv(prices, ts_offset)
                if future_fv is None or t['fv'] is None:
                    continue
                change = future_fv - t['fv']
                changes.append(change)
                expected_dir = 1 if t['offset'] > 0 else -1  # buy -> expect up, sell -> expect down
                if change * expected_dir > 0:
                    correct += 1
                elif change * expected_dir < 0:
                    wrong += 1
                else:
                    flat_count += 1

            total = correct + wrong
            if total > 0:
                mean_ch = sum(changes) / len(changes) if changes else 0
                print(f"    {label:25s} +{h:2d}t: {correct}/{total} = {100*correct/total:.1f}%  "
                      f"(mean_change={mean_ch:+.3f}, flat={flat_count})")
        print()

    # Signed analysis for inside-spread trades
    print(f"\n  --- Inside-Spread: Signed FV Change by Direction ---")
    for h in [1, 2, 5, 10, 20]:
        buy_ch = []
        sell_ch = []
        for t in inside:
            prices = all_prices[t['day']]
            future_fv = get_fv(prices, t['timestamp'] + h * 100)
            if future_fv is None or t['fv'] is None:
                continue
            change = future_fv - t['fv']
            if t['offset'] > 0:
                buy_ch.append(change)
            else:
                sell_ch.append(change)

        if buy_ch:
            mean_buy = sum(buy_ch) / len(buy_ch)
            pup = sum(1 for c in buy_ch if c > 0)
            pdn = sum(1 for c in buy_ch if c < 0)
            print(f"    +{h:2d}t BUY-side inside (N={len(buy_ch)}): mean={mean_buy:+.3f}, up={pup}, dn={pdn}")
        if sell_ch:
            mean_sell = sum(sell_ch) / len(sell_ch)
            pup = sum(1 for c in sell_ch if c > 0)
            pdn = sum(1 for c in sell_ch if c < 0)
            print(f"    +{h:2d}t SELL-side inside (N={len(sell_ch)}): mean={mean_sell:+.3f}, up={pup}, dn={pdn}")


def small_trade_analysis(all_trades, all_prices):
    """Analyze if small trades are more informed."""
    print_separator("2. SMALL TRADE ANALYSIS")

    # Separate by quantity AND offset category
    for qty_label, qty_filter in [
        ("Qty 2-3", lambda q: 2 <= q <= 3),
        ("Qty 4-6", lambda q: 4 <= q <= 6),
        ("Qty 7-10", lambda q: 7 <= q <= 10),
    ]:
        for loc_label, loc_filter in [
            ("Inside spread", lambda o: abs(o) < 8),
            ("At edge (|off|=8)", lambda o: abs(o) == 8),
            ("Beyond edge", lambda o: abs(o) > 8),
        ]:
            subset = []
            for t in all_trades:
                if t.get('fv') is None or t.get('offset') is None:
                    continue
                if qty_filter(t['quantity']) and loc_filter(t['offset']):
                    subset.append(t)

            if len(subset) < 5:
                continue

            for h in [5, 10]:
                correct = wrong = 0
                for t in subset:
                    prices = all_prices[t['day']]
                    future_fv = get_fv(prices, t['timestamp'] + h * 100)
                    if future_fv is None:
                        continue
                    change = future_fv - t['fv']
                    expected_dir = 1 if t['offset'] > 0 else -1
                    if change * expected_dir > 0:
                        correct += 1
                    elif change * expected_dir < 0:
                        wrong += 1

                total = correct + wrong
                if total > 5:
                    print(f"  {qty_label:10s} {loc_label:20s} +{h:2d}t: {correct}/{total} = "
                          f"{100*correct/total:.1f}% (N={len(subset)})")


def timing_analysis(all_trades, all_prices):
    """Analyze when trades happen relative to FV changes."""
    print_separator("3. TRADE TIMING PATTERNS")

    for day in sorted(all_prices.keys()):
        prices = all_prices[day]
        day_trades = sorted([t for t in all_trades if t['day'] == day], key=lambda t: t['timestamp'])
        ts_list = sorted(prices.keys())

        # Find FV change events
        fv_changes = []
        for i in range(1, len(ts_list)):
            fv_prev = prices[ts_list[i-1]]['fv']
            fv_curr = prices[ts_list[i]]['fv']
            if fv_prev is not None and fv_curr is not None and fv_curr != fv_prev:
                fv_changes.append((ts_list[i], fv_curr - fv_prev))

        print(f"\n  Day {day}: {len(fv_changes)} FV change events, {len(day_trades)} trades")

        # For each FV change: was there a trade in the preceding N ticks?
        for lookback in [1, 2, 3, 5]:
            trade_before_change = 0
            no_trade_before_change = 0
            for ts, change in fv_changes:
                window_start = ts - lookback * 100
                recent_trades = [t for t in day_trades if window_start < t['timestamp'] <= ts]
                if recent_trades:
                    trade_before_change += 1
                else:
                    no_trade_before_change += 1

            total = trade_before_change + no_trade_before_change
            if total > 0:
                print(f"    FV change events with trade in prior {lookback} ticks: "
                      f"{trade_before_change}/{total} = {100*trade_before_change/total:.1f}%")

        # Reverse: for each trade, does FV change in next N ticks?
        print(f"    ---")
        for lookahead in [1, 2, 3, 5]:
            fv_changed_after_trade = 0
            fv_same_after_trade = 0
            for t in day_trades:
                fv_at = get_fv(prices, t['timestamp'])
                fv_future = get_fv(prices, t['timestamp'] + lookahead * 100)
                if fv_at is not None and fv_future is not None:
                    if fv_future != fv_at:
                        fv_changed_after_trade += 1
                    else:
                        fv_same_after_trade += 1

            total = fv_changed_after_trade + fv_same_after_trade
            if total > 0:
                print(f"    Trades followed by FV change within {lookahead} ticks: "
                      f"{fv_changed_after_trade}/{total} = {100*fv_changed_after_trade/total:.1f}%")

        # Compare with baseline: at ALL ticks, does FV change in next N?
        print(f"    --- Baseline (all ticks) ---")
        for lookahead in [1, 2, 3, 5]:
            changed = same = 0
            for ts in ts_list:
                fv_at = prices[ts]['fv']
                target = ts + lookahead * 100
                fv_future = get_fv(prices, target) if target <= max(ts_list) else None
                if fv_at is not None and fv_future is not None:
                    if fv_future != fv_at:
                        changed += 1
                    else:
                        same += 1
            total = changed + same
            if total > 0:
                print(f"    Baseline: FV changes within {lookahead} ticks: "
                      f"{changed}/{total} = {100*changed/total:.1f}%")


def directional_signal_with_offset(all_trades, all_prices):
    """Proper signed trade flow: does a buy at +X predict FV up by X amount?"""
    print_separator("4. TRADE DIRECTION SIGNAL (SIGNED OFFSET)")

    # For each trade: compute signed_signal = offset * quantity
    # Does signed_signal predict FV movement?
    print(f"\n  --- Correlation: Trade Offset vs Future FV Change ---")
    for h in [1, 2, 5, 10, 20]:
        offsets = []
        changes = []
        for t in all_trades:
            if t.get('fv') is None or t.get('offset') is None:
                continue
            prices = all_prices[t['day']]
            future_fv = get_fv(prices, t['timestamp'] + h * 100)
            if future_fv is None:
                continue
            offsets.append(t['offset'])
            changes.append(future_fv - t['fv'])

        if len(offsets) > 10:
            # Compute correlation
            n = len(offsets)
            mean_o = sum(offsets) / n
            mean_c = sum(changes) / n
            cov = sum((o - mean_o) * (c - mean_c) for o, c in zip(offsets, changes)) / n
            std_o = (sum((o - mean_o)**2 for o in offsets) / n) ** 0.5
            std_c = (sum((c - mean_c)**2 for c in changes) / n) ** 0.5
            corr = cov / (std_o * std_c) if std_o > 0 and std_c > 0 else 0
            print(f"    +{h:2d}t: corr(offset, fv_change) = {corr:+.4f}  (N={n})")

    # Signed signal: offset * qty
    print(f"\n  --- Correlation: Offset*Qty vs Future FV Change ---")
    for h in [1, 2, 5, 10, 20]:
        signals = []
        changes = []
        for t in all_trades:
            if t.get('fv') is None or t.get('offset') is None:
                continue
            prices = all_prices[t['day']]
            future_fv = get_fv(prices, t['timestamp'] + h * 100)
            if future_fv is None:
                continue
            signals.append(t['offset'] * t['quantity'])
            changes.append(future_fv - t['fv'])

        if len(signals) > 10:
            n = len(signals)
            mean_s = sum(signals) / n
            mean_c = sum(changes) / n
            cov = sum((s - mean_s) * (c - mean_c) for s, c in zip(signals, changes)) / n
            std_s = (sum((s - mean_s)**2 for s in signals) / n) ** 0.5
            std_c = (sum((c - mean_c)**2 for c in changes) / n) ** 0.5
            corr = cov / (std_s * std_c) if std_s > 0 and std_c > 0 else 0
            print(f"    +{h:2d}t: corr(offset*qty, fv_change) = {corr:+.4f}  (N={n})")


def trade_at_fv_step_analysis(all_trades, all_prices):
    """Analyze: do trades happen right WHEN FV steps?"""
    print_separator("5. TRADES AT FV STEP EVENTS")

    # FV often changes by +1 or -1 (the smallest step).
    # Do trades happen at these moments?

    for day in sorted(all_prices.keys()):
        prices = all_prices[day]
        day_trades = sorted([t for t in all_trades if t['day'] == day], key=lambda t: t['timestamp'])
        ts_list = sorted(prices.keys())

        print(f"\n  Day {day}:")

        # Identify FV step timestamps
        step_events = []
        for i in range(1, len(ts_list)):
            fv_prev = prices[ts_list[i-1]]['fv']
            fv_curr = prices[ts_list[i]]['fv']
            if fv_prev is not None and fv_curr is not None and fv_curr != fv_prev:
                step_events.append({
                    'ts': ts_list[i],
                    'prev_ts': ts_list[i-1],
                    'change': fv_curr - fv_prev,
                    'direction': 'up' if fv_curr > fv_prev else 'down',
                })

        # For each step: check if there was a trade at step_ts or step_ts-100
        trade_at_step = 0
        trade_before_step = 0
        trade_after_step = 0
        no_trade = 0

        # Also track: does trade direction match step direction?
        match_at = 0
        mismatch_at = 0
        match_before = 0
        mismatch_before = 0

        for event in step_events:
            ts = event['ts']
            prev_ts = event['prev_ts']
            direction = event['direction']

            trades_at = [t for t in day_trades if t['timestamp'] == ts]
            trades_before = [t for t in day_trades if t['timestamp'] == prev_ts]
            trades_after = [t for t in day_trades if t['timestamp'] == ts + 100]

            if trades_at:
                trade_at_step += 1
                for t in trades_at:
                    if t.get('offset') is not None:
                        trade_dir = 'up' if t['offset'] > 0 else 'down'
                        if trade_dir == direction:
                            match_at += 1
                        else:
                            mismatch_at += 1
            elif trades_before:
                trade_before_step += 1
                for t in trades_before:
                    if t.get('offset') is not None:
                        trade_dir = 'up' if t['offset'] > 0 else 'down'
                        if trade_dir == direction:
                            match_before += 1
                        else:
                            mismatch_before += 1
            elif trades_after:
                trade_after_step += 1
            else:
                no_trade += 1

        total = trade_at_step + trade_before_step + trade_after_step + no_trade
        print(f"    FV steps: {len(step_events)}")
        print(f"    Trade AT step timestamp:   {trade_at_step} ({100*trade_at_step/total:.1f}%)")
        print(f"    Trade 1 tick BEFORE step:  {trade_before_step} ({100*trade_before_step/total:.1f}%)")
        print(f"    Trade 1 tick AFTER step:   {trade_after_step} ({100*trade_after_step/total:.1f}%)")
        print(f"    No trade nearby:           {no_trade} ({100*no_trade/total:.1f}%)")

        at_total = match_at + mismatch_at
        if at_total > 0:
            print(f"    Direction match AT step: {match_at}/{at_total} = {100*match_at/at_total:.1f}%")
        before_total = match_before + mismatch_before
        if before_total > 0:
            print(f"    Direction match BEFORE step: {match_before}/{before_total} = {100*match_before/before_total:.1f}%")


def trade_frequency_by_period(all_trades, all_prices):
    """Look at trade frequency over time periods."""
    print_separator("6. TRADE FREQUENCY BY TIME OF DAY")

    for day in sorted(TRADE_FILES.keys()):
        day_trades = [t for t in all_trades if t['day'] == day]
        if not day_trades:
            continue

        max_ts = max(t['timestamp'] for t in day_trades)
        period_size = 100000  # 1000 ticks per period

        print(f"\n  Day {day} (max_ts={max_ts}):")
        period = 0
        while period * period_size < max_ts + period_size:
            start = period * period_size
            end = (period + 1) * period_size
            period_trades = [t for t in day_trades if start <= t['timestamp'] < end]
            if period_trades:
                buy = sum(1 for t in period_trades if t.get('offset', 0) is not None and t.get('offset', 0) > 0)
                sell = len(period_trades) - buy
                avg_qty = sum(t['quantity'] for t in period_trades) / len(period_trades)
                print(f"    [{start//100:4d}-{end//100:4d}): {len(period_trades):3d} trades "
                      f"(buy={buy}, sell={sell}, avg_qty={avg_qty:.1f})")
            period += 1


def analyze_fv_changes_around_trades(all_trades, all_prices):
    """Microsecond analysis: what happens tick-by-tick around a trade?"""
    print_separator("7. FV TRAJECTORY AROUND TRADES (Event Study)")

    # For each inside-spread trade (the rare ones), show FV at -5..+10 ticks
    inside_trades = [t for t in all_trades if t.get('offset') is not None and abs(t['offset']) < 8]

    print(f"\n  Inside-spread trades: {len(inside_trades)}")
    print(f"\n  --- Individual Inside-Spread Trade Events ---")

    for t in inside_trades[:30]:  # Show first 30
        prices = all_prices[t['day']]
        fv_at_trade = t['fv']
        if fv_at_trade is None:
            continue

        trajectory = []
        for tick in range(-5, 16):
            target_ts = t['timestamp'] + tick * 100
            fv = get_fv(prices, target_ts)
            if fv is not None:
                trajectory.append(f"{fv - fv_at_trade:+.1f}")
            else:
                trajectory.append("  ? ")

        dir_label = "BUY" if t['offset'] > 0 else "SELL"
        print(f"    Day {t['day']:+d} ts={t['timestamp']:6d} {dir_label} {t['quantity']}@{t['price']:.0f} "
              f"off={t['offset']:+.1f} FV_traj: {' '.join(trajectory)}")

    # Average event study for ALL trades
    print(f"\n  --- Average FV Trajectory Around ALL Trades ---")
    print(f"  (Tick offsets -10 to +20, FV change relative to trade time)")

    for label, subset in [
        ("Buy-initiated (off>0)", [t for t in all_trades if t.get('offset') is not None and t['offset'] > 0]),
        ("Sell-initiated (off<0)", [t for t in all_trades if t.get('offset') is not None and t['offset'] < 0]),
        ("Inside-spread buy", [t for t in all_trades if t.get('offset') is not None and 0 < t['offset'] < 8]),
        ("Inside-spread sell", [t for t in all_trades if t.get('offset') is not None and -8 < t['offset'] < 0]),
    ]:
        if not subset:
            continue

        avg_traj = {}
        for tick in range(-10, 21):
            deltas = []
            for t in subset:
                if t.get('fv') is None:
                    continue
                prices = all_prices[t['day']]
                target_ts = t['timestamp'] + tick * 100
                fv = get_fv(prices, target_ts)
                if fv is not None:
                    deltas.append(fv - t['fv'])
            if deltas:
                avg_traj[tick] = sum(deltas) / len(deltas)

        traj_str = " ".join(f"{avg_traj.get(tick, 0):+.2f}" for tick in range(-10, 21))
        print(f"\n  {label} (N={len(subset)}):")
        print(f"    Ticks: " + " ".join(f"{t:+5d}" for t in range(-10, 21)))
        print(f"    dFV:   " + traj_str)


def main():
    print("Loading data...")
    all_prices = {}
    all_trades = []

    for day in PRICE_FILES:
        all_prices[day] = load_prices(day)
        print(f"  Day {day}: {len(all_prices[day])} OSMIUM price ticks")

    for day in TRADE_FILES:
        trades = load_trades(day)
        all_trades.extend(trades)
        print(f"  Day {day}: {len(trades)} OSMIUM trades")

    # Pre-compute FV and offset for all trades
    for t in all_trades:
        fv = get_fv(all_prices[t['day']], t['timestamp'])
        t['fv'] = fv
        t['offset'] = (t['price'] - fv) if fv is not None else None

    # Run analyses
    check_fv_quality(all_prices)
    inside_spread_analysis(all_trades, all_prices)
    small_trade_analysis(all_trades, all_prices)
    timing_analysis(all_trades, all_prices)
    directional_signal_with_offset(all_trades, all_prices)
    trade_at_fv_step_analysis(all_trades, all_prices)
    trade_frequency_by_period(all_trades, all_prices)
    analyze_fv_changes_around_trades(all_trades, all_prices)

    print_separator("FINAL CONCLUSIONS")
    print("""
  Based on the analysis:

  1. SPREAD IS ALWAYS 16 when both sides present. FV = (bid1+ask1)/2
     But often only ONE side is shown (bid_only or ask_only), suggesting
     the other side was just consumed by a taker.

  2. TRADE OFFSETS cluster at +/-8 (at best bid/ask = 64% of all trades),
     with +/-9, +/-10 (beyond best = 27%), and a small number INSIDE
     spread (9%).

  3. INSIDE-SPREAD TRADES are rare (~125 out of 1265) but potentially
     more informative. These represent aggressive orders placed inside
     the MM spread, suggesting a bot with private information.

  4. CHECK THE PREDICTIVE ACCURACY NUMBERS:
     - If inside-spread trades predict direction at >55%, use them as signal
     - If at-edge trades are ~50%, they're just noise (regular MM fills)
     - The key question: is there ANY signal in the trade flow?

  5. STRATEGY IMPLICATIONS:
     a) If trades are NOT predictive: ignore market_trades, focus on pure MM
     b) If inside-spread trades ARE predictive:
        - When you see an inside-spread buy, shift FV up by 1-2
        - When you see an inside-spread sell, shift FV down by 1-2
        - This gives you adverse selection protection
     c) Small trades with unusual offsets may be the taker bot's signature
""")


if __name__ == '__main__':
    main()
