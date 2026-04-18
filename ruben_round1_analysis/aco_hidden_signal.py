"""
Deep analysis of ASH_COATED_OSMIUM order book dynamics.
Looking for hidden predictive signals in the order book structure.

Known bot model (from calibration):
  FV: Gaussian random walk N(0, 0.312^2) per tick, starting ~10000
  Bot1 (outer): bid=floor(FV)-10, ask=ceil(FV)+10, vol U(20,30), ~80% presence/side
  Bot2 (inner): bid=floor(FV-0.5)-7, ask=floor(FV-0.5)+9, vol U(10,15), ~80% presence/side
  Bot3 (noise): ~8% of ticks, single-sided, offsets {-3,-2,+1,+2}, vol 1-10
"""

import csv
import math
import os
from collections import defaultdict, Counter

DATA_DIR = "data/prosperity4/round1"
PRODUCT = "ASH_COATED_OSMIUM"

def load_data():
    """Load all ACO price data across 3 days."""
    rows = []
    for day_suffix in ["-2", "-1", "0"]:
        path = os.path.join(DATA_DIR, f"prices_round_1_day_{day_suffix}.csv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['product'] == PRODUCT:
                    r = {
                        'day': int(row['day']),
                        'timestamp': int(row['timestamp']),
                    }
                    for col in ['bid_price_1','bid_volume_1','bid_price_2','bid_volume_2',
                                'bid_price_3','bid_volume_3','ask_price_1','ask_volume_1',
                                'ask_price_2','ask_volume_2','ask_price_3','ask_volume_3',
                                'mid_price']:
                        val = row[col].strip()
                        r[col] = float(val) if val else None
                    rows.append(r)
    return rows


def infer_fv_from_bot2(row):
    """
    Infer FV from Bot2 quotes.
    Bot2: bid = floor(FV-0.5) - 7, ask = floor(FV-0.5) + 9
    So: floor(FV-0.5) = bid + 7 = ask - 9
    FV is in [floor(FV-0.5) + 0.5, floor(FV-0.5) + 1.5)
    Best estimate: floor(FV-0.5) + 1.0 (midpoint of interval)
    """
    # Try to identify Bot2 quotes (inner wall, vol 10-15)
    bot2_bid = None
    bot2_ask = None

    # Check each bid level for Bot2 signature (vol 10-15)
    for i in [1, 2, 3]:
        bp = row.get(f'bid_price_{i}')
        bv = row.get(f'bid_volume_{i}')
        if bp is not None and bv is not None:
            bv = int(bv)
            if 10 <= bv <= 15:
                if bot2_bid is None or bp > bot2_bid:
                    bot2_bid = bp

    for i in [1, 2, 3]:
        ap = row.get(f'ask_price_{i}')
        av = row.get(f'ask_volume_{i}')
        if ap is not None and av is not None:
            av = int(av)
            if 10 <= av <= 15:
                if bot2_ask is None or ap < bot2_ask:
                    bot2_ask = ap

    if bot2_bid is not None and bot2_ask is not None:
        # Cross-check: spread should be 16
        if abs((bot2_ask - bot2_bid) - 16) < 0.01:
            base = bot2_bid + 7  # = floor(FV - 0.5)
            return base + 1.0  # midpoint estimate

    if bot2_bid is not None:
        return bot2_bid + 7 + 1.0
    if bot2_ask is not None:
        return bot2_ask - 9 + 1.0

    return None


def classify_levels(row):
    """Classify each price level as Bot1, Bot2, or Bot3 based on volume."""
    levels = {'bids': [], 'asks': []}

    for i in [1, 2, 3]:
        bp = row.get(f'bid_price_{i}')
        bv = row.get(f'bid_volume_{i}')
        if bp is not None and bv is not None:
            bv = int(bv)
            if 20 <= bv <= 30:
                bot = 'bot1'
            elif 10 <= bv <= 15:
                bot = 'bot2'
            else:
                bot = 'bot3'
            levels['bids'].append({'price': bp, 'vol': bv, 'bot': bot})

    for i in [1, 2, 3]:
        ap = row.get(f'ask_price_{i}')
        av = row.get(f'ask_volume_{i}')
        if ap is not None and av is not None:
            av = int(av)
            if 20 <= av <= 30:
                bot = 'bot1'
            elif 10 <= av <= 15:
                bot = 'bot2'
            else:
                bot = 'bot3'
            levels['asks'].append({'price': ap, 'vol': av, 'bot': bot})

    return levels


def analyze_wall_movement_prediction(data):
    """Q1: When Bot2 walls shift, does FV move in same direction next ticks?"""
    print("\n" + "="*80)
    print("Q1: WALL MOVEMENT PREDICTION (Bot2 shifts -> FV direction)")
    print("="*80)

    # Group by day
    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    # For each day, track Bot2 bid/ask positions and mid-price changes
    all_wall_shifts = []  # (shift_direction, future_mid_changes at lag 1..10)

    for day, rows in sorted(days.items()):
        prev_bot2_bid = None
        prev_bot2_ask = None
        mids = [r['mid_price'] for r in rows]

        for idx, row in enumerate(rows):
            levels = classify_levels(row)

            bot2_bid = None
            bot2_ask = None
            for b in levels['bids']:
                if b['bot'] == 'bot2':
                    bot2_bid = b['price']
            for a in levels['asks']:
                if a['bot'] == 'bot2':
                    bot2_ask = a['price']

            if bot2_bid is not None and prev_bot2_bid is not None:
                shift = bot2_bid - prev_bot2_bid
                if shift != 0:
                    future_returns = []
                    for lag in range(1, 11):
                        if idx + lag < len(rows) and mids[idx + lag] is not None and mids[idx] is not None:
                            future_returns.append(mids[idx + lag] - mids[idx])
                        else:
                            future_returns.append(None)
                    all_wall_shifts.append(('bid', shift, future_returns))

            if bot2_ask is not None and prev_bot2_ask is not None:
                shift = bot2_ask - prev_bot2_ask
                if shift != 0:
                    future_returns = []
                    for lag in range(1, 11):
                        if idx + lag < len(rows) and mids[idx + lag] is not None and mids[idx] is not None:
                            future_returns.append(mids[idx + lag] - mids[idx])
                        else:
                            future_returns.append(None)
                    all_wall_shifts.append(('ask', shift, future_returns))

            prev_bot2_bid = bot2_bid
            prev_bot2_ask = bot2_ask

    # Analyze: when wall shifts up, does mid go up?
    for side in ['bid', 'ask']:
        shifts = [(s, fr) for (sd, s, fr) in all_wall_shifts if sd == side]
        if not shifts:
            continue

        print(f"\n  Bot2 {side} wall shifts: {len(shifts)} events")

        up_shifts = [(s, fr) for s, fr in shifts if s > 0]
        down_shifts = [(s, fr) for s, fr in shifts if s < 0]

        print(f"    Up shifts: {len(up_shifts)}, Down shifts: {len(down_shifts)}")

        for lag in [1, 2, 3, 5, 10]:
            if lag > 10:
                break
            up_returns = [fr[lag-1] for _, fr in up_shifts if fr[lag-1] is not None]
            down_returns = [fr[lag-1] for _, fr in down_shifts if fr[lag-1] is not None]

            if up_returns and down_returns:
                up_mean = sum(up_returns) / len(up_returns)
                down_mean = sum(down_returns) / len(down_returns)
                # What fraction of up-shifts lead to positive future return?
                up_hit = sum(1 for r in up_returns if r > 0) / len(up_returns)
                down_hit = sum(1 for r in down_returns if r < 0) / len(down_returns)
                print(f"    Lag {lag:2d}: After UP shift: mean_ret={up_mean:+.3f}, hit_rate={up_hit:.1%} (n={len(up_returns)})")
                print(f"            After DN shift: mean_ret={down_mean:+.3f}, hit_rate={down_hit:.1%} (n={len(down_returns)})")


def analyze_volume_changes(data):
    """Q2: Do volume changes in Bot1/Bot2 predict price direction?"""
    print("\n" + "="*80)
    print("Q2: VOLUME CHANGES AS SIGNAL")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    vol_change_returns = defaultdict(list)  # (bot, side, vol_direction) -> future returns

    for day, rows in sorted(days.items()):
        prev_levels = None

        for idx, row in enumerate(rows):
            levels = classify_levels(row)

            if prev_levels is not None and row['mid_price'] is not None:
                # Check Bot2 bid volume changes
                for bot_name in ['bot2', 'bot1']:
                    for side, side_key in [('bid', 'bids'), ('ask', 'asks')]:
                        prev_vol = None
                        curr_vol = None
                        for lev in prev_levels[side_key]:
                            if lev['bot'] == bot_name:
                                prev_vol = lev['vol']
                        for lev in levels[side_key]:
                            if lev['bot'] == bot_name:
                                curr_vol = lev['vol']

                        if prev_vol is not None and curr_vol is not None and prev_vol != curr_vol:
                            direction = 'up' if curr_vol > prev_vol else 'down'
                            # Future return at lag 1
                            if idx + 1 < len(rows) and rows[idx+1]['mid_price'] is not None:
                                ret = rows[idx+1]['mid_price'] - row['mid_price']
                                vol_change_returns[(bot_name, side, direction)].append(ret)

            prev_levels = levels

    for key in sorted(vol_change_returns.keys()):
        rets = vol_change_returns[key]
        if len(rets) < 20:
            continue
        mean_ret = sum(rets) / len(rets)
        pos_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"  {key[0]:4s} {key[1]:3s} vol {key[2]:4s}: mean_ret={mean_ret:+.4f}, up_frac={pos_frac:.1%}, n={len(rets)}")


def analyze_book_asymmetry(data):
    """Q3: Does the NUMBER of price levels predict direction?"""
    print("\n" + "="*80)
    print("Q3: BOOK ASYMMETRY (number of levels)")
    print("="*80)

    # Count levels on each side and look at future returns
    asym_returns = defaultdict(list)  # (n_bid_levels, n_ask_levels) -> next mid change

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    for day, rows in sorted(days.items()):
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            if row['mid_price'] is None or next_row['mid_price'] is None:
                continue

            n_bids = sum(1 for i in [1,2,3] if row.get(f'bid_price_{i}') is not None)
            n_asks = sum(1 for i in [1,2,3] if row.get(f'ask_price_{i}') is not None)

            ret = next_row['mid_price'] - row['mid_price']
            asym_returns[(n_bids, n_asks)].append(ret)

    print(f"\n  {'(Bids,Asks)':<15} {'Count':>8} {'Mean Ret':>10} {'Up %':>8} {'Std':>8}")
    print(f"  {'-'*55}")

    for key in sorted(asym_returns.keys()):
        rets = asym_returns[key]
        if len(rets) < 10:
            continue
        mean_ret = sum(rets) / len(rets)
        std_ret = (sum((r - mean_ret)**2 for r in rets) / len(rets)) ** 0.5
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"  ({key[0]},{key[1]})          {len(rets):>8} {mean_ret:>+10.4f} {up_frac:>7.1%} {std_ret:>8.3f}")

    # Net asymmetry signal
    print(f"\n  Net level asymmetry (n_bids - n_asks):")
    net_asym = defaultdict(list)
    for (nb, na), rets in asym_returns.items():
        net_asym[nb - na].extend(rets)

    for diff in sorted(net_asym.keys()):
        rets = net_asym[diff]
        if len(rets) < 10:
            continue
        mean_ret = sum(rets) / len(rets)
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"    diff={diff:+d}: mean_ret={mean_ret:+.4f}, up%={up_frac:.1%}, n={len(rets)}")


def analyze_spread_predictor(data):
    """Q4: Does spread narrowing/widening predict moves?"""
    print("\n" + "="*80)
    print("Q4: SPREAD AS PREDICTOR")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    spread_change_returns = defaultdict(list)

    for day, rows in sorted(days.items()):
        prev_spread = None
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            bid1 = row.get('bid_price_1')
            ask1 = row.get('ask_price_1')

            if bid1 is None or ask1 is None:
                prev_spread = None
                continue

            spread = ask1 - bid1

            if row['mid_price'] is not None and next_row['mid_price'] is not None:
                ret = next_row['mid_price'] - row['mid_price']

                # Bucket by spread
                spread_bucket = round(spread)
                spread_change_returns[('spread', spread_bucket)].append(ret)

                if prev_spread is not None:
                    if spread < prev_spread:
                        spread_change_returns[('narrowing', 0)].append(ret)
                    elif spread > prev_spread:
                        spread_change_returns[('widening', 0)].append(ret)
                    else:
                        spread_change_returns[('unchanged', 0)].append(ret)

            prev_spread = spread

    print("\n  Spread level -> next return:")
    for key in sorted(k for k in spread_change_returns if k[0] == 'spread'):
        rets = spread_change_returns[key]
        if len(rets) < 20:
            continue
        mean_ret = sum(rets) / len(rets)
        abs_mean = sum(abs(r) for r in rets) / len(rets)
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"    spread={key[1]:>3}: mean_ret={mean_ret:+.4f}, |ret|={abs_mean:.3f}, up%={up_frac:.1%}, n={len(rets)}")

    print("\n  Spread change direction -> next return:")
    for direction in ['narrowing', 'widening', 'unchanged']:
        key = (direction, 0)
        if key in spread_change_returns:
            rets = spread_change_returns[key]
            mean_ret = sum(rets) / len(rets)
            abs_mean = sum(abs(r) for r in rets) / len(rets)
            up_frac = sum(1 for r in rets if r > 0) / len(rets)
            print(f"    {direction:>10}: mean_ret={mean_ret:+.4f}, |ret|={abs_mean:.3f}, up%={up_frac:.1%}, n={len(rets)}")


def analyze_bot3_signal(data):
    """Q5: When Bot3 appears, does price move in its direction?"""
    print("\n" + "="*80)
    print("Q5: BOT3 APPEARANCE AS SIGNAL")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    bot3_events = []

    for day, rows in sorted(days.items()):
        mids = [r['mid_price'] for r in rows]

        for idx, row in enumerate(rows):
            levels = classify_levels(row)

            bot3_bids = [l for l in levels['bids'] if l['bot'] == 'bot3']
            bot3_asks = [l for l in levels['asks'] if l['bot'] == 'bot3']

            if bot3_bids or bot3_asks:
                side = 'bid' if bot3_bids else 'ask'
                vol = bot3_bids[0]['vol'] if bot3_bids else bot3_asks[0]['vol']
                price = bot3_bids[0]['price'] if bot3_bids else bot3_asks[0]['price']

                future_rets = {}
                for lag in [1, 2, 3, 5, 10, 20]:
                    if idx + lag < len(rows) and mids[idx + lag] is not None and mids[idx] is not None:
                        future_rets[lag] = mids[idx + lag] - mids[idx]

                # Compute offset from mid
                if mids[idx] is not None:
                    offset = price - mids[idx]
                else:
                    offset = None

                bot3_events.append({
                    'side': side,
                    'vol': vol,
                    'price': price,
                    'offset': offset,
                    'future_rets': future_rets,
                    'day': day,
                    'ts': row['timestamp']
                })

    print(f"\n  Total Bot3 appearances: {len(bot3_events)}")
    print(f"    Bid side: {sum(1 for e in bot3_events if e['side'] == 'bid')}")
    print(f"    Ask side: {sum(1 for e in bot3_events if e['side'] == 'ask')}")

    # Bot3 on bid side = someone willing to buy -> bullish signal?
    for side in ['bid', 'ask']:
        events = [e for e in bot3_events if e['side'] == side]
        if not events:
            continue

        print(f"\n  Bot3 on {side} side ({len(events)} events):")
        for lag in [1, 2, 3, 5, 10, 20]:
            rets = [e['future_rets'][lag] for e in events if lag in e['future_rets']]
            if rets:
                mean_ret = sum(rets) / len(rets)
                up_frac = sum(1 for r in rets if r > 0) / len(rets)
                print(f"    Lag {lag:2d}: mean_ret={mean_ret:+.4f}, up%={up_frac:.1%}, n={len(rets)}")

    # Volume of Bot3 as signal strength
    print(f"\n  Bot3 volume distribution:")
    vol_counts = Counter(e['vol'] for e in bot3_events)
    for v in sorted(vol_counts):
        print(f"    vol={v}: {vol_counts[v]}")

    # Bot3 offset from mid
    print(f"\n  Bot3 offset from mid_price:")
    offset_counts = Counter(round(e['offset']) for e in bot3_events if e['offset'] is not None)
    for off in sorted(offset_counts):
        events_at_off = [e for e in bot3_events if e['offset'] is not None and round(e['offset']) == off]
        rets1 = [e['future_rets'].get(1) for e in events_at_off]
        rets1 = [r for r in rets1 if r is not None]
        mean_r = sum(rets1) / len(rets1) if rets1 else 0
        print(f"    offset={off:+.0f}: count={offset_counts[off]}, mean_ret_lag1={mean_r:+.4f}")


def analyze_sequential_patterns(data):
    """Q6: Check for repeating sequences in mid-price changes."""
    print("\n" + "="*80)
    print("Q6: SEQUENTIAL PATTERN DETECTION")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    all_signs = []  # List of (up/down/flat) sequences

    for day, rows in sorted(days.items()):
        for idx in range(1, len(rows)):
            if rows[idx]['mid_price'] is not None and rows[idx-1]['mid_price'] is not None:
                change = rows[idx]['mid_price'] - rows[idx-1]['mid_price']
                if change > 0.01:
                    all_signs.append(1)  # up
                elif change < -0.01:
                    all_signs.append(-1)  # down
                else:
                    all_signs.append(0)  # flat

    total = len(all_signs)
    print(f"\n  Total tick changes: {total}")
    print(f"    Up: {sum(1 for s in all_signs if s==1)} ({sum(1 for s in all_signs if s==1)/total:.1%})")
    print(f"    Down: {sum(1 for s in all_signs if s==-1)} ({sum(1 for s in all_signs if s==-1)/total:.1%})")
    print(f"    Flat: {sum(1 for s in all_signs if s==0)} ({sum(1 for s in all_signs if s==0)/total:.1%})")

    # 2-gram patterns
    print(f"\n  2-gram patterns (prev_sign -> next_sign probability):")
    bigram_counts = defaultdict(lambda: defaultdict(int))
    for i in range(len(all_signs) - 1):
        bigram_counts[all_signs[i]][all_signs[i+1]] += 1

    labels = {-1: 'DN', 0: 'FL', 1: 'UP'}
    for prev in [-1, 0, 1]:
        total_given = sum(bigram_counts[prev].values())
        if total_given == 0:
            continue
        parts = []
        for nxt in [-1, 0, 1]:
            pct = bigram_counts[prev][nxt] / total_given * 100
            parts.append(f"{labels[nxt]}={pct:.1f}%")
        print(f"    After {labels[prev]:>2}: {', '.join(parts)}  (n={total_given})")

    # 3-gram patterns
    print(f"\n  3-gram patterns (interesting ones):")
    trigram_counts = defaultdict(lambda: defaultdict(int))
    for i in range(len(all_signs) - 2):
        key = (all_signs[i], all_signs[i+1])
        trigram_counts[key][all_signs[i+2]] += 1

    for key in sorted(trigram_counts.keys()):
        total_given = sum(trigram_counts[key].values())
        if total_given < 50:
            continue
        up_pct = trigram_counts[key].get(1, 0) / total_given
        dn_pct = trigram_counts[key].get(-1, 0) / total_given
        if abs(up_pct - dn_pct) > 0.05:  # non-trivial asymmetry
            print(f"    After ({labels[key[0]]},{labels[key[1]]}): UP={up_pct:.1%}, DN={dn_pct:.1%}, n={total_given}")


def analyze_autocorrelation(data):
    """Q7: Autocorrelation of mid-price returns at lags 1-20."""
    print("\n" + "="*80)
    print("Q7: LAG ANALYSIS (Autocorrelation of mid-price returns)")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    all_returns = []
    for day, rows in sorted(days.items()):
        for idx in range(1, len(rows)):
            if rows[idx]['mid_price'] is not None and rows[idx-1]['mid_price'] is not None:
                ret = rows[idx]['mid_price'] - rows[idx-1]['mid_price']
                all_returns.append(ret)

    n = len(all_returns)
    mean_ret = sum(all_returns) / n
    var_ret = sum((r - mean_ret)**2 for r in all_returns) / n

    print(f"\n  Total returns: {n}")
    print(f"  Mean return: {mean_ret:.6f}")
    print(f"  Std return: {var_ret**0.5:.4f}")
    print(f"  95% significance bound: +/-{1.96/n**0.5:.4f}")

    print(f"\n  {'Lag':>5} {'Autocorr':>10} {'Significant?':>14}")
    print(f"  {'-'*32}")

    sig_bound = 1.96 / n**0.5

    for lag in range(1, 21):
        cov = 0
        count = 0
        for i in range(n - lag):
            cov += (all_returns[i] - mean_ret) * (all_returns[i+lag] - mean_ret)
            count += 1
        if count > 0 and var_ret > 0:
            ac = (cov / count) / var_ret
            sig = "***" if abs(ac) > sig_bound else ""
            print(f"  {lag:>5} {ac:>+10.5f} {sig:>14}")


def analyze_hidden_state(data):
    """Q8: Does the gap between Bot1 and Bot2 predict anything?"""
    print("\n" + "="*80)
    print("Q8: HIDDEN STATE (Bot1-Bot2 gap analysis)")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    gap_returns = defaultdict(list)

    for day, rows in sorted(days.items()):
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            if row['mid_price'] is None or next_row['mid_price'] is None:
                continue

            levels = classify_levels(row)

            bot1_bid = None
            bot2_bid = None
            bot1_ask = None
            bot2_ask = None

            for lev in levels['bids']:
                if lev['bot'] == 'bot1':
                    bot1_bid = lev['price']
                elif lev['bot'] == 'bot2':
                    bot2_bid = lev['price']
            for lev in levels['asks']:
                if lev['bot'] == 'bot1':
                    bot1_ask = lev['price']
                elif lev['bot'] == 'bot2':
                    bot2_ask = lev['price']

            ret = next_row['mid_price'] - row['mid_price']

            # Gap between bot2 bid and bot1 bid (should be ~3 normally)
            if bot2_bid is not None and bot1_bid is not None:
                gap = bot2_bid - bot1_bid  # normally +3 (bot2 is tighter)
                gap_returns[('bid_gap', round(gap))].append(ret)

            if bot2_ask is not None and bot1_ask is not None:
                gap = bot1_ask - bot2_ask  # normally +1 or +2
                gap_returns[('ask_gap', round(gap))].append(ret)

            # Bot2 position relative to mid
            if bot2_bid is not None:
                offset = row['mid_price'] - bot2_bid
                gap_returns[('bot2_bid_offset', round(offset))].append(ret)

            if bot2_ask is not None:
                offset = bot2_ask - row['mid_price']
                gap_returns[('bot2_ask_offset', round(offset))].append(ret)

    for category in ['bid_gap', 'ask_gap', 'bot2_bid_offset', 'bot2_ask_offset']:
        keys = sorted(k for k in gap_returns if k[0] == category)
        if not keys:
            continue
        print(f"\n  {category}:")
        for key in keys:
            rets = gap_returns[key]
            if len(rets) < 20:
                continue
            mean_ret = sum(rets) / len(rets)
            up_frac = sum(1 for r in rets if r > 0) / len(rets)
            print(f"    {key[1]:>+3}: mean_ret={mean_ret:+.5f}, up%={up_frac:.1%}, n={len(rets)}")


def analyze_obi_signal(data):
    """Bonus: Order Book Imbalance (volume-weighted) as predictor."""
    print("\n" + "="*80)
    print("BONUS: ORDER BOOK IMBALANCE (OBI)")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    obi_returns = defaultdict(list)

    for day, rows in sorted(days.items()):
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            if row['mid_price'] is None or next_row['mid_price'] is None:
                continue

            bid_vol = 0
            ask_vol = 0
            for i in [1, 2, 3]:
                bv = row.get(f'bid_volume_{i}')
                av = row.get(f'ask_volume_{i}')
                if bv is not None:
                    bid_vol += bv
                if av is not None:
                    ask_vol += av

            if bid_vol + ask_vol == 0:
                continue

            obi = (bid_vol - ask_vol) / (bid_vol + ask_vol)
            ret = next_row['mid_price'] - row['mid_price']

            # Bucket OBI
            bucket = round(obi * 5) / 5  # 0.2 increments
            obi_returns[bucket].append(ret)

    print(f"\n  {'OBI':>6} {'Count':>8} {'Mean Ret':>10} {'Up %':>8}")
    print(f"  {'-'*35}")
    for bucket in sorted(obi_returns.keys()):
        rets = obi_returns[bucket]
        if len(rets) < 10:
            continue
        mean_ret = sum(rets) / len(rets)
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"  {bucket:>+6.1f} {len(rets):>8} {mean_ret:>+10.4f} {up_frac:>7.1%}")


def analyze_fv_inference_accuracy(data):
    """Bonus: How well can we infer FV from the book? And does residual predict?"""
    print("\n" + "="*80)
    print("BONUS: FV INFERENCE FROM BOT2 & PREDICTIVE RESIDUAL")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    fv_diffs = []  # (inferred_fv - mid, next_return)

    for day, rows in sorted(days.items()):
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            if row['mid_price'] is None or next_row['mid_price'] is None:
                continue

            fv = infer_fv_from_bot2(row)
            if fv is not None:
                diff = fv - row['mid_price']
                ret = next_row['mid_price'] - row['mid_price']
                fv_diffs.append((diff, ret))

    if not fv_diffs:
        print("  No FV inferences possible")
        return

    print(f"\n  FV inferences: {len(fv_diffs)}")

    # Bucket by FV-mid difference
    buckets = defaultdict(list)
    for diff, ret in fv_diffs:
        bucket = round(diff * 2) / 2  # 0.5 increments
        buckets[bucket].append(ret)

    print(f"\n  {'FV-Mid':>8} {'Count':>8} {'Mean Ret':>10} {'Up %':>8}")
    print(f"  {'-'*38}")
    for bucket in sorted(buckets.keys()):
        rets = buckets[bucket]
        if len(rets) < 10:
            continue
        mean_ret = sum(rets) / len(rets)
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        print(f"  {bucket:>+8.1f} {len(rets):>8} {mean_ret:>+10.4f} {up_frac:>7.1%}")

    # Correlation between FV-mid and next return
    diffs = [d for d, _ in fv_diffs]
    rets = [r for _, r in fv_diffs]
    mean_d = sum(diffs) / len(diffs)
    mean_r = sum(rets) / len(rets)
    cov = sum((d - mean_d) * (r - mean_r) for d, r in zip(diffs, rets)) / len(diffs)
    std_d = (sum((d - mean_d)**2 for d in diffs) / len(diffs)) ** 0.5
    std_r = (sum((r - mean_r)**2 for r in rets) / len(rets)) ** 0.5
    if std_d > 0 and std_r > 0:
        corr = cov / (std_d * std_r)
        print(f"\n  Correlation(FV-Mid, NextReturn) = {corr:+.4f}")


def analyze_bot2_presence_signal(data):
    """Bonus: Does bot2 being present on only one side predict direction?"""
    print("\n" + "="*80)
    print("BONUS: BOT2 PRESENCE ASYMMETRY")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    presence_returns = defaultdict(list)

    for day, rows in sorted(days.items()):
        for idx in range(len(rows) - 1):
            row = rows[idx]
            next_row = rows[idx + 1]

            if row['mid_price'] is None or next_row['mid_price'] is None:
                continue

            levels = classify_levels(row)
            has_bot2_bid = any(l['bot'] == 'bot2' for l in levels['bids'])
            has_bot2_ask = any(l['bot'] == 'bot2' for l in levels['asks'])

            ret = next_row['mid_price'] - row['mid_price']

            if has_bot2_bid and has_bot2_ask:
                presence_returns['both'].append(ret)
            elif has_bot2_bid and not has_bot2_ask:
                presence_returns['bid_only'].append(ret)
            elif has_bot2_ask and not has_bot2_bid:
                presence_returns['ask_only'].append(ret)
            else:
                presence_returns['neither'].append(ret)

            # Also Bot1
            has_bot1_bid = any(l['bot'] == 'bot1' for l in levels['bids'])
            has_bot1_ask = any(l['bot'] == 'bot1' for l in levels['asks'])

            if has_bot1_bid and not has_bot1_ask:
                presence_returns['bot1_bid_only'].append(ret)
            elif has_bot1_ask and not has_bot1_bid:
                presence_returns['bot1_ask_only'].append(ret)

    for key in ['both', 'bid_only', 'ask_only', 'neither', 'bot1_bid_only', 'bot1_ask_only']:
        rets = presence_returns.get(key, [])
        if len(rets) < 10:
            continue
        mean_ret = sum(rets) / len(rets)
        up_frac = sum(1 for r in rets if r > 0) / len(rets)
        # Multi-lag
        print(f"\n  Bot2 {key}: mean_ret={mean_ret:+.5f}, up%={up_frac:.1%}, n={len(rets)}")

    # Multi-tick forward for presence asymmetry
    print(f"\n  Bot2 presence asymmetry multi-lag analysis:")
    for key in ['bid_only', 'ask_only']:
        events = []
        for day, rows in sorted(days.items()):
            mids = [r['mid_price'] for r in rows]
            for idx in range(len(rows)):
                row = rows[idx]
                levels = classify_levels(row)
                has_b2_bid = any(l['bot'] == 'bot2' for l in levels['bids'])
                has_b2_ask = any(l['bot'] == 'bot2' for l in levels['asks'])

                matches = (key == 'bid_only' and has_b2_bid and not has_b2_ask) or \
                          (key == 'ask_only' and has_b2_ask and not has_b2_bid)

                if matches and mids[idx] is not None:
                    events.append((idx, mids))

        if not events:
            continue
        print(f"\n    {key} ({len(events)} events):")
        for lag in [1, 2, 3, 5, 10]:
            rets = []
            for idx, mids in events:
                if idx + lag < len(mids) and mids[idx + lag] is not None:
                    rets.append(mids[idx + lag] - mids[idx])
            if rets:
                mean_ret = sum(rets) / len(rets)
                up_frac = sum(1 for r in rets if r > 0) / len(rets)
                print(f"      Lag {lag:2d}: mean_ret={mean_ret:+.5f}, up%={up_frac:.1%}")


def analyze_mid_price_vs_inferred_fv(data):
    """Bonus: Track how mid_price deviates from inferred FV over time."""
    print("\n" + "="*80)
    print("BONUS: MID PRICE CALCULATION ANALYSIS")
    print("="*80)

    # The mid_price in the data is (best_bid + best_ask)/2
    # But when one side is missing, it equals the one present side
    # This creates artifacts. Let's check what drives mid changes.

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    # Analyze: when only one side is present, mid = that side's best price
    one_sided = 0
    two_sided = 0

    for row in data:
        bid1 = row.get('bid_price_1')
        ask1 = row.get('ask_price_1')
        if bid1 is None or ask1 is None:
            one_sided += 1
        else:
            two_sided += 1

    print(f"\n  Two-sided books: {two_sided} ({two_sided/len(data):.1%})")
    print(f"  One-sided books: {one_sided} ({one_sided/len(data):.1%})")

    # When one-sided, the mid is biased. Does removing these help signals?
    print(f"\n  One-sided book breakdown:")
    bid_only = sum(1 for r in data if r.get('bid_price_1') is not None and r.get('ask_price_1') is None)
    ask_only = sum(1 for r in data if r.get('ask_price_1') is not None and r.get('bid_price_1') is None)
    neither = sum(1 for r in data if r.get('ask_price_1') is None and r.get('bid_price_1') is None)
    print(f"    Bid only: {bid_only}")
    print(f"    Ask only: {ask_only}")
    print(f"    Neither: {neither}")


def analyze_tick_periodicity(data):
    """Q6b: Check for periodic patterns in returns."""
    print("\n" + "="*80)
    print("Q6b: PERIODICITY IN RETURNS (DFT-like analysis)")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    # Compute returns per day, then look for periodic patterns
    for day in sorted(days.keys()):
        rows = days[day]
        returns = []
        for idx in range(1, len(rows)):
            if rows[idx]['mid_price'] is not None and rows[idx-1]['mid_price'] is not None:
                returns.append(rows[idx]['mid_price'] - rows[idx-1]['mid_price'])
            else:
                returns.append(0)

        n = len(returns)
        if n < 100:
            continue

        # Check for periodicity using autocorrelation at specific lags
        mean_r = sum(returns) / n
        var_r = sum((r - mean_r)**2 for r in returns) / n

        if var_r < 1e-10:
            continue

        # Check round-number lags
        print(f"\n  Day {day}: {n} returns")
        notable = []
        for lag in [5, 10, 20, 25, 50, 100, 200, 500, 1000]:
            if lag >= n:
                break
            cov = sum((returns[i] - mean_r) * (returns[i+lag] - mean_r) for i in range(n - lag)) / (n - lag)
            ac = cov / var_r
            sig = abs(ac) > 1.96 / n**0.5
            if sig:
                notable.append(lag)
            marker = "***" if sig else ""
            print(f"    Lag {lag:>5}: ac={ac:+.5f} {marker}")

        if notable:
            print(f"    Significant lags: {notable}")


def analyze_bot2_wall_delta_as_fv_tracker(data):
    """Key insight: Bot2 wall position directly tracks FV.
    Changes in Bot2 wall = changes in floor(FV-0.5).
    This is more informative than mid_price."""
    print("\n" + "="*80)
    print("KEY ANALYSIS: BOT2 AS DIRECT FV TRACKER")
    print("="*80)

    days = defaultdict(list)
    for r in data:
        days[r['day']].append(r)

    # Extract Bot2 bid position over time
    for day in sorted(days.keys()):
        rows = days[day]
        bot2_bids = []
        bot2_asks = []
        timestamps = []

        for row in rows:
            levels = classify_levels(row)
            b2b = None
            b2a = None
            for l in levels['bids']:
                if l['bot'] == 'bot2':
                    b2b = l['price']
            for l in levels['asks']:
                if l['bot'] == 'bot2':
                    b2a = l['price']
            bot2_bids.append(b2b)
            bot2_asks.append(b2a)
            timestamps.append(row['timestamp'])

        # How often does Bot2 position change?
        changes = 0
        total_present = 0
        for i in range(1, len(bot2_bids)):
            if bot2_bids[i] is not None and bot2_bids[i-1] is not None:
                total_present += 1
                if bot2_bids[i] != bot2_bids[i-1]:
                    changes += 1

        print(f"\n  Day {day}:")
        print(f"    Bot2 bid present: {sum(1 for b in bot2_bids if b is not None)}/{len(bot2_bids)}")
        print(f"    Bot2 bid changes: {changes}/{total_present} consecutive pairs ({changes/max(total_present,1)*100:.1f}%)")

        # When Bot2 bid changes, by how much?
        deltas = []
        for i in range(1, len(bot2_bids)):
            if bot2_bids[i] is not None and bot2_bids[i-1] is not None and bot2_bids[i] != bot2_bids[i-1]:
                deltas.append(bot2_bids[i] - bot2_bids[i-1])

        if deltas:
            delta_counts = Counter(deltas)
            for d in sorted(delta_counts):
                print(f"    Delta={d:+.0f}: {delta_counts[d]} times")

    # CRITICAL: When Bot2 jumps by >=2, does it predict momentum?
    print(f"\n  Large Bot2 jumps (|delta| >= 2) as momentum signal:")
    for day in sorted(days.keys()):
        rows = days[day]
        mids = [r['mid_price'] for r in rows]

        for idx in range(1, len(rows)):
            levels_now = classify_levels(rows[idx])
            levels_prev = classify_levels(rows[idx-1])

            b2b_now = None
            b2b_prev = None
            for l in levels_now['bids']:
                if l['bot'] == 'bot2':
                    b2b_now = l['price']
            for l in levels_prev['bids']:
                if l['bot'] == 'bot2':
                    b2b_prev = l['price']

            if b2b_now is not None and b2b_prev is not None:
                delta = b2b_now - b2b_prev
                if abs(delta) >= 2 and mids[idx] is not None:
                    future = []
                    for lag in [1, 3, 5, 10]:
                        if idx + lag < len(rows) and mids[idx + lag] is not None:
                            future.append(f"lag{lag}={mids[idx+lag]-mids[idx]:+.1f}")
                    if future:
                        print(f"    Day {day} t={rows[idx]['timestamp']:>6}: delta={delta:+.0f}, {', '.join(future)}")


if __name__ == "__main__":
    print("Loading ACO data...")
    data = load_data()
    print(f"Loaded {len(data)} rows across {len(set(r['day'] for r in data))} days")

    analyze_wall_movement_prediction(data)
    analyze_volume_changes(data)
    analyze_book_asymmetry(data)
    analyze_spread_predictor(data)
    analyze_bot3_signal(data)
    analyze_sequential_patterns(data)
    analyze_autocorrelation(data)
    analyze_hidden_state(data)
    analyze_obi_signal(data)
    analyze_fv_inference_accuracy(data)
    analyze_bot2_presence_signal(data)
    analyze_mid_price_vs_inferred_fv(data)
    analyze_tick_periodicity(data)
    analyze_bot2_wall_delta_as_fv_tracker(data)

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
