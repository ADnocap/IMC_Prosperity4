"""
Deep statistical analysis of ASH_COATED_OSMIUM (ACO) returns.
Looking for hidden patterns that top teams may be exploiting.
"""
import csv
import math
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prosperity4", "round1")
DAYS = [-2, -1, 0]

def load_aco_mids():
    """Load ACO mid prices per day, only where both bid and ask exist."""
    day_data = {}
    for day in DAYS:
        fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
        timestamps = []
        mids = []
        with open(fname, "r") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row["product"] != "ASH_COATED_OSMIUM":
                    continue
                bp1 = row["bid_price_1"].strip()
                ap1 = row["ask_price_1"].strip()
                if not bp1 or not ap1:
                    continue
                mid = (float(bp1) + float(ap1)) / 2.0
                ts = int(row["timestamp"])
                timestamps.append(ts)
                mids.append(mid)
        day_data[day] = (timestamps, mids)
    return day_data


def load_aco_trades():
    """Load ACO trades per day."""
    day_trades = {}
    for day in DAYS:
        fname = os.path.join(DATA_DIR, f"trades_round_1_day_{day}.csv")
        trades = []
        with open(fname, "r") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row["symbol"].strip() != "ASH_COATED_OSMIUM":
                    continue
                trades.append({
                    "timestamp": int(row["timestamp"]),
                    "buyer": row["buyer"].strip(),
                    "seller": row["seller"].strip(),
                    "price": float(row["price"]),
                    "quantity": int(row["quantity"]),
                })
        day_trades[day] = trades
    return day_trades


def compute_returns(mids):
    """Compute tick-to-tick returns (differences, not log returns since prices are close)."""
    return [mids[i] - mids[i-1] for i in range(1, len(mids))]


def rolling_std(values, window):
    """Compute rolling standard deviation."""
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i+1]
        if len(chunk) < 2:
            result.append(0.0)
            continue
        mean = sum(chunk) / len(chunk)
        var = sum((x - mean)**2 for x in chunk) / (len(chunk) - 1)
        result.append(math.sqrt(var))
    return result


def autocorrelation(x, lag=1):
    """Compute autocorrelation at given lag."""
    n = len(x)
    if n < lag + 2:
        return 0.0
    mean = sum(x) / n
    var = sum((xi - mean)**2 for xi in x)
    if var == 0:
        return 0.0
    cov = sum((x[i] - mean) * (x[i + lag] - mean) for i in range(n - lag))
    return cov / var


def hurst_exponent(ts, max_lag=100):
    """Estimate Hurst exponent using R/S analysis."""
    lags = []
    rs_values = []
    for lag in range(10, min(max_lag, len(ts) // 4), 5):
        rs_list = []
        for start in range(0, len(ts) - lag, lag):
            chunk = ts[start:start + lag]
            mean = sum(chunk) / len(chunk)
            deviations = [x - mean for x in chunk]
            cumdev = []
            s = 0
            for d in deviations:
                s += d
                cumdev.append(s)
            R = max(cumdev) - min(cumdev)
            S = math.sqrt(sum(d**2 for d in deviations) / len(deviations))
            if S > 0:
                rs_list.append(R / S)
        if rs_list:
            lags.append(math.log(lag))
            rs_values.append(math.log(sum(rs_list) / len(rs_list)))

    # Linear regression of log(R/S) on log(lag)
    if len(lags) < 3:
        return 0.5
    n = len(lags)
    sx = sum(lags)
    sy = sum(rs_values)
    sxy = sum(lags[i] * rs_values[i] for i in range(n))
    sx2 = sum(x**2 for x in lags)
    H = (n * sxy - sx * sy) / (n * sx2 - sx**2)
    return H


def fft_analysis(returns, top_n=10):
    """Simple FFT using only math (no numpy)."""
    N = len(returns)
    # Zero-pad to power of 2 for efficiency (but we'll just do DFT on first 1024 points)
    n = min(N, 2048)
    data = returns[:n]

    # Compute power spectrum using DFT for select frequencies
    # Check periods from 2 to n//2
    mean_r = sum(data) / len(data)
    data = [x - mean_r for x in data]

    results = []
    for period in range(2, min(n // 2, 500)):
        freq = 2 * math.pi / period
        real = sum(data[t] * math.cos(freq * t) for t in range(n))
        imag = sum(data[t] * math.sin(freq * t) for t in range(n))
        power = (real**2 + imag**2) / n
        results.append((period, power))

    results.sort(key=lambda x: -x[1])
    return results[:top_n]


def run_length_analysis(returns):
    """Analyze run lengths of consecutive up/down moves."""
    if not returns:
        return {}, {}, 0, 0

    signs = []
    for r in returns:
        if r > 0:
            signs.append(1)
        elif r < 0:
            signs.append(-1)
        else:
            signs.append(0)

    # Count runs
    run_lengths = defaultdict(int)
    current_sign = signs[0]
    current_len = 1

    for i in range(1, len(signs)):
        if signs[i] == current_sign:
            current_len += 1
        else:
            if current_sign != 0:
                run_lengths[current_len] = run_lengths.get(current_len, 0) + 1
            current_sign = signs[i]
            current_len = 1
    if current_sign != 0:
        run_lengths[current_len] = run_lengths.get(current_len, 0) + 1

    # Expected run lengths for random walk
    # P(run of length k) = p * (1-p)^(k-1) where p = prob of direction change
    n_up = sum(1 for s in signs if s > 0)
    n_down = sum(1 for s in signs if s < 0)
    n_zero = sum(1 for s in signs if s == 0)

    return run_lengths, {"up": n_up, "down": n_down, "zero": n_zero}, n_up, n_down


def transition_probs(returns):
    """Compute transition probabilities."""
    up_after_up = 0
    down_after_up = 0
    up_after_down = 0
    down_after_down = 0

    for i in range(1, len(returns)):
        prev = returns[i-1]
        curr = returns[i]
        if prev > 0 and curr > 0:
            up_after_up += 1
        elif prev > 0 and curr < 0:
            down_after_up += 1
        elif prev < 0 and curr > 0:
            up_after_down += 1
        elif prev < 0 and curr < 0:
            down_after_down += 1

    total_after_up = up_after_up + down_after_up
    total_after_down = up_after_down + down_after_down

    return {
        "P(up|up)": up_after_up / total_after_up if total_after_up else 0,
        "P(down|up)": down_after_up / total_after_up if total_after_up else 0,
        "P(up|down)": up_after_down / total_after_down if total_after_down else 0,
        "P(down|down)": down_after_down / total_after_down if total_after_down else 0,
        "n_after_up": total_after_up,
        "n_after_down": total_after_down,
    }


def conditional_return_after_big_move(returns, threshold=1.0):
    """What happens after a big move?"""
    next_returns_after_big_up = []
    next_returns_after_big_down = []

    for i in range(1, len(returns)):
        if returns[i-1] > threshold:
            next_returns_after_big_up.append(returns[i])
        elif returns[i-1] < -threshold:
            next_returns_after_big_down.append(returns[i])

    return next_returns_after_big_up, next_returns_after_big_down


def consecutive_direction_analysis(returns, max_consec=6):
    """After N consecutive up/down moves, what happens next?"""
    results = {}
    for n in range(1, max_consec + 1):
        cont_up = 0
        rev_up = 0
        cont_down = 0
        rev_down = 0
        for i in range(n, len(returns)):
            # Check if previous n moves are all up
            all_up = all(returns[i - j - 1] > 0 for j in range(n))
            all_down = all(returns[i - j - 1] < 0 for j in range(n))
            if all_up:
                if returns[i] > 0:
                    cont_up += 1
                elif returns[i] < 0:
                    rev_up += 1
            if all_down:
                if returns[i] < 0:
                    cont_down += 1
                elif returns[i] > 0:
                    rev_down += 1
        results[n] = {
            "after_n_up": {"continue": cont_up, "reverse": rev_up,
                           "P(continue)": cont_up / (cont_up + rev_up) if (cont_up + rev_up) else 0},
            "after_n_down": {"continue": cont_down, "reverse": rev_down,
                             "P(continue)": cont_down / (cont_down + rev_down) if (cont_down + rev_down) else 0},
        }
    return results


def distribution_stats(returns):
    """Compute distribution statistics."""
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean)**2 for r in returns) / (n - 1)
    std = math.sqrt(var)

    # Skewness
    skew = sum(((r - mean) / std)**3 for r in returns) / n if std > 0 else 0

    # Kurtosis (excess)
    kurt = sum(((r - mean) / std)**4 for r in returns) / n - 3.0 if std > 0 else 0

    # Quantiles
    sorted_r = sorted(returns)
    def quantile(q):
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_r[lo] * (1 - frac) + sorted_r[hi] * frac

    return {
        "mean": mean,
        "std": std,
        "skewness": skew,
        "excess_kurtosis": kurt,
        "min": sorted_r[0],
        "p1": quantile(0.01),
        "p5": quantile(0.05),
        "p25": quantile(0.25),
        "median": quantile(0.50),
        "p75": quantile(0.75),
        "p95": quantile(0.95),
        "p99": quantile(0.99),
        "max": sorted_r[-1],
        "n": n,
    }


def squared_returns_autocorr(returns, max_lag=20):
    """Check for GARCH effects via autocorrelation of squared returns."""
    sq_returns = [r**2 for r in returns]
    return {lag: autocorrelation(sq_returns, lag) for lag in range(1, max_lag + 1)}


def regime_analysis(timestamps, mids, returns, window=50):
    """Analyze volatility regimes over the day."""
    rstd = rolling_std(returns, window)

    # Split into segments
    n = len(returns)
    n_segments = 10
    seg_size = n // n_segments

    segments = []
    for i in range(n_segments):
        start = i * seg_size
        end = start + seg_size if i < n_segments - 1 else n
        seg_returns = returns[start:end]
        seg_std = math.sqrt(sum(r**2 for r in seg_returns) / len(seg_returns)) if seg_returns else 0
        seg_mean = sum(seg_returns) / len(seg_returns) if seg_returns else 0
        ts_start = timestamps[start + 1] if start + 1 < len(timestamps) else 0
        ts_end = timestamps[min(end, len(timestamps) - 1)]
        segments.append({
            "segment": i + 1,
            "ts_range": f"{ts_start}-{ts_end}",
            "n_ticks": len(seg_returns),
            "mean_return": seg_mean,
            "volatility": seg_std,
        })

    return segments


def analyze_trade_patterns(day_trades):
    """Analyze trade data for patterns."""
    for day, trades in day_trades.items():
        print(f"\n  Day {day}: {len(trades)} trades")
        if not trades:
            continue

        # Who are the counterparties?
        buyers = defaultdict(int)
        sellers = defaultdict(int)
        for t in trades:
            buyers[t["buyer"]] += t["quantity"]
            sellers[t["seller"]] += t["quantity"]

        print(f"    Buyers:  {dict(buyers)}")
        print(f"    Sellers: {dict(sellers)}")

        # Trade timing
        ts_counts = defaultdict(int)
        for t in trades:
            ts_counts[t["timestamp"]] += 1

        # How many timestamps have trades?
        print(f"    Timestamps with trades: {len(ts_counts)} / ~10000")

        # Average trade price vs mid
        avg_price = sum(t["price"] * t["quantity"] for t in trades) / sum(t["quantity"] for t in trades)
        print(f"    VWAP: {avg_price:.2f}")


def analyze_lag_autocorrelation(returns, max_lag=50):
    """Detailed autocorrelation at many lags."""
    print("\n  Autocorrelation of returns:")
    significant = []
    for lag in range(1, max_lag + 1):
        ac = autocorrelation(returns, lag)
        # Approximate 95% significance: 2/sqrt(n)
        threshold = 2.0 / math.sqrt(len(returns))
        marker = " ***" if abs(ac) > threshold else ""
        if lag <= 20 or abs(ac) > threshold:
            print(f"    Lag {lag:3d}: {ac:+.4f}{marker}")
        if abs(ac) > threshold:
            significant.append((lag, ac))

    return significant


def cross_day_comparison(day_data):
    """Compare patterns across days."""
    print("\n" + "="*70)
    print("8. CROSS-DAY COMPARISON")
    print("="*70)

    all_acs = {}
    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        acs = [autocorrelation(returns, lag) for lag in range(1, 21)]
        all_acs[day] = acs
        tp = transition_probs(returns)
        print(f"\n  Day {day}:")
        print(f"    N ticks: {len(mids)}, N returns: {len(returns)}")
        print(f"    Price range: {min(mids):.1f} - {max(mids):.1f}")
        print(f"    Return std: {math.sqrt(sum(r**2 for r in returns)/len(returns)):.4f}")
        print(f"    P(up|up)={tp['P(up|up)']:.4f}  P(down|down)={tp['P(down|down)']:.4f}")
        print(f"    AC(1)={acs[0]:.4f}  AC(2)={acs[1]:.4f}  AC(3)={acs[2]:.4f}")

    # Check consistency
    print("\n  Cross-day autocorrelation consistency (lag 1-10):")
    for lag in range(10):
        vals = [all_acs[d][lag] for d in DAYS]
        mean_ac = sum(vals) / len(vals)
        print(f"    Lag {lag+1}: days=[{', '.join(f'{v:.4f}' for v in vals)}]  mean={mean_ac:.4f}")


def multi_tick_returns_analysis(mids, max_horizon=20):
    """Check returns over multiple tick horizons for mean reversion / momentum."""
    print("\n  Multi-tick return autocorrelation (does aggregation help?):")
    for h in [2, 3, 5, 10, 15, 20]:
        if h >= len(mids):
            continue
        h_returns = [mids[i] - mids[i-h] for i in range(h, len(mids))]
        ac1 = autocorrelation(h_returns, 1)
        # Variance ratio test: Var(h-tick) / (h * Var(1-tick))
        one_returns = compute_returns(mids)
        var1 = sum(r**2 for r in one_returns) / len(one_returns)
        varh = sum(r**2 for r in h_returns) / len(h_returns)
        vr = varh / (h * var1) if var1 > 0 else 0
        print(f"    Horizon {h:2d}: AC(1)={ac1:+.4f}, Variance Ratio={vr:.4f} (1.0=RW, <1=MR, >1=trend)")


def spread_analysis(day):
    """Analyze bid-ask spread patterns."""
    fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    spreads = []
    timestamps = []
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "ASH_COATED_OSMIUM":
                continue
            bp1 = row["bid_price_1"].strip()
            ap1 = row["ask_price_1"].strip()
            if not bp1 or not ap1:
                continue
            spread = float(ap1) - float(bp1)
            spreads.append(spread)
            timestamps.append(int(row["timestamp"]))

    if spreads:
        mean_s = sum(spreads) / len(spreads)
        print(f"    Day {day}: mean spread={mean_s:.2f}, min={min(spreads):.0f}, max={max(spreads):.0f}")
        # Spread distribution
        spread_counts = defaultdict(int)
        for s in spreads:
            spread_counts[s] += 1
        for s in sorted(spread_counts.keys()):
            pct = spread_counts[s] / len(spreads) * 100
            print(f"      Spread {s:6.1f}: {spread_counts[s]:5d} ({pct:5.1f}%)")


def return_by_spread(day):
    """Analyze if spread predicts next return."""
    fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    data = []
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "ASH_COATED_OSMIUM":
                continue
            bp1 = row["bid_price_1"].strip()
            ap1 = row["ask_price_1"].strip()
            if not bp1 or not ap1:
                continue
            mid = (float(bp1) + float(ap1)) / 2.0
            spread = float(ap1) - float(bp1)
            data.append((int(row["timestamp"]), mid, spread))

    # Group next-tick return by current spread
    spread_returns = defaultdict(list)
    for i in range(1, len(data)):
        ret = data[i][1] - data[i-1][1]
        spread_returns[data[i-1][2]].append(ret)

    print(f"\n    Day {day}: Return conditional on spread")
    for s in sorted(spread_returns.keys()):
        rets = spread_returns[s]
        if len(rets) < 5:
            continue
        mean_r = sum(rets) / len(rets)
        std_r = math.sqrt(sum((r - mean_r)**2 for r in rets) / len(rets)) if len(rets) > 1 else 0
        print(f"      Spread {s:6.1f}: mean_ret={mean_r:+.4f}, std={std_r:.4f}, n={len(rets)}")


def mid_price_asymmetry(day):
    """Check if bid/ask are symmetric around mid. Asymmetry might signal direction."""
    fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    data = []
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "ASH_COATED_OSMIUM":
                continue
            bp1 = row["bid_price_1"].strip()
            ap1 = row["ask_price_1"].strip()
            if not bp1 or not ap1:
                continue
            bid = float(bp1)
            ask = float(ap1)
            mid = (bid + ask) / 2.0
            # microprice: volume-weighted mid
            bv1 = row["bid_volume_1"].strip()
            av1 = row["ask_volume_1"].strip()
            if bv1 and av1:
                bv = float(bv1)
                av = float(av1)
                microprice = (bid * av + ask * bv) / (av + bv)
                imbalance = bv / (bv + av)  # >0.5 means more on bid side
                data.append((int(row["timestamp"]), mid, microprice, imbalance))

    if not data:
        return

    # Does microprice predict next return?
    correct = 0
    total = 0
    for i in range(1, len(data)):
        next_ret = data[i][1] - data[i-1][1]
        micro_signal = data[i-1][2] - data[i-1][1]  # microprice - mid
        if next_ret != 0 and micro_signal != 0:
            total += 1
            if (next_ret > 0 and micro_signal > 0) or (next_ret < 0 and micro_signal < 0):
                correct += 1

    if total > 0:
        print(f"    Day {day}: Microprice predicts direction: {correct}/{total} = {correct/total:.4f}")

    # Imbalance bins
    imb_returns = defaultdict(list)
    for i in range(1, len(data)):
        next_ret = data[i][1] - data[i-1][1]
        imb_bin = round(data[i-1][3], 1)  # round to 0.1
        imb_returns[imb_bin].append(next_ret)

    print(f"    Day {day}: Return by order imbalance bin:")
    for b in sorted(imb_returns.keys()):
        rets = imb_returns[b]
        if len(rets) < 10:
            continue
        mean_r = sum(rets) / len(rets)
        print(f"      Imbalance {b:.1f}: mean_ret={mean_r:+.4f}, n={len(rets)}")


def ipr_cross_signal(day):
    """Check if INTARIAN_PEPPER_ROOT moves predict ACO moves."""
    fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    aco_data = {}
    ipr_data = {}
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            bp1 = row["bid_price_1"].strip()
            ap1 = row["ask_price_1"].strip()
            if not bp1 or not ap1:
                continue
            mid = (float(bp1) + float(ap1)) / 2.0
            ts = int(row["timestamp"])
            if row["product"] == "ASH_COATED_OSMIUM":
                aco_data[ts] = mid
            elif row["product"] == "INTARIAN_PEPPER_ROOT":
                ipr_data[ts] = mid

    # Align timestamps
    common_ts = sorted(set(aco_data.keys()) & set(ipr_data.keys()))
    if len(common_ts) < 100:
        print(f"    Day {day}: Not enough common timestamps ({len(common_ts)})")
        return

    # Compute returns
    aco_rets = []
    ipr_rets = []
    for i in range(1, len(common_ts)):
        aco_rets.append(aco_data[common_ts[i]] - aco_data[common_ts[i-1]])
        ipr_rets.append(ipr_data[common_ts[i]] - ipr_data[common_ts[i-1]])

    # Cross-correlation: does IPR(t) predict ACO(t+1)?
    n = len(aco_rets)
    for lag_name, x, y in [
        ("IPR(t) -> ACO(t)", ipr_rets, aco_rets),
        ("IPR(t) -> ACO(t+1)", ipr_rets[:-1], aco_rets[1:]),
        ("ACO(t) -> IPR(t+1)", aco_rets[:-1], ipr_rets[1:]),
    ]:
        mx = sum(x) / len(x)
        my = sum(y) / len(y)
        cov = sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / len(x)
        sx = math.sqrt(sum((xi - mx)**2 for xi in x) / len(x))
        sy = math.sqrt(sum((yi - my)**2 for yi in y) / len(y))
        corr = cov / (sx * sy) if sx > 0 and sy > 0 else 0
        print(f"    Day {day}: {lag_name}: corr={corr:+.4f}")


def tick_of_day_pattern(day_data):
    """Check if certain tick positions within the day have predictable returns."""
    print("\n" + "="*70)
    print("BONUS: TICK-OF-DAY PATTERN")
    print("="*70)

    # Aggregate returns by tick position across days
    tick_returns = defaultdict(list)
    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        for i, r in enumerate(returns):
            tick_returns[i].append(r)

    # Find ticks with consistent direction across all days
    consistent = []
    for tick in sorted(tick_returns.keys()):
        rets = tick_returns[tick]
        if len(rets) == 3:
            if all(r > 0 for r in rets) or all(r < 0 for r in rets):
                mean_r = sum(rets) / len(rets)
                consistent.append((tick, mean_r, rets))

    print(f"  Ticks with same-direction return on ALL 3 days: {len(consistent)} / {len(tick_returns)}")
    if consistent:
        # Expected by chance: ~25% of ticks (prob all same sign for 3 days ≈ 2*(0.5)^3 = 0.25)
        print(f"  Expected by chance: ~{len(tick_returns) * 0.25:.0f}")
        # Show strongest
        consistent.sort(key=lambda x: abs(x[1]), reverse=True)
        print(f"  Top 20 strongest consistent ticks:")
        for tick, mean_r, rets in consistent[:20]:
            print(f"    Tick {tick:4d}: mean={mean_r:+.3f}, days={[f'{r:+.1f}' for r in rets]}")


def main():
    print("="*70)
    print("ASH_COATED_OSMIUM - DEEP STATISTICAL ANALYSIS")
    print("="*70)

    day_data = load_aco_mids()
    day_trades = load_aco_trades()

    # Combine all days for aggregate analysis
    all_mids = []
    all_returns = []
    for day in DAYS:
        ts, mids = day_data[day]
        print(f"\nDay {day}: {len(mids)} clean ticks (with bid+ask), price range [{min(mids):.1f}, {max(mids):.1f}]")
        returns = compute_returns(mids)
        all_mids.extend(mids)
        all_returns.extend(returns)

    print(f"\nTotal: {len(all_mids)} ticks, {len(all_returns)} returns")

    # =========================================================================
    # 1. REGIME DETECTION
    # =========================================================================
    print("\n" + "="*70)
    print("1. REGIME DETECTION (volatility by segment)")
    print("="*70)
    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        print(f"\n  Day {day}:")
        segments = regime_analysis(ts, mids, returns)
        for seg in segments:
            bar = "#" * int(seg["volatility"] * 10)
            print(f"    Seg {seg['segment']:2d} ({seg['ts_range']:>13s}): "
                  f"vol={seg['volatility']:.4f}  mean={seg['mean_return']:+.4f}  {bar}")

    # =========================================================================
    # 2. DISTRIBUTION ANALYSIS
    # =========================================================================
    print("\n" + "="*70)
    print("2. DISTRIBUTION ANALYSIS")
    print("="*70)
    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        stats = distribution_stats(returns)
        print(f"\n  Day {day}:")
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"    {k:20s}: {v:+.4f}")
            else:
                print(f"    {k:20s}: {v}")

    print("\n  AGGREGATE:")
    stats = distribution_stats(all_returns)
    for k, v in stats.items():
        if isinstance(v, float):
            print(f"    {k:20s}: {v:+.4f}")
        else:
            print(f"    {k:20s}: {v}")

    # Histogram (text-based)
    print("\n  Return histogram (aggregate):")
    sorted_r = sorted(all_returns)
    bins = list(range(int(min(all_returns)) - 1, int(max(all_returns)) + 2))
    hist = defaultdict(int)
    for r in all_returns:
        b = int(round(r))
        hist[b] += 1
    max_count = max(hist.values())
    for b in sorted(hist.keys()):
        bar_len = int(hist[b] / max_count * 60)
        print(f"    {b:+4d}: {'#' * bar_len} ({hist[b]})")

    # =========================================================================
    # 3. CONDITIONAL RETURNS
    # =========================================================================
    print("\n" + "="*70)
    print("3. CONDITIONAL RETURNS")
    print("="*70)

    # 3a. Transition probabilities
    print("\n  3a. Transition probabilities:")
    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        tp = transition_probs(returns)
        print(f"    Day {day}: P(up|up)={tp['P(up|up)']:.4f}  P(down|up)={tp['P(down|up)']:.4f}  "
              f"P(up|down)={tp['P(up|down)']:.4f}  P(down|down)={tp['P(down|down)']:.4f}")

    tp = transition_probs(all_returns)
    print(f"    ALL:    P(up|up)={tp['P(up|up)']:.4f}  P(down|up)={tp['P(down|up)']:.4f}  "
          f"P(up|down)={tp['P(up|down)']:.4f}  P(down|down)={tp['P(down|down)']:.4f}")
    print(f"            n_after_up={tp['n_after_up']}, n_after_down={tp['n_after_down']}")

    # Random walk would give ~0.5 for each. Deviation = signal!
    for key in ["P(up|up)", "P(down|down)"]:
        val = tp[key]
        if val > 0.52:
            print(f"    >>> MOMENTUM SIGNAL: {key}={val:.4f} (>0.52)")
        elif val < 0.48:
            print(f"    >>> MEAN REVERSION SIGNAL: {key}={val:.4f} (<0.48)")

    # 3b. After big moves
    print("\n  3b. After big moves (|return| > 1):")
    for threshold in [1, 2, 3, 5]:
        big_up, big_down = conditional_return_after_big_move(all_returns, threshold)
        if big_up:
            mu = sum(big_up) / len(big_up)
            print(f"    After return > {threshold}: mean next return = {mu:+.4f} (n={len(big_up)})")
        if big_down:
            mu = sum(big_down) / len(big_down)
            print(f"    After return < -{threshold}: mean next return = {mu:+.4f} (n={len(big_down)})")

    # 3c. Consecutive direction analysis
    print("\n  3c. After N consecutive same-direction moves:")
    consec = consecutive_direction_analysis(all_returns)
    for n, data in consec.items():
        au = data["after_n_up"]
        ad = data["after_n_down"]
        total_up = au["continue"] + au["reverse"]
        total_dn = ad["continue"] + ad["reverse"]
        print(f"    After {n} up:   P(continue)={au['P(continue)']:.4f} ({au['continue']}/{total_up})")
        print(f"    After {n} down: P(continue)={ad['P(continue)']:.4f} ({ad['continue']}/{total_dn})")

    # =========================================================================
    # 4. AUTOCORRELATION & FOURIER ANALYSIS
    # =========================================================================
    print("\n" + "="*70)
    print("4. AUTOCORRELATION & FOURIER ANALYSIS")
    print("="*70)

    print("\n  4a. Return autocorrelation (aggregate):")
    sig_lags = analyze_lag_autocorrelation(all_returns, max_lag=50)

    if sig_lags:
        print(f"\n  Significant lags: {sig_lags}")

    print("\n  4b. Top FFT periods (aggregate, checking periods 2-500):")
    fft_results = fft_analysis(all_returns, top_n=15)
    for period, power in fft_results:
        print(f"    Period {period:4d} ticks: power = {power:.2f}")

    # =========================================================================
    # 5. RUN LENGTH ANALYSIS
    # =========================================================================
    print("\n" + "="*70)
    print("5. RUN LENGTH ANALYSIS")
    print("="*70)

    run_lens, counts, n_up, n_down = run_length_analysis(all_returns)
    print(f"\n  Direction counts: up={n_up}, down={n_down}, zero={counts['zero']}")
    p_up = n_up / (n_up + n_down) if (n_up + n_down) else 0.5
    print(f"  P(up) = {p_up:.4f}")

    print(f"\n  Run length distribution (observed vs expected for random walk):")
    total_runs = sum(run_lens.values())
    for length in sorted(run_lens.keys()):
        observed = run_lens[length]
        obs_pct = observed / total_runs * 100
        # Expected: geometric distribution P(run=k) = p * (1-p)^(k-1)
        # For p_continue (after up, prob of another up, etc.)
        expected_pct = p_up * (1 - p_up) ** (length - 1) * 100 * 2  # *2 for up+down
        print(f"    Length {length:2d}: observed={observed:5d} ({obs_pct:5.1f}%)  "
              f"expected_RW~{expected_pct:5.1f}%  ratio={obs_pct/expected_pct:.3f}" if expected_pct > 0 else
              f"    Length {length:2d}: observed={observed:5d} ({obs_pct:5.1f}%)")

    # =========================================================================
    # 6. HURST EXPONENT
    # =========================================================================
    print("\n" + "="*70)
    print("6. HURST EXPONENT")
    print("="*70)

    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        H = hurst_exponent(returns)
        interp = "MEAN REVERTING" if H < 0.45 else ("TRENDING" if H > 0.55 else "RANDOM WALK")
        print(f"  Day {day}: H = {H:.4f} ({interp})")

    H = hurst_exponent(all_returns)
    interp = "MEAN REVERTING" if H < 0.45 else ("TRENDING" if H > 0.55 else "RANDOM WALK")
    print(f"  ALL:    H = {H:.4f} ({interp})")

    # =========================================================================
    # 7. VARIANCE RATIO TEST
    # =========================================================================
    print("\n" + "="*70)
    print("7. VARIANCE RATIO TEST (multi-tick horizon)")
    print("="*70)
    for day in DAYS:
        ts, mids = day_data[day]
        print(f"\n  Day {day}:")
        multi_tick_returns_analysis(mids)

    # =========================================================================
    # 8. CROSS-DAY COMPARISON
    # =========================================================================
    cross_day_comparison(day_data)

    # =========================================================================
    # 9. GARCH EFFECTS (volatility clustering)
    # =========================================================================
    print("\n" + "="*70)
    print("9. GARCH EFFECTS (squared returns autocorrelation)")
    print("="*70)

    for day in DAYS:
        ts, mids = day_data[day]
        returns = compute_returns(mids)
        sq_ac = squared_returns_autocorr(returns, max_lag=10)
        threshold = 2.0 / math.sqrt(len(returns))
        sigs = [(lag, ac) for lag, ac in sq_ac.items() if abs(ac) > threshold]
        print(f"  Day {day}: threshold={threshold:.4f}")
        for lag, ac in sq_ac.items():
            marker = " ***" if abs(ac) > threshold else ""
            print(f"    Lag {lag:2d}: {ac:+.4f}{marker}")
        if sigs:
            print(f"    SIGNIFICANT: {sigs}")

    # =========================================================================
    # 10. SPREAD & MICROSTRUCTURE
    # =========================================================================
    print("\n" + "="*70)
    print("10. SPREAD & MICROSTRUCTURE ANALYSIS")
    print("="*70)

    print("\n  Spread distribution:")
    for day in DAYS:
        spread_analysis(day)

    print("\n  Return conditional on spread:")
    for day in DAYS:
        return_by_spread(day)

    print("\n  Microprice & order imbalance:")
    for day in DAYS:
        mid_price_asymmetry(day)

    # =========================================================================
    # 11. CROSS-PRODUCT SIGNAL
    # =========================================================================
    print("\n" + "="*70)
    print("11. CROSS-PRODUCT SIGNAL (IPR -> ACO)")
    print("="*70)
    for day in DAYS:
        ipr_cross_signal(day)

    # =========================================================================
    # 12. TRADE ANALYSIS
    # =========================================================================
    print("\n" + "="*70)
    print("12. TRADE ANALYSIS (who trades ACO?)")
    print("="*70)
    analyze_trade_patterns(day_trades)

    # =========================================================================
    # TICK OF DAY PATTERN
    # =========================================================================
    tick_of_day_pattern(day_data)

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "="*70)
    print("SUMMARY OF FINDINGS")
    print("="*70)

    tp = transition_probs(all_returns)
    H = hurst_exponent(all_returns)
    stats = distribution_stats(all_returns)
    sq_ac = squared_returns_autocorr(all_returns, 5)
    ac1 = autocorrelation(all_returns, 1)

    print(f"""
  Return autocorrelation(1): {ac1:+.4f}
  Hurst exponent: {H:.4f}
  P(up|up): {tp['P(up|up)']:.4f}
  P(down|down): {tp['P(down|down)']:.4f}
  Skewness: {stats['skewness']:.4f}
  Excess kurtosis: {stats['excess_kurtosis']:.4f}
  Squared returns AC(1): {sq_ac[1]:+.4f}

  INTERPRETATION:
  - AC(1) {'< 0 suggests MEAN REVERSION' if ac1 < -0.02 else ('> 0 suggests MOMENTUM' if ac1 > 0.02 else 'near zero = no linear signal')}
  - Hurst {'< 0.5 suggests MEAN REVERSION' if H < 0.45 else ('> 0.5 suggests TRENDING' if H > 0.55 else 'near 0.5 = random walk')}
  - Kurtosis {'> 0 = FAT TAILS (extreme moves more likely than normal)' if stats['excess_kurtosis'] > 0.5 else 'near normal'}
  - Vol clustering {'PRESENT' if sq_ac[1] > 0.05 else 'ABSENT'}
    """)


if __name__ == "__main__":
    main()
