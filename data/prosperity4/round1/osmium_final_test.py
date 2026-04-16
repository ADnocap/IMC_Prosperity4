"""
OSMIUM: Final definitive tests
1. Does imbalance at non-16 tell us current TRUE FV (not visible in spread)?
2. At spread=16, does previous direction (from last non-16 imbalance) predict?
3. Can we combine all signals into an expected edge per tick?
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

def sf(v): return float(v) if v and v != '' else None
def si(v): return int(v) if v and v != '' else None

def extract_osm(prices):
    data = []
    for row in prices:
        if row['product'] != PRODUCT:
            continue
        data.append({
            'ts': int(row['timestamp']),
            'bp1': sf(row['bid_price_1']), 'bv1': si(row['bid_volume_1']),
            'bp2': sf(row['bid_price_2']), 'bv2': si(row['bid_volume_2']),
            'ap1': sf(row['ask_price_1']), 'av1': si(row['ask_volume_1']),
            'ap2': sf(row['ask_price_2']), 'av2': si(row['ask_volume_2']),
        })
    return data

# ============================================================
# TEST 1: At non-16 spreads, does imbalance resolve FV ambiguity?
# ============================================================
print("=" * 80)
print("TEST 1: IMBALANCE RESOLVES FV AT NON-16 SPREADS")
print("=" * 80)

# At spread=18: mid = FV - 0.5 or FV + 0.5 (FV is between bid+9 and ask-9)
# If bid=9991, ask=10009: mid=10000. True FV is either 10000 or 10001
# (since FV moved ±1 from old FV which was an integer)
#
# If FV=10001 (moved up): ask=FV+8=10009, bid should be FV-8=9993 but it's still 9991
#   -> ask is correct (moved), bid is lagging -> av1 should be "new" volume
# If FV=9999 (moved down): bid=FV-8=9991 (correct), ask should be FV+8=10007 but it's 10009
#   -> bid is correct (moved), ask is lagging -> bv1 should be "new" volume
#
# The side that MOVED gets the L2 from the new position, the lagging side has old L1 volume.
#
# But which side has MORE volume? Let's check against the NEXT spread=16 FV.

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    # Get exact FV from spread-16 ticks only
    exact_fv = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    timestamps = [d['ts'] for d in osm]
    osm_by_ts = {d['ts']: d for d in osm}

    # For each non-16 tick, find the PREVIOUS and NEXT spread-16 FVs
    s16_times = sorted(exact_fv.keys())

    results = Counter()  # (imb_sign, fv_went) -> count

    for i, d in enumerate(osm):
        ts = d['ts']
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16:
            continue
        if d['bv1'] is None or d['av1'] is None:
            continue
        if d['bv1'] == d['av1']:
            continue

        mid = (d['bp1'] + d['ap1']) / 2

        # Find previous spread-16 FV
        prev_fv = None
        for st in s16_times:
            if st < ts:
                prev_fv = exact_fv[st]
            else:
                break

        # Find next spread-16 FV
        next_fv = None
        for st in s16_times:
            if st > ts:
                next_fv = exact_fv[st]
                break

        if prev_fv is None or next_fv is None:
            continue

        imb_sign = 'bv_big' if d['bv1'] > d['av1'] else 'av_big'

        # Did FV go up or down from prev to next?
        if next_fv > prev_fv:
            fv_went = 'up'
        elif next_fv < prev_fv:
            fv_went = 'down'
        else:
            fv_went = 'same'

        results[(imb_sign, fv_went)] += 1

    print(f"\nDay {day}:")
    print(f"  {'IMB':>8} {'FV_WENT':>8} {'COUNT':>8}")
    for key in sorted(results.keys()):
        print(f"  {key[0]:>8} {key[1]:>8} {results[key]:>8}")

    # Summary
    bv_big_up = results[('bv_big', 'up')]
    bv_big_dn = results[('bv_big', 'down')]
    bv_big_same = results[('bv_big', 'same')]
    av_big_up = results[('av_big', 'up')]
    av_big_dn = results[('av_big', 'down')]
    av_big_same = results[('av_big', 'same')]

    bv_total = bv_big_up + bv_big_dn + bv_big_same
    av_total = av_big_up + av_big_dn + av_big_same

    if bv_total > 0:
        print(f"  bv_big: P(next_fv_up) = {bv_big_up/bv_total:.3f}, P(down) = {bv_big_dn/bv_total:.3f}, P(same) = {bv_big_same/bv_total:.3f}")
    if av_total > 0:
        print(f"  av_big: P(next_fv_up) = {av_big_up/av_total:.3f}, P(down) = {av_big_dn/av_total:.3f}, P(same) = {av_big_same/av_total:.3f}")

# ============================================================
# TEST 2: At spread=18, which side has more volume, and what
#          happened between the previous and next spread-16 FVs?
# ============================================================
print("\n" + "=" * 80)
print("TEST 2: SPREAD=18/19 IMBALANCE vs PREVIOUS-TO-NEXT FV CHANGE")
print("=" * 80)

for spread_target in [18, 19]:
    for day in DAYS:
        prices = load_prices(day)
        osm = extract_osm(prices)

        exact_fv = {}
        for d in osm:
            if d['bp1'] is not None and d['ap1'] is not None:
                if d['ap1'] - d['bp1'] == 16:
                    exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

        s16_times = sorted(exact_fv.keys())
        results = Counter()

        for d in osm:
            ts = d['ts']
            if d['bp1'] is None or d['ap1'] is None:
                continue
            if int(d['ap1'] - d['bp1']) != spread_target:
                continue
            if d['bv1'] is None or d['av1'] is None:
                continue
            if d['bv1'] == d['av1']:
                continue

            # Find bracketing spread-16 FVs
            prev_fv = None
            next_fv = None
            prev_ts = None
            next_ts = None
            for st in s16_times:
                if st < ts:
                    prev_fv = exact_fv[st]
                    prev_ts = st
                elif st > ts and next_fv is None:
                    next_fv = exact_fv[st]
                    next_ts = st

            if prev_fv is None or next_fv is None:
                continue

            imb = 'bv_big' if d['bv1'] > d['av1'] else 'av_big'
            fv_change = next_fv - prev_fv

            if fv_change > 0:
                results[(imb, 'fv_up')] += 1
            elif fv_change < 0:
                results[(imb, 'fv_down')] += 1
            else:
                results[(imb, 'fv_same')] += 1

        # Print only if data exists
        total = sum(results.values())
        if total > 0:
            print(f"\n  Spread={spread_target}, Day {day} ({total} samples):")
            for key in sorted(results.keys()):
                print(f"    {key}: {results[key]}")

            # Key ratio: does bv_big predict fv_up or fv_down?
            bv_up = results[('bv_big', 'fv_up')]
            bv_dn = results[('bv_big', 'fv_down')]
            bv_same = results[('bv_big', 'fv_same')]
            av_up = results[('av_big', 'fv_up')]
            av_dn = results[('av_big', 'fv_down')]
            av_same = results[('av_big', 'fv_same')]

            bv_t = bv_up + bv_dn + bv_same
            av_t = av_up + av_dn + av_same
            if bv_t > 0:
                print(f"    bv_big: P(up)={bv_up/bv_t:.3f}, P(dn)={bv_dn/bv_t:.3f}, P(same)={bv_same/bv_t:.3f} (n={bv_t})")
            if av_t > 0:
                print(f"    av_big: P(up)={av_up/av_t:.3f}, P(dn)={av_dn/av_t:.3f}, P(same)={av_same/av_t:.3f} (n={av_t})")

# ============================================================
# TEST 3: The DEFINITIVE signal: at spread=18, does bv1>av1
#          tell us the DIRECTION of the most recent FV step?
# ============================================================
print("\n" + "=" * 80)
print("TEST 3: AT SPREAD=18, WHICH SIDE HAS MORE VOLUME TELLS US CURRENT DIRECTION")
print("=" * 80)

# This is the definitive test. At spread=18:
# The mid = (bid+ask)/2. We compare to the PREVIOUS spread-16 FV.
# If mid > prev_fv: FV likely went up.
# If mid < prev_fv: FV likely went down.
# Does the volume imbalance agree?

for spread_target in [18, 19, 21]:
    agree_bv_up = 0
    agree_av_dn = 0
    disagree = 0
    total_samples = 0

    for day in DAYS:
        prices = load_prices(day)
        osm = extract_osm(prices)

        exact_fv = {}
        for d in osm:
            if d['bp1'] is not None and d['ap1'] is not None:
                if d['ap1'] - d['bp1'] == 16:
                    exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

        s16_times = sorted(exact_fv.keys())

        for d in osm:
            ts = d['ts']
            if d['bp1'] is None or d['ap1'] is None:
                continue
            if int(d['ap1'] - d['bp1']) != spread_target:
                continue
            if d['bv1'] is None or d['av1'] is None:
                continue
            if d['bv1'] == d['av1']:
                continue

            mid = (d['bp1'] + d['ap1']) / 2

            # Find previous spread-16 FV
            prev_fv = None
            for st in s16_times:
                if st < ts:
                    prev_fv = exact_fv[st]
                else:
                    break

            if prev_fv is None:
                continue

            mid_vs_fv = mid - prev_fv  # positive = FV went up

            if mid_vs_fv > 0:
                # FV went up
                if d['av1'] > d['bv1']:  # ask has more vol = ask side is new
                    agree_av_dn += 1  # av_big when mid>fv means ask side is the "new" side
                else:
                    disagree += 1
            elif mid_vs_fv < 0:
                if d['bv1'] > d['av1']:
                    agree_bv_up += 1
                else:
                    disagree += 1
            total_samples += 1

    print(f"\nSpread={spread_target} ({total_samples} samples):")
    print(f"  mid>prev_fv AND av1>bv1: {agree_av_dn}")
    print(f"  mid<prev_fv AND bv1>av1: {agree_bv_up}")
    print(f"  Disagree: {disagree}")
    if total_samples > 0:
        agree_total = agree_av_dn + agree_bv_up
        print(f"  Agreement rate: {agree_total}/{agree_total+disagree} = {agree_total/(agree_total+disagree):.3f}")

# ============================================================
# TEST 4: ACTUAL ACTIONABLE SIGNAL - AT SPREAD=18, INFER FV
#          DIRECTION, PREDICT NEXT CHANGE, AND COMPUTE EDGE
# ============================================================
print("\n" + "=" * 80)
print("TEST 4: ACTIONABLE SIGNAL AND EXPECTED EDGE")
print("=" * 80)

# Step 1: At spread=18/19, use imbalance to determine current FV direction
# Step 2: Apply reversal probability to predict next direction
# Step 3: Compute: if we place an order in the predicted direction, what edge?

total_preds = 0
correct_preds = 0
wrong_preds = 0

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    exact_fv = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    s16_times = sorted(exact_fv.keys())

    for d in osm:
        ts = d['ts']
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread not in [18, 19]:
            continue
        if d['bv1'] is None or d['av1'] is None:
            continue
        if d['bv1'] == d['av1']:
            continue

        mid = (d['bp1'] + d['ap1']) / 2

        # Find previous and next spread-16 FVs
        prev_fv = None
        next_fv = None
        next_next_fv = None
        found_next = False
        for st in s16_times:
            if st < ts:
                prev_fv = exact_fv[st]
            elif st > ts:
                if not found_next:
                    next_fv = exact_fv[st]
                    found_next = True
                else:
                    if exact_fv[st] != next_fv:
                        next_next_fv = exact_fv[st]
                        break

        if prev_fv is None or next_fv is None:
            continue

        # Current direction from mid vs prev_fv
        if mid > prev_fv:
            current_dir = 1  # FV went up
        elif mid < prev_fv:
            current_dir = -1
        else:
            continue  # Can't tell

        # Predict NEXT = reversal of current
        predicted_next = -current_dir

        # Check: what actually happened?
        # The "next" FV change is from next_fv to next_next_fv
        if next_next_fv is not None:
            actual_next = 1 if next_next_fv > next_fv else -1
            if predicted_next == actual_next:
                correct_preds += 1
            else:
                wrong_preds += 1
            total_preds += 1

print(f"\nReversal prediction from spread=18/19:")
print(f"  Correct: {correct_preds}/{total_preds} = {correct_preds/total_preds:.4f}" if total_preds > 0 else "  No data")
print(f"  (Expected: ~68% from reversal alone)")

# ============================================================
# TEST 5: PURE REVERSAL ACCURACY (no imbalance needed)
# ============================================================
print("\n" + "=" * 80)
print("TEST 5: PURE REVERSAL (from spread-16 exact FV only)")
print("=" * 80)

total_exact = 0
correct_exact = 0

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    exact_fv = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    s16_times = sorted(exact_fv.keys())

    # Build chain of FV changes (from spread-16 only)
    changes = []
    for i in range(1, len(s16_times)):
        diff = exact_fv[s16_times[i]] - exact_fv[s16_times[i-1]]
        if diff != 0:
            changes.append(diff)

    # Predict next = reversal of previous
    for i in range(1, len(changes)):
        predicted = -changes[i-1]  # reversal
        actual = changes[i]

        # Just check sign
        if (predicted > 0 and actual > 0) or (predicted < 0 and actual < 0):
            correct_exact += 1
        total_exact += 1

print(f"Pure reversal accuracy (spread-16 changes only): {correct_exact}/{total_exact} = {correct_exact/total_exact:.4f}")

# ============================================================
# TEST 6: DOES KNOWING THE TRANSITION TICK (non-16 spread) HELP
#          US PREDICT EARLIER THAN JUST WAITING FOR SPREAD=16?
# ============================================================
print("\n" + "=" * 80)
print("TEST 6: TIME ADVANTAGE FROM NON-16 SPREAD DETECTION")
print("=" * 80)

# When FV changes, the sequence is typically:
# spread=16 (old FV) -> spread=18/19 (transition) -> spread=16 (new FV)
# How many ticks between the non-16 detection and the new spread=16?

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    # Find all transitions from spread=16 to non-16
    delays = []
    for i in range(len(osm)):
        d = osm[i]
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread != 16:
            # Find next spread=16
            for j in range(i+1, min(i+30, len(osm))):
                d2 = osm[j]
                if d2['bp1'] is not None and d2['ap1'] is not None:
                    if int(d2['ap1'] - d2['bp1']) == 16:
                        delays.append(d2['ts'] - d['ts'])
                        break

    if delays:
        print(f"\nDay {day}: Delay from non-16 to next spread=16:")
        delay_counter = Counter(delays)
        for delay in sorted(delay_counter.keys())[:10]:
            print(f"  {delay}ms: {delay_counter[delay]} ({100*delay_counter[delay]/len(delays):.1f}%)")

# ============================================================
# TEST 7: BID/ASK PRICE POSITION AT SPREAD=18 vs EXACT FV
# ============================================================
print("\n" + "=" * 80)
print("TEST 7: EXACT PRICE STRUCTURE AT SPREAD=18")
print("=" * 80)

# At spread=18 with prev_fv known:
# If FV went UP by 1: new FV = prev_fv+1
#   Ask should be new_fv+8 = prev_fv+9
#   Bid should be new_fv-8 = prev_fv-7
#   But we see bid=prev_fv-9, ask=prev_fv+9 (spread=18)
#   -> bid is 2 below expected, ask is at expected
#   -> bid hasn't updated yet!
# If FV went DOWN by 1: new FV = prev_fv-1
#   Bid should be new_fv-8 = prev_fv-9
#   Ask should be new_fv+8 = prev_fv+7
#   But we see bid=prev_fv-9, ask=prev_fv+9 (spread=18)
#   -> ask is 2 above expected, bid is at expected
#   -> ask hasn't updated yet!

for day in [DAYS[0]]:
    prices = load_prices(day)
    osm = extract_osm(prices)

    exact_fv = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    s16_times = sorted(exact_fv.keys())

    print(f"\nDay {day}: Spread=18 examples with exact prev/next FV:")
    count = 0
    for d in osm:
        ts = d['ts']
        if d['bp1'] is None or d['ap1'] is None:
            continue
        if int(d['ap1'] - d['bp1']) != 18:
            continue

        # Find prev and next spread-16 FVs
        prev_fv = None
        next_fv = None
        for st in s16_times:
            if st < ts:
                prev_fv = exact_fv[st]
            elif st > ts and next_fv is None:
                next_fv = exact_fv[st]
                break

        if prev_fv is None or next_fv is None:
            continue

        bid_off_prev = int(d['bp1']) - prev_fv
        ask_off_prev = int(d['ap1']) - prev_fv
        fv_change = next_fv - prev_fv

        bv = d['bv1'] or 0
        av = d['av1'] or 0
        imb = 'bv>av' if bv > av else ('av>bv' if av > bv else 'eq')

        if count < 30:
            print(f"  t={ts}: bid={int(d['bp1'])}({bid_off_prev:+d}) ask={int(d['ap1'])}({ask_off_prev:+d}) "
                  f"bv={bv} av={av} {imb} | prev_fv={prev_fv} next_fv={next_fv} fv_chg={fv_change:+d}")
        count += 1

    print(f"  ... total {count} cases")

# ============================================================
# TEST 8: WHERE IS THE EDGE FOR MARKET MAKING?
# ============================================================
print("\n" + "=" * 80)
print("TEST 8: EDGE FOR MARKET MAKING")
print("=" * 80)

print("""
Key numbers for a market making strategy:

1. FV changes ~5400 times per day (every ~183ms average)
2. At spread=16 (58% of ticks), book is symmetric, no edge in volumes
   -> Use reversal of last known direction to skew quotes
   -> Reversal probability: 68% after 1 move, 81% after 2, etc.

3. At spread=18/19 (23% of ticks), FV just changed:
   -> Volume imbalance tells you WHICH DIRECTION FV just moved
   -> The side with MORE volume = the side that MOVED (new position)
   -> The side with LESS volume = lagging side (old position)
   -> This gives you the TRUE current FV with ~85% confidence
   -> Combined with 68% reversal: predict next direction ~58% of time

4. At tight spreads 5-13 (8% of ticks), aggressive bot is present:
   -> L2 and volume patterns indicate direction
   -> Can potentially take the aggressive side

5. At one-sided book (8%), the absent side means strong directional move
   -> Only ask visible: FV just dropped significantly
   -> Only bid visible: FV just rose significantly

MARKET MAKING EDGE:
- At spread=16: bid at FV-7, ask at FV+7 (tighter than MM bot's FV-8/FV+8)
- Skew based on reversal: if last move was UP, offer more on ask side
  (expect DOWN = our bid gets filled = we want to be net neutral/short)
- At non-16: infer true FV from imbalance, place orders at better prices
- Expected edge: ~1-2 per trade on ~50% of fills = ~500-1000 per day
""")

# ============================================================
# TEST 9: VERIFY BV1=AV1 ALWAYS AT SPREAD=16
# ============================================================
print("=" * 80)
print("TEST 9: IS BV1 TRULY ALWAYS EQUAL TO AV1 AT SPREAD=16?")
print("=" * 80)

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    asymmetric_at_16 = 0
    symmetric_at_16 = 0
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if int(d['ap1'] - d['bp1']) == 16:
                if d['bv1'] != d['av1']:
                    asymmetric_at_16 += 1
                else:
                    symmetric_at_16 += 1

    print(f"  Day {day}: symmetric={symmetric_at_16}, asymmetric={asymmetric_at_16}")

# ============================================================
# TEST 10: NON-16 IMBALANCE -> INFER DIRECTION -> PREDICT NEXT -> VERIFY
# ============================================================
print("\n" + "=" * 80)
print("TEST 10: FULL PIPELINE: Non-16 imbalance -> infer dir -> reversal -> verify")
print("=" * 80)

# At each non-16 spread with bv1 != av1:
# 1. Infer current direction: bv1>av1 -> UP (because bid side moved/has more vol)
# 2. But TEST 3 showed: bv1>av1 at spread=18 when mid>prev_fv AND
#    av1>bv1 agrees with mid>prev_fv. Let me check the sign again.

# Actually: at spread=18, TEST 3 found:
# "mid>prev_fv AND av1>bv1" agrees  = ask side has more vol when FV went up
# "mid<prev_fv AND bv1>av1" agrees  = bid side has more vol when FV went down
# Agreement rate = ~50% (which is useless)

# Wait, TEST 3 had a confusing setup. Let me redo simply:
# When FV goes UP: which side has more L1 volume?

fv_up_bv_big = 0
fv_up_av_big = 0
fv_dn_bv_big = 0
fv_dn_av_big = 0

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    exact_fv = {}
    for d in osm:
        if d['bp1'] is not None and d['ap1'] is not None:
            if d['ap1'] - d['bp1'] == 16:
                exact_fv[d['ts']] = int((d['bp1'] + d['ap1']) / 2)

    s16_times = sorted(exact_fv.keys())

    for d in osm:
        ts = d['ts']
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = int(d['ap1'] - d['bp1'])
        if spread == 16 or spread == 21:  # 21 is symmetric too
            continue
        if d['bv1'] is None or d['av1'] is None:
            continue
        if d['bv1'] == d['av1']:
            continue

        # Find prev spread=16 FV
        prev_fv = None
        for st in s16_times:
            if st < ts:
                prev_fv = exact_fv[st]
            else:
                break

        # Find next spread=16 FV
        next_fv = None
        for st in s16_times:
            if st > ts:
                next_fv = exact_fv[st]
                break

        if prev_fv is None or next_fv is None:
            continue

        fv_change = next_fv - prev_fv
        if fv_change == 0:
            continue

        if fv_change > 0:  # FV went up
            if d['bv1'] > d['av1']:
                fv_up_bv_big += 1
            else:
                fv_up_av_big += 1
        else:  # FV went down
            if d['bv1'] > d['av1']:
                fv_dn_bv_big += 1
            else:
                fv_dn_av_big += 1

print(f"\nWhen FV goes UP (prev_s16 to next_s16):")
total_up = fv_up_bv_big + fv_up_av_big
print(f"  bv1>av1: {fv_up_bv_big} ({100*fv_up_bv_big/total_up:.1f}%)")
print(f"  av1>bv1: {fv_up_av_big} ({100*fv_up_av_big/total_up:.1f}%)")

print(f"\nWhen FV goes DOWN (prev_s16 to next_s16):")
total_dn = fv_dn_bv_big + fv_dn_av_big
print(f"  bv1>av1: {fv_dn_bv_big} ({100*fv_dn_bv_big/total_dn:.1f}%)")
print(f"  av1>bv1: {fv_dn_av_big} ({100*fv_dn_av_big/total_dn:.1f}%)")

print(f"\nSo: bv1>av1 means FV went {'UP' if fv_up_bv_big > fv_dn_bv_big else 'DOWN'}")
print(f"    av1>bv1 means FV went {'UP' if fv_up_av_big > fv_dn_av_big else 'DOWN'}")

# ============================================================
# TEST 11: WHICH SIDE GETS MORE VOLUME? THE NEW OR OLD SIDE?
# ============================================================
print("\n" + "=" * 80)
print("TEST 11: AT SPREAD=18, DETAILED PRICE+VOLUME ANALYSIS")
print("=" * 80)

# Look at spread=18 transitions from spread=16
# When FV goes UP by 1: old_fv -> new_fv = old_fv+1
#   Old book: bid=old_fv-8, ask=old_fv+8
#   Transition options:
#     (a) bid stays, ask goes up by 2: bid=old_fv-8, ask=old_fv+10 -> spread=18
#     (b) ask stays, bid drops by 2: bid=old_fv-10, ask=old_fv+8 -> spread=18
# In case (a): ask moved -> ask is "new" side. Does it get more vol?

cases = defaultdict(lambda: [0, 0])  # (who_moved, new_side_bigger) -> count

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    for i in range(1, len(osm)):
        d0 = osm[i-1]
        d1 = osm[i]

        if d0['bp1'] is None or d0['ap1'] is None or d1['bp1'] is None or d1['ap1'] is None:
            continue
        if d0['bv1'] is None or d0['av1'] is None or d1['bv1'] is None or d1['av1'] is None:
            continue

        s0 = int(d0['ap1'] - d0['bp1'])
        s1 = int(d1['ap1'] - d1['bp1'])

        if s0 != 16 or s1 != 18:
            continue

        bid_chg = int(d1['bp1'] - d0['bp1'])
        ask_chg = int(d1['ap1'] - d0['ap1'])

        if ask_chg > 0 and bid_chg == 0:
            # Ask moved up -> FV went up -> ask is new side
            new_side_vol = d1['av1']
            old_side_vol = d1['bv1']
            cases[('ask_moved_up', 'new_bigger' if new_side_vol > old_side_vol else 'old_bigger')][0] += 1
        elif bid_chg < 0 and ask_chg == 0:
            # Bid moved down -> FV went down -> bid is new side
            new_side_vol = d1['bv1']
            old_side_vol = d1['av1']
            cases[('bid_moved_down', 'new_bigger' if new_side_vol > old_side_vol else 'old_bigger')][0] += 1
        elif ask_chg > 0 and bid_chg < 0:
            # Both moved
            cases[('both_moved', 'na')][0] += 1
        else:
            cases[('other', f'bid_chg={bid_chg},ask_chg={ask_chg}')][0] += 1

print("\n16->18 transitions:")
for key, counts in sorted(cases.items()):
    print(f"  {key}: {counts[0]}")

# More detail: what are the actual volume values?
print("\nDetailed volume analysis for 16->18 transitions:")

new_vols = []
old_vols = []

for day in DAYS:
    prices = load_prices(day)
    osm = extract_osm(prices)

    for i in range(1, len(osm)):
        d0 = osm[i-1]
        d1 = osm[i]

        if d0['bp1'] is None or d0['ap1'] is None or d1['bp1'] is None or d1['ap1'] is None:
            continue
        if d0['bv1'] is None or d0['av1'] is None or d1['bv1'] is None or d1['av1'] is None:
            continue

        s0 = int(d0['ap1'] - d0['bp1'])
        s1 = int(d1['ap1'] - d1['bp1'])

        if s0 != 16 or s1 != 18:
            continue

        bid_chg = int(d1['bp1'] - d0['bp1'])
        ask_chg = int(d1['ap1'] - d0['ap1'])

        if ask_chg > 0 and bid_chg == 0:
            # Ask moved: new side is ask
            new_vols.append(d1['av1'])
            old_vols.append(d1['bv1'])
        elif bid_chg < 0 and ask_chg == 0:
            # Bid moved: new side is bid
            new_vols.append(d1['bv1'])
            old_vols.append(d1['av1'])

if new_vols:
    print(f"  New side (moved) volume: mean={sum(new_vols)/len(new_vols):.1f}, min={min(new_vols)}, max={max(new_vols)}")
    print(f"  Old side (lagging) volume: mean={sum(old_vols)/len(old_vols):.1f}, min={min(old_vols)}, max={max(old_vols)}")

    # Volume distribution
    print(f"  New side volume distribution: {Counter(new_vols).most_common(10)}")
    print(f"  Old side volume distribution: {Counter(old_vols).most_common(10)}")

    # Ratio
    bigger = sum(1 for n, o in zip(new_vols, old_vols) if n > o)
    smaller = sum(1 for n, o in zip(new_vols, old_vols) if n < o)
    equal = sum(1 for n, o in zip(new_vols, old_vols) if n == o)
    print(f"  New side bigger: {bigger}, smaller: {smaller}, equal: {equal}")
    print(f"  P(new side has more volume) = {bigger/(bigger+smaller):.3f}")
