"""
OSMIUM Deep Analysis Phase 2: Clean FV Extraction & Hidden Pattern Detection
============================================================================
Focus on extracting the TRUE fair value from clean (two-sided) book states,
then analyze its dynamics for hidden patterns.
"""
import numpy as np
import csv
from collections import defaultdict

# ── Load data ──
def load_prices(path, product="ASH_COATED_OSMIUM"):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            if r['product'] == product:
                row = {
                    'ts': int(r['timestamp']),
                    'bid1': float(r['bid_price_1']) if r['bid_price_1'] else None,
                    'bv1': int(r['bid_volume_1']) if r['bid_volume_1'] else 0,
                    'bid2': float(r['bid_price_2']) if r['bid_price_2'] else None,
                    'bv2': int(r['bid_volume_2']) if r['bid_volume_2'] else 0,
                    'bid3': float(r['bid_price_3']) if r['bid_price_3'] else None,
                    'bv3': int(r['bid_volume_3']) if r['bid_volume_3'] else 0,
                    'ask1': float(r['ask_price_1']) if r['ask_price_1'] else None,
                    'av1': int(r['ask_volume_1']) if r['ask_volume_1'] else 0,
                    'ask2': float(r['ask_price_2']) if r['ask_price_2'] else None,
                    'av2': int(r['ask_volume_2']) if r['ask_volume_2'] else 0,
                    'ask3': float(r['ask_price_3']) if r['ask_price_3'] else None,
                    'av3': int(r['ask_volume_3']) if r['ask_volume_3'] else 0,
                    'mid': float(r['mid_price']) if r['mid_price'] else None,
                }
                rows.append(row)
    return rows

def load_trades(path, product="ASH_COATED_OSMIUM"):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            if r['symbol'] == product:
                rows.append({
                    'ts': int(r['timestamp']),
                    'price': float(r['price']),
                    'qty': int(r['quantity']),
                })
    return rows

base = "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round1/"

print("=" * 80)
print("OSMIUM DEEP ANALYSIS - CLEAN FAIR VALUE EXTRACTION")
print("=" * 80)

days = {
    'day-2': (load_prices(base + "prices_round_1_day_-2.csv"),
              load_trades(base + "trades_round_1_day_-2.csv")),
    'day-1': (load_prices(base + "prices_round_1_day_-1.csv"),
              load_trades(base + "trades_round_1_day_-1.csv")),
    'day0':  (load_prices(base + "prices_round_1_day_0.csv"),
              load_trades(base + "trades_round_1_day_0.csv")),
}

# ══════════════════════════════════════════════════════════════════════════
# A. CLASSIFY EACH TICK INTO BOOK STATES
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("A. BOOK STATE CLASSIFICATION")
print("=" * 80)

def classify_tick(r):
    """Classify a tick into a book state."""
    has_bid = r['bid1'] is not None
    has_ask = r['ask1'] is not None

    if not has_bid and not has_ask:
        return 'EMPTY'
    if not has_bid:
        return 'ASK_ONLY'
    if not has_ask:
        return 'BID_ONLY'

    spread = r['ask1'] - r['bid1']
    symmetric = r['bv1'] == r['av1'] and r['bv1'] > 0

    if spread == 16 and symmetric:
        return 'MM_SYMMETRIC_16'  # core market maker state
    elif spread == 16:
        return 'MM_ASYM_16'
    elif spread in (18, 19):
        return 'MM_WIDE_18_19'
    elif spread == 21:
        return 'MM_WIDE_21'
    elif spread <= 13:
        return 'TIGHT_SPREAD'
    else:
        return f'OTHER_{int(spread)}'

for day_name, (prices, trades) in days.items():
    states = defaultdict(int)
    for r in prices:
        s = classify_tick(r)
        states[s] += 1

    print(f"\n{day_name}:")
    for s, c in sorted(states.items(), key=lambda x: -x[1]):
        print(f"  {s:25s}: {c:5d} ({100*c/len(prices):.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# B. EXTRACT CLEAN FV FROM MM_SYMMETRIC_16 STATES
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("B. CLEAN FAIR VALUE (FV) FROM SYMMETRIC STATES")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    # Extract FV from symmetric states
    fvs = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fv = (r['bid1'] + r['ask1']) / 2
            fvs.append((r['ts'], fv))

    if not fvs:
        continue

    ts_arr = np.array([t for t, _ in fvs])
    fv_arr = np.array([f for _, f in fvs])

    print(f"\n{day_name} ({len(fvs)} symmetric ticks):")
    print(f"  FV: mean={np.mean(fv_arr):.2f}, std={np.std(fv_arr):.2f}, "
          f"min={np.min(fv_arr):.1f}, max={np.max(fv_arr):.1f}")
    print(f"  FV range: {np.max(fv_arr) - np.min(fv_arr):.1f}")
    print(f"  Start FV: {fv_arr[0]:.1f}, End FV: {fv_arr[-1]:.1f}, "
          f"Net drift: {fv_arr[-1] - fv_arr[0]:+.1f}")

    # FV returns (only between consecutive symmetric states)
    fv_rets = np.diff(fv_arr)
    print(f"  FV returns: mean={np.mean(fv_rets):.4f}, std={np.std(fv_rets):.4f}")

    # Autocorrelation of FV returns
    print(f"  FV return autocorrelations:")
    for lag in [1, 2, 3, 5, 10, 20, 50]:
        if len(fv_rets) > lag + 1:
            ac = np.corrcoef(fv_rets[:-lag], fv_rets[lag:])[0, 1]
            sig = " ***" if abs(ac) > 2/np.sqrt(len(fv_rets)) else ""
            print(f"    lag {lag:3d}: {ac:+.4f}{sig}")

    # FV change distribution
    print(f"  FV change distribution:")
    unique_ch, counts = np.unique(fv_rets, return_counts=True)
    for ch, c in sorted(zip(unique_ch, counts), key=lambda x: -x[1])[:15]:
        print(f"    {ch:+6.1f}: {c:5d} ({100*c/len(fv_rets):.1f}%)")

    # Time between FV changes
    change_indices = np.where(fv_rets != 0)[0]
    if len(change_indices) > 1:
        inter_change_ticks = np.diff(change_indices)
        inter_change_time = np.diff(ts_arr[change_indices])
        print(f"\n  Time between FV changes:")
        print(f"    Mean: {np.mean(inter_change_time):.1f} ts ({np.mean(inter_change_ticks):.1f} sym ticks)")
        print(f"    Median: {np.median(inter_change_time):.1f} ts")
        print(f"    Std: {np.std(inter_change_time):.1f} ts")

        # Distribution of FV jump sizes
        jump_sizes = fv_rets[change_indices]
        print(f"\n  FV jump size distribution:")
        unique_js, js_counts = np.unique(jump_sizes, return_counts=True)
        for js, jc in sorted(zip(unique_js, js_counts), key=lambda x: -x[1])[:10]:
            print(f"    {js:+.1f}: {jc:4d} ({100*jc/len(jump_sizes):.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# C. FV TRAJECTORY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("C. FV TRAJECTORY (10 windows per day)")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    fvs = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fvs.append((r['ts'], (r['bid1'] + r['ask1']) / 2))

    if not fvs:
        continue

    ts_arr = np.array([t for t, _ in fvs])
    fv_arr = np.array([f for _, f in fvs])

    max_ts = max(r['ts'] for r in prices)

    print(f"\n{day_name}:")
    for b in range(10):
        lo = b * max_ts / 10
        hi = (b + 1) * max_ts / 10
        mask = (ts_arr >= lo) & (ts_arr < hi)
        if np.sum(mask) > 5:
            seg = fv_arr[mask]
            rets = np.diff(seg)
            print(f"  Window {b} (ts {int(lo):6d}-{int(hi):6d}): "
                  f"FV_start={seg[0]:.0f}, FV_end={seg[-1]:.0f}, "
                  f"mean={np.mean(seg):.1f}, vol={np.std(rets):.3f}, "
                  f"drift={seg[-1]-seg[0]:+.0f}, n={np.sum(mask)}")

# ══════════════════════════════════════════════════════════════════════════
# D. WHAT HAPPENS AROUND TRADES?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("D. FV BEHAVIOR AROUND TRADES")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    # Build FV timeseries (from symmetric states, forward-filled)
    fv_by_ts = {}
    last_fv = None
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            last_fv = (r['bid1'] + r['ask1']) / 2
        if last_fv is not None:
            fv_by_ts[r['ts']] = last_fv

    print(f"\n{day_name} ({len(trades)} trades):")

    # For each trade, look at FV before and after
    fv_before = []
    fv_after = []
    trade_vs_fv = []
    for t in trades:
        ts = t['ts']
        # FV before trade
        fv_b = None
        for dt in range(0, 2000, 100):
            if (ts - dt) in fv_by_ts:
                fv_b = fv_by_ts[ts - dt]
                break
        # FV after trade
        fv_a = None
        for dt in range(100, 3000, 100):
            if (ts + dt) in fv_by_ts:
                fv_a = fv_by_ts[ts + dt]
                break

        if fv_b is not None and fv_a is not None:
            fv_before.append(fv_b)
            fv_after.append(fv_a)
            trade_vs_fv.append(t['price'] - fv_b)

    if fv_before:
        fb = np.array(fv_before)
        fa = np.array(fv_after)
        tvf = np.array(trade_vs_fv)
        fv_change = fa - fb

        print(f"  Trade price vs FV: mean={np.mean(tvf):+.2f}, std={np.std(tvf):.2f}")
        print(f"  FV change around trade: mean={np.mean(fv_change):+.4f}, std={np.std(fv_change):.4f}")

        # Bucket by trade direction (relative to FV)
        buys = tvf > 0
        sells = tvf < 0

        if np.sum(buys) > 5:
            print(f"  After BUY trades: avg FV change = {np.mean(fv_change[buys]):+.4f} (n={np.sum(buys)})")
        if np.sum(sells) > 5:
            print(f"  After SELL trades: avg FV change = {np.mean(fv_change[sells]):+.4f} (n={np.sum(sells)})")

# ══════════════════════════════════════════════════════════════════════════
# E. FV PROCESS IDENTIFICATION
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("E. FV PROCESS IDENTIFICATION")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    fvs = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fvs.append((r['ts'], (r['bid1'] + r['ask1']) / 2))

    if len(fvs) < 100:
        continue

    ts_arr = np.array([t for t, _ in fvs])
    fv_arr = np.array([f for _, f in fvs])

    print(f"\n{day_name}:")

    # Test 1: Random Walk? (variance ratio test)
    print(f"\n  Variance Ratio Test (RW if VR=1):")
    rets = np.diff(fv_arr)
    var1 = np.var(rets)
    for k in [2, 5, 10, 20, 50, 100]:
        if len(fv_arr) > k:
            krets = fv_arr[k:] - fv_arr[:-k]
            vark = np.var(krets)
            vr = vark / (k * var1) if var1 > 0 else float('nan')
            print(f"    VR({k:3d}) = {vr:.4f}")

    # Test 2: Mean reversion speed (Ornstein-Uhlenbeck fit)
    # dX = -theta*(X - mu)*dt + sigma*dW
    # Regression: X(t+1) - X(t) = alpha + beta * X(t) + epsilon
    print(f"\n  OU Fit (mean reversion):")
    X = fv_arr[:-1]
    dX = np.diff(fv_arr)
    if np.std(X) > 0:
        beta = np.polyfit(X, dX, 1)
        theta = -beta[0]  # mean reversion speed
        mu = -beta[1] / beta[0] if abs(beta[0]) > 1e-10 else float('nan')
        print(f"    theta (reversion speed) = {theta:.6f}")
        print(f"    mu (long-run mean) = {mu:.2f}")
        print(f"    Half-life = {np.log(2)/theta:.1f} ticks" if theta > 0 else
              f"    NOT mean reverting (theta <= 0)")
        corr = np.corrcoef(X, dX)[0, 1]
        print(f"    X vs dX correlation: {corr:.4f}")

    # Test 3: Trend analysis
    print(f"\n  Linear trend:")
    t_idx = np.arange(len(fv_arr))
    slope, intercept = np.polyfit(t_idx, fv_arr, 1)
    residuals = fv_arr - (slope * t_idx + intercept)
    r_squared = 1 - np.var(residuals) / np.var(fv_arr)
    print(f"    Slope: {slope:.4f} per tick, R2: {r_squared:.4f}")
    print(f"    Projected drift: {slope * len(fv_arr):.1f} over day")

    # Test 4: Is FV integer or half-integer?
    print(f"\n  FV discreteness:")
    fv_mod = fv_arr % 1
    unique_mod, mod_counts = np.unique(fv_mod, return_counts=True)
    for m, c in sorted(zip(unique_mod, mod_counts), key=lambda x: -x[1])[:5]:
        print(f"    FV mod 1 = {m:.1f}: {c} ({100*c/len(fv_arr):.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# F. TIGHT SPREAD ANALYSIS (post-trade states)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("F. TIGHT SPREAD STATES (potential information leakage)")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    tight_ticks = []
    for i, r in enumerate(prices):
        state = classify_tick(r)
        if state == 'TIGHT_SPREAD':
            # Get context
            spread = r['ask1'] - r['bid1']

            # Find nearest symmetric FV before
            fv_before = None
            for j in range(i-1, max(i-20, -1), -1):
                if classify_tick(prices[j]) == 'MM_SYMMETRIC_16':
                    fv_before = (prices[j]['bid1'] + prices[j]['ask1']) / 2
                    break

            # Find nearest symmetric FV after
            fv_after = None
            for j in range(i+1, min(i+20, len(prices))):
                if classify_tick(prices[j]) == 'MM_SYMMETRIC_16':
                    fv_after = (prices[j]['bid1'] + prices[j]['ask1']) / 2
                    break

            tight_ticks.append({
                'ts': r['ts'],
                'bid1': r['bid1'], 'ask1': r['ask1'],
                'bv1': r['bv1'], 'av1': r['av1'],
                'spread': spread,
                'mid': (r['bid1'] + r['ask1']) / 2,
                'fv_before': fv_before,
                'fv_after': fv_after,
            })

    print(f"\n{day_name}: {len(tight_ticks)} tight spread ticks")

    if tight_ticks:
        spreads = [t['spread'] for t in tight_ticks]
        print(f"  Spread distribution:")
        for s, c in sorted(defaultdict(int, [(s, 1) for s in spreads]).items()):
            pass
        unique_s, s_counts = np.unique(spreads, return_counts=True)
        for s, c in sorted(zip(unique_s, s_counts), key=lambda x: -x[1]):
            print(f"    {s:.0f}: {c}")

        # What's the tight mid vs FV?
        for t in tight_ticks[:20]:
            delta_before = t['mid'] - t['fv_before'] if t['fv_before'] else None
            delta_after = t['fv_after'] - t['fv_before'] if (t['fv_after'] and t['fv_before']) else None
            print(f"  ts={t['ts']:6d}: bid={int(t['bid1'])}x{t['bv1']:2d} ask={int(t['ask1'])}x{t['av1']:2d} "
                  f"spread={t['spread']:.0f} mid={t['mid']:.1f} "
                  f"fv_before={t['fv_before'] if t['fv_before'] else '?':>7} "
                  f"fv_after={t['fv_after'] if t['fv_after'] else '?':>7} "
                  f"fv_change={delta_after if delta_after is not None else '?'}")

        # Does tight mid predict FV direction?
        predictive = []
        for t in tight_ticks:
            if t['fv_before'] is not None and t['fv_after'] is not None:
                side = 'buy' if t['mid'] > t['fv_before'] else ('sell' if t['mid'] < t['fv_before'] else 'neutral')
                fv_change = t['fv_after'] - t['fv_before']
                predictive.append((side, fv_change))

        if predictive:
            for side in ['buy', 'sell', 'neutral']:
                subset = [fc for s, fc in predictive if s == side]
                if subset:
                    print(f"  Tight spread {side}: avg FV change = {np.mean(subset):+.4f} (n={len(subset)})")

# ══════════════════════════════════════════════════════════════════════════
# G. DEEPER LOOK AT FV STEPS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("G. FV STEP ANALYSIS")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    fvs = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fvs.append((r['ts'], int(r['bid1']), int(r['ask1']),
                        (r['bid1'] + r['ask1']) / 2, r['bv1']))

    if not fvs:
        continue

    print(f"\n{day_name}: FV steps (first 100 changes)")

    # Show each FV change
    changes = 0
    prev_fv = fvs[0][3]
    for ts, bid, ask, fv, vol in fvs[1:]:
        if fv != prev_fv and changes < 100:
            print(f"  ts={ts:6d}: FV {prev_fv:.0f} -> {fv:.0f} ({fv-prev_fv:+.0f})  "
                  f"bid={bid} ask={ask} vol={vol}")
            changes += 1
        prev_fv = fv

    # FV step statistics
    prev_fv = fvs[0][3]
    step_sizes = []
    step_times = []
    prev_ts = fvs[0][0]
    for ts, bid, ask, fv, vol in fvs[1:]:
        if fv != prev_fv:
            step_sizes.append(fv - prev_fv)
            step_times.append(ts - prev_ts)
            prev_ts = ts
            prev_fv = fv

    if step_sizes:
        ss = np.array(step_sizes)
        st = np.array(step_times)
        print(f"\n  Total FV changes: {len(ss)}")
        print(f"  Step sizes: mean={np.mean(ss):+.2f}, std={np.std(ss):.2f}")
        print(f"  Step size distribution:")
        unique_ss, ss_counts = np.unique(ss, return_counts=True)
        for s, c in sorted(zip(unique_ss, ss_counts), key=lambda x: -x[1])[:15]:
            print(f"    {s:+5.1f}: {c:4d} ({100*c/len(ss):.1f}%)")

        print(f"\n  Time between steps: mean={np.mean(st):.0f}, median={np.median(st):.0f}, std={np.std(st):.0f}")

        # Direction persistence (does the FV tend to continue or reverse?)
        print(f"\n  Direction persistence:")
        dirs = np.sign(ss)
        for lag in [1, 2, 3, 5, 10]:
            if len(dirs) > lag:
                matches = np.sum(dirs[:-lag] == dirs[lag:])
                total = len(dirs) - lag
                print(f"    lag {lag}: same_dir={matches}/{total} ({100*matches/total:.1f}%)")

        # Run length analysis
        run_lengths = []
        current_dir = dirs[0]
        run_len = 1
        for d in dirs[1:]:
            if d == current_dir:
                run_len += 1
            else:
                run_lengths.append((current_dir, run_len))
                current_dir = d
                run_len = 1
        run_lengths.append((current_dir, run_len))

        up_runs = [rl for d, rl in run_lengths if d > 0]
        down_runs = [rl for d, rl in run_lengths if d < 0]
        print(f"\n  Run lengths:")
        print(f"    Up runs: mean={np.mean(up_runs):.2f}, max={max(up_runs)}, n={len(up_runs)}")
        print(f"    Down runs: mean={np.mean(down_runs):.2f}, max={max(down_runs)}, n={len(down_runs)}")

        # Autocorrelation of step sizes
        print(f"\n  Step size autocorrelations:")
        for lag in [1, 2, 3, 5, 10]:
            if len(ss) > lag + 1:
                ac = np.corrcoef(ss[:-lag], ss[lag:])[0, 1]
                sig = " ***" if abs(ac) > 2/np.sqrt(len(ss)) else ""
                print(f"    lag {lag}: {ac:+.4f}{sig}")

# ══════════════════════════════════════════════════════════════════════════
# H. THE KEY QUESTION: CAN WE PREDICT FV DIRECTION FROM BOOK FEATURES?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("H. PREDICTING FV DIRECTION FROM BOOK FEATURES")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    # Build feature vector at each symmetric tick
    # Target: next FV change direction
    syms = []
    for i, r in enumerate(prices):
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fv = (r['bid1'] + r['ask1']) / 2
            syms.append((i, r['ts'], fv, r['bid1'], r['ask1'], r['bv1'], r['av1'],
                         r['bid2'], r['bv2'], r['ask2'], r['av2']))

    if len(syms) < 100:
        continue

    print(f"\n{day_name} ({len(syms)} symmetric ticks):")

    # Features at each symmetric tick, target = next FV change
    feats = []
    targets = []

    for j in range(len(syms) - 1):
        i, ts, fv, bid1, ask1, bv1, av1, bid2, bv2, ask2, av2 = syms[j]
        next_fv = syms[j+1][2]
        fv_change = next_fv - fv

        # Feature: volume (same for both sides in symmetric state, but check)
        vol = bv1  # = av1 in symmetric state

        # Feature: distance from 10000
        dist_10k = fv - 10000

        # Feature: L2 presence and depth
        has_l2 = bid2 is not None or ask2 is not None
        l2_depth = (bv2 or 0) + (av2 or 0)

        # Feature: what happened in the PREVIOUS ticks (non-symmetric states)
        prev_states = []
        for k in range(max(0, i-5), i):
            prev_states.append(classify_tick(prices[k]))

        had_tight = 'TIGHT_SPREAD' in prev_states
        had_one_sided = any(s in ('BID_ONLY', 'ASK_ONLY') for s in prev_states)
        had_wide = any('WIDE' in s for s in prev_states)

        # Feature: was there a trade nearby?
        ts_range = range(ts - 500, ts + 100, 100)

        feats.append({
            'vol': vol,
            'dist_10k': dist_10k,
            'has_l2': int(has_l2),
            'l2_depth': l2_depth,
            'had_tight': int(had_tight),
            'had_one_sided': int(had_one_sided),
            'had_wide': int(had_wide),
            'fv_level': fv,
        })
        targets.append(fv_change)

    targets = np.array(targets)

    # Test each feature
    for fname in ['vol', 'dist_10k', 'has_l2', 'l2_depth', 'had_tight', 'had_one_sided', 'had_wide']:
        vals = np.array([f[fname] for f in feats], dtype=float)
        if np.std(vals) > 0:
            corr = np.corrcoef(vals, targets)[0, 1]
            sig = " ***" if abs(corr) > 2/np.sqrt(len(vals)) else ""
            print(f"  {fname:20s} -> FV_change: corr={corr:+.4f}{sig}")

    # Most promising: check if L1 volume predicts direction
    print(f"\n  Volume -> FV change (detailed):")
    vols = np.array([f['vol'] for f in feats])
    for vol_val in sorted(np.unique(vols)):
        mask = vols == vol_val
        if np.sum(mask) > 10:
            avg_change = np.mean(targets[mask])
            n = np.sum(mask)
            print(f"    vol={int(vol_val):3d}: avg_fv_change={avg_change:+.4f}, n={n}")

    # L2 presence and direction
    print(f"\n  L2 presence -> FV change:")
    for l2_val in [0, 1]:
        mask = np.array([f['has_l2'] for f in feats]) == l2_val
        if np.sum(mask) > 10:
            print(f"    has_l2={l2_val}: avg_fv_change={np.mean(targets[mask]):+.4f}, n={np.sum(mask)}")

# ══════════════════════════════════════════════════════════════════════════
# I. NON-SYMMETRIC STATES: WHAT DO THEY TELL US?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("I. NON-SYMMETRIC STATE INFORMATION")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    print(f"\n{day_name}:")

    # When asymmetric (bv1 != av1), which side is bigger?
    asym_ticks = []
    for i, r in enumerate(prices):
        if (r['bid1'] is not None and r['ask1'] is not None and
            r['bv1'] > 0 and r['av1'] > 0 and r['bv1'] != r['av1']):

            spread = r['ask1'] - r['bid1']
            bigger_side = 'bid' if r['bv1'] > r['av1'] else 'ask'
            imbalance = r['bv1'] - r['av1']

            # Find next symmetric FV
            next_fv = None
            for j in range(i+1, min(i+50, len(prices))):
                if classify_tick(prices[j]) == 'MM_SYMMETRIC_16':
                    next_fv = (prices[j]['bid1'] + prices[j]['ask1']) / 2
                    break

            # Find previous symmetric FV
            prev_fv = None
            for j in range(i-1, max(i-50, -1), -1):
                if classify_tick(prices[j]) == 'MM_SYMMETRIC_16':
                    prev_fv = (prices[j]['bid1'] + prices[j]['ask1']) / 2
                    break

            if prev_fv and next_fv:
                asym_ticks.append({
                    'bigger_side': bigger_side,
                    'imbalance': imbalance,
                    'spread': spread,
                    'fv_change': next_fv - prev_fv,
                    'bid_vol': r['bv1'],
                    'ask_vol': r['av1'],
                })

    if asym_ticks:
        bid_bigger = [t for t in asym_ticks if t['bigger_side'] == 'bid']
        ask_bigger = [t for t in asym_ticks if t['bigger_side'] == 'ask']

        if bid_bigger:
            avg_fvc = np.mean([t['fv_change'] for t in bid_bigger])
            print(f"  Bid vol > Ask vol: avg FV change = {avg_fvc:+.4f} (n={len(bid_bigger)})")
        if ask_bigger:
            avg_fvc = np.mean([t['fv_change'] for t in ask_bigger])
            print(f"  Ask vol > Bid vol: avg FV change = {avg_fvc:+.4f} (n={len(ask_bigger)})")

        # By spread
        for sp in [16, 18, 19, 21]:
            sp_ticks = [t for t in asym_ticks if t['spread'] == sp]
            if sp_ticks:
                imb = np.array([t['imbalance'] for t in sp_ticks])
                fvc = np.array([t['fv_change'] for t in sp_ticks])
                corr = np.corrcoef(imb, fvc)[0, 1] if np.std(imb) > 0 and np.std(fvc) > 0 else 0
                print(f"  Spread={sp}: imbalance->FV_change corr={corr:+.4f} (n={len(sp_ticks)})")

# ══════════════════════════════════════════════════════════════════════════
# J. DETAILED L2 ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("J. L2 DEPTH ANALYSIS (when extra levels appear)")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    l2_events = []
    for i, r in enumerate(prices):
        has_l2_bid = r['bid2'] is not None
        has_l2_ask = r['ask2'] is not None

        if has_l2_bid or has_l2_ask:
            # Find nearest FV
            fv = None
            if classify_tick(r) == 'MM_SYMMETRIC_16':
                fv = (r['bid1'] + r['ask1']) / 2
            else:
                for j in range(i-1, max(i-10, -1), -1):
                    if classify_tick(prices[j]) == 'MM_SYMMETRIC_16':
                        fv = (prices[j]['bid1'] + prices[j]['ask1']) / 2
                        break

            l2_events.append({
                'ts': r['ts'],
                'has_l2_bid': has_l2_bid,
                'has_l2_ask': has_l2_ask,
                'bid2': r['bid2'],
                'bv2': r['bv2'],
                'ask2': r['ask2'],
                'av2': r['av2'],
                'fv': fv,
                'bid1': r['bid1'],
                'ask1': r['ask1'],
                'bv1': r['bv1'],
                'av1': r['av1'],
            })

    print(f"\n{day_name}: {len(l2_events)} ticks with L2")

    if l2_events:
        # What are the L2 bid/ask values relative to L1?
        bid_gaps = [e['bid1'] - e['bid2'] for e in l2_events if e['bid2'] is not None and e['bid1'] is not None]
        ask_gaps = [e['ask2'] - e['ask1'] for e in l2_events if e['ask2'] is not None and e['ask1'] is not None]

        if bid_gaps:
            bg = np.array(bid_gaps)
            print(f"  Bid L1-L2 gap: {np.unique(bg, return_counts=True)}")
        if ask_gaps:
            ag = np.array(ask_gaps)
            print(f"  Ask L2-L1 gap: {np.unique(ag, return_counts=True)}")

        # L2 volume patterns
        l2_bvols = [e['bv2'] for e in l2_events if e['bv2'] > 0]
        l2_avols = [e['av2'] for e in l2_events if e['av2'] > 0]
        if l2_bvols:
            print(f"  L2 bid volumes: mean={np.mean(l2_bvols):.1f}, unique top: {sorted(list(set(l2_bvols)), key=lambda x: -l2_bvols.count(x))[:10]}")
        if l2_avols:
            print(f"  L2 ask volumes: mean={np.mean(l2_avols):.1f}, unique top: {sorted(list(set(l2_avols)), key=lambda x: -l2_avols.count(x))[:10]}")

# ══════════════════════════════════════════════════════════════════════════
# K. THE BIG PICTURE: FV OVER ALL 3 DAYS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("K. FV EVOLUTION ACROSS ALL DAYS")
print("=" * 80)

all_fvs = []
for day_name, (prices, trades) in [('day-2', days['day-2']), ('day-1', days['day-1']), ('day0', days['day0'])]:
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fv = (r['bid1'] + r['ask1']) / 2
            all_fvs.append((day_name, r['ts'], fv))

for day_name in ['day-2', 'day-1', 'day0']:
    day_fvs = [f for d, _, f in all_fvs if d == day_name]
    if day_fvs:
        fv = np.array(day_fvs)
        print(f"\n{day_name}:")
        print(f"  FV: start={fv[0]:.0f}, end={fv[-1]:.0f}, net={fv[-1]-fv[0]:+.0f}")
        print(f"  Mean={np.mean(fv):.1f}, Range=[{np.min(fv):.0f}, {np.max(fv):.0f}]")

# Day-to-day continuity
for d1, d2 in [('day-2', 'day-1'), ('day-1', 'day0')]:
    end_fv = [f for d, _, f in all_fvs if d == d1][-1]
    start_fv = [f for d, _, f in all_fvs if d == d2][0]
    print(f"\n{d1} end -> {d2} start: {end_fv:.0f} -> {start_fv:.0f} (gap={start_fv-end_fv:+.0f})")

# ══════════════════════════════════════════════════════════════════════════
# L. VOLUME ENCODING HYPOTHESIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("L. VOLUME ENCODING HYPOTHESIS")
print("=" * 80)
print("Testing if L1 volume carries encoded information about FV direction")

for day_name, (prices, trades) in days.items():
    syms = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fv = (r['bid1'] + r['ask1']) / 2
            syms.append((r['ts'], fv, r['bv1']))

    if len(syms) < 100:
        continue

    ts_arr = np.array([s[0] for s in syms])
    fv_arr = np.array([s[1] for s in syms])
    vol_arr = np.array([s[2] for s in syms])

    print(f"\n{day_name}:")

    # Does volume predict FUTURE fv direction?
    for horizon in [1, 5, 10, 20]:
        if len(fv_arr) > horizon:
            future_change = fv_arr[horizon:] - fv_arr[:-horizon]
            vols = vol_arr[:-horizon]

            corr = np.corrcoef(vols, future_change)[0, 1]
            sig = " ***" if abs(corr) > 2/np.sqrt(len(vols)) else ""
            print(f"  vol -> fv_change(+{horizon:2d}): corr={corr:+.4f}{sig}")

    # Volume at FV change points vs stable points
    fv_rets = np.diff(fv_arr)
    change_mask = fv_rets != 0
    stable_mask = fv_rets == 0

    change_vols = vol_arr[:-1][change_mask]
    stable_vols = vol_arr[:-1][stable_mask]

    print(f"  Vol at FV change: mean={np.mean(change_vols):.2f}, median={np.median(change_vols):.0f}")
    print(f"  Vol at FV stable: mean={np.mean(stable_vols):.2f}, median={np.median(stable_vols):.0f}")

    # Volume pattern around FV changes
    print(f"\n  Volume patterns at FV steps:")
    for step in [-2, -1, 1, 2]:
        step_mask = fv_rets == step
        if np.sum(step_mask) > 5:
            step_vols = vol_arr[:-1][step_mask]
            print(f"    FV step={step:+d}: avg_vol={np.mean(step_vols):.2f}, "
                  f"median={np.median(step_vols):.0f}, n={np.sum(step_mask)}")

# ══════════════════════════════════════════════════════════════════════════
# M. CHECK IF FV FOLLOWS SPECIFIC MATHEMATICAL SEQUENCES
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("M. FV SEQUENCE ANALYSIS")
print("=" * 80)

for day_name, (prices, trades) in days.items():
    fvs = []
    for r in prices:
        if classify_tick(r) == 'MM_SYMMETRIC_16':
            fv = (r['bid1'] + r['ask1']) / 2
            fvs.append((r['ts'], fv))

    if len(fvs) < 100:
        continue

    fv_arr = np.array([f for _, f in fvs])
    ts_arr = np.array([t for t, _ in fvs])

    # Get unique FV values in order of appearance (dedup consecutive)
    unique_fvs = [fv_arr[0]]
    for fv in fv_arr[1:]:
        if fv != unique_fvs[-1]:
            unique_fvs.append(fv)
    unique_fvs = np.array(unique_fvs)

    print(f"\n{day_name}: {len(unique_fvs)} distinct FV levels visited")
    print(f"  First 50 FV levels: {[int(f) for f in unique_fvs[:50]]}")

    # Steps between levels
    steps = np.diff(unique_fvs)
    print(f"  First 50 steps: {[int(s) for s in steps[:50]]}")

    # Is there a pattern in the step sequence?
    # Check if steps repeat
    for period in range(2, min(50, len(steps)//3)):
        base = steps[:period]
        matches = 0
        total = 0
        for k in range(1, len(steps)//period):
            seg = steps[k*period:(k+1)*period]
            if len(seg) == period:
                if np.array_equal(seg, base):
                    matches += 1
                total += 1
        if total > 0 and matches / total > 0.3:
            print(f"  Period {period}: {matches}/{total} exact repeats ({100*matches/total:.0f}%) "
                  f"base={[int(s) for s in base]}")

    # Cumulative sum pattern
    cumsum = np.cumsum(steps)
    print(f"  Cumulative drift: {cumsum[-1]:+.0f} after {len(steps)} steps")

    # Is FV following a sine wave?
    detrended = unique_fvs - np.linspace(unique_fvs[0], unique_fvs[-1], len(unique_fvs))
    if np.std(detrended) > 0:
        fft_vals = np.fft.rfft(detrended)
        power = np.abs(fft_vals) ** 2
        freqs = np.fft.rfftfreq(len(detrended))
        top_idx = np.argsort(power[1:])[::-1][:5] + 1
        print(f"\n  FFT on detrended FV levels:")
        for idx in top_idx:
            if freqs[idx] > 0:
                period = 1.0 / freqs[idx]
                print(f"    freq={freqs[idx]:.4f}, period={period:.1f} levels, power={power[idx]:.1f}")

print("\n\nANALYSIS COMPLETE")
