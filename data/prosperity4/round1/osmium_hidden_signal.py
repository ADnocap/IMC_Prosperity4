"""
OSMIUM HIDDEN SIGNAL - Deep Dive into Book Asymmetry
====================================================
The first analysis found that when spread != 16, the volume imbalance
(bv1 - av1) predicts the NEXT FV direction with 83-97% accuracy.

This script digs into:
1. EXACTLY how the asymmetric spreads encode direction
2. Which bot creates the asymmetry and how
3. Precise signal extraction rules for a trading strategy
4. The noise bot (Bot 3) signal from small/offset trades
5. Whether BV2/AV2 at spread=16 predict anything
"""

import csv
from collections import defaultdict, Counter

DATA_DIR = "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round1"
DAYS = [-2, -1, 0]
PRODUCT = "ASH_COATED_OSMIUM"

def load_prices(day):
    path = f"{DATA_DIR}/prices_round_1_day_{day}.csv"
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def load_trades(day):
    path = f"{DATA_DIR}/trades_round_1_day_{day}.csv"
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def sf(v):
    return float(v) if v and v != '' else None

def si(v):
    return int(v) if v and v != '' else None

def extract_osm(prices):
    data = []
    for row in prices:
        if row['product'] != PRODUCT:
            continue
        data.append({
            'ts': int(row['timestamp']),
            'bp1': sf(row['bid_price_1']), 'bv1': si(row['bid_volume_1']),
            'bp2': sf(row['bid_price_2']), 'bv2': si(row['bid_volume_2']),
            'bp3': sf(row['bid_price_3']), 'bv3': si(row['bid_volume_3']),
            'ap1': sf(row['ask_price_1']), 'av1': si(row['ask_volume_1']),
            'ap2': sf(row['ask_price_2']), 'av2': si(row['ask_volume_2']),
            'ap3': sf(row['ask_price_3']), 'av3': si(row['ask_volume_3']),
            'mid': sf(row['mid_price']),
        })
    return data

# ============================================================
# LOAD DATA
# ============================================================
all_osm = {}
all_trades = {}
for day in DAYS:
    prices = load_prices(day)
    all_osm[day] = extract_osm(prices)
    trades = load_trades(day)
    all_trades[day] = [t for t in trades if t['symbol'] == PRODUCT]

# ============================================================
# 1. WHAT EXACTLY ARE THE NON-SPREAD-16 BOOK STATES?
# ============================================================
print("=" * 80)
print("1. NON-SPREAD-16 BOOK STATES - EXACT STRUCTURE")
print("=" * 80)

# For spread=18, 19, 21: show the full book (prices + volumes)
# relative to inferred FV

for spread_target in [5, 6, 7, 9, 10, 11, 13, 18, 19, 21]:
    examples = []
    for day in DAYS:
        for d in all_osm[day]:
            if d['bp1'] is not None and d['ap1'] is not None:
                spread = d['ap1'] - d['bp1']
                if int(spread) == spread_target and len(examples) < 5:
                    mid = (d['bp1'] + d['ap1']) / 2
                    examples.append({
                        'day': day, 'ts': d['ts'],
                        'bp1': d['bp1'], 'bv1': d['bv1'],
                        'bp2': d['bp2'], 'bv2': d['bv2'],
                        'ap1': d['ap1'], 'av1': d['av1'],
                        'ap2': d['ap2'], 'av2': d['av2'],
                        'mid': mid, 'spread': spread
                    })

    if examples:
        print(f"\n--- Spread = {spread_target} (showing up to 5 examples) ---")
        for e in examples:
            bp2_str = f", L2bid={e['bp2']}x{e['bv2']}" if e['bp2'] else ""
            ap2_str = f", L2ask={e['ap2']}x{e['av2']}" if e['ap2'] else ""
            print(f"  Day {e['day']} t={e['ts']}: bid={e['bp1']}x{e['bv1']}{bp2_str} | ask={e['ap1']}x{e['av1']}{ap2_str} | mid={e['mid']}")

# ============================================================
# 2. THE KEY SIGNAL: HOW DOES ASYMMETRY WORK AT SPREAD=18/19?
# ============================================================
print("\n" + "=" * 80)
print("2. SPREAD=18/19: VOLUME IMBALANCE DETAILS")
print("=" * 80)

# At spread=18/19, the FV is in between. The side with more volume
# tells us which way FV moved (or is about to move).

for spread_target in [18, 19]:
    imb_stats = defaultdict(lambda: {'up': 0, 'down': 0, 'total': 0})

    for day in DAYS:
        osm = all_osm[day]
        # Build FV dict from spread-16
        fv_dict = {}
        for d in osm:
            if d['bp1'] is not None and d['ap1'] is not None:
                if d['ap1'] - d['bp1'] == 16:
                    fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

        # Forward-fill FV
        last_fv = None
        fv_ff = {}
        for d in osm:
            ts = d['ts']
            if ts in fv_dict:
                last_fv = fv_dict[ts]
            if last_fv is not None:
                fv_ff[ts] = last_fv

        osm_by_ts = {d['ts']: d for d in osm}
        timestamps = [d['ts'] for d in osm]

        for i in range(len(timestamps) - 1):
            t0 = timestamps[i]
            d = osm_by_ts[t0]

            if d['bp1'] is None or d['ap1'] is None:
                continue
            spread = int(d['ap1'] - d['bp1'])
            if spread != spread_target:
                continue

            if d['bv1'] is None or d['av1'] is None:
                continue

            # Find next FV change
            next_dir = None
            for j in range(i+1, min(i+20, len(timestamps))):
                t_next = timestamps[j]
                if t_next in fv_ff and t0 in fv_ff:
                    diff = fv_ff[t_next] - fv_ff[t0]
                    if diff != 0:
                        next_dir = 1 if diff > 0 else -1
                        break

            imb = d['bv1'] - d['av1']
            imb_sign = 'pos' if imb > 0 else ('neg' if imb < 0 else 'zero')

            if next_dir is not None:
                key = (imb_sign, imb)
                if next_dir == 1:
                    imb_stats[key]['up'] += 1
                else:
                    imb_stats[key]['down'] += 1
                imb_stats[key]['total'] += 1

    print(f"\nSpread={spread_target}:")
    print(f"  {'IMB_SIGN':>10} {'IMB_VAL':>8} {'UP':>6} {'DOWN':>6} {'TOTAL':>6} {'P(UP)':>8}")
    for key in sorted(imb_stats.keys(), key=lambda x: x[1]):
        s = imb_stats[key]
        p_up = s['up'] / s['total'] if s['total'] > 0 else 0
        print(f"  {key[0]:>10} {key[1]:>8} {s['up']:>6} {s['down']:>6} {s['total']:>6} {p_up:>8.3f}")

# ============================================================
# 3. THE EXACT MECHANISM: SPREAD=18 DECOMPOSITION
# ============================================================
print("\n" + "=" * 80)
print("3. SPREAD=18 DECOMPOSITION: WHICH SIDE MOVED FROM SPREAD=16?")
print("=" * 80)

# When spread goes from 16 to 18, did:
# (a) bid drop by 1, ask stay -> FV went down by 1 -> bid closer to new FV
# (b) ask rise by 1, bid stay -> FV went up by 1 -> ask closer to new FV
# Track the EXACT price changes

for day in DAYS:
    osm = all_osm[day]

    transitions_16_to_18 = []
    for i in range(1, len(osm)):
        d0 = osm[i-1]
        d1 = osm[i]

        if d0['bp1'] is None or d0['ap1'] is None or d1['bp1'] is None or d1['ap1'] is None:
            continue

        s0 = int(d0['ap1'] - d0['bp1'])
        s1 = int(d1['ap1'] - d1['bp1'])

        if s0 == 16 and s1 == 18:
            bid_change = int(d1['bp1'] - d0['bp1'])
            ask_change = int(d1['ap1'] - d0['ap1'])
            vol_change_bid = (d1['bv1'] or 0) - (d0['bv1'] or 0) if d0['bv1'] and d1['bv1'] else None
            vol_change_ask = (d1['av1'] or 0) - (d0['av1'] or 0) if d0['av1'] and d1['av1'] else None
            transitions_16_to_18.append({
                'ts': d1['ts'],
                'bid_chg': bid_change, 'ask_chg': ask_change,
                'bv0': d0['bv1'], 'av0': d0['av1'],
                'bv1': d1['bv1'], 'av1': d1['av1'],
                'bp0': int(d0['bp1']), 'ap0': int(d0['ap1']),
                'bp1': int(d1['bp1']), 'ap1': int(d1['ap1']),
            })

    print(f"\nDay {day}: {len(transitions_16_to_18)} transitions from spread=16 to spread=18")

    # Categorize
    bid_drop = [t for t in transitions_16_to_18 if t['bid_chg'] < 0 and t['ask_chg'] == 0]
    ask_rise = [t for t in transitions_16_to_18 if t['ask_chg'] > 0 and t['bid_chg'] == 0]
    both_move = [t for t in transitions_16_to_18 if t['bid_chg'] != 0 and t['ask_chg'] != 0]
    bid_drop_1 = [t for t in transitions_16_to_18 if t['bid_chg'] == -1 and t['ask_chg'] == 1]

    print(f"  Bid dropped, ask same: {len(bid_drop)}")
    print(f"  Ask rose, bid same: {len(ask_rise)}")
    print(f"  Bid -1, ask +1: {len(bid_drop_1)}")
    print(f"  Both moved: {len(both_move)}")
    if bid_drop:
        print(f"  First bid_drop example: {bid_drop[0]}")
    if ask_rise:
        print(f"  First ask_rise example: {ask_rise[0]}")
    if bid_drop_1:
        print(f"  First bid-1/ask+1 example: {bid_drop_1[0]}")

    # Show first 5 transitions in detail
    for t in transitions_16_to_18[:5]:
        print(f"    t={t['ts']}: [{t['bp0']}x{t['bv0']}|{t['ap0']}x{t['av0']}] -> [{t['bp1']}x{t['bv1']}|{t['ap1']}x{t['av1']}] bid_chg={t['bid_chg']:+d} ask_chg={t['ask_chg']:+d}")

# ============================================================
# 4. SIGNAL RELIABILITY: WHICH SIDE HAS MORE VOLUME AT SPREAD=18?
# ============================================================
print("\n" + "=" * 80)
print("4. AT SPREAD=18: DOES THE SIDE WITH MORE VOLUME = SIDE CLOSER TO NEW FV?")
print("=" * 80)

# Theory: when FV goes from 10000 to 10001 (up), the MM book shifts:
# Old: bid=9992, ask=10008 (spread=16, FV=10000)
# New: bid=9993, ask=10009 (spread=16, FV=10001)
# Transition: bid=9992, ask=10010 (spread=18)
# or: bid=9993, ask=10009 would already be spread=16 at new FV
# So spread=18 means: one side hasn't updated yet
# If ask moved first (to 10010), bid is still at 9992 -> mid=10001 -> FV went up
# bid volume might be larger (old quote) or smaller (being pulled)

for day in DAYS:
    osm = all_osm[day]

    # At spread=18 ticks, check bv1 vs av1
    bv_bigger_count = 0
    av_bigger_count = 0
    equal_count = 0

    for d in osm:
        if d['bp1'] is None or d['ap1'] is None:
            continue
        if int(d['ap1'] - d['bp1']) == 18 and d['bv1'] is not None and d['av1'] is not None:
            if d['bv1'] > d['av1']:
                bv_bigger_count += 1
            elif d['av1'] > d['bv1']:
                av_bigger_count += 1
            else:
                equal_count += 1

    print(f"\nDay {day} spread=18: bv1>av1={bv_bigger_count}, av1>bv1={av_bigger_count}, equal={equal_count}")

# ============================================================
# 5. PRECISE SIGNAL EXTRACTION AT EACH SPREAD STATE
# ============================================================
print("\n" + "=" * 80)
print("5. SIGNAL AT EACH SPREAD STATE: bv1 > av1 means which FV direction?")
print("=" * 80)

# For each non-16 spread, when bv1 > av1, does FV go up or down NEXT?
# This is the money question.

all_signal_data = defaultdict(lambda: {'bv_big_up': 0, 'bv_big_dn': 0, 'av_big_up': 0, 'av_big_dn': 0})

for day in DAYS:
    osm = all_osm[day]
    osm_by_ts = {d['ts']: d for d in osm}

    # Reconstruct FV from spread-16
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    # Forward-fill
    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv

    timestamps = [d['ts'] for d in osm]

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]

        if d['bp1'] is None or d['ap1'] is None or d['bv1'] is None or d['av1'] is None:
            continue

        spread = int(d['ap1'] - d['bp1'])
        if spread == 16:
            continue
        if d['bv1'] == d['av1']:
            continue

        # Find next FV that differs from current
        if t0 not in fv_ff:
            continue
        current_fv = fv_ff[t0]

        next_dir = None
        for j in range(i+1, min(i+30, len(timestamps))):
            t_next = timestamps[j]
            if t_next in fv_ff:
                diff = fv_ff[t_next] - current_fv
                if diff != 0:
                    next_dir = 1 if diff > 0 else -1
                    break

        if next_dir is None:
            continue

        if d['bv1'] > d['av1']:
            if next_dir == 1:
                all_signal_data[spread]['bv_big_up'] += 1
            else:
                all_signal_data[spread]['bv_big_dn'] += 1
        else:
            if next_dir == 1:
                all_signal_data[spread]['av_big_up'] += 1
            else:
                all_signal_data[spread]['av_big_dn'] += 1

print(f"\n{'SPREAD':>6} | {'BV>AV -> UP':>12} {'BV>AV -> DN':>12} {'P(UP|BV>AV)':>12} | {'AV>BV -> UP':>12} {'AV>BV -> DN':>12} {'P(UP|AV>BV)':>12}")
print("-" * 95)
for spread in sorted(all_signal_data.keys()):
    s = all_signal_data[spread]
    total_bv = s['bv_big_up'] + s['bv_big_dn']
    total_av = s['av_big_up'] + s['av_big_dn']
    p_up_bv = s['bv_big_up'] / total_bv if total_bv > 0 else 0
    p_up_av = s['av_big_up'] / total_av if total_av > 0 else 0
    print(f"{spread:>6} | {s['bv_big_up']:>12} {s['bv_big_dn']:>12} {p_up_bv:>12.3f} | {s['av_big_up']:>12} {s['av_big_dn']:>12} {p_up_av:>12.3f}")

# ============================================================
# 6. AT SPREAD=18: DOES BV1 > AV1 MEAN FV WENT UP OR DOWN?
# ============================================================
print("\n" + "=" * 80)
print("6. SPREAD=18 MICROSTRUCTURE: BID vs ASK PRICE RELATIVE TO MID")
print("=" * 80)

# At spread=18 with FV estimated:
# If FV=10001 (moved up from 10000):
#   new MM should be: bid=9993, ask=10009
#   but if transition: bid=9992, ask=10010 (old bid, new ask)
#   mid = 10001, but bid is 9 below mid, ask is 9 above mid -> symmetric mid
#   However, bid=9992 is 1 below where it should be
#   The VOLUMES should differ: the "lagging" side has old volume

for day in [DAYS[0]]:  # Just one day for detail
    osm = all_osm[day]

    for d in osm[:200]:  # First 200 ticks
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread in [18, 19, 21]:
            bp2_str = f" L2bid={d['bp2']}x{d['bv2']}" if d['bp2'] else ""
            ap2_str = f" L2ask={d['ap2']}x{d['av2']}" if d['ap2'] else ""
            print(f"  t={d['ts']} s={spread}: bid={int(d['bp1'])}x{d['bv1']}{bp2_str} | ask={int(d['ap1'])}x{d['av1']}{ap2_str}")

# ============================================================
# 7. BV2/AV2 AT SPREAD=16: DO L2 VOLUMES PREDICT?
# ============================================================
print("\n" + "=" * 80)
print("7. L2 VOLUMES (BV2, AV2) AT SPREAD=16 vs NEXT FV DIRECTION")
print("=" * 80)

l2_vol_vs_dir = defaultdict(lambda: [0, 0])  # (bv2, av2) -> [up, down]
l2_imb_vs_dir = defaultdict(lambda: [0, 0])  # bv2-av2 sign -> [up, down]

for day in DAYS:
    osm = all_osm[day]
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv

    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]
        if d['bp1'] is None or d['ap1'] is None:
            continue
        if int(d['ap1'] - d['bp1']) != 16:
            continue
        if d['bv2'] is None or d['av2'] is None:
            continue
        if t0 not in fv_ff:
            continue

        current_fv = fv_ff[t0]
        next_dir = None
        for j in range(i+1, min(i+30, len(timestamps))):
            t_next = timestamps[j]
            if t_next in fv_ff and fv_ff[t_next] != current_fv:
                next_dir = 1 if fv_ff[t_next] > current_fv else -1
                break

        if next_dir is None:
            continue

        idx = 0 if next_dir == 1 else 1

        bv2 = d['bv2']
        av2 = d['av2']
        l2_vol_vs_dir[(bv2, av2)][idx] += 1

        imb = bv2 - av2
        imb_sign = 'pos' if imb > 0 else ('neg' if imb < 0 else 'zero')
        l2_imb_vs_dir[imb_sign][idx] += 1

print("\nL2 volume imbalance (bv2 - av2) sign vs next FV direction:")
for sign in ['neg', 'zero', 'pos']:
    up, dn = l2_imb_vs_dir[sign]
    total = up + dn
    p_up = up/total if total > 0 else 0
    print(f"  {sign}: up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

print("\nL2 volume pairs (bv2, av2) with most samples:")
sorted_pairs = sorted(l2_vol_vs_dir.items(), key=lambda x: -(x[1][0]+x[1][1]))
for (bv2, av2), (up, dn) in sorted_pairs[:30]:
    total = up + dn
    if total >= 10:
        p_up = up/total
        print(f"  ({bv2}, {av2}): up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

# ============================================================
# 8. NOISE BOT DETECTION: TRADES AT UNUSUAL PRICES
# ============================================================
print("\n" + "=" * 80)
print("8. NOISE BOT TRADES: SMALL QTY AT CLOSE-TO-MID PRICES")
print("=" * 80)

for day in DAYS:
    osm = all_osm[day]
    trades = all_trades[day]

    # Build FV
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv

    print(f"\nDay {day}: {len(trades)} trades total")

    # Categorize by offset from FV
    close_trades = []  # trades within ±5 of FV (noise bot)
    far_trades = []    # trades at ±8 or more (MM bot)

    for t in trades:
        tts = int(t['timestamp'])
        tp = float(t['price'])
        qty = int(t['quantity'])

        if tts not in fv_ff:
            continue
        fv = fv_ff[tts]
        offset = tp - fv

        if abs(offset) <= 5:
            close_trades.append({'ts': tts, 'price': tp, 'qty': qty, 'offset': offset, 'fv': fv})
        else:
            far_trades.append({'ts': tts, 'price': tp, 'qty': qty, 'offset': offset, 'fv': fv})

    print(f"  Close trades (|offset| <= 5): {len(close_trades)}")
    print(f"  Far trades (|offset| > 5): {len(far_trades)}")

    # Do close trades predict FV direction?
    if close_trades:
        close_buy_then_up = 0
        close_buy_then_dn = 0
        close_sell_then_up = 0
        close_sell_then_dn = 0

        for ct in close_trades:
            # Trade above FV = someone bought (aggressive buyer)
            # Trade below FV = someone sold (aggressive seller)
            side = 'buy' if ct['offset'] > 0 else 'sell'

            # Find next FV change
            for t_next in sorted(fv_ff.keys()):
                if t_next > ct['ts']:
                    diff = fv_ff[t_next] - ct['fv']
                    if diff != 0:
                        if side == 'buy' and diff > 0:
                            close_buy_then_up += 1
                        elif side == 'buy' and diff < 0:
                            close_buy_then_dn += 1
                        elif side == 'sell' and diff > 0:
                            close_sell_then_up += 1
                        elif side == 'sell' and diff < 0:
                            close_sell_then_dn += 1
                        break

        total_buy = close_buy_then_up + close_buy_then_dn
        total_sell = close_sell_then_up + close_sell_then_dn
        print(f"  Close BUY then UP: {close_buy_then_up}/{total_buy} = {close_buy_then_up/total_buy:.3f}" if total_buy > 0 else "  Close BUY: no data")
        print(f"  Close SELL then DOWN: {close_sell_then_dn}/{total_sell} = {close_sell_then_dn/total_sell:.3f}" if total_sell > 0 else "  Close SELL: no data")

    # Show all close trades
    for ct in close_trades[:20]:
        print(f"    t={ct['ts']}: price={ct['price']}, FV={ct['fv']}, offset={ct['offset']:+.0f}, qty={ct['qty']}")

# ============================================================
# 9. COMPREHENSIVE SIGNAL TABLE
# ============================================================
print("\n" + "=" * 80)
print("9. COMPREHENSIVE EXPLOITABLE SIGNALS")
print("=" * 80)

print("""
SIGNAL 1: BOOK ASYMMETRY AT NON-SPREAD-16 TICKS (83-97% accurate)
=================================================================
When spread != 16, the book is asymmetric. The side (bid vs ask) with
MORE volume indicates the LAST direction of FV movement. Since FV has
~68% reversal probability, this gives us the NEXT direction prediction:

  If bv1 > av1: FV just moved DOWN -> 68% chance FV goes UP next
  If av1 > bv1: FV just moved UP -> 68% chance FV goes DOWN next

But wait - the analysis showed 83-97% accuracy, NOT 68%. Why?
Because at non-16 spreads, we see FV IN TRANSITION. The imbalance
tells us which way FV IS CURRENTLY MOVING, and the reversal is from
the PREVIOUS move. The combined signal is much stronger than just
reversal.

SIGNAL 2: SPREAD VALUE ITSELF
==============================
- Spread=16: FV is stable at mid. ~45% chance FV changes next tick.
- Spread=18/19: FV just changed. High probability of seeing the next
  FV value at the next spread=16 tick.
- Spread=5-13: These are TIGHT spreads, meaning aggressive orders
  are present. FV is likely about to change.
- Spread=21: Wide spread, FV just moved, similar to 18/19.

SIGNAL 3: REVERSAL PROBABILITY ESCALATION
==========================================
After 1 same-dir: P(reverse) = 68%
After 2 same-dir: P(reverse) = 81%
After 3 same-dir: P(reverse) = 86%
After 4 same-dir: P(reverse) = 93%
This is NOT geometric - it's super-geometric (stronger reversal pressure).
""")

# ============================================================
# 10. WHAT FRACTION OF TICKS HAVE A SIGNAL?
# ============================================================
print("=" * 80)
print("10. SIGNAL AVAILABILITY: HOW OFTEN IS SPREAD != 16?")
print("=" * 80)

for day in DAYS:
    osm = all_osm[day]
    total = len(osm)
    s16 = sum(1 for d in osm if d['bp1'] is not None and d['ap1'] is not None and int(d['ap1'] - d['bp1']) == 16)
    has_signal = sum(1 for d in osm if d['bp1'] is not None and d['ap1'] is not None and int(d['ap1'] - d['bp1']) != 16)
    one_sided = sum(1 for d in osm if (d['bp1'] is None) != (d['ap1'] is None))
    empty = sum(1 for d in osm if d['bp1'] is None and d['ap1'] is None)

    print(f"\nDay {day}:")
    print(f"  Spread=16 (no signal): {s16} ({100*s16/total:.1f}%)")
    print(f"  Spread!=16 (signal):   {has_signal} ({100*has_signal/total:.1f}%)")
    print(f"  One-sided book:        {one_sided} ({100*one_sided/total:.1f}%)")
    print(f"  Empty book:            {empty} ({100*empty/total:.1f}%)")

# ============================================================
# 11. ONE-SIDED BOOK: PREDICTIVE?
# ============================================================
print("\n" + "=" * 80)
print("11. ONE-SIDED BOOK (bid_only or ask_only): WHICH SIDE AND FV DIRECTION")
print("=" * 80)

for day in DAYS:
    osm = all_osm[day]
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)
    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv

    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    bid_only_up = 0
    bid_only_dn = 0
    ask_only_up = 0
    ask_only_dn = 0

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]
        if t0 not in fv_ff:
            continue

        is_bid_only = d['bp1'] is not None and d['ap1'] is None
        is_ask_only = d['ap1'] is not None and d['bp1'] is None

        if not is_bid_only and not is_ask_only:
            continue

        current_fv = fv_ff[t0]
        next_dir = None
        for j in range(i+1, min(i+30, len(timestamps))):
            t_next = timestamps[j]
            if t_next in fv_ff and fv_ff[t_next] != current_fv:
                next_dir = 1 if fv_ff[t_next] > current_fv else -1
                break

        if next_dir is None:
            continue

        if is_bid_only:
            if next_dir == 1:
                bid_only_up += 1
            else:
                bid_only_dn += 1
        if is_ask_only:
            if next_dir == 1:
                ask_only_up += 1
            else:
                ask_only_dn += 1

    total_bid = bid_only_up + bid_only_dn
    total_ask = ask_only_up + ask_only_dn
    print(f"\nDay {day}:")
    if total_bid > 0:
        print(f"  BID_ONLY: up={bid_only_up}, down={bid_only_dn}, P(up)={bid_only_up/total_bid:.3f} (n={total_bid})")
    if total_ask > 0:
        print(f"  ASK_ONLY: up={ask_only_up}, down={ask_only_dn}, P(up)={ask_only_up/total_ask:.3f} (n={total_ask})")

# ============================================================
# 12. COMBINED SIGNAL: SPREAD TYPE + IMBALANCE + REVERSAL
# ============================================================
print("\n" + "=" * 80)
print("12. COMBINED SIGNAL STRENGTH: IMBALANCE + RUN-LENGTH")
print("=" * 80)

# When we see spread!=16 with bv1>av1 (FV went down), AND we know
# the previous N moves were also down, what's P(up)?

combined_stats = defaultdict(lambda: [0, 0])  # (imb_sign, run_len) -> [correct, wrong]

for day in DAYS:
    osm = all_osm[day]
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv

    # Build FV change history
    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    fv_changes = []  # (timestamp, direction)
    for i in range(1, len(timestamps)):
        t0 = timestamps[i-1]
        t1 = timestamps[i]
        if t0 in fv_ff and t1 in fv_ff:
            diff = fv_ff[t1] - fv_ff[t0]
            if diff != 0:
                fv_changes.append((t1, 1 if diff > 0 else -1))

    # Build a lookup: at timestamp t, how many consecutive same-dir moves?
    run_at = {}
    current_run = 0
    current_dir = 0
    for ts, d in fv_changes:
        if d == current_dir:
            current_run += 1
        else:
            current_run = 1
            current_dir = d
        run_at[ts] = (current_run, current_dir)

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]

        if d['bp1'] is None or d['ap1'] is None or d['bv1'] is None or d['av1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16 or d['bv1'] == d['av1']:
            continue
        if t0 not in fv_ff:
            continue

        imb_sign = 'bv_big' if d['bv1'] > d['av1'] else 'av_big'

        # Find the run length at this point
        # Get the most recent fv_change before t0
        recent_run = 0
        recent_dir = 0
        for ts, (rl, rd) in sorted(run_at.items()):
            if ts <= t0:
                recent_run = rl
                recent_dir = rd
            else:
                break

        current_fv = fv_ff[t0]
        next_dir = None
        for j in range(i+1, min(i+30, len(timestamps))):
            t_next = timestamps[j]
            if t_next in fv_ff and fv_ff[t_next] != current_fv:
                next_dir = 1 if fv_ff[t_next] > current_fv else -1
                break

        if next_dir is None:
            continue

        # The signal says: if bv_big, FV went down -> predict UP
        predicted = 1 if imb_sign == 'bv_big' else -1
        correct = 1 if predicted == next_dir else 0

        combined_stats[(imb_sign, min(recent_run, 5))][correct] += 1
        combined_stats[(imb_sign, 'any')][correct] += 1

print(f"\n{'IMB_SIGN':>10} {'RUN_LEN':>8} {'CORRECT':>8} {'WRONG':>8} {'ACCURACY':>10}")
print("-" * 50)
for key in sorted(combined_stats.keys(), key=lambda x: (x[0], str(x[1]))):
    correct, wrong = combined_stats[key]
    total = correct + wrong
    acc = correct / total if total > 0 else 0
    print(f"{key[0]:>10} {str(key[1]):>8} {correct:>8} {wrong:>8} {acc:>10.3f}")

print("\n" + "=" * 80)
print("FINAL SUMMARY: THE HIDDEN PATTERN")
print("=" * 80)
print("""
1. FV moves in +/-1 steps with 65% reversal probability at lag-1.
   After 2 consecutive same-direction moves: 81% reversal.
   After 3: 86%. After 4: 93%. This is SUPER-GEOMETRIC.

2. The book is symmetric (bv1=av1) at spread=16 (~58% of ticks).
   At spread=16, there is NO predictive signal in volumes.

3. **THE HIDDEN PATTERN**: At spread != 16 (~34% of ticks), the book
   becomes ASYMMETRIC. The side with MORE volume reveals which direction
   FV just moved. Combined with the reversal probability, this gives
   83-97% accuracy for predicting the NEXT FV direction.

4. Spread != 16 occurs right when FV transitions. The MM bot adjusts
   one side at a time, creating a brief window where the book "leaks"
   the FV direction.

5. One-sided book states (ask_only ~4%, bid_only ~4%) also contain
   directional signal.

6. Trade data shows no buyer/seller info, and trades at +-8 from FV
   are the dominant MM bot. Small trades near FV are noise bot but
   appear too infrequently to be useful.

7. PEPPER has ZERO correlation with OSMIUM. They are independent.

STRATEGY IMPLICATION:
- When spread != 16 and bv1 > av1: FV went DOWN -> predict UP -> BUY
- When spread != 16 and av1 > bv1: FV went UP -> predict DOWN -> SELL
- Scale confidence by run length (more consecutive = stronger reversal)
- At spread=16, use the reversal from last known direction
""")
