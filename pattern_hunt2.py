"""
Deep pattern hunt on OSMIUM using ALL available data (3 days × 10k ticks).
Try EVERYTHING to find the hidden pattern.
"""
import csv
import math
import statistics
from collections import Counter, defaultdict

DATA_DIR = "data/prosperity4/round1"

def load_prices(day):
    rows = []
    with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def extract_fv_clean(row):
    """Extract FV only when Bot2 is on both sides (most reliable)."""
    bids, asks = [], []
    for i in range(1, 4):
        bp, bv = row.get(f'bid_price_{i}', ''), row.get(f'bid_volume_{i}', '')
        if bp and bv: bids.append((int(float(bp)), int(bv)))
        ap, av = row.get(f'ask_price_{i}', ''), row.get(f'ask_volume_{i}', '')
        if ap and av: asks.append((int(float(ap)), int(av)))
    bot2_b = [(p,v) for p,v in bids if 10 <= v <= 15]
    bot2_a = [(p,v) for p,v in asks if 10 <= v <= 15]
    if bot2_b and bot2_a:
        return (bot2_b[0][0] + bot2_a[0][0]) / 2
    return None

# Build clean FV series for all days
all_fv = {}
for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]
    series = []
    for r in osmium:
        fv = extract_fv_clean(r)
        series.append(fv)
    all_fv[day] = series

# Get only non-None values with their tick indices
def clean_series(day):
    return [(i, fv) for i, fv in enumerate(all_fv[day]) if fv is not None]

# ============================================================
# TEST 1: Sinusoidal pattern detection
# Does FV follow a sine wave around 10000?
# ============================================================
print("=" * 80)
print("TEST 1: SINUSOIDAL PATTERN (test specific periods)")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]
    ticks = [t for t, _ in clean]
    n = len(fvs)
    mean_fv = statistics.mean(fvs)
    detrended = [fv - mean_fv for fv in fvs]

    print(f"\n--- Day {day} ({n} points, mean={mean_fv:.1f}) ---")

    # Test many periods, find the one with max power
    best_power = 0
    best_period = 0
    powers = {}
    for period in range(10, 5001, 5):
        freq = 2 * math.pi / period
        cos_sum = sum(detrended[j] * math.cos(freq * ticks[j]) for j in range(n))
        sin_sum = sum(detrended[j] * math.sin(freq * ticks[j]) for j in range(n))
        power = (cos_sum**2 + sin_sum**2) / n
        powers[period] = power
        if power > best_power:
            best_power = power
            best_period = period

    # Top 10 periods by power
    top = sorted(powers.items(), key=lambda x: -x[1])[:10]
    print(f"  Top 10 periods by spectral power:")
    for period, power in top:
        # Compute amplitude: A = 2 * sqrt(power / n)
        amplitude = 2 * math.sqrt(power / n)
        print(f"    Period={period:>5}, power={power:>10.1f}, amplitude={amplitude:.2f}")


# ============================================================
# TEST 2: FV changes - are they truly random or structured?
# ============================================================
print("\n" + "=" * 80)
print("TEST 2: FV CHANGE PATTERNS")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)

    # Compute changes between consecutive clean observations
    changes = []
    for i in range(1, len(clean)):
        tick_gap = clean[i][0] - clean[i-1][0]
        if tick_gap <= 2:  # only adjacent or near-adjacent ticks
            changes.append((clean[i][1] - clean[i-1][1], tick_gap))

    # Look at the sequence of non-zero changes
    nonzero = [c for c, g in changes if c != 0]

    print(f"\n--- Day {day} ---")
    print(f"  Total changes: {len(changes)}, nonzero: {len(nonzero)}")

    if len(nonzero) < 50:
        continue

    # Are consecutive nonzero changes correlated?
    nz_pairs = [(nonzero[i], nonzero[i+1]) for i in range(len(nonzero)-1)]
    same_dir = sum(1 for a, b in nz_pairs if (a > 0) == (b > 0))
    diff_dir = sum(1 for a, b in nz_pairs if (a > 0) != (b > 0))
    print(f"  Consecutive nonzero: same_dir={same_dir}, diff_dir={diff_dir}, ratio={same_dir/(same_dir+diff_dir):.3f}")
    print(f"  (random = 0.500, momentum > 0.5, MR < 0.5)")

    # What about the SIZE of changes? Does a big change predict a big change?
    abs_pairs = [(abs(nonzero[i]), abs(nonzero[i+1])) for i in range(len(nonzero)-1)]
    if abs_pairs:
        x = [a for a, _ in abs_pairs]
        y = [b for _, b in abs_pairs]
        mx, my = statistics.mean(x), statistics.mean(y)
        cov = sum((a-mx)*(b-my) for a, b in zip(x, y)) / len(x)
        sx, sy = statistics.stdev(x), statistics.stdev(y)
        corr = cov / (sx * sy) if sx > 0 and sy > 0 else 0
        print(f"  Abs change autocorrelation: {corr:.3f} (volatility clustering if > 0)")

    # Pattern in change VALUES: does +1 tend to be followed by -1?
    change_vals = [c for c in nonzero if abs(c) <= 1.5]
    if len(change_vals) > 100:
        transitions = Counter()
        for i in range(len(change_vals)-1):
            a = 1 if change_vals[i] > 0 else -1
            b = 1 if change_vals[i+1] > 0 else -1
            transitions[(a, b)] += 1
        print(f"  ±1 change transitions: {dict(transitions)}")
        # P(+1 after +1) vs P(-1 after +1)
        pp = transitions.get((1,1), 0)
        pm = transitions.get((1,-1), 0)
        mp = transitions.get((-1,1), 0)
        mm = transitions.get((-1,-1), 0)
        if pp + pm > 0:
            print(f"    P(+1|+1)={pp/(pp+pm):.3f}, P(-1|+1)={pm/(pp+pm):.3f}")
        if mp + mm > 0:
            print(f"    P(+1|-1)={mp/(mp+mm):.3f}, P(-1|-1)={mm/(mp+mm):.3f}")


# ============================================================
# TEST 3: Does FV depend on its LEVEL (not just changes)?
# Mean reversion to 10000, but is it linear or nonlinear?
# ============================================================
print("\n" + "=" * 80)
print("TEST 3: FV LEVEL → FUTURE RETURN (nonlinear MR check)")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]

    print(f"\n--- Day {day} ---")

    # For different horizons, bin by FV level and compute future return
    for horizon in [5, 20, 50, 100]:
        level_return = defaultdict(list)
        for i in range(len(fvs) - horizon):
            level = round(fvs[i])
            ret = fvs[i + horizon] - fvs[i]
            level_return[level].append(ret)

        print(f"\n  Horizon {horizon}:")
        for level in sorted(level_return.keys()):
            returns = level_return[level]
            if len(returns) >= 20:
                avg = statistics.mean(returns)
                dev = level - 10000
                print(f"    FV={level:>6} (dev={dev:>+3}): n={len(returns):>4}, avg_{horizon}tick_return={avg:>+6.3f}")


# ============================================================
# TEST 4: Time-of-day effects
# Does OSMIUM behave differently at start vs middle vs end?
# ============================================================
print("\n" + "=" * 80)
print("TEST 4: TIME-OF-DAY EFFECTS")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)

    print(f"\n--- Day {day} ---")

    # Split into quintiles by tick number
    n = len(clean)
    q_size = n // 5
    for q in range(5):
        start = q * q_size
        end = start + q_size if q < 4 else n
        chunk_fvs = [fv for _, fv in clean[start:end]]
        chunk_changes = [chunk_fvs[i+1] - chunk_fvs[i] for i in range(len(chunk_fvs)-1)]
        nonzero = [c for c in chunk_changes if c != 0]

        tick_range = f"{clean[start][0]:>5}-{clean[min(end-1,n-1)][0]:>5}"
        print(f"  Q{q+1} (tick {tick_range}): mean={statistics.mean(chunk_fvs):.1f}, std={statistics.stdev(chunk_fvs):.2f}, "
              f"changes={len(nonzero)}, abs_mean={statistics.mean([abs(c) for c in nonzero]) if nonzero else 0:.2f}")


# ============================================================
# TEST 5: Cross-day patterns
# Does day -2 end predict day -1 start?
# ============================================================
print("\n" + "=" * 80)
print("TEST 5: CROSS-DAY CONTINUITY")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]
    if fvs:
        print(f"  Day {day}: start={fvs[0]:.1f}, end={fvs[-1]:.1f}, mean={statistics.mean(fvs):.1f}")


# ============================================================
# TEST 6: Hidden Markov / Regime detection
# Split changes into "high vol" and "low vol" regimes
# ============================================================
print("\n" + "=" * 80)
print("TEST 6: REGIME DETECTION (volatility regimes)")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]
    changes = [fvs[i+1] - fvs[i] for i in range(len(fvs)-1)]

    print(f"\n--- Day {day} ---")

    # Rolling volatility (window 50)
    window = 50
    vol_series = []
    for i in range(len(changes) - window):
        chunk = changes[i:i+window]
        vol = statistics.stdev(chunk) if len(chunk) > 1 else 0
        vol_series.append(vol)

    if vol_series:
        median_vol = statistics.median(vol_series)
        print(f"  Rolling vol: mean={statistics.mean(vol_series):.3f}, median={median_vol:.3f}")

        # In high-vol regime: what's the behavior?
        high_vol_returns = []
        low_vol_returns = []
        for i in range(len(vol_series) - 10):
            if vol_series[i] > median_vol:
                high_vol_returns.append(sum(changes[i+window:i+window+10]))
            else:
                low_vol_returns.append(sum(changes[i+window:i+window+10]))

        if high_vol_returns and low_vol_returns:
            print(f"  High-vol regime: n={len(high_vol_returns)}, next_10tick_return={statistics.mean(high_vol_returns):+.3f}")
            print(f"  Low-vol regime:  n={len(low_vol_returns)}, next_10tick_return={statistics.mean(low_vol_returns):+.3f}")


# ============================================================
# TEST 7: Trade timing as signal
# Do market trades predict FV movement?
# ============================================================
print("\n" + "=" * 80)
print("TEST 7: TRADE TIMING AS SIGNAL")
print("=" * 80)

def load_trades(day):
    rows = []
    with open(f"{DATA_DIR}/trades_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

for day in [-2, -1, 0]:
    trades = load_trades(day)
    osm_trades = [t for t in trades if 'OSMIUM' in t['symbol']]
    clean = clean_series(day)
    fv_lookup = {t: fv for t, fv in clean}

    print(f"\n--- Day {day} ({len(osm_trades)} trades) ---")

    # After a trade occurs, what happens to FV?
    for horizon in [1, 5, 10, 20]:
        trade_returns = []
        no_trade_returns = []

        trade_ticks = set()
        for t in osm_trades:
            trade_ticks.add(int(t['timestamp']) // 100)

        for tick, fv in clean:
            future_fv = fv_lookup.get(tick + horizon)
            if future_fv is None:
                continue
            ret = future_fv - fv
            if tick in trade_ticks:
                trade_returns.append(ret)
            else:
                no_trade_returns.append(ret)

        if trade_returns and no_trade_returns:
            print(f"  Horizon {horizon:>2}: after_trade={statistics.mean(trade_returns):+.4f} (n={len(trade_returns)}), "
                  f"no_trade={statistics.mean(no_trade_returns):+.4f} (n={len(no_trade_returns)})")


# ============================================================
# TEST 8: FV quantization - is FV always integer or half-integer?
# ============================================================
print("\n" + "=" * 80)
print("TEST 8: FV QUANTIZATION")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]

    # Check fractional parts
    fracs = Counter()
    for fv in fvs:
        frac = round(fv % 1, 2)
        fracs[frac] += 1

    print(f"\n  Day {day}: {dict(sorted(fracs.items()))}")


# ============================================================
# TEST 9: CONSECUTIVE FLAT periods - does duration predict breakout?
# ============================================================
print("\n" + "=" * 80)
print("TEST 9: FLAT PERIOD → BREAKOUT PREDICTION")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]

    print(f"\n--- Day {day} ---")

    # Find flat periods (consecutive same FV)
    flat_periods = []
    start_idx = 0
    for i in range(1, len(fvs)):
        if fvs[i] != fvs[start_idx]:
            duration = i - start_idx
            if duration >= 3:
                # What happens after this flat period?
                if i + 5 < len(fvs):
                    breakout = fvs[i+5] - fvs[i]
                    flat_periods.append((duration, fvs[start_idx], breakout))
            start_idx = i

    # Does longer flat period predict bigger breakout?
    by_duration = defaultdict(list)
    for dur, level, breakout in flat_periods:
        bucket = min(dur, 20)
        by_duration[bucket].append(abs(breakout))

    for dur in sorted(by_duration.keys()):
        vals = by_duration[dur]
        if len(vals) >= 5:
            print(f"  Flat duration {dur:>2}: n={len(vals):>3}, avg_abs_breakout_5tick={statistics.mean(vals):.3f}")


# ============================================================
# TEST 10: Is the FV process the SAME across all 3 days?
# Compare distributions and dynamics
# ============================================================
print("\n" + "=" * 80)
print("TEST 10: CROSS-DAY CONSISTENCY")
print("=" * 80)

for day in [-2, -1, 0]:
    clean = clean_series(day)
    fvs = [fv for _, fv in clean]
    changes = [fvs[i+1] - fvs[i] for i in range(len(fvs)-1)]
    nonzero = [c for c in changes if c != 0]

    # Change frequency
    change_rate = len(nonzero) / len(changes)

    # Change size distribution
    abs_changes = [abs(c) for c in nonzero]

    print(f"  Day {day}: change_rate={change_rate:.3f}, "
          f"mean_abs={statistics.mean(abs_changes):.3f}, "
          f"std_abs={statistics.stdev(abs_changes):.3f}, "
          f"P(|c|>1)={sum(1 for c in abs_changes if c > 1.1)/len(abs_changes):.3f}")


print("\nDone!")
