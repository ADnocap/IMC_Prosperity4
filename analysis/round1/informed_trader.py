"""
Informed Trader Analysis for ASH_COATED_OSMIUM (Round 1)
========================================================
Since buyer/seller names are empty in CSV exports, we infer trade direction
from price relative to mid-price, and look for patterns that predict future
price movement. We also analyze trade sizes, timing, and clustering.

In live execution, market_trades DO have buyer/seller names -- this analysis
will help us know what patterns to look for when we see named traders.
"""

import csv
import os
from collections import defaultdict
import statistics

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prosperity4", "round1")
SYMBOL = "ASH_COATED_OSMIUM"

def load_prices(day_label):
    """Load mid-prices indexed by timestamp for a given day."""
    fname = os.path.join(DATA_DIR, f"prices_round_1_day_{day_label}.csv")
    prices = {}  # timestamp -> dict with mid, bid1, ask1, etc.
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != SYMBOL:
                continue
            ts = int(row["timestamp"])
            mid = float(row["mid_price"]) if row["mid_price"] else None
            bid1 = float(row["bid_price_1"]) if row.get("bid_price_1") and row["bid_price_1"] else None
            ask1 = float(row["ask_price_1"]) if row.get("ask_price_1") and row["ask_price_1"] else None
            bid_vol1 = int(row["bid_volume_1"]) if row.get("bid_volume_1") and row["bid_volume_1"] else None
            ask_vol1 = int(row["ask_volume_1"]) if row.get("ask_volume_1") and row["ask_volume_1"] else None
            prices[ts] = {
                "mid": mid, "bid1": bid1, "ask1": ask1,
                "bid_vol1": bid_vol1, "ask_vol1": ask_vol1,
            }
    return prices


def load_trades(day_label):
    """Load trades for the symbol."""
    fname = os.path.join(DATA_DIR, f"trades_round_1_day_{day_label}.csv")
    trades = []
    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["symbol"] != SYMBOL:
                continue
            trades.append({
                "timestamp": int(row["timestamp"]),
                "buyer": row.get("buyer", "").strip(),
                "seller": row.get("seller", "").strip(),
                "price": float(row["price"]),
                "quantity": int(row["quantity"]),
            })
    return trades


def infer_side(trade, prices):
    """Infer whether a trade is a buy or sell based on price vs mid/bid/ask."""
    ts = trade["timestamp"]
    p = prices.get(ts)
    if p is None:
        # Try previous timestamp
        prev_ts = ts - 100
        p = prices.get(prev_ts)
    if p is None:
        return "unknown"

    price = trade["price"]
    mid = p["mid"]
    bid1 = p["bid1"]
    ask1 = p["ask1"]

    if mid is None:
        return "unknown"

    # If trade is at/above ask -> aggressive buy (taker bought)
    # If trade is at/below bid -> aggressive sell (taker sold)
    # If between bid and ask but above mid -> lean buy
    # If between bid and ask but below mid -> lean sell
    if ask1 is not None and price >= ask1:
        return "buy"
    elif bid1 is not None and price <= bid1:
        return "sell"
    elif price > mid:
        return "buy"
    elif price < mid:
        return "sell"
    else:
        return "neutral"


def get_future_mid(prices, ts, ticks_ahead):
    """Get mid-price N ticks (x100) ahead."""
    future_ts = ts + ticks_ahead * 100
    p = prices.get(future_ts)
    if p and p["mid"] is not None:
        return p["mid"]
    return None


def analyze_day(day_label, verbose=True):
    """Full analysis for one day."""
    prices = load_prices(day_label)
    trades = load_trades(day_label)

    if verbose:
        print(f"\n{'='*80}")
        print(f"DAY {day_label}: {len(trades)} ACO trades, {len(prices)} price snapshots")
        print(f"{'='*80}")

    # Sort timestamps
    sorted_ts = sorted(prices.keys())
    ts_to_idx = {ts: i for i, ts in enumerate(sorted_ts)}

    # 1. Basic trade stats
    all_prices = [t["price"] for t in trades]
    all_quantities = [t["quantity"] for t in trades]

    if verbose:
        print(f"\n--- Basic Stats ---")
        print(f"Trade count: {len(trades)}")
        print(f"Price range: {min(all_prices):.0f} - {max(all_prices):.0f}")
        print(f"Quantity range: {min(all_quantities)} - {max(all_quantities)}")
        print(f"Avg quantity: {statistics.mean(all_quantities):.1f}")
        print(f"Quantity distribution: {sorted(set(all_quantities))}")

        # Quantity frequency
        qty_counts = defaultdict(int)
        for q in all_quantities:
            qty_counts[q] += 1
        print(f"Quantity frequencies: {dict(sorted(qty_counts.items()))}")

    # 2. Infer trade sides
    side_counts = defaultdict(int)
    trades_with_side = []
    for t in trades:
        side = infer_side(t, prices)
        side_counts[side] += 1
        t["side"] = side
        trades_with_side.append(t)

    if verbose:
        print(f"\n--- Trade Side Inference ---")
        for side, count in sorted(side_counts.items()):
            print(f"  {side}: {count}")

    # 3. Predictive power by trade characteristics
    horizons = [1, 3, 5, 10, 20, 50]

    # Group trades by side
    buy_trades = [t for t in trades_with_side if t["side"] == "buy"]
    sell_trades = [t for t in trades_with_side if t["side"] == "sell"]

    if verbose:
        print(f"\n--- Predictive Power: Future Returns After Trades ---")
        print(f"{'Horizon':>10} | {'Buy->Ret':>10} {'(n)':>5} {'Hit%':>6} | {'Sell->Ret':>10} {'(n)':>5} {'Hit%':>6} | {'Spread':>10}")

    results = {}
    for h in horizons:
        buy_returns = []
        sell_returns = []

        for t in buy_trades:
            current_mid = prices.get(t["timestamp"], {}).get("mid")
            future_mid = get_future_mid(prices, t["timestamp"], h)
            if current_mid and future_mid:
                buy_returns.append(future_mid - current_mid)

        for t in sell_trades:
            current_mid = prices.get(t["timestamp"], {}).get("mid")
            future_mid = get_future_mid(prices, t["timestamp"], h)
            if current_mid and future_mid:
                sell_returns.append(future_mid - current_mid)

        buy_avg = statistics.mean(buy_returns) if buy_returns else 0
        sell_avg = statistics.mean(sell_returns) if sell_returns else 0
        buy_hit = sum(1 for r in buy_returns if r > 0) / len(buy_returns) * 100 if buy_returns else 0
        sell_hit = sum(1 for r in sell_returns if r < 0) / len(sell_returns) * 100 if sell_returns else 0
        spread = buy_avg - sell_avg  # positive = trades predict direction

        results[h] = {
            "buy_avg": buy_avg, "sell_avg": sell_avg,
            "buy_n": len(buy_returns), "sell_n": len(sell_returns),
            "buy_hit": buy_hit, "sell_hit": sell_hit,
            "spread": spread,
        }

        if verbose:
            print(f"{h:>10} | {buy_avg:>+10.2f} {len(buy_returns):>5} {buy_hit:>5.1f}% | {sell_avg:>+10.2f} {len(sell_returns):>5} {sell_hit:>5.1f}% | {spread:>+10.2f}")

    # 4. Predictive power by QUANTITY (size-based analysis)
    if verbose:
        print(f"\n--- Predictive Power by Trade Size ---")
        # Split into small vs large trades
        median_qty = statistics.median(all_quantities)
        print(f"Median quantity: {median_qty}")

        for size_label, size_filter in [("small (<=5)", lambda q: q <= 5),
                                         ("medium (6-8)", lambda q: 6 <= q <= 8),
                                         ("large (>=9)", lambda q: q >= 9)]:
            size_trades = [t for t in trades_with_side if size_filter(t["quantity"]) and t["side"] in ("buy", "sell")]
            if not size_trades:
                continue

            print(f"\n  {size_label}: {len(size_trades)} trades")
            for h in [1, 5, 10, 20]:
                returns = []
                for t in size_trades:
                    current_mid = prices.get(t["timestamp"], {}).get("mid")
                    future_mid = get_future_mid(prices, t["timestamp"], h)
                    if current_mid and future_mid:
                        sign = 1 if t["side"] == "buy" else -1
                        returns.append(sign * (future_mid - current_mid))

                if returns:
                    avg_ret = statistics.mean(returns)
                    hit = sum(1 for r in returns if r > 0) / len(returns) * 100
                    print(f"    h={h:>2}: avg_signed_ret={avg_ret:>+7.2f}, hit={hit:>5.1f}%, n={len(returns)}")

    # 5. Analyze trade PRICE relative to mid -- how aggressive are trades?
    if verbose:
        print(f"\n--- Trade Aggressiveness (price distance from mid) ---")
        for side_label, side_trades in [("Buys", buy_trades), ("Sells", sell_trades)]:
            distances = []
            for t in side_trades:
                p = prices.get(t["timestamp"])
                if p and p["mid"]:
                    dist = t["price"] - p["mid"]
                    distances.append(dist)
            if distances:
                print(f"  {side_label}: avg_dist_from_mid={statistics.mean(distances):>+7.2f}, "
                      f"std={statistics.stdev(distances) if len(distances) > 1 else 0:.2f}")

    # 6. Timing analysis -- when do trades happen?
    if verbose:
        print(f"\n--- Trade Timing ---")
        # Inter-trade gaps
        trade_ts = [t["timestamp"] for t in trades]
        gaps = [trade_ts[i+1] - trade_ts[i] for i in range(len(trade_ts)-1)]
        if gaps:
            print(f"Inter-trade gap: min={min(gaps)}, median={statistics.median(gaps):.0f}, "
                  f"max={max(gaps)}, mean={statistics.mean(gaps):.0f}")

        # Cluster detection: trades within 500ms of each other
        clusters = []
        current_cluster = [trades[0]]
        for i in range(1, len(trades)):
            if trades[i]["timestamp"] - trades[i-1]["timestamp"] <= 300:
                current_cluster.append(trades[i])
            else:
                if len(current_cluster) >= 2:
                    clusters.append(current_cluster)
                current_cluster = [trades[i]]
        if len(current_cluster) >= 2:
            clusters.append(current_cluster)

        print(f"Trade clusters (gap<=300): {len(clusters)} clusters")
        for ci, cluster in enumerate(clusters[:10]):
            sides = [t["side"] for t in cluster]
            qtys = [t["quantity"] for t in cluster]
            prices_c = [t["price"] for t in cluster]
            ts_range = f"{cluster[0]['timestamp']}-{cluster[-1]['timestamp']}"
            print(f"  Cluster {ci}: ts={ts_range}, sides={sides}, qtys={qtys}, prices={prices_c}")

    # 7. Consecutive same-direction trades as signal
    if verbose:
        print(f"\n--- Consecutive Same-Direction Trades ---")
        for min_consecutive in [2, 3, 4]:
            sequences = []
            current_seq = [trades_with_side[0]]
            for i in range(1, len(trades_with_side)):
                if (trades_with_side[i]["side"] == trades_with_side[i-1]["side"] and
                    trades_with_side[i]["side"] in ("buy", "sell") and
                    trades_with_side[i]["timestamp"] - trades_with_side[i-1]["timestamp"] <= 500):
                    current_seq.append(trades_with_side[i])
                else:
                    if len(current_seq) >= min_consecutive:
                        sequences.append(current_seq)
                    current_seq = [trades_with_side[i]]
            if len(current_seq) >= min_consecutive:
                sequences.append(current_seq)

            if sequences:
                returns_after = []
                for seq in sequences:
                    last_ts = seq[-1]["timestamp"]
                    direction = 1 if seq[0]["side"] == "buy" else -1
                    current_mid = prices.get(last_ts, {}).get("mid")
                    future_mid = get_future_mid(prices, last_ts, 10)
                    if current_mid and future_mid:
                        returns_after.append(direction * (future_mid - current_mid))

                avg_ret = statistics.mean(returns_after) if returns_after else 0
                hit = sum(1 for r in returns_after if r > 0) / len(returns_after) * 100 if returns_after else 0
                print(f"  {min_consecutive}+ consecutive: {len(sequences)} sequences, "
                      f"avg_signed_ret_h10={avg_ret:>+7.2f}, hit={hit:.1f}%")

    # 8. Volume-weighted direction signal
    if verbose:
        print(f"\n--- Volume-Weighted Direction as Signal ---")
        # For each timestamp, compute net volume (buy vol - sell vol)
        ts_net_vol = defaultdict(float)
        for t in trades_with_side:
            if t["side"] == "buy":
                ts_net_vol[t["timestamp"]] += t["quantity"]
            elif t["side"] == "sell":
                ts_net_vol[t["timestamp"]] -= t["quantity"]

        # Predictiveness of net volume at a timestamp
        for h in [1, 5, 10, 20]:
            signed_returns = []
            for ts, net_vol in ts_net_vol.items():
                if net_vol == 0:
                    continue
                current_mid = prices.get(ts, {}).get("mid")
                future_mid = get_future_mid(prices, ts, h)
                if current_mid and future_mid:
                    sign = 1 if net_vol > 0 else -1
                    signed_returns.append(sign * (future_mid - current_mid))

            if signed_returns:
                avg = statistics.mean(signed_returns)
                hit = sum(1 for r in signed_returns if r > 0) / len(signed_returns) * 100
                print(f"  h={h:>2}: avg_signed_ret={avg:>+7.2f}, hit={hit:>5.1f}%, n={len(signed_returns)}")

    # 9. Price level analysis -- do trades at certain price levels predict better?
    if verbose:
        print(f"\n--- Trades at Extreme Prices ---")
        # Trades far from recent mid
        for t in trades_with_side:
            p = prices.get(t["timestamp"])
            if p and p["mid"]:
                t["dist_from_mid"] = abs(t["price"] - p["mid"])
            else:
                t["dist_from_mid"] = None

        valid_trades = [t for t in trades_with_side if t["dist_from_mid"] is not None and t["side"] in ("buy", "sell")]
        if valid_trades:
            median_dist = statistics.median([t["dist_from_mid"] for t in valid_trades])

            for label, filt in [("Close to mid (<=median)", lambda t: t["dist_from_mid"] <= median_dist),
                                 ("Far from mid (>median)", lambda t: t["dist_from_mid"] > median_dist)]:
                subset = [t for t in valid_trades if filt(t)]
                for h in [5, 10, 20]:
                    returns = []
                    for t in subset:
                        current_mid = prices.get(t["timestamp"], {}).get("mid")
                        future_mid = get_future_mid(prices, t["timestamp"], h)
                        if current_mid and future_mid:
                            sign = 1 if t["side"] == "buy" else -1
                            returns.append(sign * (future_mid - current_mid))
                    if returns:
                        avg = statistics.mean(returns)
                        hit = sum(1 for r in returns if r > 0) / len(returns) * 100
                        print(f"  {label}, h={h:>2}: avg={avg:>+7.2f}, hit={hit:>5.1f}%, n={len(returns)}")

    return trades_with_side, prices, results


def cross_day_analysis():
    """Aggregate analysis across all days."""
    print("\n" + "="*80)
    print("CROSS-DAY AGGREGATE ANALYSIS")
    print("="*80)

    all_trades = []
    all_prices = {}

    for day in ["-2", "-1", "0"]:
        trades, prices, _ = analyze_day(day, verbose=True)
        for t in trades:
            t["day"] = day
        all_trades.extend(trades)
        all_prices[day] = prices

    # Aggregate predictive power
    print(f"\n{'='*80}")
    print(f"AGGREGATE ACROSS ALL 3 DAYS")
    print(f"{'='*80}")

    buy_trades = [t for t in all_trades if t["side"] == "buy"]
    sell_trades = [t for t in all_trades if t["side"] == "sell"]
    print(f"Total trades: {len(all_trades)}, Buys: {len(buy_trades)}, Sells: {len(sell_trades)}")

    print(f"\n{'Horizon':>10} | {'Buy->Ret':>10} {'(n)':>5} {'Hit%':>6} | {'Sell->Ret':>10} {'(n)':>5} {'Hit%':>6} | {'Spread':>10}")

    for h in [1, 3, 5, 10, 20, 50]:
        buy_returns = []
        sell_returns = []

        for t in buy_trades:
            prices_day = all_prices[t["day"]]
            current_mid = prices_day.get(t["timestamp"], {}).get("mid")
            future_mid = get_future_mid(prices_day, t["timestamp"], h)
            if current_mid and future_mid:
                buy_returns.append(future_mid - current_mid)

        for t in sell_trades:
            prices_day = all_prices[t["day"]]
            current_mid = prices_day.get(t["timestamp"], {}).get("mid")
            future_mid = get_future_mid(prices_day, t["timestamp"], h)
            if current_mid and future_mid:
                sell_returns.append(future_mid - current_mid)

        buy_avg = statistics.mean(buy_returns) if buy_returns else 0
        sell_avg = statistics.mean(sell_returns) if sell_returns else 0
        buy_hit = sum(1 for r in buy_returns if r > 0) / len(buy_returns) * 100 if buy_returns else 0
        sell_hit = sum(1 for r in sell_returns if r < 0) / len(sell_returns) * 100 if sell_returns else 0
        spread = buy_avg - sell_avg

        print(f"{h:>10} | {buy_avg:>+10.2f} {len(buy_returns):>5} {buy_hit:>5.1f}% | {sell_avg:>+10.2f} {len(sell_returns):>5} {sell_hit:>5.1f}% | {spread:>+10.2f}")

    # Size-conditioned aggregate
    print(f"\n--- Aggregate: Size-Conditioned Predictive Power ---")
    for size_label, size_filter in [("small (<=5)", lambda q: q <= 5),
                                     ("medium (6-8)", lambda q: 6 <= q <= 8),
                                     ("large (>=9)", lambda q: q >= 9),
                                     ("qty==10", lambda q: q == 10)]:
        subset = [t for t in all_trades if size_filter(t["quantity"]) and t["side"] in ("buy", "sell")]
        if not subset:
            continue
        print(f"\n  {size_label}: {len(subset)} trades")
        for h in [1, 5, 10, 20, 50]:
            returns = []
            for t in subset:
                prices_day = all_prices[t["day"]]
                current_mid = prices_day.get(t["timestamp"], {}).get("mid")
                future_mid = get_future_mid(prices_day, t["timestamp"], h)
                if current_mid and future_mid:
                    sign = 1 if t["side"] == "buy" else -1
                    returns.append(sign * (future_mid - current_mid))
            if returns:
                avg = statistics.mean(returns)
                hit = sum(1 for r in returns if r > 0) / len(returns) * 100
                print(f"    h={h:>2}: avg_signed_ret={avg:>+7.2f}, hit={hit:>5.1f}%, n={len(returns)}")

    # Time-of-day pattern
    print(f"\n--- Trade Frequency by Time Period ---")
    for day in ["-2", "-1", "0"]:
        day_trades = [t for t in all_trades if t["day"] == day]
        early = [t for t in day_trades if t["timestamp"] < 300000]
        mid_period = [t for t in day_trades if 300000 <= t["timestamp"] < 700000]
        late = [t for t in day_trades if t["timestamp"] >= 700000]
        print(f"  Day {day}: early(<300k)={len(early)}, mid(300-700k)={len(mid_period)}, late(>700k)={len(late)}")

    # Check for specific quantity patterns that might identify bot types
    print(f"\n--- Quantity-Side Cross-tabulation ---")
    qty_side = defaultdict(lambda: defaultdict(int))
    for t in all_trades:
        qty_side[t["quantity"]][t["side"]] += 1

    print(f"  {'Qty':>4} | {'buy':>5} {'sell':>5} {'neutral':>7} {'unknown':>7} | {'buy%':>5}")
    for qty in sorted(qty_side.keys()):
        sides = qty_side[qty]
        total = sum(sides.values())
        buy_pct = sides.get("buy", 0) / total * 100 if total else 0
        print(f"  {qty:>4} | {sides.get('buy',0):>5} {sides.get('sell',0):>5} "
              f"{sides.get('neutral',0):>7} {sides.get('unknown',0):>7} | {buy_pct:>5.1f}%")

    # KEY ANALYSIS: Do trades at ask vs bid have different predictive power?
    # This helps identify if there's an informed TAKER
    print(f"\n--- At-Ask (aggressive buy) vs At-Bid (aggressive sell) Predictive Power ---")
    for day in ["-2", "-1", "0"]:
        day_trades = [t for t in all_trades if t["day"] == day]
        prices_day = all_prices[day]

        at_ask = []
        at_bid = []
        for t in day_trades:
            p = prices_day.get(t["timestamp"])
            if p and p["ask1"] and p["bid1"]:
                if t["price"] >= p["ask1"]:
                    at_ask.append(t)
                elif t["price"] <= p["bid1"]:
                    at_bid.append(t)

        print(f"\n  Day {day}: {len(at_ask)} at-ask trades, {len(at_bid)} at-bid trades")
        for label, subset in [("At-Ask (agg buy)", at_ask), ("At-Bid (agg sell)", at_bid)]:
            for h in [5, 10, 20]:
                returns = []
                for t in subset:
                    current_mid = prices_day.get(t["timestamp"], {}).get("mid")
                    future_mid = get_future_mid(prices_day, t["timestamp"], h)
                    if current_mid and future_mid:
                        returns.append(future_mid - current_mid)
                if returns:
                    avg = statistics.mean(returns)
                    hit_up = sum(1 for r in returns if r > 0) / len(returns) * 100
                    print(f"    {label}, h={h:>2}: avg_ret={avg:>+7.2f}, "
                          f"{'up' if 'Ask' in label else 'down'}_hit={hit_up if 'Ask' in label else 100-hit_up:.1f}%, n={len(returns)}")


    # CRITICAL: Look at mid-price CHANGE patterns
    print(f"\n--- Mid-Price Dynamics Around Trades ---")
    for day in ["-2", "-1", "0"]:
        day_trades = [t for t in all_trades if t["day"] == day and t["side"] in ("buy", "sell")]
        prices_day = all_prices[day]

        # For each trade, look at mid-price change BEFORE the trade
        # (did mid already move before the trade? momentum or mean-reversion?)
        before_rets = {"buy": [], "sell": []}
        for t in day_trades:
            ts = t["timestamp"]
            mid_now = prices_day.get(ts, {}).get("mid")
            mid_before = prices_day.get(ts - 500, {}).get("mid")  # 5 ticks before
            if mid_now and mid_before:
                before_rets[t["side"]].append(mid_now - mid_before)

        print(f"\n  Day {day}: Mid change 5-ticks BEFORE trade")
        for side in ["buy", "sell"]:
            if before_rets[side]:
                avg = statistics.mean(before_rets[side])
                print(f"    Before {side}: avg_mid_change={avg:>+7.2f} (n={len(before_rets[side])})")

    # Look for large trades specifically -- potential informed trader
    print(f"\n{'='*80}")
    print(f"DETAILED LARGE TRADE ANALYSIS (qty >= 9)")
    print(f"{'='*80}")

    large_trades = [t for t in all_trades if t["quantity"] >= 9 and t["side"] in ("buy", "sell")]
    print(f"Total large trades: {len(large_trades)}")

    for t in large_trades[:50]:
        prices_day = all_prices[t["day"]]
        ts = t["timestamp"]
        mid_now = prices_day.get(ts, {}).get("mid")
        mid_5 = get_future_mid(prices_day, ts, 5)
        mid_10 = get_future_mid(prices_day, ts, 10)
        mid_20 = get_future_mid(prices_day, ts, 20)

        sign = 1 if t["side"] == "buy" else -1
        ret5 = sign * (mid_5 - mid_now) if mid_5 and mid_now else None
        ret10 = sign * (mid_10 - mid_now) if mid_10 and mid_now else None
        ret20 = sign * (mid_20 - mid_now) if mid_20 and mid_now else None

        print(f"  Day {t['day']} ts={ts:>7} {t['side']:>4} qty={t['quantity']:>2} "
              f"px={t['price']:>8.0f} mid={mid_now if mid_now else 'N/A':>8} "
              f"ret5={ret5:>+7.1f} ret10={ret10:>+7.1f} ret20={ret20:>+7.1f}"
              if ret5 is not None and ret10 is not None and ret20 is not None
              else f"  Day {t['day']} ts={ts:>7} {t['side']:>4} qty={t['quantity']:>2} px={t['price']:>8.0f}")


def mean_reversion_analysis():
    """Check if ACO trades cause temporary impact that reverts -- key for strategy."""
    print(f"\n{'='*80}")
    print(f"MEAN REVERSION / TEMPORARY IMPACT ANALYSIS")
    print(f"{'='*80}")

    all_prices = {}
    all_trades = []
    for day in ["-2", "-1", "0"]:
        prices = load_prices(day)
        trades = load_trades(day)
        for t in trades:
            t["side"] = infer_side(t, prices)
            t["day"] = day
        all_prices[day] = prices
        all_trades.extend(trades)

    # For each trade, compute the return profile over time
    # If trades cause temporary impact that reverts, we see:
    #   - immediate return in trade direction (impact)
    #   - later return reverses (reversion)
    horizons = list(range(1, 51))
    buy_profile = {h: [] for h in horizons}
    sell_profile = {h: [] for h in horizons}

    for t in all_trades:
        if t["side"] not in ("buy", "sell"):
            continue
        prices_day = all_prices[t["day"]]
        current_mid = prices_day.get(t["timestamp"], {}).get("mid")
        if not current_mid:
            continue

        for h in horizons:
            future_mid = get_future_mid(prices_day, t["timestamp"], h)
            if future_mid:
                ret = future_mid - current_mid
                if t["side"] == "buy":
                    buy_profile[h].append(ret)
                else:
                    sell_profile[h].append(ret)

    print(f"\nReturn profile after BUY trades (should be positive if informed):")
    print(f"{'Horizon':>8} {'Avg Ret':>10} {'Hit Up%':>8} {'N':>5}")
    for h in [1, 2, 3, 5, 10, 15, 20, 30, 40, 50]:
        if buy_profile[h]:
            avg = statistics.mean(buy_profile[h])
            hit = sum(1 for r in buy_profile[h] if r > 0) / len(buy_profile[h]) * 100
            print(f"{h:>8} {avg:>+10.3f} {hit:>7.1f}% {len(buy_profile[h]):>5}")

    print(f"\nReturn profile after SELL trades (should be negative if informed):")
    print(f"{'Horizon':>8} {'Avg Ret':>10} {'Hit Dn%':>8} {'N':>5}")
    for h in [1, 2, 3, 5, 10, 15, 20, 30, 40, 50]:
        if sell_profile[h]:
            avg = statistics.mean(sell_profile[h])
            hit = sum(1 for r in sell_profile[h] if r < 0) / len(sell_profile[h]) * 100
            print(f"{h:>8} {avg:>+10.3f} {hit:>7.1f}% {len(sell_profile[h]):>5}")

    # SIGNED return profile (buy=+1, sell=-1) to see if trades predict direction
    print(f"\nSIGNED return profile (positive = trade predicted correctly):")
    print(f"{'Horizon':>8} {'Avg Signed':>10} {'Hit%':>8} {'N':>5}")
    for h in [1, 2, 3, 5, 10, 15, 20, 30, 40, 50]:
        signed = []
        for t in all_trades:
            if t["side"] not in ("buy", "sell"):
                continue
            prices_day = all_prices[t["day"]]
            current_mid = prices_day.get(t["timestamp"], {}).get("mid")
            future_mid = get_future_mid(prices_day, t["timestamp"], h)
            if current_mid and future_mid:
                sign = 1 if t["side"] == "buy" else -1
                signed.append(sign * (future_mid - current_mid))
        if signed:
            avg = statistics.mean(signed)
            hit = sum(1 for r in signed if r > 0) / len(signed) * 100
            print(f"{h:>8} {avg:>+10.3f} {hit:>7.1f}% {len(signed):>5}")

    # KEY: Now split by quantity and check the signed return
    print(f"\n--- Signed Return Profile by Quantity ---")
    for qty_range, qty_filter in [
        ("qty 2-3 (noise?)", lambda q: 2 <= q <= 3),
        ("qty 4-5", lambda q: 4 <= q <= 5),
        ("qty 6", lambda q: q == 6),
        ("qty 7-8", lambda q: 7 <= q <= 8),
        ("qty 9-10 (informed?)", lambda q: 9 <= q <= 10),
    ]:
        subset = [t for t in all_trades if qty_filter(t["quantity"]) and t["side"] in ("buy", "sell")]
        if not subset:
            continue
        print(f"\n  {qty_range}: {len(subset)} trades")
        for h in [1, 3, 5, 10, 20, 50]:
            signed = []
            for t in subset:
                prices_day = all_prices[t["day"]]
                current_mid = prices_day.get(t["timestamp"], {}).get("mid")
                future_mid = get_future_mid(prices_day, t["timestamp"], h)
                if current_mid and future_mid:
                    sign = 1 if t["side"] == "buy" else -1
                    signed.append(sign * (future_mid - current_mid))
            if signed:
                avg = statistics.mean(signed)
                hit = sum(1 for r in signed if r > 0) / len(signed) * 100
                print(f"    h={h:>2}: avg={avg:>+7.3f}, hit={hit:>5.1f}%")

    # Autocorrelation of mid-price changes
    print(f"\n--- Mid-Price Autocorrelation (mean-reversion check) ---")
    for day in ["-2", "-1", "0"]:
        prices_day = all_prices[day]
        sorted_ts = sorted(prices_day.keys())
        mids = [prices_day[ts]["mid"] for ts in sorted_ts if prices_day[ts]["mid"] is not None]
        changes = [mids[i+1] - mids[i] for i in range(len(mids)-1)]

        for lag in [1, 2, 5, 10]:
            if len(changes) > lag:
                pairs = [(changes[i], changes[i+lag]) for i in range(len(changes)-lag)]
                n = len(pairs)
                mean_x = sum(p[0] for p in pairs) / n
                mean_y = sum(p[1] for p in pairs) / n
                cov = sum((p[0]-mean_x)*(p[1]-mean_y) for p in pairs) / n
                var_x = sum((p[0]-mean_x)**2 for p in pairs) / n
                var_y = sum((p[1]-mean_y)**2 for p in pairs) / n
                if var_x > 0 and var_y > 0:
                    corr = cov / (var_x**0.5 * var_y**0.5)
                    print(f"  Day {day}, lag {lag}: autocorr = {corr:+.4f}")


def data_gathering_recommendation():
    """Print recommendation for data gathering submission."""
    print(f"\n{'='*80}")
    print(f"RECOMMENDED: DATA-GATHERING TRADER SUBMISSION")
    print(f"{'='*80}")
    print("""
To identify informed traders by NAME, we need to submit a trader that logs
state.market_trades. The CSV exports do NOT contain trader names.

Add this to traders/a.py run() method to log market trades:

    if "ASH_COATED_OSMIUM" in state.market_trades:
        for trade in state.market_trades["ASH_COATED_OSMIUM"]:
            print(f"MT|{state.timestamp}|{trade.symbol}|{trade.buyer}|{trade.seller}|{trade.price}|{trade.quantity}")

Then download the submission log and parse the sandboxLog/lambdaLog fields.
The buyer/seller fields will show bot names like in P3 (where "Olivia" was found).

IMPORTANT: In P4 Round 1, the bot names will likely be different from P3.
Look for a trader whose trades consistently predict future price direction.
""")


if __name__ == "__main__":
    cross_day_analysis()
    mean_reversion_analysis()
    data_gathering_recommendation()
