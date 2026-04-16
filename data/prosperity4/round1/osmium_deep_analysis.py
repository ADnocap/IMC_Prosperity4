"""
Comprehensive OSMIUM (ASH_COATED_OSMIUM) Hidden Pattern Analysis
================================================================
Investigates FV dynamics, book features, cross-asset signals, and determinism.
"""

import csv
import math
from collections import defaultdict, Counter

DATA_DIR = "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round1"
DAYS = [-2, -1, 0]
PRODUCT = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

# ============================================================
# DATA LOADING
# ============================================================
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

def safe_float(v):
    if v is None or v == '':
        return None
    return float(v)

def safe_int(v):
    if v is None or v == '':
        return None
    return int(v)

# ============================================================
# EXTRACT PER-PRODUCT DATA
# ============================================================
def extract_product_data(all_prices, product):
    """Extract time series for a single product."""
    data = []
    for row in all_prices:
        if row['product'] != product:
            continue
        ts = int(row['timestamp'])
        bp1 = safe_float(row['bid_price_1'])
        bv1 = safe_int(row['bid_volume_1'])
        bp2 = safe_float(row['bid_price_2'])
        bv2 = safe_int(row['bid_volume_2'])
        bp3 = safe_float(row['bid_price_3'])
        bv3 = safe_int(row['bid_volume_3'])
        ap1 = safe_float(row['ask_price_1'])
        av1 = safe_int(row['ask_volume_1'])
        ap2 = safe_float(row['ask_price_2'])
        av2 = safe_int(row['ask_volume_2'])
        ap3 = safe_float(row['ask_price_3'])
        av3 = safe_int(row['ask_volume_3'])
        mid = safe_float(row['mid_price'])
        data.append({
            'ts': ts, 'bp1': bp1, 'bv1': bv1, 'bp2': bp2, 'bv2': bv2,
            'bp3': bp3, 'bv3': bv3, 'ap1': ap1, 'av1': av1,
            'ap2': ap2, 'av2': av2, 'ap3': ap3, 'av3': av3, 'mid': mid,
        })
    return data

# ============================================================
# EXTRACT FV FROM SPREAD-16 STATES
# ============================================================
def extract_fv_series(osm_data):
    """
    FV is best extracted from spread=16 states where book is symmetric.
    FV = (best_bid + best_ask) / 2
    When spread != 16, FV is between observations.
    """
    fv_points = []  # (timestamp, fv)
    for d in osm_data:
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            if spread == 16:
                fv = (d['bp1'] + d['ap1']) / 2
                fv_points.append((d['ts'], fv))
    return fv_points

def extract_fv_full(osm_data):
    """
    Extract FV for every timestamp using spread-16 anchoring.
    For non-spread-16 ticks, infer from the closest spread-16 observation
    and whether current mid shifted.
    """
    # First get all spread-16 anchors
    anchors = extract_fv_series(osm_data)

    # Also try: for every tick, estimate FV from book
    all_fv = []
    last_fv = None
    for d in osm_data:
        ts = d['ts']
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            if spread == 16:
                fv = (d['bp1'] + d['ap1']) / 2
                last_fv = fv
                all_fv.append((ts, fv, 'exact'))
            elif spread == 17:
                # FV just moved - between two values
                # If ask moved up by 1 relative to symmetric: FV went up 0.5
                # Use mid but we know it's between two integer FVs
                mid = (d['bp1'] + d['ap1']) / 2
                all_fv.append((ts, mid, 'spread17'))
            elif spread == 18:
                mid = (d['bp1'] + d['ap1']) / 2
                all_fv.append((ts, mid, 'spread18'))
            elif spread == 21:
                # Wide spread - 3 levels visible sometimes
                mid = (d['bp1'] + d['ap1']) / 2
                all_fv.append((ts, mid, 'wide'))
            else:
                mid = (d['bp1'] + d['ap1']) / 2
                all_fv.append((ts, mid, f'spread{int(spread)}'))
        elif d['ap1'] is not None and d['bp1'] is None:
            all_fv.append((ts, None, 'ask_only'))
        elif d['bp1'] is not None and d['ap1'] is None:
            all_fv.append((ts, None, 'bid_only'))
        else:
            all_fv.append((ts, None, 'empty'))
    return all_fv, anchors

# ============================================================
# ANALYSIS
# ============================================================

print("=" * 80)
print("OSMIUM (ASH_COATED_OSMIUM) DEEP PATTERN ANALYSIS")
print("=" * 80)

# Load all data
all_osm = {}
all_pepper = {}
all_trades = {}
all_fv_anchors = {}
all_fv_full = {}

for day in DAYS:
    prices = load_prices(day)
    trades = load_trades(day)

    osm = extract_product_data(prices, PRODUCT)
    pep = extract_product_data(prices, PEPPER)
    osm_trades = [t for t in trades if t['symbol'] == PRODUCT]
    pep_trades = [t for t in trades if t['symbol'] == PEPPER]

    all_osm[day] = osm
    all_pepper[day] = pep
    all_trades[day] = {'osm': osm_trades, 'pep': pep_trades}

    fv_full, fv_anchors = extract_fv_full(osm)
    all_fv_anchors[day] = fv_anchors
    all_fv_full[day] = fv_full

# ============================================================
# 1. FV SEQUENCE AND STARTING VALUES
# ============================================================
print("\n" + "=" * 80)
print("1. FV SEQUENCE OVERVIEW (spread=16 anchors)")
print("=" * 80)

for day in DAYS:
    anchors = all_fv_anchors[day]
    fvs = [a[1] for a in anchors]
    print(f"\nDay {day}: {len(anchors)} spread-16 observations out of {len(all_osm[day])} total ticks")
    if fvs:
        print(f"  First FV: {fvs[0]} at t={anchors[0][0]}")
        print(f"  Last FV:  {fvs[-1]} at t={anchors[-1][0]}")
        print(f"  Min: {min(fvs)}, Max: {max(fvs)}, Range: {max(fvs) - min(fvs)}")

        # FV value distribution
        fv_counts = Counter(fvs)
        print(f"  Unique FV values: {len(fv_counts)}")

        # First 20 FV transitions
        changes = []
        for i in range(1, len(anchors)):
            diff = anchors[i][1] - anchors[i-1][1]
            if diff != 0:
                changes.append((anchors[i][0], diff, anchors[i][1]))
        print(f"  Total FV changes: {len(changes)}")
        if changes:
            print(f"  First 15 changes: {[(c[0], int(c[1]), int(c[2])) for c in changes[:15]]}")

# ============================================================
# 2. SPREAD DISTRIBUTION
# ============================================================
print("\n" + "=" * 80)
print("2. SPREAD DISTRIBUTION")
print("=" * 80)

for day in DAYS:
    spread_counts = Counter()
    for d in all_osm[day]:
        if d['bp1'] is not None and d['ap1'] is not None:
            s = int(d['ap1'] - d['bp1'])
            spread_counts[s] += 1
        elif d['bp1'] is None and d['ap1'] is not None:
            spread_counts['ask_only'] += 1
        elif d['bp1'] is not None and d['ap1'] is None:
            spread_counts['bid_only'] += 1
        else:
            spread_counts['empty'] += 1
    print(f"\nDay {day} spread distribution:")
    for s in sorted(spread_counts.keys(), key=lambda x: (isinstance(x, str), x)):
        print(f"  spread={s}: {spread_counts[s]} ({100*spread_counts[s]/len(all_osm[day]):.1f}%)")

# ============================================================
# 3. FV CHANGES - DERIVE INTEGER FV PATH
# ============================================================
print("\n" + "=" * 80)
print("3. INTEGER FV PATH RECONSTRUCTION")
print("=" * 80)

def reconstruct_integer_fv(osm_data):
    """
    Reconstruct integer FV path.
    spread=16 -> FV is midpoint (integer if both bid/ask are integers)
    FV moves in ±1 steps.
    """
    fv_path = []  # (timestamp, fv_int)
    last_fv = None

    for d in osm_data:
        ts = d['ts']
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            mid = (d['bp1'] + d['ap1']) / 2

            if spread == 16:
                fv = int(mid)
                last_fv = fv
                fv_path.append((ts, fv))
            elif last_fv is not None:
                # For non-16 spreads, FV is still one of the integer values
                # Use the mid as approximation, round to nearest integer
                # But constrain to be ±1 from last known FV
                candidates = [last_fv - 1, last_fv, last_fv + 1]
                best = min(candidates, key=lambda c: abs(c - mid))
                fv_path.append((ts, best))
                last_fv = best
            else:
                fv_path.append((ts, None))
        else:
            if last_fv is not None:
                fv_path.append((ts, last_fv))
            else:
                fv_path.append((ts, None))

    return fv_path

all_fv_int = {}
for day in DAYS:
    fv_int = reconstruct_integer_fv(all_osm[day])
    all_fv_int[day] = fv_int

    valid = [(ts, fv) for ts, fv in fv_int if fv is not None]
    if valid:
        print(f"\nDay {day}: {len(valid)} FV observations")
        print(f"  Start: FV={valid[0][1]} at t={valid[0][0]}")
        print(f"  End:   FV={valid[-1][1]} at t={valid[-1][0]}")

        # Count changes
        changes = []
        for i in range(1, len(valid)):
            diff = valid[i][1] - valid[i-1][1]
            if diff != 0:
                changes.append((valid[i][0], diff))

        ups = sum(1 for _, d in changes if d > 0)
        downs = sum(1 for _, d in changes if d < 0)
        print(f"  Changes: {len(changes)} (ups={ups}, downs={downs})")

        # FV at specific timestamps
        fv_dict = {ts: fv for ts, fv in valid}
        sample_ts = [0, 100, 1000, 5000, 50000, 99900]
        for t in sample_ts:
            if t in fv_dict:
                print(f"  FV at t={t}: {fv_dict[t]}")

# ============================================================
# 4. REVERSAL PROBABILITY BY RUN LENGTH
# ============================================================
print("\n" + "=" * 80)
print("4. REVERSAL PROBABILITY BY CONSECUTIVE SAME-DIRECTION MOVES")
print("=" * 80)

all_changes = []
for day in DAYS:
    valid = [(ts, fv) for ts, fv in all_fv_int[day] if fv is not None]
    prev_fv = None
    for ts, fv in valid:
        if prev_fv is not None and fv != prev_fv:
            direction = 1 if fv > prev_fv else -1
            all_changes.append((day, ts, direction))
        prev_fv = fv

print(f"Total FV changes across all days: {len(all_changes)}")
directions = [d for _, _, d in all_changes]

# Run-length analysis
for max_run in range(1, 8):
    # After seeing `max_run` consecutive same-direction moves, P(reversal)?
    count_same = 0
    count_reverse = 0

    for i in range(max_run, len(directions)):
        # Check if previous max_run moves are all the same direction
        prev_dirs = directions[i-max_run:i]
        if len(set(prev_dirs)) == 1:
            if directions[i] != prev_dirs[0]:
                count_reverse += 1
            else:
                count_same += 1

    total = count_same + count_reverse
    if total > 0:
        p_reverse = count_reverse / total
        print(f"  After {max_run} consecutive same-dir moves: P(reverse) = {p_reverse:.4f} ({count_reverse}/{total})")
    else:
        print(f"  After {max_run} consecutive same-dir moves: no data")

# ============================================================
# 5. RUN-LENGTH DISTRIBUTION
# ============================================================
print("\n" + "=" * 80)
print("5. RUN-LENGTH DISTRIBUTION (consecutive same-direction FV moves)")
print("=" * 80)

run_lengths = []
current_run = 1
for i in range(1, len(directions)):
    if directions[i] == directions[i-1]:
        current_run += 1
    else:
        run_lengths.append(current_run)
        current_run = 1
run_lengths.append(current_run)  # last run

rl_counter = Counter(run_lengths)
print(f"Total runs: {len(run_lengths)}")
for rl in sorted(rl_counter.keys()):
    pct = 100 * rl_counter[rl] / len(run_lengths)
    print(f"  Run length {rl}: {rl_counter[rl]} ({pct:.1f}%)")

# Geometric distribution check
p_cont = sum(1 for r in run_lengths if r > 1) / len(run_lengths) if run_lengths else 0
print(f"\nEmpirical P(continue) = {p_cont:.4f} (complement of P(reverse at length 1))")
print(f"If geometric with p_stop={1-p_cont:.4f}: expected run lengths:")
for rl in range(1, 8):
    expected = len(run_lengths) * ((p_cont)**(rl-1)) * (1 - p_cont)
    actual = rl_counter.get(rl, 0)
    print(f"  RL={rl}: expected={expected:.1f}, actual={actual}, ratio={actual/expected:.3f}" if expected > 0 else f"  RL={rl}: expected=0, actual={actual}")

# ============================================================
# 6. TIME BETWEEN FV CHANGES
# ============================================================
print("\n" + "=" * 80)
print("6. TIME BETWEEN FV CHANGES")
print("=" * 80)

for day in DAYS:
    day_changes = [(ts, d) for dy, ts, d in all_changes if dy == day]
    if len(day_changes) < 2:
        continue

    intervals = []
    for i in range(1, len(day_changes)):
        dt = day_changes[i][0] - day_changes[i-1][0]
        intervals.append(dt)

    print(f"\nDay {day}: {len(intervals)} inter-change intervals")
    print(f"  Mean: {sum(intervals)/len(intervals):.1f}")
    print(f"  Min: {min(intervals)}, Max: {max(intervals)}")
    print(f"  Median: {sorted(intervals)[len(intervals)//2]}")

    # Distribution of intervals
    int_counter = Counter(intervals)
    print(f"  Most common intervals:")
    for iv, cnt in int_counter.most_common(15):
        print(f"    dt={iv}: {cnt} ({100*cnt/len(intervals):.1f}%)")

# Check if FV changes happen at specific timestamps modulo some period
print("\n--- FV change timestamps modulo analysis ---")
for day in DAYS:
    day_changes = [(ts, d) for dy, ts, d in all_changes if dy == day]
    change_ts = [ts for ts, _ in day_changes]

    for mod in [200, 300, 400, 500, 1000, 2000]:
        residues = Counter([t % mod for t in change_ts])
        print(f"  Day {day}, mod {mod}: top residues = {residues.most_common(5)}")

# ============================================================
# 7. FV CHANGE VS MARKET TRADES TIMING
# ============================================================
print("\n" + "=" * 80)
print("7. FV CHANGE VS MARKET TRADES TIMING")
print("=" * 80)

for day in DAYS:
    day_changes = [(ts, d) for dy, ts, d in all_changes if dy == day]
    osm_tr = all_trades[day]['osm']

    if not day_changes or not osm_tr:
        continue

    trade_ts = [int(t['timestamp']) for t in osm_tr]
    trade_prices = [float(t['price']) for t in osm_tr]
    trade_qtys = [int(t['quantity']) for t in osm_tr]

    print(f"\nDay {day}: {len(day_changes)} FV changes, {len(osm_tr)} trades")

    # For each FV change, find closest trade
    change_to_trade_offsets = []
    for fv_ts, fv_dir in day_changes:
        closest_offset = None
        closest_trade = None
        for j, tts in enumerate(trade_ts):
            offset = tts - fv_ts
            if closest_offset is None or abs(offset) < abs(closest_offset):
                closest_offset = offset
                closest_trade = j
        if closest_offset is not None:
            change_to_trade_offsets.append(closest_offset)

    if change_to_trade_offsets:
        neg = [o for o in change_to_trade_offsets if o < 0]
        zero = [o for o in change_to_trade_offsets if o == 0]
        pos = [o for o in change_to_trade_offsets if o > 0]
        print(f"  Closest trade before FV change: {len(neg)} times")
        print(f"  Closest trade at same tick: {len(zero)} times")
        print(f"  Closest trade after FV change: {len(pos)} times")
        print(f"  Mean offset: {sum(change_to_trade_offsets)/len(change_to_trade_offsets):.1f}")

    # For each trade, did FV change in the next 100-500 ticks?
    fv_change_set = {ts: d for ts, d in day_changes}
    trade_predicts_fv = Counter()
    for j, tts in enumerate(trade_ts):
        tp = trade_prices[j]
        # Get FV at or near trade time
        fv_at_trade = None
        for ts, fv in all_fv_int[day]:
            if ts == tts and fv is not None:
                fv_at_trade = fv
                break

        if fv_at_trade is None:
            continue

        # Trade above FV -> sell signal? Below FV -> buy signal?
        if tp > fv_at_trade + 2:
            trade_side = 'above_fv'
        elif tp < fv_at_trade - 2:
            trade_side = 'below_fv'
        else:
            trade_side = 'near_fv'

        # Check FV direction in next few ticks
        for look_ts, look_dir in day_changes:
            if 0 < look_ts - tts <= 500:
                trade_predicts_fv[(trade_side, look_dir)] += 1
                break

    print(f"  Trade position vs next FV change: {dict(trade_predicts_fv)}")

# ============================================================
# 8. PEPPER CORRELATION
# ============================================================
print("\n" + "=" * 80)
print("8. PEPPER MID-PRICE vs OSMIUM FV CORRELATION")
print("=" * 80)

for day in DAYS:
    # Build timestamp-indexed pepper mids
    pep_mids = {}
    for d in all_pepper[day]:
        if d['mid'] is not None:
            pep_mids[d['ts']] = d['mid']

    # Build timestamp-indexed osmium FV
    osm_fvs = {}
    for ts, fv in all_fv_int[day]:
        if fv is not None:
            osm_fvs[ts] = fv

    # Get common timestamps
    common_ts = sorted(set(pep_mids.keys()) & set(osm_fvs.keys()))

    if len(common_ts) < 100:
        print(f"Day {day}: insufficient common timestamps ({len(common_ts)})")
        continue

    # Compute returns/changes
    pep_changes = []
    osm_changes = []
    for i in range(1, len(common_ts)):
        t0, t1 = common_ts[i-1], common_ts[i]
        pep_changes.append(pep_mids[t1] - pep_mids[t0])
        osm_changes.append(osm_fvs[t1] - osm_fvs[t0])

    # Correlation
    n = len(pep_changes)
    mean_p = sum(pep_changes) / n
    mean_o = sum(osm_changes) / n
    cov = sum((pep_changes[i] - mean_p) * (osm_changes[i] - mean_o) for i in range(n)) / n
    std_p = math.sqrt(sum((p - mean_p)**2 for p in pep_changes) / n)
    std_o = math.sqrt(sum((o - mean_o)**2 for o in osm_changes) / n)

    if std_p > 0 and std_o > 0:
        corr = cov / (std_p * std_o)
        print(f"Day {day}: Contemporaneous correlation = {corr:.4f} (n={n})")

    # Lead-lag: does PEPPER change at t predict OSMIUM change at t+100?
    for lag in [1, 2, 3, 5, 10]:
        if lag >= len(pep_changes):
            continue
        n_lag = len(pep_changes) - lag
        cov_lag = sum((pep_changes[i] - mean_p) * (osm_changes[i+lag] - mean_o) for i in range(n_lag)) / n_lag
        if std_p > 0 and std_o > 0:
            corr_lag = cov_lag / (std_p * std_o)
            print(f"  PEPPER leads OSMIUM by {lag} ticks: corr = {corr_lag:.4f}")

    # Does sign of PEPPER return predict sign of OSMIUM return?
    sign_match = 0
    sign_total = 0
    for i in range(len(pep_changes)):
        if pep_changes[i] != 0 and osm_changes[i] != 0:
            sign_match += 1 if (pep_changes[i] > 0) == (osm_changes[i] > 0) else 0
            sign_total += 1
    if sign_total > 0:
        print(f"  Sign agreement (contemp, both non-zero): {sign_match}/{sign_total} = {sign_match/sign_total:.4f}")

# ============================================================
# 9. L2/L3 ORDER BOOK FEATURES
# ============================================================
print("\n" + "=" * 80)
print("9. L2/L3 BOOK FEATURES AND FV PREDICTION")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}

    # For each tick, compute book features and see if they predict next FV change direction
    # Feature: presence of L2, L3; asymmetry of L2; volume ratios

    l2_bid_predicts = Counter()  # (has_l2_bid, next_fv_dir) -> count
    l2_ask_predicts = Counter()
    l2_asym_predicts = Counter()

    timestamps = sorted(fv_dict.keys())
    osm_by_ts = {d['ts']: d for d in osm_data}

    for i in range(len(timestamps) - 1):
        t0 = timestamps[i]
        t1 = timestamps[i+1]
        fv_change = fv_dict[t1] - fv_dict[t0]

        if fv_change == 0 or t0 not in osm_by_ts:
            continue

        d = osm_by_ts[t0]
        direction = 1 if fv_change > 0 else -1

        has_l2_bid = 1 if d['bp2'] is not None else 0
        has_l2_ask = 1 if d['ap2'] is not None else 0
        has_l3_bid = 1 if d['bp3'] is not None else 0
        has_l3_ask = 1 if d['ap3'] is not None else 0

        l2_bid_predicts[(has_l2_bid, direction)] += 1
        l2_ask_predicts[(has_l2_ask, direction)] += 1

        # L2 asymmetry
        if has_l2_bid and has_l2_ask:
            l2_asym_predicts[('both_l2', direction)] += 1
        elif has_l2_bid and not has_l2_ask:
            l2_asym_predicts[('bid_only_l2', direction)] += 1
        elif not has_l2_bid and has_l2_ask:
            l2_asym_predicts[('ask_only_l2', direction)] += 1
        else:
            l2_asym_predicts[('no_l2', direction)] += 1

    print(f"\nDay {day}:")
    print("  L2 bid presence vs next FV direction:")
    for key in sorted(l2_bid_predicts.keys()):
        print(f"    {key}: {l2_bid_predicts[key]}")

    print("  L2 ask presence vs next FV direction:")
    for key in sorted(l2_ask_predicts.keys()):
        print(f"    {key}: {l2_ask_predicts[key]}")

    print("  L2 asymmetry vs next FV direction:")
    for key in sorted(l2_asym_predicts.keys()):
        print(f"    {key}: {l2_asym_predicts[key]}")

# ============================================================
# 10. VOLUME PATTERNS - BV1/AV1 AND FV DIRECTION
# ============================================================
print("\n" + "=" * 80)
print("10. VOLUME PATTERNS (BV1, AV1) AND FV PREDICTION")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    osm_by_ts = {d['ts']: d for d in osm_data}

    # Collect (bv1, av1) at spread-16 ticks, and the NEXT FV change direction
    vol_vs_dir = []

    timestamps = sorted(fv_dict.keys())
    for i in range(len(timestamps) - 1):
        t0 = timestamps[i]
        t1 = timestamps[i+1]
        fv_change = fv_dict[t1] - fv_dict[t0]

        if fv_change == 0 or t0 not in osm_by_ts:
            continue

        d = osm_by_ts[t0]
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            if spread == 16:
                vol_vs_dir.append((d['bv1'], d['av1'], 1 if fv_change > 0 else -1))

    if not vol_vs_dir:
        continue

    print(f"\nDay {day}: {len(vol_vs_dir)} spread-16 ticks followed by FV change")

    # BV1 values
    bv1_vals = set(v[0] for v in vol_vs_dir if v[0] is not None)
    av1_vals = set(v[1] for v in vol_vs_dir if v[1] is not None)
    print(f"  Unique BV1 values: {sorted(bv1_vals)}")
    print(f"  Unique AV1 values: {sorted(av1_vals)}")

    # BV1 value vs direction
    bv1_dir = defaultdict(lambda: [0, 0])  # bv1 -> [up_count, down_count]
    av1_dir = defaultdict(lambda: [0, 0])

    for bv1, av1, direction in vol_vs_dir:
        if bv1 is not None:
            idx = 0 if direction == 1 else 1
            bv1_dir[bv1][idx] += 1
        if av1 is not None:
            idx = 0 if direction == 1 else 1
            av1_dir[av1][idx] += 1

    print("  BV1 value -> [up_count, down_count]:")
    for bv1 in sorted(bv1_dir.keys()):
        up, dn = bv1_dir[bv1]
        total = up + dn
        p_up = up/total if total > 0 else 0
        print(f"    BV1={bv1}: up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

    print("  AV1 value -> [up_count, down_count]:")
    for av1 in sorted(av1_dir.keys()):
        up, dn = av1_dir[av1]
        total = up + dn
        p_up = up/total if total > 0 else 0
        print(f"    AV1={av1}: up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

    # BV1 - AV1 imbalance
    print("  Volume imbalance (BV1 - AV1) vs direction:")
    imb_dir = defaultdict(lambda: [0, 0])
    for bv1, av1, direction in vol_vs_dir:
        if bv1 is not None and av1 is not None:
            imb = bv1 - av1
            idx = 0 if direction == 1 else 1
            imb_dir[imb][idx] += 1

    for imb in sorted(imb_dir.keys()):
        up, dn = imb_dir[imb]
        total = up + dn
        p_up = up/total if total > 0 else 0
        print(f"    IMB={imb:+d}: up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

# ============================================================
# 11. BOOK ASYMMETRY SIGNAL (BV1 != AV1)
# ============================================================
print("\n" + "=" * 80)
print("11. BOOK ASYMMETRY SIGNAL - ALL SPREAD STATES")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    osm_by_ts = {d['ts']: d for d in osm_data}

    # For every tick with both sides, compute imbalance = bv1 - av1
    # Group by spread and check if imbalance predicts next FV move

    by_spread = defaultdict(list)  # spread -> list of (imb, next_dir)

    timestamps = sorted(fv_dict.keys())
    for i in range(len(timestamps) - 1):
        t0 = timestamps[i]
        t1 = timestamps[i+1]
        fv_change = fv_dict[t1] - fv_dict[t0]

        if fv_change == 0 or t0 not in osm_by_ts:
            continue

        d = osm_by_ts[t0]
        if d['bp1'] is not None and d['ap1'] is not None and d['bv1'] is not None and d['av1'] is not None:
            spread = int(d['ap1'] - d['bp1'])
            imb = d['bv1'] - d['av1']
            direction = 1 if fv_change > 0 else -1
            by_spread[spread].append((imb, direction))

    print(f"\nDay {day}:")
    for spread in sorted(by_spread.keys()):
        entries = by_spread[spread]
        if len(entries) < 10:
            continue

        # Compute correlation between imbalance sign and direction
        imb_correct = sum(1 for imb, d in entries if (imb > 0 and d == 1) or (imb < 0 and d == -1))
        imb_wrong = sum(1 for imb, d in entries if (imb > 0 and d == -1) or (imb < 0 and d == 1))
        imb_zero = sum(1 for imb, d in entries if imb == 0)
        total = imb_correct + imb_wrong

        if total > 0:
            p_correct = imb_correct / total
            print(f"  Spread={spread}: imbalance predicts direction {imb_correct}/{total} = {p_correct:.3f} (zero_imb={imb_zero}, n={len(entries)})")

# ============================================================
# 12. AUTOCORRELATION OF FV CHANGES AT LAGS 1-20
# ============================================================
print("\n" + "=" * 80)
print("12. AUTOCORRELATION OF FV CHANGES (lags 1-20)")
print("=" * 80)

for day in DAYS:
    valid = [(ts, fv) for ts, fv in all_fv_int[day] if fv is not None]
    changes = []
    for i in range(1, len(valid)):
        diff = valid[i][1] - valid[i-1][1]
        changes.append(diff)

    # Filter to non-zero changes only (FV step changes)
    nz_changes = [c for c in changes if c != 0]

    n = len(nz_changes)
    if n < 30:
        continue

    mean_c = sum(nz_changes) / n
    var_c = sum((c - mean_c)**2 for c in nz_changes) / n

    print(f"\nDay {day}: {n} non-zero FV changes")
    print(f"  Mean: {mean_c:.4f}, Var: {var_c:.4f}")

    for lag in range(1, 21):
        if lag >= n:
            break
        cov = sum((nz_changes[i] - mean_c) * (nz_changes[i+lag] - mean_c) for i in range(n - lag)) / (n - lag)
        acf = cov / var_c if var_c > 0 else 0
        sig = 1.96 / math.sqrt(n)
        marker = " ***" if abs(acf) > sig else ""
        print(f"  Lag {lag:2d}: ACF = {acf:+.4f} (sig threshold: ±{sig:.4f}){marker}")

# Also do autocorrelation of FV change DIRECTION (±1 only)
print("\n--- Autocorrelation of FV change DIRECTION (±1) ---")
all_nz_dirs = []
for day in DAYS:
    valid = [(ts, fv) for ts, fv in all_fv_int[day] if fv is not None]
    for i in range(1, len(valid)):
        diff = valid[i][1] - valid[i-1][1]
        if diff != 0:
            all_nz_dirs.append(1 if diff > 0 else -1)

n = len(all_nz_dirs)
mean_d = sum(all_nz_dirs) / n
var_d = sum((d - mean_d)**2 for d in all_nz_dirs) / n

print(f"\nAll days combined: {n} directional changes")
print(f"Mean direction: {mean_d:.4f} (0=balanced), Var: {var_d:.4f}")
for lag in range(1, 21):
    if lag >= n:
        break
    cov = sum((all_nz_dirs[i] - mean_d) * (all_nz_dirs[i+lag] - mean_d) for i in range(n - lag)) / (n - lag)
    acf = cov / var_d if var_d > 0 else 0
    sig = 1.96 / math.sqrt(n)
    marker = " ***" if abs(acf) > sig else ""
    print(f"  Lag {lag:2d}: ACF = {acf:+.4f}{marker}")

# ============================================================
# 13. DETERMINISM CHECK - SAME FV SEQUENCE ACROSS DAYS?
# ============================================================
print("\n" + "=" * 80)
print("13. DETERMINISM CHECK")
print("=" * 80)

# Extract FV change sequences for each day
day_change_seqs = {}
for day in DAYS:
    valid = [(ts, fv) for ts, fv in all_fv_int[day] if fv is not None]
    changes = []
    for i in range(1, len(valid)):
        diff = valid[i][1] - valid[i-1][1]
        if diff != 0:
            changes.append((valid[i][0], diff))
    day_change_seqs[day] = changes

# Compare day -2 vs day -1 vs day 0
for d1, d2 in [(-2, -1), (-2, 0), (-1, 0)]:
    seq1 = [d for _, d in day_change_seqs[d1]]
    seq2 = [d for _, d in day_change_seqs[d2]]

    min_len = min(len(seq1), len(seq2))
    matches = sum(1 for i in range(min_len) if seq1[i] == seq2[i])

    print(f"\nDay {d1} vs Day {d2}:")
    print(f"  Lengths: {len(seq1)} vs {len(seq2)}")
    print(f"  First {min_len} changes match: {matches}/{min_len} = {matches/min_len:.3f}")

    # Check if timestamps of changes match
    ts1 = [t for t, _ in day_change_seqs[d1]]
    ts2 = [t for t, _ in day_change_seqs[d2]]
    ts_matches = sum(1 for i in range(min_len) if ts1[i] == ts2[i])
    print(f"  Timestamp matches: {ts_matches}/{min_len}")

# Check if FV sequence could be from a PRNG (look for periodicity)
print("\n--- Periodicity check ---")
for day in DAYS:
    seq = [d for _, d in day_change_seqs[day]]
    n = len(seq)

    # Check for period P: does seq[i] == seq[i+P] for all i?
    for P in range(10, min(n//2, 500)):
        matches = sum(1 for i in range(n - P) if seq[i] == seq[i+P])
        total = n - P
        if matches / total > 0.8:
            print(f"  Day {day}: period {P} has {matches}/{total} = {matches/total:.3f} match rate!")
            break
    else:
        print(f"  Day {day}: No strong period found (checked P=10..{min(n//2, 500)-1})")

# ============================================================
# 14. FV STARTING VALUES
# ============================================================
print("\n" + "=" * 80)
print("14. FV STARTING VALUES")
print("=" * 80)

for day in DAYS:
    anchors = all_fv_anchors[day]
    if anchors:
        print(f"Day {day}: First spread-16 FV = {anchors[0][1]} at t={anchors[0][0]}")

    # What about the very first tick?
    d = all_osm[day][0]
    print(f"  t=0 book: bid={d['bp1']}, ask={d['ap1']}, mid={d['mid']}")

# ============================================================
# 15. BOOK STATE AND WHEN FV CHANGES
# ============================================================
print("\n" + "=" * 80)
print("15. BOOK STATE (SPREAD) AND CONDITIONAL FV CHANGE PROBABILITY")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    osm_by_ts = {d['ts']: d for d in osm_data}

    timestamps = sorted(fv_dict.keys())

    spread_change = defaultdict(lambda: [0, 0])  # spread -> [changed, unchanged]

    for i in range(len(timestamps) - 1):
        t0 = timestamps[i]
        t1 = timestamps[i+1]
        fv_change = fv_dict[t1] - fv_dict[t0]

        if t0 not in osm_by_ts:
            continue

        d = osm_by_ts[t0]
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = int(d['ap1'] - d['bp1'])
            if fv_change != 0:
                spread_change[spread][0] += 1
            else:
                spread_change[spread][1] += 1

    print(f"\nDay {day}:")
    for spread in sorted(spread_change.keys()):
        changed, unchanged = spread_change[spread]
        total = changed + unchanged
        p_change = changed / total if total > 0 else 0
        print(f"  Spread={spread}: P(FV changes) = {changed}/{total} = {p_change:.4f}")

# ============================================================
# 16. BOT 3 / NOISE TRADER ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("16. TRADE ANALYSIS - BUYER/SELLER INFO AND FV PREDICTION")
print("=" * 80)

for day in DAYS:
    osm_tr = all_trades[day]['osm']
    print(f"\nDay {day}: {len(osm_tr)} OSMIUM trades")

    # Check buyer/seller fields
    buyers = Counter()
    sellers = Counter()
    for t in osm_tr:
        buyers[t.get('buyer', '')] += 1
        sellers[t.get('seller', '')] += 1

    print(f"  Buyers: {dict(buyers)}")
    print(f"  Sellers: {dict(sellers)}")

    # Trade quantity distribution
    qtys = [int(t['quantity']) for t in osm_tr]
    qty_counter = Counter(qtys)
    print(f"  Quantity distribution: {dict(sorted(qty_counter.items()))}")

    # Trade price relative to FV
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}

    for t in osm_tr[:5]:
        tts = int(t['timestamp'])
        tp = float(t['price'])
        # Find closest FV
        closest_ts = min(fv_dict.keys(), key=lambda x: abs(x - tts))
        fv_at = fv_dict[closest_ts]
        offset = tp - fv_at
        print(f"  Trade t={tts}, price={tp}, FV~{fv_at}, offset={offset:+.0f}, qty={t['quantity']}")

# ============================================================
# 17. DEEPER VOLUME ANALYSIS - EXACT BOOK STATES
# ============================================================
print("\n" + "=" * 80)
print("17. EXACT BOOK STATES AT SPREAD-16 (The MM Bot Fingerprint)")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]

    # At spread=16, what are the exact (bv1, av1, bp2, bv2, ap2, av2) combos?
    book_states = Counter()
    for d in osm_data:
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            if spread == 16:
                state = (d['bv1'], d['av1'],
                         int(d['bp1'] - (d['ap1'] + d['bp1'])/2) if d['bp1'] else None,
                         d['bp2'] is not None, d['ap2'] is not None,
                         d['bv2'], d['av2'])
                book_states[state] += 1

    print(f"\nDay {day}: {sum(book_states.values())} spread-16 ticks")
    print(f"  Unique (bv1, av1, has_l2_bid, has_l2_ask, bv2, av2) states: {len(book_states)}")
    for state, count in book_states.most_common(20):
        print(f"    {state}: {count}")

# ============================================================
# 18. BV1/AV1 AT SPREAD=16 - FULL INVENTORY ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("18. BV1/AV1 VALUES AT SPREAD=16 WITH NEXT FV DIRECTION")
print("=" * 80)

all_vol_dir = []  # Collect across all days
for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    osm_by_ts = {d['ts']: d for d in osm_data}

    timestamps = sorted(fv_dict.keys())

    for i in range(len(timestamps)):
        t0 = timestamps[i]
        if t0 not in osm_by_ts:
            continue
        d = osm_by_ts[t0]
        if d['bp1'] is None or d['ap1'] is None:
            continue
        spread = d['ap1'] - d['bp1']
        if spread != 16:
            continue

        # Find next FV change
        next_dir = None
        for j in range(i+1, min(i+50, len(timestamps))):
            fv_change = fv_dict[timestamps[j]] - fv_dict[t0]
            if fv_change != 0:
                next_dir = 1 if fv_change > 0 else -1
                break

        if next_dir is not None:
            all_vol_dir.append((d['bv1'], d['av1'], next_dir, day))

print(f"\nTotal spread-16 samples with known next direction: {len(all_vol_dir)}")

# Group by (bv1, av1) pair
pair_stats = defaultdict(lambda: [0, 0])
for bv1, av1, direction, _ in all_vol_dir:
    idx = 0 if direction == 1 else 1
    pair_stats[(bv1, av1)][idx] += 1

print("\n(BV1, AV1) -> [up, down], P(up):")
for (bv1, av1) in sorted(pair_stats.keys()):
    up, dn = pair_stats[(bv1, av1)]
    total = up + dn
    if total >= 5:
        p_up = up / total
        print(f"  ({bv1}, {av1}): up={up}, down={dn}, P(up)={p_up:.3f} (n={total})")

# ============================================================
# 19. L2 PRICE OFFSETS AND VOLUMES
# ============================================================
print("\n" + "=" * 80)
print("19. L2 PRICE OFFSETS AND VOLUMES")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]

    l2_bid_offsets = Counter()
    l2_ask_offsets = Counter()

    for d in osm_data:
        if d['bp1'] is not None and d['bp2'] is not None:
            offset = int(d['bp1'] - d['bp2'])
            l2_bid_offsets[offset] += 1
        if d['ap1'] is not None and d['ap2'] is not None:
            offset = int(d['ap2'] - d['ap1'])
            l2_ask_offsets[offset] += 1

    print(f"\nDay {day}:")
    print(f"  L2 bid offsets (bp1 - bp2): {dict(sorted(l2_bid_offsets.items()))}")
    print(f"  L2 ask offsets (ap2 - ap1): {dict(sorted(l2_ask_offsets.items()))}")

# ============================================================
# 20. CONDITIONAL: WHEN BV1 != AV1 AT SPREAD=16
# ============================================================
print("\n" + "=" * 80)
print("20. ASYMMETRIC VOLUME AT SPREAD=16: WHAT CAUSES IT?")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]

    asym_cases = []
    sym_cases = []

    for d in osm_data:
        if d['bp1'] is not None and d['ap1'] is not None:
            spread = d['ap1'] - d['bp1']
            if spread == 16 and d['bv1'] is not None and d['av1'] is not None:
                if d['bv1'] != d['av1']:
                    asym_cases.append(d)
                else:
                    sym_cases.append(d)

    print(f"\nDay {day}: {len(asym_cases)} asymmetric, {len(sym_cases)} symmetric spread-16 ticks")

    if asym_cases:
        # Show some examples
        print("  First 10 asymmetric cases:")
        for d in asym_cases[:10]:
            print(f"    t={d['ts']}: bid={d['bp1']}x{d['bv1']}, ask={d['ap1']}x{d['av1']}, "
                  f"L2: bid2={d['bp2']}x{d['bv2']}, ask2={d['ap2']}x{d['av2']}")

# ============================================================
# 21. PEPPER-OSMIUM CROSS-ASSET LEAD-LAG (FINER GRAIN)
# ============================================================
print("\n" + "=" * 80)
print("21. PEPPER RETURN -> OSMIUM FV CHANGE (LEAD-LAG AT TICK LEVEL)")
print("=" * 80)

for day in DAYS:
    pep_data = all_pepper[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}

    # Build PEPPER mid changes
    pep_by_ts = {}
    for d in pep_data:
        if d['mid'] is not None:
            pep_by_ts[d['ts']] = d['mid']

    pep_ts_sorted = sorted(pep_by_ts.keys())
    pep_changes = {}
    for i in range(1, len(pep_ts_sorted)):
        t = pep_ts_sorted[i]
        t_prev = pep_ts_sorted[i-1]
        pep_changes[t] = pep_by_ts[t] - pep_by_ts[t_prev]

    # For each FV change, what was PEPPER doing in the ticks before?
    fv_changes_ts = []
    fv_ts_sorted = sorted(fv_dict.keys())
    for i in range(1, len(fv_ts_sorted)):
        diff = fv_dict[fv_ts_sorted[i]] - fv_dict[fv_ts_sorted[i-1]]
        if diff != 0:
            fv_changes_ts.append((fv_ts_sorted[i], diff))

    # For each FV change, sum PEPPER changes in windows before
    results = defaultdict(list)  # lookback -> list of (pep_return, osm_dir)

    for fv_t, fv_d in fv_changes_ts:
        osm_dir = 1 if fv_d > 0 else -1

        for lookback in [100, 200, 500, 1000, 2000]:
            pep_ret = sum(v for t, v in pep_changes.items() if fv_t - lookback <= t < fv_t)
            results[lookback].append((pep_ret, osm_dir))

    print(f"\nDay {day}:")
    for lb in [100, 200, 500, 1000, 2000]:
        data = results[lb]
        if not data:
            continue
        # Sign agreement
        n_agree = sum(1 for pr, od in data if (pr > 0 and od > 0) or (pr < 0 and od < 0))
        n_nonzero = sum(1 for pr, od in data if pr != 0)
        n_total = len(data)
        if n_nonzero > 0:
            print(f"  Lookback {lb}: sign agreement = {n_agree}/{n_nonzero} = {n_agree/n_nonzero:.3f} (of {n_nonzero} non-zero pepper returns)")

# ============================================================
# 22. TICK-BY-TICK: SPREAD TRANSITIONS
# ============================================================
print("\n" + "=" * 80)
print("22. SPREAD TRANSITION MATRIX")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]

    transitions = Counter()
    for i in range(1, len(osm_data)):
        d0 = osm_data[i-1]
        d1 = osm_data[i]

        if d0['bp1'] is not None and d0['ap1'] is not None and d1['bp1'] is not None and d1['ap1'] is not None:
            s0 = int(d0['ap1'] - d0['bp1'])
            s1 = int(d1['ap1'] - d1['bp1'])
            transitions[(s0, s1)] += 1

    print(f"\nDay {day} spread transitions (from -> to: count):")
    for (s0, s1) in sorted(transitions.keys()):
        count = transitions[(s0, s1)]
        if count >= 5:
            print(f"  {s0} -> {s1}: {count}")

# ============================================================
# 23. KEY INSIGHT: SPREAD STATE ENCODES FV TRANSITION
# ============================================================
print("\n" + "=" * 80)
print("23. WHEN SPREAD != 16, WHICH SIDE MOVED? (FV DIRECTION INFERENCE)")
print("=" * 80)

for day in DAYS:
    osm_data = all_osm[day]
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}

    # When spread transitions from 16 to 17, check if bid dropped or ask rose
    for i in range(1, len(osm_data)):
        d0 = osm_data[i-1]
        d1 = osm_data[i]

        if d0['bp1'] is None or d0['ap1'] is None or d1['bp1'] is None or d1['ap1'] is None:
            continue

        s0 = d0['ap1'] - d0['bp1']
        s1 = d1['ap1'] - d1['bp1']

        if s0 == 16 and s1 == 17 and i < 15:  # Just show first few
            bid_change = d1['bp1'] - d0['bp1']
            ask_change = d1['ap1'] - d0['ap1']
            print(f"  Day {day} t={d1['ts']}: 16->17, bid {d0['bp1']}->{d1['bp1']} ({bid_change:+.0f}), "
                  f"ask {d0['ap1']}->{d1['ap1']} ({ask_change:+.0f})")

    if day == DAYS[0]:
        break  # Just show one day

# ============================================================
# 24. FV TEXT TRAJECTORY (COMPACT)
# ============================================================
print("\n" + "=" * 80)
print("24. FV TRAJECTORY (compact text plot, samples every 500 ticks)")
print("=" * 80)

for day in DAYS:
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    timestamps = sorted(fv_dict.keys())

    min_fv = min(fv_dict[t] for t in timestamps)
    max_fv = max(fv_dict[t] for t in timestamps)

    print(f"\nDay {day} (FV range: {min_fv} to {max_fv}):")

    width = 60
    for t in range(0, max(timestamps) + 1, 500):
        if t in fv_dict:
            fv = fv_dict[t]
            if max_fv > min_fv:
                pos = int((fv - min_fv) / (max_fv - min_fv) * width)
            else:
                pos = width // 2
            bar = ' ' * pos + '*'
            print(f"  t={t:6d} FV={fv:5d} |{bar}")

# ============================================================
# 25. TRADE SIZE / PRICE PATTERNS
# ============================================================
print("\n" + "=" * 80)
print("25. OSMIUM TRADE ANALYSIS - SIZE AND PRICE PATTERNS")
print("=" * 80)

for day in DAYS:
    osm_tr = all_trades[day]['osm']
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}

    if not osm_tr:
        continue

    print(f"\nDay {day}: {len(osm_tr)} trades")

    # Categorize trades by offset from FV
    offsets = []
    for t in osm_tr:
        tts = int(t['timestamp'])
        tp = float(t['price'])
        qty = int(t['quantity'])

        # Find FV at this timestamp
        closest_ts = min(fv_dict.keys(), key=lambda x: abs(x - tts)) if fv_dict else None
        if closest_ts is not None:
            fv = fv_dict[closest_ts]
            offset = tp - fv
            offsets.append((offset, qty, tts))

    offset_counter = Counter()
    for off, qty, _ in offsets:
        offset_counter[int(off)] += 1

    print(f"  Trade price offset from FV distribution:")
    for off in sorted(offset_counter.keys()):
        print(f"    offset={off:+d}: {offset_counter[off]}")

    # Trade volume by offset
    vol_by_offset = defaultdict(list)
    for off, qty, _ in offsets:
        vol_by_offset[int(off)].append(qty)

    print(f"  Mean trade volume by offset:")
    for off in sorted(vol_by_offset.keys()):
        vols = vol_by_offset[off]
        print(f"    offset={off:+d}: mean_qty={sum(vols)/len(vols):.1f}, n={len(vols)}")

# ============================================================
# 26. CROSS-DAY FV CHANGE TIMING COMPARISON
# ============================================================
print("\n" + "=" * 80)
print("26. CROSS-DAY: FV CHANGES AT SAME TIMESTAMPS?")
print("=" * 80)

change_timestamps = {}
for day in DAYS:
    change_timestamps[day] = set()
    fv_ts = [(ts, fv) for ts, fv in all_fv_int[day] if fv is not None]
    for i in range(1, len(fv_ts)):
        if fv_ts[i][1] != fv_ts[i-1][1]:
            change_timestamps[day].add(fv_ts[i][0])
    print(f"Day {day}: {len(change_timestamps[day])} timestamps with FV changes")

for d1, d2 in [(-2, -1), (-2, 0), (-1, 0)]:
    overlap = change_timestamps[d1] & change_timestamps[d2]
    union = change_timestamps[d1] | change_timestamps[d2]
    jaccard = len(overlap) / len(union) if union else 0
    print(f"  Day {d1} vs Day {d2}: {len(overlap)} common timestamps, Jaccard = {jaccard:.4f}")

# Random baseline: if changes happen at ~200 random timestamps out of 10000
n_ts = 10000
for day in DAYS:
    p = len(change_timestamps[day]) / n_ts
    expected_overlap = p * p * n_ts
    print(f"  Day {day}: {len(change_timestamps[day])} changes -> random overlap expectation = {expected_overlap:.1f}")

# ============================================================
# 27. SPREAD SEQUENCE AROUND FV CHANGES
# ============================================================
print("\n" + "=" * 80)
print("27. SPREAD SEQUENCE AROUND FV CHANGES (typical pattern)")
print("=" * 80)

for day in [DAYS[0]]:  # Just one day
    osm_data = all_osm[day]
    osm_by_ts = {d['ts']: d for d in osm_data}
    fv_dict = {ts: fv for ts, fv in all_fv_int[day] if fv is not None}
    fv_ts_sorted = sorted(fv_dict.keys())

    # Find FV change timestamps
    change_indices = []
    for i in range(1, len(fv_ts_sorted)):
        if fv_dict[fv_ts_sorted[i]] != fv_dict[fv_ts_sorted[i-1]]:
            change_indices.append(i)

    # Show spread sequence around first 10 changes
    print(f"\nDay {day}: Showing spread pattern around first 10 FV changes:")
    shown = 0
    for ci in change_indices[:10]:
        t_change = fv_ts_sorted[ci]
        t_before = fv_ts_sorted[ci-1] if ci > 0 else None

        window = []
        for offset in range(-3, 4):
            idx = ci + offset
            if 0 <= idx < len(fv_ts_sorted):
                t = fv_ts_sorted[idx]
                if t in osm_by_ts:
                    d = osm_by_ts[t]
                    spread = int(d['ap1'] - d['bp1']) if d['bp1'] is not None and d['ap1'] is not None else None
                    fv = fv_dict[t]
                    window.append(f"t={t}:s={spread},fv={fv}")

        print(f"  Change at t={t_change}: {' | '.join(window)}")

# ============================================================
# 28. COMPREHENSIVE SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("28. COMPREHENSIVE SUMMARY")
print("=" * 80)

# Aggregate stats
total_changes = len(all_nz_dirs)
up_pct = sum(1 for d in all_nz_dirs if d == 1) / total_changes * 100
print(f"\nTotal FV changes (all days): {total_changes}")
print(f"Up moves: {up_pct:.1f}%, Down moves: {100-up_pct:.1f}%")

# Overall reversal stats
for run_len in range(1, 6):
    count_same = 0
    count_reverse = 0
    for i in range(run_len, len(all_nz_dirs)):
        prev = all_nz_dirs[i-run_len:i]
        if len(set(prev)) == 1:
            if all_nz_dirs[i] != prev[0]:
                count_reverse += 1
            else:
                count_same += 1
    total = count_same + count_reverse
    if total > 0:
        p_rev = count_reverse / total
        print(f"P(reversal | {run_len} same-dir): {p_rev:.4f} (n={total})")

print("\n--- Key Findings ---")
print("Look for any P(up) values significantly different from 0.5 in the volume analysis above.")
print("Look for any autocorrelation values marked with *** above.")
print("Look for any spread states that predict FV changes above.")
