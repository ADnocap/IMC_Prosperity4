"""
OSMIUM Final Analysis: Validate Hidden Pattern & Extract Trading Signal
========================================================================
Key finding from Phase 1+2: FV follows an OU-like process with:
- Integer steps of +/-1
- Strong negative AC at lag 1 (~-0.32)
- Mean reversion to ~10000
- VR test confirms strong anti-persistence

Now: quantify the exact edge, validate on day 0, and check for deeper structure.
"""
import numpy as np
import csv
from collections import defaultdict

def load_prices(path, product="ASH_COATED_OSMIUM"):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            if r['product'] == product:
                rows.append({
                    'ts': int(r['timestamp']),
                    'bid1': float(r['bid_price_1']) if r['bid_price_1'] else None,
                    'bv1': int(r['bid_volume_1']) if r['bid_volume_1'] else 0,
                    'ask1': float(r['ask_price_1']) if r['ask_price_1'] else None,
                    'av1': int(r['ask_volume_1']) if r['ask_volume_1'] else 0,
                    'bid2': float(r['bid_price_2']) if r['bid_price_2'] else None,
                    'bv2': int(r['bid_volume_2']) if r['bid_volume_2'] else 0,
                    'ask2': float(r['ask_price_2']) if r['ask_price_2'] else None,
                    'av2': int(r['ask_volume_2']) if r['ask_volume_2'] else 0,
                    'mid': float(r['mid_price']) if r['mid_price'] else None,
                })
    return rows

base = "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round1/"

# Load all days
data = {}
for day_key, day_file in [('d-2', 'day_-2'), ('d-1', 'day_-1'), ('d0', 'day_0')]:
    data[day_key] = load_prices(base + f"prices_round_1_{day_file}.csv")

def extract_fv_series(prices):
    """Extract clean FV from symmetric spread-16 states."""
    fvs = []
    for r in prices:
        if (r['bid1'] is not None and r['ask1'] is not None and
            r['bv1'] == r['av1'] and r['bv1'] > 0 and
            r['ask1'] - r['bid1'] == 16):
            fv = (r['bid1'] + r['ask1']) / 2
            fvs.append((r['ts'], fv))
    return fvs

def extract_fv_steps(fvs):
    """Get the sequence of FV changes (non-zero)."""
    steps = []
    prev_fv = fvs[0][1]
    prev_ts = fvs[0][0]
    for ts, fv in fvs[1:]:
        if fv != prev_fv:
            steps.append((ts, fv - prev_fv, fv, prev_fv))
            prev_fv = fv
            prev_ts = ts
    return steps

print("=" * 80)
print("OSMIUM FINAL ANALYSIS: EXACT EDGE QUANTIFICATION")
print("=" * 80)

# ══════════════════════════════════════════════════════════════════════════
# 1. STEP REVERSAL PROBABILITY CONDITIONED ON FV LEVEL
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("1. STEP REVERSAL PROBABILITY BY FV DISTANCE FROM 10000")
print("=" * 80)

for day_name, prices in data.items():
    fvs = extract_fv_series(prices)
    steps = extract_fv_steps(fvs)

    if len(steps) < 50:
        continue

    print(f"\n{day_name}:")

    # For each step, check if next step reverses, conditioned on FV level
    results_by_dist = defaultdict(lambda: {'same': 0, 'reverse': 0})
    results_by_prev_dir = defaultdict(lambda: {'same': 0, 'reverse': 0})

    for i in range(len(steps) - 1):
        ts, step, fv, prev_fv = steps[i]
        next_step = steps[i+1][1]

        dist = int(fv - 10000)
        dir_sign = int(np.sign(step))
        next_sign = int(np.sign(next_step))

        key = 'same' if dir_sign == next_sign else 'reverse'
        results_by_dist[dist][key] += 1
        results_by_prev_dir[dir_sign][key] += 1

    # By distance from 10000
    print(f"  Reversal prob by FV distance from 10000:")
    for dist in sorted(results_by_dist.keys()):
        d = results_by_dist[dist]
        total = d['same'] + d['reverse']
        if total >= 5:
            rev_prob = d['reverse'] / total
            print(f"    FV-10000 = {dist:+3d}: P(reverse)={rev_prob:.3f} (n={total})")

    # By previous direction
    for d in [-1, 1]:
        dd = results_by_prev_dir[d]
        total = dd['same'] + dd['reverse']
        print(f"  After step={d:+d}: P(reverse)={dd['reverse']/total:.3f} (n={total})")

# ══════════════════════════════════════════════════════════════════════════
# 2. CONDITIONAL STEP PROBABILITIES (Markov analysis)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("2. MARKOV CHAIN OF FV STEPS (2-step memory)")
print("=" * 80)

for day_name, prices in data.items():
    fvs = extract_fv_series(prices)
    steps = extract_fv_steps(fvs)

    if len(steps) < 50:
        continue

    print(f"\n{day_name}:")

    # 2-step transition matrix
    trans = defaultdict(lambda: defaultdict(int))
    for i in range(len(steps) - 2):
        s1 = int(np.sign(steps[i][1]))
        s2 = int(np.sign(steps[i+1][1]))
        s3 = int(np.sign(steps[i+2][1]))
        trans[(s1, s2)][s3] += 1

    for (s1, s2) in sorted(trans.keys()):
        total = sum(trans[(s1, s2)].values())
        probs = {k: v/total for k, v in trans[(s1, s2)].items()}
        print(f"  After ({s1:+d},{s2:+d}): ", end="")
        for s3 in [-1, 1]:
            p = probs.get(s3, 0)
            print(f"P(next={s3:+d})={p:.3f} ", end="")
        print(f"(n={total})")

# ══════════════════════════════════════════════════════════════════════════
# 3. OPTIMAL MEAN REVERSION SIGNAL
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("3. OU MEAN-REVERSION: EDGE PER TRADE")
print("=" * 80)

for day_name, prices in data.items():
    fvs = extract_fv_series(prices)
    ts_arr = np.array([t for t, _ in fvs])
    fv_arr = np.array([f for _, f in fvs])

    print(f"\n{day_name}:")

    # Strategy: if FV > mean, expect down; if FV < mean, expect up
    # Use rolling mean as estimate of the OU center
    for window in [100, 200, 500, 1000]:
        if len(fv_arr) <= window:
            continue

        predictions_correct = 0
        predictions_total = 0
        pnl_sum = 0

        for i in range(window, len(fv_arr) - 1):
            rolling_mean = np.mean(fv_arr[max(0, i-window):i])
            fv_now = fv_arr[i]
            fv_next = fv_arr[i+1]
            actual_change = fv_next - fv_now

            if actual_change == 0:
                continue

            # Prediction: if FV > rolling_mean, predict down (-1); else up (+1)
            predicted_dir = -1 if fv_now > rolling_mean else 1
            actual_dir = np.sign(actual_change)

            if predicted_dir == actual_dir:
                predictions_correct += 1
            predictions_total += 1
            pnl_sum += predicted_dir * actual_change

        if predictions_total > 0:
            accuracy = predictions_correct / predictions_total
            print(f"  Window={window:4d}: accuracy={accuracy:.3f}, "
                  f"total_pnl={pnl_sum:+.1f}, avg_pnl={pnl_sum/predictions_total:+.4f}, "
                  f"n={predictions_total}")

    # Strategy 2: Last-step reversal
    steps = extract_fv_steps(fvs)
    correct = 0
    total = 0
    for i in range(len(steps) - 1):
        predicted = -np.sign(steps[i][1])
        actual = np.sign(steps[i+1][1])
        if predicted == actual:
            correct += 1
        total += 1
    print(f"  Last-step reversal: accuracy={correct/total:.3f} (n={total})")

    # Strategy 3: Combined (distance from mean + last step)
    # If both agree -> stronger signal
    correct_agree = 0
    total_agree = 0
    correct_disagree = 0
    total_disagree = 0

    fv_lookup = dict(zip(ts_arr.tolist(), fv_arr.tolist()))
    rolling_means = {}
    for i in range(200, len(fv_arr)):
        rolling_means[ts_arr[i]] = np.mean(fv_arr[i-200:i])

    for i in range(1, len(steps) - 1):
        ts = steps[i][0]
        fv = steps[i][2]
        rm = rolling_means.get(ts)
        if rm is None:
            continue

        # Signal 1: mean reversion (distance from rolling mean)
        mr_signal = -np.sign(fv - rm) if abs(fv - rm) > 0.5 else 0

        # Signal 2: step reversal
        rev_signal = -np.sign(steps[i][1])

        actual = np.sign(steps[i+1][1])

        if mr_signal == rev_signal and mr_signal != 0:
            if mr_signal == actual:
                correct_agree += 1
            total_agree += 1
        elif mr_signal != 0 and rev_signal != 0 and mr_signal != rev_signal:
            # Conflicting signals - which is right?
            if mr_signal == actual:
                correct_disagree += 1
            total_disagree += 1

    if total_agree > 0:
        print(f"  Combined (agree): accuracy={correct_agree/total_agree:.3f} (n={total_agree})")
    if total_disagree > 0:
        print(f"  Conflict (MR correct): accuracy={correct_disagree/total_disagree:.3f} (n={total_disagree})")

# ══════════════════════════════════════════════════════════════════════════
# 4. BOOK STATE SEQUENCE ANALYSIS (Hidden Markov?)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("4. BOOK STATE SEQUENCE -> FV PREDICTION")
print("=" * 80)

def classify_state(r):
    has_bid = r['bid1'] is not None
    has_ask = r['ask1'] is not None
    if not has_bid and not has_ask:
        return 'E'  # empty
    if not has_bid:
        return 'A'  # ask only
    if not has_ask:
        return 'B'  # bid only
    spread = r['ask1'] - r['bid1']
    sym = r['bv1'] == r['av1'] and r['bv1'] > 0
    if spread == 16 and sym:
        return 'S'  # symmetric
    elif spread <= 13:
        return 'T'  # tight (post-trade)
    else:
        return 'W'  # wide

for day_name, prices in data.items():
    print(f"\n{day_name}:")

    # Build state sequence
    states = [classify_state(r) for r in prices]

    # Forward-fill FV from symmetric states
    fv_series = [None] * len(prices)
    last_fv = None
    for i, r in enumerate(prices):
        if states[i] == 'S':
            last_fv = (r['bid1'] + r['ask1']) / 2
        fv_series[i] = last_fv

    # When transitioning FROM a non-symmetric state TO a symmetric state,
    # what does the new FV tell us vs the old FV?
    patterns = defaultdict(lambda: {'up': 0, 'down': 0, 'same': 0})

    for i in range(1, len(prices)):
        if states[i] == 'S' and states[i-1] != 'S':
            prev_fv = fv_series[i-1]  # last known FV before this transition
            curr_fv = (prices[i]['bid1'] + prices[i]['ask1']) / 2

            if prev_fv is not None:
                # What was the intervening state?
                prev_state = states[i-1]
                change = curr_fv - prev_fv
                if change > 0:
                    patterns[prev_state]['up'] += 1
                elif change < 0:
                    patterns[prev_state]['down'] += 1
                else:
                    patterns[prev_state]['same'] += 1

    print(f"  State -> FV change when returning to symmetric:")
    for state in ['A', 'B', 'T', 'W', 'E']:
        p = patterns[state]
        total = p['up'] + p['down'] + p['same']
        if total > 10:
            print(f"    {state}: up={p['up']} ({100*p['up']/total:.0f}%), "
                  f"down={p['down']} ({100*p['down']/total:.0f}%), "
                  f"same={p['same']} ({100*p['same']/total:.0f}%), n={total}")

    # Look at sequences: what predicts FV change?
    # After ASK_ONLY -> symmetric: FV more likely to go up (someone sold, depleting ask)
    # After BID_ONLY -> symmetric: FV more likely to go down (someone bought, depleting bid)

# ══════════════════════════════════════════════════════════════════════════
# 5. DEEP: WHAT DETERMINES SPREAD=18 vs SPREAD=19?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("5. SPREAD 18 vs 19: WHAT'S THE DIFFERENCE?")
print("=" * 80)

for day_name, prices in data.items():
    print(f"\n{day_name}:")

    for sp_target in [18, 19]:
        ticks = []
        for r in prices:
            if (r['bid1'] is not None and r['ask1'] is not None and
                r['ask1'] - r['bid1'] == sp_target):
                ticks.append(r)

        if not ticks:
            continue

        print(f"\n  Spread={sp_target} ({len(ticks)} ticks):")

        # Which side is "normal" (8 from FV) and which is "wide" (10 or 11)?
        # We can infer FV from the "normal" side
        for r in ticks[:20]:
            # If spread=18: one side at +8, other at +10 (L2 gap=2)
            # If spread=19: one side at +8, other at +11 (L2 gap=3)
            gap = sp_target - 16  # 2 for 18, 3 for 19
            # The "wide" side is the one that used to be L2

            # Check which side has the "normal" volume pattern (10-15)
            # and which has the "L2" volume pattern (~20-30)
            bid_is_wide = r['bv1'] > 15  # L2 bid became L1
            ask_is_wide = r['av1'] > 15  # L2 ask became L1

            if bid_is_wide and not ask_is_wide:
                inferred_fv = r['ask1'] - 8  # ask is normal
            elif ask_is_wide and not bid_is_wide:
                inferred_fv = r['bid1'] + 8  # bid is normal
            else:
                inferred_fv = (r['bid1'] + r['ask1']) / 2

            print(f"    ts={r['ts']:6d}: bid={int(r['bid1'])}x{r['bv1']:2d} "
                  f"ask={int(r['ask1'])}x{r['av1']:2d} "
                  f"inferred_FV={inferred_fv:.0f}")

        # Volume analysis
        bvols = [r['bv1'] for r in ticks]
        avols = [r['av1'] for r in ticks]
        print(f"  Bid volumes: mean={np.mean(bvols):.1f}, mode-like: "
              f"{sorted(set(bvols), key=lambda x: -bvols.count(x))[:5]}")
        print(f"  Ask volumes: mean={np.mean(avols):.1f}, mode-like: "
              f"{sorted(set(avols), key=lambda x: -avols.count(x))[:5]}")

# ══════════════════════════════════════════════════════════════════════════
# 6. VALIDATE ON DAY 0: TRADING SIMULATION
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("6. DAY 0 TRADING SIMULATION (validation)")
print("=" * 80)

# Use days -2 and -1 to calibrate, test on day 0
d0_prices = data['d0']
d0_fvs = extract_fv_series(d0_prices)
d0_steps = extract_fv_steps(d0_fvs)

# Build FV timeseries for day 0 (forward-filled)
fv_by_ts_d0 = {}
last_fv = None
for r in d0_prices:
    if (r['bid1'] is not None and r['ask1'] is not None and
        r['bv1'] == r['av1'] and r['bv1'] > 0 and
        r['ask1'] - r['bid1'] == 16):
        last_fv = (r['bid1'] + r['ask1']) / 2
    if last_fv is not None:
        fv_by_ts_d0[r['ts']] = last_fv

# Strategy 1: Pure mean-reversion (trade against distance from 10000)
print("\nStrategy 1: Trade against distance from 10000")
print("  (Buy when FV<10000, sell when FV>10000)")
position = 0
pnl = 0
trades = 0
max_pos = 20

fv_values = list(fv_by_ts_d0.values())
for i in range(1, len(fv_values)):
    fv = fv_values[i]
    prev_fv = fv_values[i-1]

    if fv == prev_fv:
        continue

    dist = fv - 10000
    # Simple: go short when above, long when below
    target_pos = max(-max_pos, min(max_pos, -int(dist)))

    if target_pos != position:
        trade_size = target_pos - position
        pnl -= trade_size * fv  # cost of getting into position
        position = target_pos
        trades += 1

# Close position at end
if position != 0:
    pnl += position * fv_values[-1]

print(f"  PnL: {pnl:+.0f}, trades: {trades}, final_pos: {position}")

# Strategy 2: Step reversal
print("\nStrategy 2: Trade step reversals")
print("  (After FV goes up, short; after FV goes down, long)")
position = 0
pnl = 0
trades = 0

for i in range(1, len(d0_steps)):
    ts, step, fv, prev_fv = d0_steps[i-1]
    next_ts, next_step, next_fv, _ = d0_steps[i]

    # After a step, take opposite position
    target_pos = -int(np.sign(step)) * 5  # small fixed size

    if target_pos != position:
        # Execute at the FV (optimistic, but we're just checking direction)
        pnl -= (target_pos - position) * fv
        position = target_pos
        trades += 1

# Close
if position != 0:
    final_fv = d0_steps[-1][2]
    pnl += position * final_fv

print(f"  PnL: {pnl:+.0f}, trades: {trades}")

# Strategy 3: Combined signal with more realistic execution
print("\nStrategy 3: Combined OU + reversal with realistic MM execution")
position = 0
pnl = 0
trades = 0
fv_history = []
entry_prices = []

for r in d0_prices:
    if (r['bid1'] is None or r['ask1'] is None):
        continue

    spread = r['ask1'] - r['bid1']
    is_sym = r['bv1'] == r['av1'] and r['bv1'] > 0 and spread == 16

    if is_sym:
        fv = (r['bid1'] + r['ask1']) / 2
        fv_history.append(fv)

        if len(fv_history) < 10:
            continue

        # Signal components
        dist_10k = fv - 10000
        last_change = fv_history[-1] - fv_history[-2] if fv_history[-1] != fv_history[-2] else 0

        # Combined signal: fade distance + fade last move
        signal = 0
        if dist_10k > 3:
            signal -= 1  # sell
        elif dist_10k < -3:
            signal += 1  # buy

        if last_change > 0:
            signal -= 0.5  # fade up
        elif last_change < 0:
            signal += 0.5  # fade down

        # Target position based on signal
        target = max(-max_pos, min(max_pos, int(signal * 10)))

        # Execute passively: we'd quote and get filled over time
        # Simplified: we trade at mid +/- 1 (inside the spread)
        if target > position:
            qty = min(target - position, 5)
            exec_price = fv - 1  # buy at FV - 1 (inside bid)
            pnl -= qty * exec_price
            position += qty
            trades += 1
        elif target < position:
            qty = min(position - target, 5)
            exec_price = fv + 1  # sell at FV + 1 (inside ask)
            pnl += qty * exec_price
            position -= qty
            trades += 1

# Close at mid
if position != 0 and fv_history:
    pnl += position * fv_history[-1]

print(f"  PnL: {pnl:+.0f}, trades: {trades}, final_pos: {position}")

# ══════════════════════════════════════════════════════════════════════════
# 7. QUANTIFY THE EXACT EDGE
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("7. EDGE QUANTIFICATION")
print("=" * 80)

# What is the expected profit from knowing FV will revert?
for day_name in ['d-2', 'd-1', 'd0']:
    prices = data[day_name]
    fvs = extract_fv_series(prices)
    steps = extract_fv_steps(fvs)

    if len(steps) < 50:
        continue

    print(f"\n{day_name}:")

    # If we buy 1 unit at FV-8 (the bid) whenever FV reverts down,
    # and sell 1 unit at FV+8 (the ask) whenever FV reverts up:

    # More precisely: at each FV step, what is the expected future movement?
    for horizon in [1, 2, 3, 5, 10]:
        gains = []
        for i in range(len(steps) - horizon):
            current_fv = steps[i][2]
            future_fv = steps[min(i + horizon, len(steps)-1)][2]
            # If we predicted reversal and it happened
            predicted_dir = -np.sign(steps[i][1])
            actual_move = future_fv - current_fv
            gain = predicted_dir * actual_move
            gains.append(gain)

        g = np.array(gains)
        print(f"  Reversal signal, {horizon}-step horizon: "
              f"mean_gain={np.mean(g):+.3f}, win_rate={np.mean(g > 0):.3f}, "
              f"sharpe={np.mean(g)/np.std(g)*np.sqrt(len(g)):.2f}")

    # Edge from mean-reversion to 10000
    print(f"\n  Distance-based signal:")
    fv_arr = np.array([f for _, f in fvs])
    for threshold in [2, 3, 5, 7, 10]:
        high_mask = fv_arr[:-10] > 10000 + threshold
        low_mask = fv_arr[:-10] < 10000 - threshold
        future = fv_arr[10:]

        if np.sum(high_mask) > 5:
            avg_ret_high = np.mean(future[:len(high_mask)][high_mask] - fv_arr[:-10][high_mask])
            print(f"    FV > 10000+{threshold}: avg 10-step return = {avg_ret_high:+.3f} (n={np.sum(high_mask)})")
        if np.sum(low_mask) > 5:
            avg_ret_low = np.mean(future[:len(low_mask)][low_mask] - fv_arr[:-10][low_mask])
            print(f"    FV < 10000-{threshold}: avg 10-step return = {avg_ret_low:+.3f} (n={np.sum(low_mask)})")

# ══════════════════════════════════════════════════════════════════════════
# 8. COMPARE WITH PEPPER ROOT
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("8. PEPPER ROOT COMPARISON")
print("=" * 80)

for day_key, day_file in [('d-2', 'day_-2'), ('d0', 'day_0')]:
    pep = load_prices(base + f"prices_round_1_{day_file}.csv", "INTARIAN_PEPPER_ROOT")

    # Extract FV
    pep_fvs = []
    for r in pep:
        if (r['bid1'] is not None and r['ask1'] is not None):
            pep_fvs.append((r['ts'], (r['bid1'] + r['ask1']) / 2, r['ask1'] - r['bid1']))

    if not pep_fvs:
        continue

    fv_arr = np.array([f for _, f, _ in pep_fvs])
    sp_arr = np.array([s for _, _, s in pep_fvs])
    rets = np.diff(fv_arr)

    print(f"\n{day_key} PEPPER ROOT ({len(pep_fvs)} two-sided ticks):")
    print(f"  Mid: mean={np.mean(fv_arr):.2f}, std={np.std(fv_arr):.2f}")
    print(f"  Spread: mean={np.mean(sp_arr):.2f}, median={np.median(sp_arr):.0f}")
    print(f"  Returns: mean={np.mean(rets):.4f}, std={np.std(rets):.4f}")

    # Autocorrelation
    for lag in [1, 2, 5, 10]:
        if len(rets) > lag:
            ac = np.corrcoef(rets[:-lag], rets[lag:])[0, 1]
            print(f"  Return AC({lag}): {ac:+.4f}")

    # Variance ratio
    var1 = np.var(rets)
    for k in [2, 5, 10, 20]:
        krets = fv_arr[k:] - fv_arr[:-k]
        vr = np.var(krets) / (k * var1) if var1 > 0 else 0
        print(f"  VR({k}): {vr:.4f}")

    # Is PEPPER also mean-reverting?
    X = fv_arr[:-1]
    dX = rets
    if np.std(X) > 0:
        beta = np.polyfit(X, dX, 1)
        theta = -beta[0]
        mu = -beta[1] / beta[0] if abs(beta[0]) > 1e-10 else 0
        print(f"  OU theta: {theta:.6f}, mu: {mu:.1f}")
        if theta > 0:
            print(f"  OU half-life: {np.log(2)/theta:.1f} ticks")

# ══════════════════════════════════════════════════════════════════════════
# 9. KEY PATTERN SUMMARY
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("9. PATTERN SUMMARY")
print("=" * 80)
print("""
OSMIUM Hidden Pattern Discovery:
=================================

1. FAIR VALUE STRUCTURE:
   - FV always integer
   - Market maker quotes at FV +/- 8 (spread=16)
   - Book is symmetric (bv1 = av1) in 59% of ticks
   - When symmetric with spread=16: this is the "clean" FV signal

2. FV DYNAMICS (THE KEY FINDING):
   - FV changes in steps of +/-1 (~99% of moves)
   - ~1800 steps per day, roughly every 550 timestamps
   - STRONG NEGATIVE AUTOCORRELATION in steps: AC(1) = -0.32
   - Step reversal probability: ~65-66%
   - This means: after FV goes up, it reverses 65% of the time!
   - Variance ratio: VR(10) = 0.55, VR(100) = 0.44
   - Hurst exponent on FV returns: ~0.34 (strong mean reversion)

3. MEAN REVERSION:
   - FV oscillates around a slow-moving center near 10000
   - OU process with half-life ~50-110 symmetric ticks
   - When FV is far from 10000, it strongly reverts

4. TRADING EDGE:
   - Step reversal alone gives ~65% directional accuracy
   - Combined with distance-from-mean: even stronger
   - The spread of 16 means the MM can capture 2-4 points per round trip
   - With position limits of 50(?), significant PnL opportunity

5. WHAT'S NOT INFORMATIVE:
   - Volume (uniform 10-15, no signal)
   - Cross-asset correlation (zero with PEPPER)
   - Order book imbalance in asymmetric states (weak/inconsistent)
   - L2 depth (not predictive)

6. BOOK STATE TRANSITIONS:
   - Symmetric(16) -> Wide(18/19): L1 gets hit, L2 becomes new L1
   - Wide -> Symmetric: MM re-quotes fresh symmetric book
   - One-sided: one side completely depleted (trade happened)
   - Tight: post-trade residual orders, brief
""")

print("\nANALYSIS COMPLETE")
