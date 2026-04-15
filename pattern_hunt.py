"""
Hunt for the hidden pattern in OSMIUM FV.
The round description says: "apparent unpredictability may follow a hidden pattern"
Our backtester uses a random walk - but the REAL game has something different.
"""
import csv
import statistics
import math
from collections import Counter, defaultdict

DATA_DIR = "data/prosperity4/round1"

def load_prices(day):
    rows = []
    with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def parse_book(row):
    bids = []
    asks = []
    for i in range(1, 4):
        bp = row.get(f'bid_price_{i}', '')
        bv = row.get(f'bid_volume_{i}', '')
        if bp and bv:
            bids.append((int(float(bp)), int(bv)))
        ap = row.get(f'ask_price_{i}', '')
        av = row.get(f'ask_volume_{i}', '')
        if ap and av:
            asks.append((int(float(ap)), int(av)))
    bids.sort(key=lambda x: -x[0])
    asks.sort(key=lambda x: x[0])
    return bids, asks

def extract_fv(row):
    """Extract best FV estimate from Bot2 quotes."""
    bids, asks = parse_book(row)
    bot2_bids = [(p, v) for p, v in bids if 10 <= v <= 15]
    bot2_asks = [(p, v) for p, v in asks if 10 <= v <= 15]
    if bot2_bids and bot2_asks:
        return (bot2_bids[0][0] + bot2_asks[0][0]) / 2
    if bot2_bids:
        return bot2_bids[0][0] + 8
    if bot2_asks:
        return bot2_asks[0][0] - 8
    # Use bot1
    bot1_bids = [(p, v) for p, v in bids if v >= 20]
    bot1_asks = [(p, v) for p, v in asks if v >= 20]
    if bot1_bids and bot1_asks:
        return (bot1_bids[0][0] + bot1_asks[0][0]) / 2
    if bot1_bids:
        return bot1_bids[0][0] + 10.5
    if bot1_asks:
        return bot1_asks[0][0] - 10.5
    return None


# ============================================================
# Extract clean FV series for each day
# ============================================================
all_fv = {}
for day in [-2, -1, 0]:
    prices = load_prices(day)
    osmium = [r for r in prices if 'OSMIUM' in r['product']]
    fv_series = []
    for r in osmium:
        fv = extract_fv(r)
        fv_series.append(fv)
    # Forward-fill None values
    for i in range(1, len(fv_series)):
        if fv_series[i] is None:
            fv_series[i] = fv_series[i-1]
    all_fv[day] = fv_series

# ============================================================
# ANALYSIS 1: Long-range autocorrelation of FV changes
# ============================================================
print("=" * 80)
print("ANALYSIS 1: FV CHANGE AUTOCORRELATION (longer lags)")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    if not fv or fv[0] is None:
        continue

    # FV changes
    changes = [fv[i+1] - fv[i] for i in range(len(fv)-1) if fv[i] is not None and fv[i+1] is not None]

    n = len(changes)
    mean_c = statistics.mean(changes)
    var_c = statistics.variance(changes)

    print(f"\n--- Day {day} ({n} FV changes) ---")

    if var_c > 0:
        for lag in [1, 2, 3, 4, 5, 10, 20, 50, 100, 200, 500]:
            if lag < n:
                cov = sum((changes[i] - mean_c) * (changes[i+lag] - mean_c) for i in range(n-lag)) / (n-lag)
                acf = cov / var_c
                print(f"  Lag {lag:>4}: autocorr = {acf:+.4f}")


# ============================================================
# ANALYSIS 2: Mean reversion test - does FV revert to a mean?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 2: MEAN REVERSION / ORNSTEIN-UHLENBECK TEST")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    if not fv or fv[0] is None:
        continue

    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")
    print(f"  FV range: {min(clean_fv):.1f} to {max(clean_fv):.1f}")
    print(f"  FV mean: {statistics.mean(clean_fv):.1f}, std: {statistics.stdev(clean_fv):.2f}")

    # Regress FV change on FV level: dFV = alpha + beta * FV + noise
    # If beta < 0, FV is mean-reverting (O-U)
    # If beta > 0, FV is explosive
    # If beta ≈ 0, random walk
    changes = [(fv[i+1] - fv[i], fv[i]) for i in range(len(fv)-1) if fv[i] is not None and fv[i+1] is not None]

    if len(changes) > 100:
        # Simple OLS: dFV = alpha + beta * FV
        y_vals = [c for c, _ in changes]
        x_vals = [f for _, f in changes]
        n = len(y_vals)
        x_mean = statistics.mean(x_vals)
        y_mean = statistics.mean(y_vals)
        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        ss_xx = sum((x - x_mean) ** 2 for x in x_vals)
        beta = ss_xy / ss_xx if ss_xx > 0 else 0
        alpha = y_mean - beta * x_mean

        # Implied mean-reversion level: mu = -alpha/beta
        if beta != 0:
            mu = -alpha / beta
            half_life = -math.log(2) / beta if beta < 0 else float('inf')
            print(f"  OLS: dFV = {alpha:.6f} + {beta:.6f} * FV")
            print(f"  Mean-reversion level (mu): {mu:.1f}")
            print(f"  Mean-reversion speed (beta): {beta:.6f}")
            print(f"  Half-life: {half_life:.1f} ticks")
        else:
            print(f"  OLS: beta = 0 (random walk)")


# ============================================================
# ANALYSIS 3: Rolling window pattern detection
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 3: ROLLING STATISTICS - IS THERE A REGIME CHANGE?")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    if not fv or fv[0] is None:
        continue

    print(f"\n--- Day {day} ---")
    clean_fv = [x for x in fv if x is not None]

    # Rolling mean and std in windows of 500 ticks
    window = 500
    print(f"  Rolling stats (window={window}):")
    for start in range(0, len(clean_fv) - window, window):
        chunk = clean_fv[start:start+window]
        print(f"    [{start:>5}-{start+window:>5}]: mean={statistics.mean(chunk):.1f}, std={statistics.stdev(chunk):.2f}, min={min(chunk):.0f}, max={max(chunk):.0f}")


# ============================================================
# ANALYSIS 4: FV level distribution - is it truly unbounded?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 4: FV LEVEL DISTRIBUTION")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")

    # Bin FV into 5-unit buckets
    bucket_size = 5
    buckets = Counter()
    for f in clean_fv:
        bucket = int(f // bucket_size) * bucket_size
        buckets[bucket] += 1

    for b in sorted(buckets.keys()):
        count = buckets[b]
        if count > 20:
            bar = '#' * (count // 20)
            print(f"    {b:>6}: {count:>5} {bar}")


# ============================================================
# ANALYSIS 5: Hurst exponent (mean-reversion vs random walk vs momentum)
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 5: HURST EXPONENT (R/S analysis)")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")

    # R/S analysis for Hurst exponent
    # H < 0.5 → mean-reverting
    # H = 0.5 → random walk
    # H > 0.5 → trending/momentum

    rs_by_n = {}
    for window_size in [10, 20, 50, 100, 200, 500, 1000, 2000]:
        if window_size > len(clean_fv) // 2:
            continue

        rs_values = []
        for start in range(0, len(clean_fv) - window_size, window_size // 2):
            chunk = clean_fv[start:start + window_size]
            mean_chunk = statistics.mean(chunk)
            deviations = [x - mean_chunk for x in chunk]
            cumsum = [sum(deviations[:i+1]) for i in range(len(deviations))]
            R = max(cumsum) - min(cumsum)
            S = statistics.stdev(chunk) if len(chunk) > 1 else 1
            if S > 0:
                rs_values.append(R / S)

        if rs_values:
            rs_by_n[window_size] = statistics.mean(rs_values)

    if len(rs_by_n) >= 3:
        # Fit log(R/S) = H * log(n) + c
        log_ns = [math.log(n) for n in rs_by_n]
        log_rs = [math.log(rs_by_n[n]) for n in rs_by_n]

        n = len(log_ns)
        x_mean = statistics.mean(log_ns)
        y_mean = statistics.mean(log_rs)
        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(log_ns, log_rs))
        ss_xx = sum((x - x_mean) ** 2 for x in log_ns)
        H = ss_xy / ss_xx if ss_xx > 0 else 0.5

        print(f"  Hurst exponent: {H:.4f}")
        if H < 0.45:
            print(f"  → MEAN-REVERTING (H < 0.5)")
        elif H > 0.55:
            print(f"  → TRENDING/MOMENTUM (H > 0.5)")
        else:
            print(f"  → Random walk (H ≈ 0.5)")

        for n_val in sorted(rs_by_n):
            print(f"    n={n_val:>5}: R/S={rs_by_n[n_val]:.2f}")


# ============================================================
# ANALYSIS 6: Spectral analysis (FFT) for cyclical patterns
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 6: SPECTRAL ANALYSIS (top frequencies)")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")

    # Detrend first (remove linear trend)
    n = len(clean_fv)
    mean_fv = statistics.mean(clean_fv)
    detrended = [f - mean_fv for f in clean_fv]

    # Manual DFT for top frequencies (too slow for full FFT without numpy)
    # Just compute power at select periods
    periods_to_test = [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]

    print(f"  Power at various periods:")
    powers = {}
    for period in periods_to_test:
        if period > n // 2:
            continue
        freq = 2 * math.pi / period
        cos_sum = sum(detrended[t] * math.cos(freq * t) for t in range(n))
        sin_sum = sum(detrended[t] * math.sin(freq * t) for t in range(n))
        power = (cos_sum ** 2 + sin_sum ** 2) / n
        powers[period] = power
        print(f"    Period {period:>5}: power = {power:.1f}")


# ============================================================
# ANALYSIS 7: Look at FV differences across days - is the starting point related?
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 7: CROSS-DAY PATTERNS")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]
    print(f"  Day {day}: start={clean_fv[0]:.1f}, end={clean_fv[-1]:.1f}, range=[{min(clean_fv):.0f}, {max(clean_fv):.0f}]")

# ============================================================
# ANALYSIS 8: Local trend detection - consecutive same-direction moves
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 8: LOCAL TREND ANALYSIS")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")

    # Count consecutive same-direction FV changes
    changes = [clean_fv[i+1] - clean_fv[i] for i in range(len(clean_fv)-1)]
    nonzero_changes = [(i, c) for i, c in enumerate(changes) if c != 0]

    # Consecutive same direction
    run_lengths = []
    current_run = 1
    for i in range(1, len(nonzero_changes)):
        if (nonzero_changes[i][1] > 0) == (nonzero_changes[i-1][1] > 0):
            current_run += 1
        else:
            run_lengths.append(current_run)
            current_run = 1
    run_lengths.append(current_run)

    run_dist = Counter(run_lengths)
    print(f"  Consecutive same-direction FV changes:")
    print(f"    Distribution: {dict(sorted(run_dist.items()))}")
    if run_lengths:
        print(f"    Mean run length: {statistics.mean(run_lengths):.2f}")
        # For a truly random process, expected run length is 2
        # If > 2, there's momentum. If < 2, there's mean-reversion.


# ============================================================
# ANALYSIS 9: FV vs 10000 mean reversion
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 9: DOES FV REVERT TO 10000?")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")

    # Track deviation from 10000 and subsequent movement
    target = 10000
    deviations_and_next = []
    for i in range(len(clean_fv) - 10):
        dev = clean_fv[i] - target
        future_move = clean_fv[i+10] - clean_fv[i]
        deviations_and_next.append((dev, future_move))

    # Bin by deviation and check if future move is towards mean
    bins = [(-30, -20), (-20, -10), (-10, -5), (-5, -2), (-2, 2), (2, 5), (5, 10), (10, 20), (20, 30)]
    for lo, hi in bins:
        in_bin = [(d, m) for d, m in deviations_and_next if lo <= d < hi]
        if len(in_bin) > 20:
            avg_dev = statistics.mean([d for d, _ in in_bin])
            avg_move = statistics.mean([m for _, m in in_bin])
            # If mean-reverting: avg_move should be opposite to avg_dev
            print(f"    Dev [{lo:>3},{hi:>3}): n={len(in_bin):>5}, avg_dev={avg_dev:>+6.1f}, avg_10tick_move={avg_move:>+6.3f}, ratio={avg_move/avg_dev if avg_dev != 0 else 0:.4f}")


# ============================================================
# ANALYSIS 10: Absolute FV path analysis
# ============================================================
print("\n" + "=" * 80)
print("ANALYSIS 10: FV PATH STRUCTURE (every 100 ticks)")
print("=" * 80)

for day in [-2, -1, 0]:
    fv = all_fv[day]
    clean_fv = [x for x in fv if x is not None]

    print(f"\n--- Day {day} ---")
    for i in range(0, min(len(clean_fv), 10000), 100):
        print(f"    t={i:>5}: FV={clean_fv[i]:.1f}")


print("\nDone!")
