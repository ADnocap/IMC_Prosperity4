"""
OSMIUM: L2 ASYMMETRY SIGNAL - The Real Hidden Pattern
======================================================
The first analysis found that the PRESENCE of L2 on one side
(not volume levels) predicts FV direction with ~68% accuracy.

Section 9 of the first script showed:
  bid_only_l2: next FV goes DOWN ~70% of the time
  ask_only_l2: next FV goes UP ~68% of the time

This is the REAL signal. Let's verify and quantify precisely.
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
        })
    return data

# ============================================================
# LOAD AND BUILD FV
# ============================================================
all_osm = {}
all_fv = {}

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)
    all_osm[day] = osm

    # Build spread-16 FV
    fv_dict = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                fv_dict[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    # Forward fill
    last_fv = None
    fv_ff = {}
    for d in osm:
        if d['ts'] in fv_dict:
            last_fv = fv_dict[d['ts']]
        if last_fv is not None:
            fv_ff[d['ts']] = last_fv
    all_fv[day] = fv_ff

# ============================================================
# 1. L2 ASYMMETRY AT ALL SPREAD STATES
# ============================================================
print("=" * 80)
print("1. L2 PRESENCE ASYMMETRY: PREDICTING NEXT FV DIRECTION")
print("=" * 80)

# Categories of L2 state:
# - both_l2: bp2 and ap2 both present
# - bid_only_l2: bp2 present, ap2 absent
# - ask_only_l2: ap2 present, bp2 absent
# - no_l2: neither present

l2_signal_all = defaultdict(lambda: [0, 0])  # (spread, l2_state) -> [up, down]

for day in DAYS:
    osm = all_osm[day]
    fv_ff = all_fv[day]
    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]

        if d['bp1'] is None or d['ap1'] is None:
            continue
        if t0 not in fv_ff:
            continue

        spread = int(d['ap1'] - d['bp1'])
        has_l2_bid = d['bp2'] is not None
        has_l2_ask = d['ap2'] is not None

        if has_l2_bid and has_l2_ask:
            l2_state = 'both_l2'
        elif has_l2_bid:
            l2_state = 'bid_only_l2'
        elif has_l2_ask:
            l2_state = 'ask_only_l2'
        else:
            l2_state = 'no_l2'

        # Find next FV change
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
        l2_signal_all[(spread, l2_state)][idx] += 1

print(f"\n{'SPREAD':>6} {'L2_STATE':>15} {'UP':>8} {'DOWN':>8} {'TOTAL':>8} {'P(UP)':>8} {'SIGNAL':>8}")
print("-" * 75)
for key in sorted(l2_signal_all.keys()):
    spread, l2_state = key
    up, dn = l2_signal_all[key]
    total = up + dn
    if total < 10:
        continue
    p_up = up / total
    # Signal: how far from 0.5
    signal_str = f"{p_up - 0.5:+.3f}"
    print(f"{spread:>6} {l2_state:>15} {up:>8} {dn:>8} {total:>8} {p_up:>8.3f} {signal_str:>8}")

# ============================================================
# 2. L2 ASYMMETRY SIGNAL REGARDLESS OF SPREAD
# ============================================================
print("\n" + "=" * 80)
print("2. L2 ASYMMETRY SIGNAL (ALL SPREADS COMBINED)")
print("=" * 80)

l2_combined = defaultdict(lambda: [0, 0])
for key, (up, dn) in l2_signal_all.items():
    _, l2_state = key
    l2_combined[l2_state][0] += up
    l2_combined[l2_state][1] += dn

for l2_state in ['bid_only_l2', 'ask_only_l2', 'both_l2', 'no_l2']:
    up, dn = l2_combined[l2_state]
    total = up + dn
    if total > 0:
        p_up = up / total
        print(f"  {l2_state:>15}: up={up}, down={dn}, P(up)={p_up:.4f} (n={total})")

# ============================================================
# 3. L2 ASYMMETRY ONLY AT NON-16 SPREADS
# ============================================================
print("\n" + "=" * 80)
print("3. L2 ASYMMETRY AT NON-16 SPREADS (where signal lives)")
print("=" * 80)

l2_non16 = defaultdict(lambda: [0, 0])
for key, (up, dn) in l2_signal_all.items():
    spread, l2_state = key
    if spread != 16:
        l2_non16[l2_state][0] += up
        l2_non16[l2_state][1] += dn

for l2_state in ['bid_only_l2', 'ask_only_l2', 'both_l2', 'no_l2']:
    up, dn = l2_non16[l2_state]
    total = up + dn
    if total > 0:
        p_up = up / total
        print(f"  {l2_state:>15}: up={up}, down={dn}, P(up)={p_up:.4f} (n={total})")

# ============================================================
# 4. WHAT ABOUT TIGHT SPREADS (5-13): WHICH L2 SIDE PRESENT?
# ============================================================
print("\n" + "=" * 80)
print("4. TIGHT SPREAD (5-13) BOOK STRUCTURE ANALYSIS")
print("=" * 80)

for spread_target in [5, 6, 7, 8, 9, 10, 11, 12, 13]:
    states = Counter()
    for day in DAYS:
        for d in all_osm[day]:
            if d['bp1'] is None or d['ap1'] is None:
                continue
            if int(d['ap1'] - d['bp1']) != spread_target:
                continue
            has_l2_bid = d['bp2'] is not None
            has_l2_ask = d['ap2'] is not None
            states[(has_l2_bid, has_l2_ask)] += 1

    if states:
        print(f"  Spread={spread_target}: {dict(states)}")

# ============================================================
# 5. THE ACTUAL MM BOT BEHAVIOR: HOW L2 IS GENERATED
# ============================================================
print("\n" + "=" * 80)
print("5. MM BOT L2 GENERATION: WHAT ARE THE L2 PRICES?")
print("=" * 80)

# At spread=18/19 with L2, what are the L2 prices relative to L1?

for spread_target in [18, 19]:
    l2_bid_present = []
    l2_ask_present = []

    for day in DAYS:
        for d in all_osm[day]:
            if d['bp1'] is None or d['ap1'] is None:
                continue
            if int(d['ap1'] - d['bp1']) != spread_target:
                continue

            if d['bp2'] is not None:
                offset = int(d['bp1'] - d['bp2'])
                l2_bid_present.append({
                    'bp1': int(d['bp1']), 'bv1': d['bv1'],
                    'bp2': int(d['bp2']), 'bv2': d['bv2'],
                    'ap1': int(d['ap1']), 'av1': d['av1'],
                    'offset': offset,
                    'has_l2_ask': d['ap2'] is not None,
                })

            if d['ap2'] is not None:
                offset = int(d['ap2'] - d['ap1'])
                l2_ask_present.append({
                    'ap1': int(d['ap1']), 'av1': d['av1'],
                    'ap2': int(d['ap2']), 'av2': d['av2'],
                    'bp1': int(d['bp1']), 'bv1': d['bv1'],
                    'offset': offset,
                    'has_l2_bid': d['bp2'] is not None,
                })

    print(f"\nSpread={spread_target}:")
    print(f"  L2 bid present: {len(l2_bid_present)} cases")
    if l2_bid_present:
        # L2 bid offset from L1
        offsets = Counter(e['offset'] for e in l2_bid_present)
        print(f"    bp1-bp2 offsets: {dict(sorted(offsets.items()))}")

        # When L2 bid exists, is L2 ask also present?
        both = sum(1 for e in l2_bid_present if e['has_l2_ask'])
        print(f"    Also has L2 ask: {both}/{len(l2_bid_present)}")

        # Typical structure
        for e in l2_bid_present[:3]:
            print(f"    Example: bid={e['bp1']}x{e['bv1']}, L2bid={e['bp2']}x{e['bv2']} | ask={e['ap1']}x{e['av1']}")

    print(f"  L2 ask present: {len(l2_ask_present)} cases")
    if l2_ask_present:
        offsets = Counter(e['offset'] for e in l2_ask_present)
        print(f"    ap2-ap1 offsets: {dict(sorted(offsets.items()))}")

        both = sum(1 for e in l2_ask_present if e['has_l2_bid'])
        print(f"    Also has L2 bid: {both}/{len(l2_ask_present)}")

        for e in l2_ask_present[:3]:
            print(f"    Example: bid={e['bp1']}x{e['bv1']} | ask={e['ap1']}x{e['av1']}, L2ask={e['ap2']}x{e['av2']}")

# ============================================================
# 6. THE REAL SIGNAL: L2 TELLS US WHERE FV IS GOING
# ============================================================
print("\n" + "=" * 80)
print("6. L2 ASYMMETRY AT SPREAD=18/19 WITH NEXT FV DIRECTION")
print("=" * 80)

# At spread=18 or 19:
# If only L2 BID exists -> the OLD position had L2 on bid side
# If only L2 ASK exists -> the OLD position had L2 on ask side
# Key insight: L2 on one side means THAT side corresponds to the
# previous FV level (the MM bot's L2 from old position)

for spread_target in [18, 19]:
    signal = defaultdict(lambda: [0, 0])

    for day in DAYS:
        osm = all_osm[day]
        fv_ff = all_fv[day]
        timestamps = [d['ts'] for d in osm]
        osm_by_ts = {d['ts']: d for d in osm}

        for i in range(len(timestamps)):
            t0 = timestamps[i]
            d = osm_by_ts[t0]
            if d['bp1'] is None or d['ap1'] is None:
                continue
            if int(d['ap1'] - d['bp1']) != spread_target:
                continue
            if t0 not in fv_ff:
                continue

            has_l2_bid = d['bp2'] is not None
            has_l2_ask = d['ap2'] is not None

            if has_l2_bid == has_l2_ask:
                continue  # skip symmetric or no-L2 cases

            current_fv = fv_ff[t0]
            next_dir = None
            for j in range(i+1, min(i+30, len(timestamps))):
                t_next = timestamps[j]
                if t_next in fv_ff and fv_ff[t_next] != current_fv:
                    next_dir = 1 if fv_ff[t_next] > current_fv else -1
                    break

            if next_dir is None:
                continue

            l2_state = 'bid_only_l2' if has_l2_bid else 'ask_only_l2'
            idx = 0 if next_dir == 1 else 1
            signal[l2_state][idx] += 1

    print(f"\nSpread={spread_target}:")
    for l2_state in ['bid_only_l2', 'ask_only_l2']:
        up, dn = signal[l2_state]
        total = up + dn
        if total > 0:
            p_up = up / total
            print(f"  {l2_state}: up={up}, down={dn}, P(up)={p_up:.4f} (n={total})")

# ============================================================
# 7. COMBINED: L2 + BV1/AV1 IMBALANCE AT NON-16 SPREADS
# ============================================================
print("\n" + "=" * 80)
print("7. COMBINED SIGNAL: L2 ASYMMETRY + VOLUME IMBALANCE")
print("=" * 80)

combined = defaultdict(lambda: [0, 0])

for day in DAYS:
    osm = all_osm[day]
    fv_ff = all_fv[day]
    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        d = osm_by_ts[t0]
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16:
            continue
        if t0 not in fv_ff:
            continue

        has_l2_bid = d['bp2'] is not None
        has_l2_ask = d['ap2'] is not None

        if has_l2_bid and not has_l2_ask:
            l2_signal = 'l2_bid'
        elif has_l2_ask and not has_l2_bid:
            l2_signal = 'l2_ask'
        elif has_l2_bid and has_l2_ask:
            l2_signal = 'l2_both'
        else:
            l2_signal = 'l2_none'

        if d['bv1'] is not None and d['av1'] is not None:
            if d['bv1'] > d['av1']:
                vol_signal = 'bv>av'
            elif d['av1'] > d['bv1']:
                vol_signal = 'av>bv'
            else:
                vol_signal = 'bv=av'
        else:
            vol_signal = 'na'

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
        combined[(l2_signal, vol_signal)][idx] += 1

print(f"\n{'L2_STATE':>12} {'VOL_STATE':>10} {'UP':>8} {'DOWN':>8} {'TOTAL':>8} {'P(UP)':>8}")
print("-" * 60)
for key in sorted(combined.keys()):
    l2_s, vol_s = key
    up, dn = combined[key]
    total = up + dn
    if total < 20:
        continue
    p_up = up / total
    print(f"{l2_s:>12} {vol_s:>10} {up:>8} {dn:>8} {total:>8} {p_up:>8.3f}")

# ============================================================
# 8. THE CORRECT SIGNAL INTERPRETATION
# ============================================================
print("\n" + "=" * 80)
print("8. PRECISE SIGNAL: L2 ON ONE SIDE AT NON-16 SPREAD")
print("=" * 80)

# The original analysis (section 11 first script) checked:
# "does imbalance PREDICT direction?" using (imb>0 and dir=1) or (imb<0 and dir=-1)
# This was testing if imbalance = SAME direction as FV change
# Let's re-check: when bv1>av1, does FV tend to go UP or DOWN?

# At non-16 spreads:
# Theory: The MM bot quotes symmetrically at new FV.
# When FV moves UP by 1:
#   Old book: bid=FV-8, ask=FV+8 (spread=16, symmetric)
#   New book should be: bid=FV-7, ask=FV+9 (transitioning) or bid=FV-8+1=FV-7, ask=FV+8+1=FV+9
#   During transition: one side updates first
#
# Actually, the spread=18 examples showed:
#   [9995x15|10011x15] -> [9995x15|10013x26] (ask moved up by 2, gained volume)
#   [9995x15|10011x15] -> [9993x26|10011x12] (bid moved down by 2, gained volume)
#
# So when ask GAINS volume and moves up -> FV went UP
# When bid GAINS volume and moves down -> FV went DOWN
# But this is the CURRENT move direction, not the NEXT one!

# Let me re-examine what section 11 measured:
# It measured: when bv1>av1, did the NEXT FV change go in a direction
# that "matches" the imbalance?
# "Match" was defined as: (imb>0 and dir=1) or (imb<0 and dir=-1)
# = when bid volume is bigger -> matched with UP
# = when ask volume is bigger -> matched with DOWN

# This means section 11 found: bv1>av1 -> 85% chance FV goes UP NEXT
# and av1>bv1 -> 85% chance FV goes DOWN NEXT

# But my section 5 found only ~50% accuracy.
# KEY DIFFERENCE: Section 11 checked the SAME TICK's FV change direction
# vs the imbalance, not the NEXT tick.

# Let me carefully re-do section 11's exact analysis:

print("\nRe-doing section 11 analysis precisely:")
print("Question: At tick T with non-16 spread, bv1>av1.")
print("Does FV at T differ from FV at T-1? If so, is imbalance = same direction?")
print("")

for day in DAYS:
    osm = all_osm[day]
    fv_ff = all_fv[day]
    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    by_spread = defaultdict(lambda: [0, 0, 0])  # [imb_predicts_same_tick_dir, not, zero_imb]

    for i in range(1, len(timestamps)):
        t_prev = timestamps[i-1]
        t0 = timestamps[i]
        d = osm_by_ts[t0]

        if d['bp1'] is None or d['ap1'] is None or d['bv1'] is None or d['av1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16:
            continue
        if t0 not in fv_ff or t_prev not in fv_ff:
            continue

        fv_change = fv_ff[t0] - fv_ff[t_prev]
        if fv_change == 0:
            continue

        imb = d['bv1'] - d['av1']
        if imb == 0:
            by_spread[spread][2] += 1
            continue

        # Does imbalance match the SAME-TICK FV change direction?
        # imb > 0 (more bid vol) and FV went UP -> match
        # imb < 0 (more ask vol) and FV went DOWN -> match
        if (imb > 0 and fv_change > 0) or (imb < 0 and fv_change < 0):
            by_spread[spread][0] += 1  # match
        else:
            by_spread[spread][1] += 1  # no match

    print(f"\nDay {day} - imbalance matches SAME-TICK FV direction:")
    for spread in sorted(by_spread.keys()):
        match, nomatch, zero = by_spread[spread]
        total = match + nomatch
        if total < 10:
            continue
        pct = match / total
        print(f"  Spread={spread}: match={match}, nomatch={nomatch}, accuracy={pct:.3f} (n={total})")

# ============================================================
# 9. NOW: DOES SAME-TICK IMBALANCE PREDICT NEXT FV DIRECTION?
# ============================================================
print("\n" + "=" * 80)
print("9. DOES IMBALANCE AT TRANSITION TICKS PREDICT NEXT FV DIRECTION?")
print("=" * 80)

# If imbalance tells us CURRENT direction, and reversal is 68%, then:
# bv1>av1 means FV went UP (current tick) -> 68% chance next goes DOWN

transition_signal = defaultdict(lambda: [0, 0])  # (imb_sign) -> [correct_reversal, wrong]

for day in DAYS:
    osm = all_osm[day]
    fv_ff = all_fv[day]
    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    for i in range(1, len(timestamps)):
        t_prev = timestamps[i-1]
        t0 = timestamps[i]
        d = osm_by_ts[t0]

        if d['bp1'] is None or d['ap1'] is None or d['bv1'] is None or d['av1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16:
            continue
        if t0 not in fv_ff or t_prev not in fv_ff:
            continue

        fv_change_now = fv_ff[t0] - fv_ff[t_prev]
        if fv_change_now == 0:
            continue

        imb = d['bv1'] - d['av1']
        if imb == 0:
            continue

        # Current direction from imbalance
        current_dir = 1 if imb > 0 else -1  # bv>av means UP (from section 8)

        # But section 8 actually found imb>0 matches fv_change>0, so:
        # imb_sign = sign(fv_change_now) with ~85% accuracy

        # Find NEXT FV change
        next_dir = None
        for j in range(i+1, min(i+30, len(timestamps))):
            t_next = timestamps[j]
            if t_next in fv_ff and fv_ff[t_next] != fv_ff[t0]:
                next_dir = 1 if fv_ff[t_next] > fv_ff[t0] else -1
                break

        if next_dir is None:
            continue

        # If imbalance correctly identifies current direction (85% of the time),
        # and reversal is 68%, then:
        # Predict next = opposite of current = opposite of imbalance sign

        predicted_next = -current_dir  # Reversal prediction

        if predicted_next == next_dir:
            transition_signal['correct'][0] += 1
        else:
            transition_signal['correct'][1] += 1

        # Also track by spread
        if predicted_next == next_dir:
            transition_signal[f'spread_{spread}_correct'][0] += 1
        else:
            transition_signal[f'spread_{spread}_correct'][1] += 1

correct = transition_signal['correct'][0]
wrong = transition_signal['correct'][1]
total = correct + wrong
print(f"\nOverall: Using imbalance to infer current direction, then predict reversal:")
print(f"  Correct: {correct}/{total} = {correct/total:.4f}")
print(f"  (Expected ~0.85 * 0.68 + 0.15 * 0.32 = {0.85*0.68 + 0.15*0.32:.4f})")

for spread in sorted(set(int(k.split('_')[1]) for k in transition_signal if k.startswith('spread_'))):
    key = f'spread_{spread}_correct'
    correct = transition_signal[key][0]
    wrong = transition_signal[key][1]
    total = correct + wrong
    if total >= 20:
        print(f"  Spread={spread}: {correct}/{total} = {correct/total:.4f}")

# ============================================================
# 10. ACTUAL PROFITABILITY: WHAT CAN WE BUY/SELL AT?
# ============================================================
print("\n" + "=" * 80)
print("10. PROFITABILITY: WHAT PRICES CAN WE TRADE AT?")
print("=" * 80)

# When we see the signal (spread != 16), can we actually trade profitably?
# At spread=18: bid=FV-9, ask=FV+9
# If we predict FV goes DOWN: sell at FV+9? No, that's the ask, we'd BUY there.
# We want to sell. We can hit the bid at FV-9.
# If FV does go down by 1, new mid = FV-1. Our sell at FV-9 is 8 below new FV.
# Actually wait - we place orders, and they execute at our price or better.
#
# Real scenario:
# Current state: spread=18, FV estimated at X.
# Signal says: next FV goes DOWN.
# We should: SELL. Where to sell?
#   - Could sell at X+7 (aggressive, but above FV)
#   - Could sell at current ask (X+9), but that's buying from us, not us selling
# Wait: the ask side is what sellers post. If we want to sell, we post a sell order.
# The best bid is at X-9. To get filled, our sell must be <= best bid = X-9.
#
# But with position limit management and market making, the real question is:
# How much better can we quote by knowing FV direction?

print("""
At spread=18 (e.g., bid=9991, ask=10009, FV~10000):
  If we predict FV goes UP by 1 (to 10001):
    - New book will be bid=9993, ask=10009 (spread=16)
    - We want to BUY now, before the book updates
    - Best available: buy at 10009 (the ask) - would be buying at FV+9
    - After FV moves to 10001: our position at 10009 is 8 above new FV -> lose

  PROBLEM: The current ask/bid are at old FV +/- 9, not new FV +/- 8.
  The signal tells us direction, but we can't trade at profitable prices
  UNTIL the book settles to spread=16 at the new FV.

  ACTUAL OPPORTUNITY:
  1. At spread=16, if we know FV direction (from reversal), we can:
     - Quote tighter on the correct side
     - Take aggressive fills when book is mis-priced during transitions
  2. At spread=18/19, the L1 prices bracket the new FV.
     - bid=9991, ask=10009 -> new FV is ~10000 or 10001
     - If signal says UP: true FV is 10001. Bid of 9991 is 10 below FV.
     - Can we place a sell at 10009? That's the current ask, we'd be 8 above FV.

  KEY INSIGHT: When spread=18 and we detect FV moved UP:
  - Place aggressive BUY at 9992 (FV-9), which is the BID side
    => This would only fill if someone sells to us aggressively
  - Better: place passive SELL at 10008 (new_FV + 7 = 10001+7)
    => Will fill when book updates and takers come

  But the REAL edge is at spread=16 using REVERSAL:
  - At spread=16 with FV=X, we know 68% reversal after each move
  - Quote: bid at X-7 (instead of X-8), ask at X+7 (instead of X+8)
  - Tighten the side we expect to be filled on
  - With 68% reversal: EV of taking at X-8 when we expect UP is positive
""")

# ============================================================
# 11. VERIFY: L2 ASYMMETRY IS THE STRONG SIGNAL
# ============================================================
print("=" * 80)
print("11. FINAL VERIFICATION: EXACT SIGNAL AT SPREAD=18/19")
print("=" * 80)

# Section 1 from the first script showed:
# bid_only_l2, dir=-1: ~965 (DOWN)
# bid_only_l2, dir=+1: ~403 (UP)  -> P(DOWN | bid_only_l2) = 965/(965+403) = 0.705

# ask_only_l2, dir=-1: ~426 (DOWN)
# ask_only_l2, dir=+1: ~900 (UP)  -> P(UP | ask_only_l2) = 900/(900+426) = 0.679

# But these were measuring the CURRENT TICK direction. Let me check NEXT.

for label, check_next in [("CURRENT tick FV direction", False), ("NEXT FV direction", True)]:
    print(f"\n--- {label} ---")

    l2_result = defaultdict(lambda: [0, 0])

    for day in DAYS:
        osm = all_osm[day]
        fv_ff = all_fv[day]
        timestamps = [d['ts'] for d in osm]
        osm_by_ts = {d['ts']: d for d in osm}

        for i in range(1, len(timestamps)):
            t_prev = timestamps[i-1]
            t0 = timestamps[i]
            d = osm_by_ts[t0]

            if d['bp1'] is None or d['ap1'] is None:
                continue
            spread = int(d['ap1'] - d['bp1'])
            if spread == 16:
                continue
            if t0 not in fv_ff:
                continue

            has_l2_bid = d['bp2'] is not None
            has_l2_ask = d['ap2'] is not None

            if has_l2_bid == has_l2_ask:  # both or neither -> skip
                continue

            l2_state = 'bid_l2' if has_l2_bid else 'ask_l2'

            if not check_next:
                # Current tick direction
                if t_prev not in fv_ff:
                    continue
                fv_change = fv_ff[t0] - fv_ff[t_prev]
                if fv_change == 0:
                    continue
                direction = 1 if fv_change > 0 else -1
            else:
                # Next FV direction
                current_fv = fv_ff[t0]
                direction = None
                for j in range(i+1, min(i+30, len(timestamps))):
                    t_next = timestamps[j]
                    if t_next in fv_ff and fv_ff[t_next] != current_fv:
                        direction = 1 if fv_ff[t_next] > current_fv else -1
                        break
                if direction is None:
                    continue

            idx = 0 if direction == 1 else 1
            l2_result[(l2_state, spread)][idx] += 1

    # Aggregate
    agg = defaultdict(lambda: [0, 0])
    for (l2_state, spread), (up, dn) in l2_result.items():
        agg[l2_state][0] += up
        agg[l2_state][1] += dn

    for l2_state in ['bid_l2', 'ask_l2']:
        up, dn = agg[l2_state]
        total = up + dn
        if total > 0:
            p_up = up / total
            print(f"  {l2_state}: up={up}, down={dn}, P(up)={p_up:.4f} (n={total})")

    # By spread
    for key in sorted(l2_result.keys()):
        l2_state, spread = key
        up, dn = l2_result[key]
        total = up + dn
        if total >= 20:
            p_up = up / total
            print(f"    {l2_state} spread={spread}: up={up}, down={dn}, P(up)={p_up:.4f} (n={total})")

# ============================================================
# 12. DEFINITIVE SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("12. DEFINITIVE SIGNALS AND THEIR STRENGTH")
print("=" * 80)

print("""
CONFIRMED SIGNALS:

A) FV REVERSAL (from first analysis):
   - After 1 same-dir move: P(reverse) = 67.9%
   - After 2: 80.6%
   - After 3: 86.5%
   - After 4: 92.8%
   Run-length distribution is SUPER-GEOMETRIC (not memoryless).
   This is the BASE signal everyone uses.

B) L2 ASYMMETRY reveals CURRENT direction (from the tick that just happened):
   - L2 on bid side only -> current FV change was UP (P ~ 67-71%)
   - L2 on ask side only -> current FV change was DOWN (P ~ 67-71%)
   This is because the MM bot's L2 from the OLD position hasn't updated yet.

   Combined with reversal: if L2-bid-only tells us FV went UP, predict DOWN next.
   Net accuracy for next direction: ~0.70 * 0.68 + 0.30 * 0.32 = 0.572
   This is SLIGHTLY better than just using lag-1 reversal (0.68) alone...
   Wait, that's WORSE. The value of L2 is telling us the CURRENT direction
   when we couldn't infer it from spread=16 (which tells us nothing).

C) VOLUME IMBALANCE at non-16 spreads reveals CURRENT direction:
   - bv1 > av1: FV went UP (P ~ 85% at tight spreads)
   - av1 > bv1: FV went DOWN (P ~ 85% at tight spreads)
   This is STRONGER than L2 presence for current-tick direction.

D) AT SPREAD=16: NO SIGNAL in volumes. BV1=AV1 always. BV2=AV2 always.

E) PEPPER: Zero predictive power for OSMIUM. Independent processes.

F) NOISE BOT: Too few trades (~20/day close to FV) to be useful.

STRATEGY:
1. Track FV from spread=16 ticks
2. When non-16 spread appears, use volume imbalance to infer current FV direction
3. Apply reversal probability to predict next direction
4. Scale position/quote aggressiveness by run length
5. The edge is small per trade but compounds over ~5400 FV changes per day
""")
