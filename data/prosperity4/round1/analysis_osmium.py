"""
Deep OSMIUM Pattern Analysis
=============================
Uses days -2 and -1 for discovery, day 0 for validation.
Applies multiple quant/microstructure techniques to find hidden patterns.
"""
import numpy as np
import csv
import sys
from collections import defaultdict

# ── Load data ──────────────────────────────────────────────────────────────
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
                    'buyer': r.get('buyer', ''),
                    'seller': r.get('seller', ''),
                })
    return rows

def load_all_prices(path):
    """Load all products from a prices file."""
    products = defaultdict(list)
    with open(path, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            prod = r['product']
            row = {
                'ts': int(r['timestamp']),
                'bid1': float(r['bid_price_1']) if r['bid_price_1'] else None,
                'bv1': int(r['bid_volume_1']) if r['bid_volume_1'] else 0,
                'ask1': float(r['ask_price_1']) if r['ask_price_1'] else None,
                'av1': int(r['ask_volume_1']) if r['ask_volume_1'] else 0,
                'mid': float(r['mid_price']) if r['mid_price'] else None,
            }
            products[prod].append(row)
    return products

base = "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round1/"

print("=" * 80)
print("OSMIUM DEEP PATTERN ANALYSIS")
print("=" * 80)

# Load OSMIUM prices for 3 days
osm_d2 = load_prices(base + "prices_round_1_day_-2.csv")
osm_d1 = load_prices(base + "prices_round_1_day_-1.csv")
osm_d0 = load_prices(base + "prices_round_1_day_0.csv")

# Load trades
trades_d2 = load_trades(base + "trades_round_1_day_-2.csv")
trades_d1 = load_trades(base + "trades_round_1_day_-1.csv")
trades_d0 = load_trades(base + "trades_round_1_day_0.csv")

# Load PEPPER for cross-asset analysis
all_d2 = load_all_prices(base + "prices_round_1_day_-2.csv")
all_d1 = load_all_prices(base + "prices_round_1_day_-1.csv")
all_d0 = load_all_prices(base + "prices_round_1_day_0.csv")

# Combine training days
osm_train = osm_d2 + osm_d1
trades_train = trades_d2 + trades_d1

print(f"\nData: {len(osm_d2)} rows day-2, {len(osm_d1)} rows day-1, {len(osm_d0)} rows day 0")
print(f"Trades: {len(trades_d2)} day-2, {len(trades_d1)} day-1, {len(trades_d0)} day 0")

# ══════════════════════════════════════════════════════════════════════════
# 1. BASIC STATISTICS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("1. BASIC STATISTICS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = [r['mid'] for r in data if r['mid'] is not None]
    spreads = []
    for r in data:
        if r['bid1'] is not None and r['ask1'] is not None:
            spreads.append(r['ask1'] - r['bid1'])

    mids_arr = np.array(mids)
    print(f"\n{label}:")
    print(f"  Mid: mean={np.mean(mids_arr):.2f}, std={np.std(mids_arr):.2f}, "
          f"min={np.min(mids_arr):.1f}, max={np.max(mids_arr):.1f}")
    print(f"  Range: {np.max(mids_arr) - np.min(mids_arr):.1f}")
    if spreads:
        s = np.array(spreads)
        print(f"  Spread: mean={np.mean(s):.2f}, median={np.median(s):.1f}, "
              f"min={np.min(s):.1f}, max={np.max(s):.1f}")

    # Book presence (how often is there a bid/ask)
    has_bid = sum(1 for r in data if r['bid1'] is not None)
    has_ask = sum(1 for r in data if r['ask1'] is not None)
    has_both = sum(1 for r in data if r['bid1'] is not None and r['ask1'] is not None)
    print(f"  Book: bid_present={has_bid}/{len(data)} ({100*has_bid/len(data):.1f}%), "
          f"ask_present={has_ask}/{len(data)} ({100*has_ask/len(data):.1f}%), "
          f"both={has_both}/{len(data)} ({100*has_both/len(data):.1f}%)")

    # Book depth levels
    has_l2 = sum(1 for r in data if r['bid2'] is not None or r['ask2'] is not None)
    has_l3 = sum(1 for r in data if r['bid3'] is not None or r['ask3'] is not None)
    print(f"  Depth: L2_present={has_l2}, L3_present={has_l3}")

# ══════════════════════════════════════════════════════════════════════════
# 2. MID-PRICE DYNAMICS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("2. MID-PRICE DYNAMICS & RETURNS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])
    returns = np.diff(mids)
    pct_returns = returns / mids[:-1]

    print(f"\n{label}:")
    print(f"  Returns: mean={np.mean(returns):.4f}, std={np.std(returns):.4f}")
    print(f"  Skewness: {np.mean((returns - np.mean(returns))**3) / np.std(returns)**3:.4f}")
    kurtosis = np.mean((returns - np.mean(returns))**4) / np.std(returns)**4 - 3
    print(f"  Excess kurtosis: {kurtosis:.4f}")

    # Autocorrelation of returns
    print(f"  Return autocorrelations:")
    for lag in [1, 2, 3, 5, 10, 20, 50, 100]:
        if len(returns) > lag:
            ac = np.corrcoef(returns[:-lag], returns[lag:])[0, 1]
            print(f"    lag {lag:3d}: {ac:+.4f}", end="")
            if abs(ac) > 2/np.sqrt(len(returns)):
                print(" ***", end="")
            print()

    # Autocorrelation of absolute returns (volatility clustering)
    abs_ret = np.abs(returns)
    print(f"  |Return| autocorrelations (volatility clustering):")
    for lag in [1, 2, 5, 10, 20, 50]:
        if len(abs_ret) > lag:
            ac = np.corrcoef(abs_ret[:-lag], abs_ret[lag:])[0, 1]
            print(f"    lag {lag:3d}: {ac:+.4f}", end="")
            if abs(ac) > 2/np.sqrt(len(abs_ret)):
                print(" ***", end="")
            print()

# ══════════════════════════════════════════════════════════════════════════
# 3. ORDER BOOK IMBALANCE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("3. ORDER BOOK IMBALANCE (OBI) ANALYSIS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    obis = []
    future_returns = []

    for i, r in enumerate(data):
        if r['bid1'] is not None and r['ask1'] is not None and r['bv1'] > 0 and r['av1'] > 0:
            obi = (r['bv1'] - r['av1']) / (r['bv1'] + r['av1'])
            obis.append(obi)

            # Look ahead for future mid change
            if i + 1 < len(data) and data[i+1]['mid'] is not None and r['mid'] is not None:
                future_returns.append(data[i+1]['mid'] - r['mid'])
            else:
                future_returns.append(None)

    obis = np.array(obis)
    print(f"\n{label}:")
    print(f"  OBI: mean={np.mean(obis):.4f}, std={np.std(obis):.4f}")

    # OBI predictive power
    valid_pairs = [(o, f) for o, f in zip(obis, future_returns) if f is not None]
    if valid_pairs:
        o_arr = np.array([p[0] for p in valid_pairs])
        f_arr = np.array([p[1] for p in valid_pairs])
        corr = np.corrcoef(o_arr, f_arr)[0, 1]
        print(f"  OBI->next_mid_change correlation: {corr:.4f}")

        # Bucket analysis
        for lo, hi, name in [(-1, -0.3, "strong_sell"), (-0.3, -0.05, "weak_sell"),
                              (-0.05, 0.05, "neutral"), (0.05, 0.3, "weak_buy"), (0.3, 1.01, "strong_buy")]:
            mask = (o_arr >= lo) & (o_arr < hi)
            if np.sum(mask) > 0:
                avg_ret = np.mean(f_arr[mask])
                print(f"    {name:12s}: n={np.sum(mask):4d}, avg_future_ret={avg_ret:+.4f}")

# ══════════════════════════════════════════════════════════════════════════
# 4. SPREAD DYNAMICS & PATTERNS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("4. SPREAD DYNAMICS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    spreads = []
    ts_list = []
    for r in data:
        if r['bid1'] is not None and r['ask1'] is not None:
            spreads.append(r['ask1'] - r['bid1'])
            ts_list.append(r['ts'])

    if not spreads:
        continue

    s = np.array(spreads)
    ts = np.array(ts_list)

    print(f"\n{label}:")
    # Spread distribution
    unique_spreads, counts = np.unique(s, return_counts=True)
    print(f"  Spread distribution:")
    for sp, c in sorted(zip(unique_spreads, counts), key=lambda x: -x[1])[:10]:
        print(f"    {sp:6.1f}: {c:4d} ({100*c/len(s):.1f}%)")

    # Spread over time (quarters)
    max_ts = np.max(ts)
    for q in range(4):
        lo_ts = q * max_ts / 4
        hi_ts = (q+1) * max_ts / 4
        mask = (ts >= lo_ts) & (ts < hi_ts)
        if np.sum(mask) > 5:
            print(f"  Q{q+1} (ts {int(lo_ts)}-{int(hi_ts)}): mean_spread={np.mean(s[mask]):.2f}, "
                  f"median={np.median(s[mask]):.1f}")

# ══════════════════════════════════════════════════════════════════════════
# 5. VOLUME PATTERNS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("5. VOLUME & DEPTH PATTERNS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    # L1 volume
    bv1s = [r['bv1'] for r in data if r['bv1'] > 0]
    av1s = [r['av1'] for r in data if r['av1'] > 0]
    if bv1s:
        print(f"  Bid vol L1: mean={np.mean(bv1s):.1f}, std={np.std(bv1s):.1f}")
        unique_bv, counts = np.unique(bv1s, return_counts=True)
        top5 = sorted(zip(unique_bv, counts), key=lambda x: -x[1])[:8]
        print(f"  Bid vol distribution: {[(int(v), int(c)) for v, c in top5]}")
    if av1s:
        print(f"  Ask vol L1: mean={np.mean(av1s):.1f}, std={np.std(av1s):.1f}")
        unique_av, counts = np.unique(av1s, return_counts=True)
        top5 = sorted(zip(unique_av, counts), key=lambda x: -x[1])[:8]
        print(f"  Ask vol distribution: {[(int(v), int(c)) for v, c in top5]}")

    # Is volume symmetric?
    bv_total = [r['bv1'] + r['bv2'] + r['bv3'] for r in data]
    av_total = [r['av1'] + r['av2'] + r['av3'] for r in data]
    print(f"  Total bid vol: {sum(bv_total)}, Total ask vol: {sum(av_total)}, "
          f"ratio: {sum(bv_total)/max(sum(av_total),1):.3f}")

# ══════════════════════════════════════════════════════════════════════════
# 6. BID/ASK PRICE LEVEL ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("6. PRICE LEVEL ANALYSIS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    bid_prices = [r['bid1'] for r in data if r['bid1'] is not None]
    ask_prices = [r['ask1'] for r in data if r['ask1'] is not None]

    if bid_prices:
        bp = np.array(bid_prices)
        unique_bp, counts = np.unique(bp, return_counts=True)
        print(f"  Best bid prices (top 10):")
        for p, c in sorted(zip(unique_bp, counts), key=lambda x: -x[1])[:10]:
            print(f"    {p:8.1f}: {c:4d} times ({100*c/len(bp):.1f}%)")

    if ask_prices:
        ap = np.array(ask_prices)
        unique_ap, counts = np.unique(ap, return_counts=True)
        print(f"  Best ask prices (top 10):")
        for p, c in sorted(zip(unique_ap, counts), key=lambda x: -x[1])[:10]:
            print(f"    {p:8.1f}: {c:4d} times ({100*c/len(ap):.1f}%)")

    # Mid-price from bid1/ask1 when both exist
    mids_from_book = []
    for r in data:
        if r['bid1'] is not None and r['ask1'] is not None:
            mids_from_book.append((r['bid1'] + r['ask1']) / 2)
    if mids_from_book:
        m = np.array(mids_from_book)
        unique_m, counts = np.unique(m, return_counts=True)
        print(f"  Microprice (mid from L1, top 10):")
        for p, c in sorted(zip(unique_m, counts), key=lambda x: -x[1])[:10]:
            print(f"    {p:9.2f}: {c:4d} times")

# ══════════════════════════════════════════════════════════════════════════
# 7. SPECTRAL ANALYSIS (FFT)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("7. SPECTRAL ANALYSIS (FFT)")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])

    # Detrend
    detrended = mids - np.mean(mids)

    # FFT
    fft_vals = np.fft.rfft(detrended)
    power = np.abs(fft_vals) ** 2
    freqs = np.fft.rfftfreq(len(detrended))

    # Top frequencies (skip DC)
    top_idx = np.argsort(power[1:])[::-1][:15] + 1

    print(f"\n{label} (n={len(mids)}):")
    print(f"  Top 15 frequency components:")
    for idx in top_idx:
        period = 1.0 / freqs[idx] if freqs[idx] > 0 else float('inf')
        print(f"    freq={freqs[idx]:.6f}, period={period:.1f} ticks, power={power[idx]:.1f}")

# ══════════════════════════════════════════════════════════════════════════
# 8. HURST EXPONENT (R/S Analysis)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("8. HURST EXPONENT (R/S Analysis)")
print("=" * 80)

def hurst_rs(ts, min_n=10, max_n=None):
    """Compute Hurst exponent using R/S analysis."""
    n = len(ts)
    if max_n is None:
        max_n = n // 2

    ns = []
    rs_values = []

    # Use powers of 2 for subseries lengths
    for exp in range(int(np.log2(min_n)), int(np.log2(max_n)) + 1):
        sub_n = 2 ** exp
        if sub_n > n // 2:
            break

        num_subs = n // sub_n
        rs_list = []

        for i in range(num_subs):
            sub = ts[i*sub_n:(i+1)*sub_n]
            mean_sub = np.mean(sub)
            devs = np.cumsum(sub - mean_sub)
            R = np.max(devs) - np.min(devs)
            S = np.std(sub)
            if S > 0:
                rs_list.append(R / S)

        if rs_list:
            ns.append(sub_n)
            rs_values.append(np.mean(rs_list))

    if len(ns) > 1:
        log_n = np.log(ns)
        log_rs = np.log(rs_values)
        H = np.polyfit(log_n, log_rs, 1)[0]
        return H
    return None

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])
    returns = np.diff(mids)

    H = hurst_rs(returns)
    print(f"\n{label}:")
    print(f"  Hurst exponent (returns): {H:.4f}" if H else "  Could not compute")
    if H:
        if H < 0.45:
            print(f"  → MEAN REVERTING (H < 0.5)")
        elif H > 0.55:
            print(f"  → TRENDING (H > 0.5)")
        else:
            print(f"  → RANDOM WALK (H ≈ 0.5)")

    # Also on price levels
    H_price = hurst_rs(mids)
    print(f"  Hurst exponent (price levels): {H_price:.4f}" if H_price else "  Could not compute")

# ══════════════════════════════════════════════════════════════════════════
# 9. TRADE FLOW ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("9. TRADE FLOW ANALYSIS")
print("=" * 80)

for label, trades, prices in [("Day -2", trades_d2, osm_d2), ("Day -1", trades_d1, osm_d1), ("Day 0", trades_d0, osm_d0)]:
    print(f"\n{label}: {len(trades)} trades")
    if not trades:
        continue

    # Trade price distribution
    tprices = np.array([t['price'] for t in trades])
    tqtys = np.array([t['qty'] for t in trades])

    print(f"  Price: mean={np.mean(tprices):.2f}, std={np.std(tprices):.2f}")
    print(f"  Qty: mean={np.mean(tqtys):.2f}, total={np.sum(tqtys)}")

    # Inter-trade times
    trade_times = np.array([t['ts'] for t in trades])
    if len(trade_times) > 1:
        inter_times = np.diff(trade_times)
        print(f"  Inter-trade time: mean={np.mean(inter_times):.1f}, "
              f"median={np.median(inter_times):.1f}, std={np.std(inter_times):.1f}")

    # Trade direction estimation (Lee-Ready)
    # Compare trade price to prevailing mid at that timestamp
    mid_lookup = {}
    for r in prices:
        mid_lookup[r['ts']] = r['mid']

    buys, sells, unknown = 0, 0, 0
    for t in trades:
        mid = mid_lookup.get(t['ts'])
        if mid is not None:
            if t['price'] > mid:
                buys += 1
            elif t['price'] < mid:
                sells += 1
            else:
                unknown += 1
        else:
            unknown += 1
    print(f"  Direction (Lee-Ready): buys={buys}, sells={sells}, unknown={unknown}")

# ══════════════════════════════════════════════════════════════════════════
# 10. CROSS-ASSET ANALYSIS (OSMIUM vs PEPPER)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("10. CROSS-ASSET ANALYSIS (OSMIUM vs PEPPER ROOT)")
print("=" * 80)

for label, all_data in [("Day -2", all_d2), ("Day -1", all_d1), ("Day 0", all_d0)]:
    osm_data = {r['ts']: r['mid'] for r in all_data.get('ASH_COATED_OSMIUM', []) if r['mid'] is not None}
    pep_data = {r['ts']: r['mid'] for r in all_data.get('INTARIAN_PEPPER_ROOT', []) if r['mid'] is not None}

    common_ts = sorted(set(osm_data.keys()) & set(pep_data.keys()))
    if not common_ts:
        print(f"\n{label}: No common timestamps")
        continue

    osm_mids = np.array([osm_data[t] for t in common_ts])
    pep_mids = np.array([pep_data[t] for t in common_ts])

    # Level correlation
    corr_level = np.corrcoef(osm_mids, pep_mids)[0, 1]

    # Return correlation
    osm_ret = np.diff(osm_mids)
    pep_ret = np.diff(pep_mids)
    corr_ret = np.corrcoef(osm_ret, pep_ret)[0, 1]

    # Spread
    spread = osm_mids - pep_mids

    print(f"\n{label} ({len(common_ts)} common timestamps):")
    print(f"  Level correlation: {corr_level:.4f}")
    print(f"  Return correlation: {corr_ret:.4f}")
    print(f"  Price spread (OSM-PEP): mean={np.mean(spread):.2f}, std={np.std(spread):.2f}")

    # Lead-lag analysis
    print(f"  Lead-lag (cross-correlation):")
    for lag in [-10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 10]:
        if abs(lag) < len(osm_ret):
            if lag > 0:
                cc = np.corrcoef(pep_ret[:-lag], osm_ret[lag:])[0, 1]
                print(f"    PEP→OSM lag {lag:+3d}: {cc:+.4f}")
            elif lag < 0:
                cc = np.corrcoef(osm_ret[:lag], pep_ret[-lag:])[0, 1]
                print(f"    OSM→PEP lag {-lag:+3d}: {cc:+.4f}")
            else:
                cc = np.corrcoef(osm_ret, pep_ret)[0, 1]
                print(f"    Contemporaneous:   {cc:+.4f}")

# ══════════════════════════════════════════════════════════════════════════
# 11. TIME-OF-DAY PATTERNS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("11. TIME-OF-DAY PATTERNS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    # Divide day into 10 buckets
    mids = [(r['ts'], r['mid']) for r in data if r['mid'] is not None]
    if not mids:
        continue

    max_ts = max(t for t, _ in mids)
    n_buckets = 10

    print(f"\n{label}:")
    for b in range(n_buckets):
        lo = b * max_ts / n_buckets
        hi = (b + 1) * max_ts / n_buckets
        bucket_mids = [m for t, m in mids if lo <= t < hi]
        if bucket_mids:
            bm = np.array(bucket_mids)
            rets = np.diff(bm)
            vol = np.std(rets) if len(rets) > 1 else 0
            print(f"  Bucket {b:2d} (ts {int(lo):6d}-{int(hi):6d}): "
                  f"mean={np.mean(bm):.2f}, vol={vol:.3f}, n={len(bm)}, "
                  f"drift={bm[-1]-bm[0]:+.2f}")

# ══════════════════════════════════════════════════════════════════════════
# 12. MICROSTRUCTURE: KYLE'S LAMBDA (Price Impact)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("12. KYLE'S LAMBDA (Price Impact)")
print("=" * 80)

for label, trades, prices in [("Day -2", trades_d2, osm_d2), ("Day -1", trades_d1, osm_d1)]:
    mid_ts = {r['ts']: r['mid'] for r in prices if r['mid'] is not None}

    impacts = []
    for t in trades:
        ts = t['ts']
        # Find mid before and after
        if ts in mid_ts:
            mid_at = mid_ts[ts]
            # Find next mid
            next_ts = ts + 100
            while next_ts <= ts + 500 and next_ts not in mid_ts:
                next_ts += 100
            if next_ts in mid_ts:
                impact = mid_ts[next_ts] - mid_at
                signed_qty = t['qty'] if t['price'] > mid_at else -t['qty']
                impacts.append((signed_qty, impact))

    if impacts:
        sq = np.array([i[0] for i in impacts])
        imp = np.array([i[1] for i in impacts])
        if np.std(sq) > 0:
            lambda_kyle = np.polyfit(sq, imp, 1)[0]
            corr = np.corrcoef(sq, imp)[0, 1]
            print(f"\n{label}: lambda={lambda_kyle:.4f}, corr={corr:.4f}, n={len(impacts)}")

# ══════════════════════════════════════════════════════════════════════════
# 13. BOOK SHAPE PATTERNS (symmetry, level spacing)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("13. BOOK SHAPE & SYMMETRY ANALYSIS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    # When we have 2 levels, what's the spacing?
    bid_spacings = []
    ask_spacings = []
    for r in data:
        if r['bid1'] is not None and r['bid2'] is not None:
            bid_spacings.append(r['bid1'] - r['bid2'])
        if r['ask1'] is not None and r['ask2'] is not None:
            ask_spacings.append(r['ask2'] - r['ask1'])

    if bid_spacings:
        bs = np.array(bid_spacings)
        print(f"  Bid L1-L2 spacing: mean={np.mean(bs):.2f}, unique={np.unique(bs)}")
    if ask_spacings:
        asps = np.array(ask_spacings)
        print(f"  Ask L1-L2 spacing: mean={np.mean(asps):.2f}, unique={np.unique(asps)}")

    # Volume symmetry (bid vol vs ask vol at each timestamp)
    sym_ratios = []
    for r in data:
        if r['bv1'] > 0 and r['av1'] > 0:
            sym_ratios.append(r['bv1'] / r['av1'])
    if sym_ratios:
        sr = np.array(sym_ratios)
        print(f"  Vol symmetry (bv1/av1): mean={np.mean(sr):.3f}, std={np.std(sr):.3f}")
        # Is it perfectly symmetric?
        exact_sym = sum(1 for r in data if r['bv1'] > 0 and r['av1'] > 0 and r['bv1'] == r['av1'])
        print(f"  Exactly symmetric: {exact_sym}/{len(sym_ratios)} ({100*exact_sym/max(len(sym_ratios),1):.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# 14. REGIME DETECTION (change point analysis)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("14. REGIME DETECTION")
print("=" * 80)

def detect_regimes(mids, window=100):
    """Simple regime detection via rolling mean/vol."""
    n = len(mids)
    regimes = []
    for i in range(window, n, window):
        segment = mids[max(0, i-window):i]
        mean_s = np.mean(segment)
        std_s = np.std(segment)
        trend = segment[-1] - segment[0]
        regimes.append((i, mean_s, std_s, trend))
    return regimes

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])
    regimes = detect_regimes(mids, window=200)

    print(f"\n{label} (200-tick windows):")
    for tick, mean, vol, trend in regimes:
        marker = ""
        if abs(trend) > 2 * np.std(np.diff(mids)) * np.sqrt(200):
            marker = " ** TREND **"
        if vol > 2 * np.std(np.diff(mids)):
            marker += " ** HIGH VOL **"
        print(f"  tick {tick:5d}: mean={mean:.2f}, vol={vol:.3f}, trend={trend:+.2f}{marker}")

# ══════════════════════════════════════════════════════════════════════════
# 15. ONE-SIDED BOOK ANALYSIS (Missing bid or ask)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("15. ONE-SIDED BOOK EVENTS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    no_bid = [(r['ts'], r['ask1'], r['mid']) for r in data if r['bid1'] is None and r['ask1'] is not None]
    no_ask = [(r['ts'], r['bid1'], r['mid']) for r in data if r['ask1'] is None and r['bid1'] is not None]

    print(f"\n{label}:")
    print(f"  No bid (ask only): {len(no_bid)} events")
    if no_bid:
        for ts, ask, mid in no_bid[:10]:
            print(f"    ts={ts}: ask={ask}, mid={mid}")
    print(f"  No ask (bid only): {len(no_ask)} events")
    if no_ask:
        for ts, bid, mid in no_ask[:10]:
            print(f"    ts={ts}: bid={bid}, mid={mid}")

# ══════════════════════════════════════════════════════════════════════════
# 16. WEIGHTED MID-PRICE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("16. WEIGHTED MID-PRICE (MICROPRICE) DYNAMICS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    microprices = []
    simple_mids = []

    for r in data:
        if r['bid1'] is not None and r['ask1'] is not None and r['bv1'] > 0 and r['av1'] > 0:
            # Microprice: weighted by volume on opposite side
            microprice = (r['bid1'] * r['av1'] + r['ask1'] * r['bv1']) / (r['av1'] + r['bv1'])
            microprices.append(microprice)
            simple_mids.append((r['bid1'] + r['ask1']) / 2)

    if microprices:
        mp = np.array(microprices)
        sm = np.array(simple_mids)
        diff = mp - sm
        print(f"\n{label}:")
        print(f"  Microprice - Mid: mean={np.mean(diff):.4f}, std={np.std(diff):.4f}")
        print(f"  Microprice mean={np.mean(mp):.2f}, Simple mid mean={np.mean(sm):.2f}")

        # Which is more predictive of next mid?
        if len(mp) > 1:
            mp_ret = np.diff(mp)
            sm_ret = np.diff(sm)
            # Autocorrelation
            ac_mp = np.corrcoef(mp_ret[:-1], mp_ret[1:])[0, 1]
            ac_sm = np.corrcoef(sm_ret[:-1], sm_ret[1:])[0, 1]
            print(f"  Microprice return AC(1): {ac_mp:.4f}")
            print(f"  Simple mid return AC(1): {ac_sm:.4f}")

# ══════════════════════════════════════════════════════════════════════════
# 17. ENTROPY & INFORMATION CONTENT
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("17. ENTROPY ANALYSIS")
print("=" * 80)

def sample_entropy(data, m=2, r_mult=0.2):
    """Approximate Sample Entropy."""
    n = len(data)
    r = r_mult * np.std(data)
    if r == 0:
        return float('inf')

    # Use a subsample for speed
    if n > 2000:
        data = data[:2000]
        n = 2000

    def count_matches(m_len):
        count = 0
        templates = [data[i:i+m_len] for i in range(n - m_len)]
        for i in range(len(templates)):
            for j in range(i+1, len(templates)):
                if np.max(np.abs(templates[i] - templates[j])) < r:
                    count += 1
        return count

    A = count_matches(m + 1)
    B = count_matches(m)

    if B == 0:
        return float('inf')
    return -np.log(A / B) if A > 0 else float('inf')

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])
    returns = np.diff(mids)

    # Discretize returns for entropy
    bins = [-np.inf, -2, -1, -0.5, 0, 0.5, 1, 2, np.inf]
    digitized = np.digitize(returns, bins)
    unique, counts = np.unique(digitized, return_counts=True)
    probs = counts / counts.sum()
    shannon_entropy = -np.sum(probs * np.log2(probs))
    max_entropy = np.log2(len(bins) - 1)

    print(f"\n{label}:")
    print(f"  Shannon entropy of returns: {shannon_entropy:.4f} / {max_entropy:.4f} max "
          f"({100*shannon_entropy/max_entropy:.1f}%)")
    print(f"  Return bin distribution:")
    for u, c, p in zip(unique, counts, probs):
        print(f"    bin {u}: {c:5d} ({100*p:.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# 18. PATTERN IN EXACT PRICE SEQUENCES
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("18. EXACT PRICE SEQUENCES & REPETITION")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = [r['mid'] for r in data if r['mid'] is not None]

    # Look for repeated sequences of mid prices
    print(f"\n{label}:")

    # N-gram analysis of discretized returns
    returns = np.diff(mids)
    # Discretize: -1 (down), 0 (flat), 1 (up)
    signs = np.sign(returns).astype(int)

    for n in [3, 4, 5]:
        ngrams = defaultdict(int)
        for i in range(len(signs) - n + 1):
            key = tuple(signs[i:i+n])
            ngrams[key] += 1

        top = sorted(ngrams.items(), key=lambda x: -x[1])[:5]
        print(f"  Top {n}-grams (sign of return):")
        for gram, count in top:
            print(f"    {gram}: {count} times")

# ══════════════════════════════════════════════════════════════════════════
# 19. CONDITIONAL PATTERNS (what predicts moves?)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("19. CONDITIONAL MOVE PATTERNS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1)]:
    print(f"\n{label}:")

    # Build feature vectors
    features = []
    targets = []

    for i in range(5, len(data) - 1):
        if data[i]['mid'] is None or data[i+1]['mid'] is None:
            continue

        r = data[i]
        target = data[i+1]['mid'] - data[i]['mid']

        feat = {}

        # Spread
        if r['bid1'] is not None and r['ask1'] is not None:
            feat['spread'] = r['ask1'] - r['bid1']
        else:
            feat['spread'] = None

        # OBI
        if r['bv1'] > 0 and r['av1'] > 0:
            feat['obi'] = (r['bv1'] - r['av1']) / (r['bv1'] + r['av1'])
        else:
            feat['obi'] = None

        # Recent return
        if data[i-1]['mid'] is not None:
            feat['ret1'] = data[i]['mid'] - data[i-1]['mid']
        else:
            feat['ret1'] = None

        # 5-step return
        if data[i-5]['mid'] is not None:
            feat['ret5'] = data[i]['mid'] - data[i-5]['mid']
        else:
            feat['ret5'] = None

        # Distance from 10000
        feat['dist_10k'] = data[i]['mid'] - 10000

        # Volume total
        feat['total_vol'] = r['bv1'] + r['bv2'] + r['bv3'] + r['av1'] + r['av2'] + r['av3']

        # One-sided
        feat['one_sided'] = 1 if (r['bid1'] is None or r['ask1'] is None) else 0

        features.append(feat)
        targets.append(target)

    targets = np.array(targets)

    # Analyze each feature
    for feat_name in ['spread', 'obi', 'ret1', 'ret5', 'dist_10k', 'total_vol', 'one_sided']:
        vals = np.array([f[feat_name] for f in features])
        valid = np.array([v is not None for v in vals])
        if np.sum(valid) < 50:
            continue

        v = vals[valid].astype(float)
        t = targets[valid]

        corr = np.corrcoef(v, t)[0, 1]
        print(f"  {feat_name:12s} → next_return: corr={corr:+.4f}", end="")
        if abs(corr) > 2/np.sqrt(np.sum(valid)):
            print(" ***", end="")
        print()

        # For dist_10k, do a more detailed analysis
        if feat_name == 'dist_10k':
            # Quintile analysis
            quantiles = np.percentile(v, [0, 20, 40, 60, 80, 100])
            for q in range(5):
                mask = (v >= quantiles[q]) & (v < quantiles[q+1])
                if np.sum(mask) > 5:
                    print(f"    Q{q+1} ({quantiles[q]:+.1f} to {quantiles[q+1]:+.1f}): "
                          f"avg_next_ret={np.mean(t[mask]):+.4f}, n={np.sum(mask)}")

# ══════════════════════════════════════════════════════════════════════════
# 20. TICK RULE & MOMENTUM SIGNATURES
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("20. MOMENTUM & REVERSAL SIGNATURES AT VARIOUS HORIZONS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])

    print(f"\n{label}:")
    # For various lookback and forward horizons
    for lb in [1, 2, 3, 5, 10, 20, 50, 100]:
        for fw in [1, 2, 5, 10, 20]:
            if lb + fw < len(mids):
                past = mids[lb:] - mids[:-lb]
                past = past[:len(mids)-lb-fw]
                future = mids[lb+fw:] - mids[lb:len(mids)-fw]
                future = future[:len(past)]

                if len(past) > 50 and np.std(past) > 0 and np.std(future) > 0:
                    corr = np.corrcoef(past, future)[0, 1]
                    if abs(corr) > 0.04:  # Only show notable ones
                        label_str = "MOM" if corr > 0 else "REV"
                        print(f"  past({lb:3d}) → future({fw:3d}): corr={corr:+.4f} {label_str}")

# ══════════════════════════════════════════════════════════════════════════
# 21. MARKET MAKING BOT FINGERPRINTING
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("21. BOT BEHAVIOR FINGERPRINTING")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    # Analyze how bids/asks change together
    transitions = defaultdict(int)
    for i in range(1, len(data)):
        prev = data[i-1]
        curr = data[i]

        # State: (has_bid, has_ask, n_bid_levels, n_ask_levels)
        prev_state = (
            prev['bid1'] is not None,
            prev['ask1'] is not None,
            sum(1 for k in ['bid1','bid2','bid3'] if prev[k] is not None),
            sum(1 for k in ['ask1','ask2','ask3'] if prev[k] is not None),
        )
        curr_state = (
            curr['bid1'] is not None,
            curr['ask1'] is not None,
            sum(1 for k in ['bid1','bid2','bid3'] if curr[k] is not None),
            sum(1 for k in ['ask1','ask2','ask3'] if curr[k] is not None),
        )

        transitions[(prev_state, curr_state)] += 1

    # Show top transitions
    top_trans = sorted(transitions.items(), key=lambda x: -x[1])[:15]
    print(f"  Top state transitions (has_bid, has_ask, n_bid_lvls, n_ask_lvls):")
    for (prev, curr), count in top_trans:
        print(f"    {prev} → {curr}: {count}")

# ══════════════════════════════════════════════════════════════════════════
# 22. HIDDEN PERIODICITY IN PRICE / BID-ASK
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("22. PERIODICITY IN BID/ASK PLACEMENT")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    # Track when bid appears/disappears
    bid_events = []  # (ts, 'appear'|'disappear')
    for i in range(1, len(data)):
        prev_bid = data[i-1]['bid1'] is not None
        curr_bid = data[i]['bid1'] is not None
        if not prev_bid and curr_bid:
            bid_events.append((data[i]['ts'], 'appear'))
        elif prev_bid and not curr_bid:
            bid_events.append((data[i]['ts'], 'disappear'))

    print(f"  Bid events: {len(bid_events)}")
    if bid_events:
        appear_ts = [t for t, e in bid_events if e == 'appear']
        disappear_ts = [t for t, e in bid_events if e == 'disappear']

        if len(appear_ts) > 1:
            inter_appear = np.diff(appear_ts)
            print(f"  Bid appear intervals: mean={np.mean(inter_appear):.1f}, "
                  f"median={np.median(inter_appear):.1f}, std={np.std(inter_appear):.1f}")
        if len(disappear_ts) > 1:
            inter_disappear = np.diff(disappear_ts)
            print(f"  Bid disappear intervals: mean={np.mean(inter_disappear):.1f}, "
                  f"median={np.median(inter_disappear):.1f}")

# ══════════════════════════════════════════════════════════════════════════
# 23. PRICE RELATIVE TO ROUND NUMBERS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("23. ROUND NUMBER EFFECTS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    mids = np.array([r['mid'] for r in data if r['mid'] is not None])

    # Distance from round numbers
    mod5 = mids % 5
    mod10 = mids % 10
    mod_round = mids - 10000  # distance from 10000

    print(f"\n{label}:")
    print(f"  Mid mod 5 distribution:")
    for val in sorted(np.unique(mod5)):
        count = np.sum(mod5 == val)
        print(f"    {val:.1f}: {count}")

    print(f"  Mid mod 10 distribution (top):")
    unique_m10, counts = np.unique(mod10, return_counts=True)
    for val, count in sorted(zip(unique_m10, counts), key=lambda x: -x[1])[:10]:
        print(f"    {val:.1f}: {count}")

# ══════════════════════════════════════════════════════════════════════════
# 24. VOLUME-PRICE CORRELATION
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("24. VOLUME-PRICE DYNAMICS")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1), ("Day 0", osm_d0)]:
    print(f"\n{label}:")

    # When volume is high vs low, what happens to price?
    vols = []
    next_rets = []
    for i in range(len(data) - 1):
        if data[i]['mid'] is not None and data[i+1]['mid'] is not None:
            total_vol = data[i]['bv1'] + data[i]['bv2'] + data[i]['av1'] + data[i]['av2']
            vols.append(total_vol)
            next_rets.append(data[i+1]['mid'] - data[i]['mid'])

    if vols:
        v = np.array(vols)
        r = np.array(next_rets)
        corr = np.corrcoef(v, np.abs(r))[0, 1]
        print(f"  Vol → |next_return|: corr={corr:.4f}")

        # High vol vs low vol
        med_vol = np.median(v)
        hi_mask = v > med_vol
        lo_mask = v <= med_vol
        print(f"  High vol: avg_|ret|={np.mean(np.abs(r[hi_mask])):.4f}, n={np.sum(hi_mask)}")
        print(f"  Low vol: avg_|ret|={np.mean(np.abs(r[lo_mask])):.4f}, n={np.sum(lo_mask)}")

# ══════════════════════════════════════════════════════════════════════════
# 25. PERSISTENCE OF BOOK STATE
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("25. BOOK STATE PERSISTENCE & TRANSITION MATRIX")
print("=" * 80)

for label, data in [("Day -2", osm_d2), ("Day -1", osm_d1)]:
    # Define states based on spread quantile and OBI sign
    states = []
    for r in data:
        if r['bid1'] is not None and r['ask1'] is not None:
            spread = r['ask1'] - r['bid1']
            obi = (r['bv1'] - r['av1']) / (r['bv1'] + r['av1']) if (r['bv1'] + r['av1']) > 0 else 0
            state = f"S{'W' if spread <= 16 else 'N'}|{'B' if obi > 0.1 else ('S' if obi < -0.1 else 'N')}"
        else:
            state = "ONE_SIDED"
        states.append(state)

    print(f"\n{label}:")
    # State frequencies
    from collections import Counter
    state_counts = Counter(states)
    total = len(states)
    for s, c in state_counts.most_common():
        print(f"  {s}: {c} ({100*c/total:.1f}%)")

    # Transition probabilities
    trans = defaultdict(lambda: defaultdict(int))
    for i in range(len(states)-1):
        trans[states[i]][states[i+1]] += 1

    print(f"  Transition probs:")
    for s1 in sorted(trans.keys()):
        total_from = sum(trans[s1].values())
        parts = []
        for s2 in sorted(trans[s1].keys()):
            prob = trans[s1][s2] / total_from
            if prob > 0.05:
                parts.append(f"{s2}:{prob:.2f}")
        print(f"    {s1} → {', '.join(parts)}")

# ══════════════════════════════════════════════════════════════════════════
# 26. DEEPER: BID/ASK EXACT VALUES PATTERN
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("26. EXACT BID/ASK VALUES OVER TIME (looking for deterministic patterns)")
print("=" * 80)

for label, data in [("Day -2", osm_d2)]:
    print(f"\n{label} - First 100 ticks bid1/ask1/bv1/av1:")
    for r in data[:100]:
        bid_str = f"{int(r['bid1']):5d}" if r['bid1'] is not None else "  ---"
        ask_str = f"{int(r['ask1']):5d}" if r['ask1'] is not None else "  ---"
        bv_str = f"{r['bv1']:2d}" if r['bv1'] > 0 else " -"
        av_str = f"{r['av1']:2d}" if r['av1'] > 0 else " -"
        print(f"  ts={r['ts']:6d}: bid={bid_str}x{bv_str} | ask={ask_str}x{av_str} | mid={r['mid']}")

print("\n\n")
print("=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
