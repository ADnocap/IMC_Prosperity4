"""
Strategy simulator: replay historical data with different strategies.
Measures per-product PnL, fill rates, position curves, etc.

Key findings from analysis:
- OSMIUM: autocorrelation lag-1 = -0.5 (bid-ask bounce), random walk σ≈4.4
- PEPPER: drift = 0.1/tick, total over session = 400 (2 days × 2000 ticks)
- Bot 2 inner: OSMIUM dist=8, vol=10-15; PEPPER dist≈5.5-7, vol=8-12
- Bot 1 outer: OSMIUM dist=10.5, vol=20-30; PEPPER dist≈8.5-10, vol=15-25
- One-sided book = strong signal for FV movement direction

Competition session: 2 days × 2000 ticks = 4000 ticks
Position limit: 80 per product
"""
import csv
from collections import defaultdict
import statistics

DATA_DIR = "data/prosperity4/round1"

def load_prices(day):
    rows = []
    with open(f"{DATA_DIR}/prices_round_1_day_{day}.csv") as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows

def parse_book(row):
    bids = {}
    asks = {}
    for i in range(1, 4):
        bp = row.get(f'bid_price_{i}', '')
        bv = row.get(f'bid_volume_{i}', '')
        if bp and bv:
            bids[int(float(bp))] = int(bv)
        ap = row.get(f'ask_price_{i}', '')
        av = row.get(f'ask_volume_{i}', '')
        if ap and av:
            asks[int(float(ap))] = -int(av)  # negative like the game
    return bids, asks

def compute_ipr_fair(day_index, tick, ticks_per_day=2000):
    total_tick = day_index * ticks_per_day + tick
    return 10000.0 + total_tick * 0.1

def simulate_strategy(strategy_fn, days=[-2, -1], ticks_per_day=2000):
    """Simulate a strategy against historical data (first ticks_per_day ticks per day)."""

    # State
    osmium_pos = 0
    pepper_pos = 0
    osmium_cash = 0.0
    pepper_cash = 0.0
    trader_data = {}

    osmium_fills = 0
    pepper_fills = 0

    position_history = {"osmium": [], "pepper": []}

    for day_idx, day in enumerate(days):
        prices = load_prices(day)
        osmium_rows = [r for r in prices if 'OSMIUM' in r['product']]
        pepper_rows = [r for r in prices if 'PEPPER' in r['product']]

        for tick in range(min(ticks_per_day, len(osmium_rows))):
            osm_row = osmium_rows[tick]
            pep_row = pepper_rows[tick] if tick < len(pepper_rows) else None

            osm_bids, osm_asks = parse_book(osm_row)
            pep_bids, pep_asks = parse_book(pep_row) if pep_row else ({}, {})

            # Call strategy
            osm_orders, pep_orders, trader_data = strategy_fn(
                osm_bids, osm_asks, pep_bids, pep_asks,
                osmium_pos, pepper_pos, trader_data, day_idx, tick
            )

            # Execute OSMIUM orders (simple: aggressive orders fill immediately, passive orders don't)
            for price, qty in osm_orders:
                if qty > 0:  # buy
                    # Check if any ask <= price
                    for ask_p in sorted(osm_asks.keys()):
                        if ask_p <= price:
                            available = -osm_asks[ask_p]
                            fill = min(available, qty, 80 - osmium_pos)
                            if fill > 0:
                                osmium_cash -= ask_p * fill
                                osmium_pos += fill
                                qty -= fill
                                osmium_fills += 1
                elif qty < 0:  # sell
                    for bid_p in sorted(osm_bids.keys(), reverse=True):
                        if bid_p >= price:
                            available = osm_bids[bid_p]
                            fill = min(available, -qty, 80 + osmium_pos)
                            if fill > 0:
                                osmium_cash += bid_p * fill
                                osmium_pos -= fill
                                qty += fill
                                osmium_fills += 1

            # Execute PEPPER orders
            for price, qty in pep_orders:
                if qty > 0:  # buy
                    for ask_p in sorted(pep_asks.keys()):
                        if ask_p <= price:
                            available = -pep_asks[ask_p]
                            fill = min(available, qty, 80 - pepper_pos)
                            if fill > 0:
                                pepper_cash -= ask_p * fill
                                pepper_pos += fill
                                qty -= fill
                                pepper_fills += 1
                elif qty < 0:  # sell
                    for bid_p in sorted(pep_bids.keys(), reverse=True):
                        if bid_p >= price:
                            available = pep_bids[bid_p]
                            fill = min(available, -qty, 80 + pepper_pos)
                            if fill > 0:
                                pepper_cash += bid_p * fill
                                pepper_pos -= fill
                                qty += fill
                                pepper_fills += 1

            position_history["osmium"].append(osmium_pos)
            position_history["pepper"].append(pepper_pos)

    # Mark to market at final FV
    # OSMIUM: use last mid as FV proxy
    last_osm_row = [r for r in load_prices(days[-1]) if 'OSMIUM' in r['product']][min(ticks_per_day-1, 1999)]
    osm_mid = float(last_osm_row['mid_price']) if last_osm_row['mid_price'] else 10000

    # PEPPER: use computed fair value
    ipr_final_fv = compute_ipr_fair(len(days)-1, ticks_per_day-1, ticks_per_day)

    osmium_pnl = osmium_cash + osmium_pos * osm_mid
    pepper_pnl = pepper_cash + pepper_pos * ipr_final_fv
    total_pnl = osmium_pnl + pepper_pnl

    return {
        "osmium_pnl": osmium_pnl,
        "pepper_pnl": pepper_pnl,
        "total_pnl": total_pnl,
        "osmium_pos": osmium_pos,
        "pepper_pos": pepper_pos,
        "osmium_fills": osmium_fills,
        "pepper_fills": pepper_fills,
        "osmium_cash": osmium_cash,
        "pepper_cash": pepper_cash,
        "position_history": position_history,
    }


# ============================================================
# Strategy 1: Current approach (baseline) - buy-and-hold PEPPER, MM OSMIUM
# ============================================================
def strategy_current(osm_bids, osm_asks, pep_bids, pep_asks, osm_pos, pep_pos, td, day_idx, tick):
    osm_orders = []
    pep_orders = []

    # OSMIUM: simple FV estimation + penny jump
    bids_sorted = sorted(osm_bids.keys(), reverse=True)
    asks_sorted = sorted(osm_asks.keys())

    # FV estimation (simplified version of current code)
    fv = None
    estimates = []
    if bids_sorted and asks_sorted:
        raw_mid = (bids_sorted[0] + asks_sorted[0]) / 2
    elif bids_sorted:
        raw_mid = td.get("fv", bids_sorted[0] + 8)
    elif asks_sorted:
        raw_mid = td.get("fv", asks_sorted[0] - 8)
    else:
        fv = td.get("fv")

    if fv is None:
        for p in bids_sorted:
            v = osm_bids[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks_sorted:
            v = -osm_asks[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids_sorted and asks_sorted:
            fv = (bids_sorted[0] + asks_sorted[0]) / 2
        elif bids_sorted:
            fv = bids_sorted[0] + 10.5
        elif asks_sorted:
            fv = asks_sorted[0] - 10.5

    if fv is None:
        return osm_orders, pep_orders, td

    td["fv"] = fv
    fv_r = int(round(fv))
    buy_ordered = 0
    sell_ordered = 0

    # Take mispriced
    for p in asks_sorted:
        if p > fv_r:
            break
        vol = -osm_asks[p]
        can = 80 - osm_pos - buy_ordered
        if can <= 0:
            break
        q = min(vol, can)
        osm_orders.append((p, q))
        buy_ordered += q

    for p in bids_sorted:
        if p < fv_r:
            break
        vol = osm_bids[p]
        can = 80 + osm_pos - sell_ordered
        if can <= 0:
            break
        q = min(vol, can)
        osm_orders.append((p, -q))
        sell_ordered += q

    # Passive penny-jump
    ref_bid = bids_sorted[1] if len(bids_sorted) >= 2 else (bids_sorted[0] if bids_sorted else fv_r - 8)
    ref_ask = asks_sorted[1] if len(asks_sorted) >= 2 else (asks_sorted[0] if asks_sorted else fv_r + 8)

    our_bid = min(ref_bid + 1, fv_r - 1)
    our_ask = max(ref_ask - 1, fv_r + 1)
    if our_bid >= our_ask:
        our_bid = fv_r - 1
        our_ask = fv_r + 1

    pb = 80 - osm_pos - buy_ordered
    ps = 80 + osm_pos - sell_ordered
    if pb > 0:
        osm_orders.append((our_bid, pb))
    if ps > 0:
        osm_orders.append((our_ask, -ps))

    # PEPPER: buy-and-hold, skip Bot 1
    remaining = 80 - pep_pos
    if remaining > 0:
        for p in sorted(pep_asks.keys()):
            v = -pep_asks[p]
            if remaining > 20 and v > 15:
                continue
            q = min(v, remaining)
            pep_orders.append((p, q))
            remaining -= q
            if remaining <= 0:
                break

    return osm_orders, pep_orders, td


# ============================================================
# Strategy 2: PEPPER aggressive buy + MM cycling at max
# ============================================================
def strategy_pepper_cycle(osm_bids, osm_asks, pep_bids, pep_asks, osm_pos, pep_pos, td, day_idx, tick):
    osm_orders = []
    pep_orders = []

    # OSMIUM: same as current
    bids_sorted = sorted(osm_bids.keys(), reverse=True)
    asks_sorted = sorted(osm_asks.keys())

    fv = None
    estimates = []
    if bids_sorted and asks_sorted:
        raw_mid = (bids_sorted[0] + asks_sorted[0]) / 2
    elif bids_sorted:
        raw_mid = td.get("fv", bids_sorted[0] + 8)
    elif asks_sorted:
        raw_mid = td.get("fv", asks_sorted[0] - 8)
    else:
        fv = td.get("fv")

    if fv is None:
        for p in bids_sorted:
            v = osm_bids[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks_sorted:
            v = -osm_asks[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))
        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids_sorted and asks_sorted:
            fv = (bids_sorted[0] + asks_sorted[0]) / 2
        elif bids_sorted:
            fv = bids_sorted[0] + 10.5
        elif asks_sorted:
            fv = asks_sorted[0] - 10.5

    if fv is not None:
        td["fv"] = fv
        fv_r = int(round(fv))
        buy_ordered = 0
        sell_ordered = 0

        for p in asks_sorted:
            if p > fv_r:
                break
            vol = -osm_asks[p]
            can = 80 - osm_pos - buy_ordered
            if can <= 0:
                break
            q = min(vol, can)
            osm_orders.append((p, q))
            buy_ordered += q

        for p in bids_sorted:
            if p < fv_r:
                break
            vol = osm_bids[p]
            can = 80 + osm_pos - sell_ordered
            if can <= 0:
                break
            q = min(vol, can)
            osm_orders.append((p, -q))
            sell_ordered += q

        ref_bid = bids_sorted[1] if len(bids_sorted) >= 2 else (bids_sorted[0] if bids_sorted else fv_r - 8)
        ref_ask = asks_sorted[1] if len(asks_sorted) >= 2 else (asks_sorted[0] if asks_sorted else fv_r + 8)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1
        pb = 80 - osm_pos - buy_ordered
        ps = 80 + osm_pos - sell_ordered
        if pb > 0:
            osm_orders.append((our_bid, pb))
        if ps > 0:
            osm_orders.append((our_ask, -ps))

    # PEPPER: Aggressive buy (take ALL asks including Bot 1), then MM cycle
    remaining = 80 - pep_pos

    if remaining > 0:
        # Take ALL available asks aggressively (don't skip Bot 1)
        for p in sorted(pep_asks.keys()):
            v = -pep_asks[p]
            q = min(v, remaining)
            pep_orders.append((p, q))
            remaining -= q
            if remaining <= 0:
                break

        # Also place aggressive passive bid to fill remaining
        if remaining > 0 and pep_bids:
            best_bid = max(pep_bids.keys())
            pep_orders.append((best_bid + 1, remaining))

    elif pep_pos >= 80:
        # At max position: sell a chunk to capture spread, will rebuy next tick
        # Sell 10 units at best bid (aggressive sell) and place buy order
        cycle_size = td.get("pepper_cycle_size", 0)

        if cycle_size == 0:
            # Sell phase: place aggressive sell at best bid
            if pep_bids:
                best_bid = max(pep_bids.keys())
                sell_qty = min(10, pep_pos + 80)  # don't exceed limit
                pep_orders.append((best_bid, -sell_qty))
                td["pepper_cycle_size"] = sell_qty
        else:
            # Rebuy phase: buy back what we sold
            for p in sorted(pep_asks.keys()):
                v = -pep_asks[p]
                q = min(v, cycle_size)
                pep_orders.append((p, q))
                cycle_size -= q
                if cycle_size <= 0:
                    break
            td["pepper_cycle_size"] = 0

    return osm_orders, pep_orders, td


# ============================================================
# Strategy 3: PEPPER aggressive + no OSMIUM (baseline test)
# ============================================================
def strategy_pepper_only(osm_bids, osm_asks, pep_bids, pep_asks, osm_pos, pep_pos, td, day_idx, tick):
    osm_orders = []
    pep_orders = []

    # No OSMIUM trading

    # PEPPER: aggressive buy ALL asks
    remaining = 80 - pep_pos
    if remaining > 0:
        for p in sorted(pep_asks.keys()):
            v = -pep_asks[p]
            q = min(v, remaining)
            pep_orders.append((p, q))
            remaining -= q
            if remaining <= 0:
                break
        if remaining > 0 and pep_bids:
            best_bid = max(pep_bids.keys())
            pep_orders.append((best_bid + 1, remaining))

    return osm_orders, pep_orders, td


# ============================================================
# Strategy 4: OSMIUM only - pure MM (test OSMIUM edge)
# ============================================================
def strategy_osmium_only(osm_bids, osm_asks, pep_bids, pep_asks, osm_pos, pep_pos, td, day_idx, tick):
    osm_orders = []
    pep_orders = []

    bids_sorted = sorted(osm_bids.keys(), reverse=True)
    asks_sorted = sorted(osm_asks.keys())

    fv = None
    estimates = []
    if bids_sorted and asks_sorted:
        raw_mid = (bids_sorted[0] + asks_sorted[0]) / 2
    elif bids_sorted:
        raw_mid = td.get("fv", bids_sorted[0] + 8)
    elif asks_sorted:
        raw_mid = td.get("fv", asks_sorted[0] - 8)
    else:
        fv = td.get("fv")

    if fv is None:
        for p in bids_sorted:
            v = osm_bids[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks_sorted:
            v = -osm_asks[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))
        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids_sorted and asks_sorted:
            fv = (bids_sorted[0] + asks_sorted[0]) / 2
        elif bids_sorted:
            fv = bids_sorted[0] + 10.5
        elif asks_sorted:
            fv = asks_sorted[0] - 10.5

    if fv is not None:
        td["fv"] = fv
        fv_r = int(round(fv))
        buy_ordered = 0
        sell_ordered = 0

        # NO TAKING - pure passive

        ref_bid = bids_sorted[1] if len(bids_sorted) >= 2 else (bids_sorted[0] if bids_sorted else fv_r - 8)
        ref_ask = asks_sorted[1] if len(asks_sorted) >= 2 else (asks_sorted[0] if asks_sorted else fv_r + 8)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1
        pb = 80 - osm_pos
        ps = 80 + osm_pos
        if pb > 0:
            osm_orders.append((our_bid, pb))
        if ps > 0:
            osm_orders.append((our_ask, -ps))

    return osm_orders, pep_orders, td


# ============================================================
# Strategy 5: PEPPER aggressive + sell-side MM at max position
# ============================================================
def strategy_pepper_sell_mm(osm_bids, osm_asks, pep_bids, pep_asks, osm_pos, pep_pos, td, day_idx, tick):
    """When at max PEPPER, also place asks above FV to earn spread."""
    osm_orders = []
    pep_orders = []

    # Same OSMIUM as current
    bids_sorted = sorted(osm_bids.keys(), reverse=True)
    asks_sorted = sorted(osm_asks.keys())

    fv = None
    estimates = []
    if bids_sorted and asks_sorted:
        raw_mid = (bids_sorted[0] + asks_sorted[0]) / 2
    elif bids_sorted:
        raw_mid = td.get("fv", bids_sorted[0] + 8)
    elif asks_sorted:
        raw_mid = td.get("fv", asks_sorted[0] - 8)
    else:
        fv = td.get("fv")

    if fv is None:
        for p in bids_sorted:
            v = osm_bids[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks_sorted:
            v = -osm_asks[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))
        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids_sorted and asks_sorted:
            fv = (bids_sorted[0] + asks_sorted[0]) / 2
        elif bids_sorted:
            fv = bids_sorted[0] + 10.5
        elif asks_sorted:
            fv = asks_sorted[0] - 10.5

    if fv is not None:
        td["fv"] = fv
        fv_r = int(round(fv))
        buy_ordered = 0
        sell_ordered = 0

        for p in asks_sorted:
            if p > fv_r:
                break
            vol = -osm_asks[p]
            can = 80 - osm_pos - buy_ordered
            if can <= 0:
                break
            q = min(vol, can)
            osm_orders.append((p, q))
            buy_ordered += q

        for p in bids_sorted:
            if p < fv_r:
                break
            vol = osm_bids[p]
            can = 80 + osm_pos - sell_ordered
            if can <= 0:
                break
            q = min(vol, can)
            osm_orders.append((p, -q))
            sell_ordered += q

        ref_bid = bids_sorted[1] if len(bids_sorted) >= 2 else (bids_sorted[0] if bids_sorted else fv_r - 8)
        ref_ask = asks_sorted[1] if len(asks_sorted) >= 2 else (asks_sorted[0] if asks_sorted else fv_r + 8)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1
        pb = 80 - osm_pos - buy_ordered
        ps = 80 + osm_pos - sell_ordered
        if pb > 0:
            osm_orders.append((our_bid, pb))
        if ps > 0:
            osm_orders.append((our_ask, -ps))

    # PEPPER: aggressive buy, then sell-side MM when at max
    remaining = 80 - pep_pos
    if remaining > 0:
        # Take ALL asks
        for p in sorted(pep_asks.keys()):
            v = -pep_asks[p]
            q = min(v, remaining)
            pep_orders.append((p, q))
            remaining -= q
            if remaining <= 0:
                break
        if remaining > 0 and pep_bids:
            best_bid = max(pep_bids.keys())
            pep_orders.append((best_bid + 1, remaining))
    else:
        # At max position: sell small amount at premium, rebuy later
        # Don't sell: just hold. The drift is the main edge.
        pass

    return osm_orders, pep_orders, td


# ============================================================
# Run all strategies
# ============================================================
print("=" * 80)
print("STRATEGY COMPARISON (historical replay, 2000 ticks/day, 2 days)")
print("=" * 80)

strategies = {
    "1_current": strategy_current,
    "2_pepper_cycle": strategy_pepper_cycle,
    "3_pepper_only": strategy_pepper_only,
    "4_osmium_only": strategy_osmium_only,
    "5_pepper_aggressive": strategy_pepper_sell_mm,
}

for name, fn in strategies.items():
    results = simulate_strategy(fn, days=[-2, -1], ticks_per_day=2000)
    print(f"\n--- {name} ---")
    print(f"  OSMIUM PnL: {results['osmium_pnl']:>10.0f}  (pos={results['osmium_pos']:>3}, fills={results['osmium_fills']})")
    print(f"  PEPPER PnL: {results['pepper_pnl']:>10.0f}  (pos={results['pepper_pos']:>3}, fills={results['pepper_fills']})")
    print(f"  TOTAL  PnL: {results['total_pnl']:>10.0f}")

    # Analyze position buildup
    pep_hist = results["position_history"]["pepper"]
    if pep_hist:
        # When did we reach max position?
        max_tick = None
        for i, p in enumerate(pep_hist):
            if p >= 80:
                max_tick = i
                break
        if max_tick is not None:
            print(f"  PEPPER max pos reached at tick {max_tick}")
        else:
            print(f"  PEPPER never reached max pos (final={pep_hist[-1]})")

# ============================================================
# Additional analysis: theoretical bounds
# ============================================================
print("\n" + "=" * 80)
print("THEORETICAL BOUNDS (2 days × 2000 ticks)")
print("=" * 80)

# PEPPER theoretical max
ipr_fair_0 = compute_ipr_fair(0, 0, 2000)
ipr_fair_end = compute_ipr_fair(1, 1999, 2000)
drift = ipr_fair_end - ipr_fair_0
print(f"  PEPPER FV range: {ipr_fair_0:.1f} to {ipr_fair_end:.1f}")
print(f"  PEPPER total drift: {drift:.1f}")
print(f"  PEPPER max PnL (80 units at tick 0): {80 * drift:.0f}")
print(f"  PEPPER minus avg entry cost (~5/unit): {80 * drift - 80 * 5:.0f}")

# What if we could also earn spread on PEPPER?
print(f"\n  If MM cycling 10 units every 50 ticks:")
total_cycles = 4000 // 50
spread_per_cycle = 12  # approx spread
drift_loss_per_cycle = 10 * 0.1 * 50  # 10 units × 0.1 drift × 50 ticks
mm_profit = total_cycles * (spread_per_cycle * 10 - drift_loss_per_cycle)
print(f"    Cycles: {total_cycles}, Spread earned: {total_cycles * spread_per_cycle * 10:.0f}, Drift lost: {total_cycles * drift_loss_per_cycle:.0f}")
print(f"    Net MM profit: {mm_profit:.0f}")

# ============================================================
# Simulate: how fast can we accumulate PEPPER with different approaches?
# ============================================================
print("\n" + "=" * 80)
print("PEPPER ACCUMULATION SPEED TEST")
print("=" * 80)

for day in [-2, -1, 0]:
    prices = load_prices(day)
    pepper = [r for r in prices if 'PEPPER' in r['product']]

    print(f"\n  Day {day}:")

    # Approach A: take all asks (including Bot 1)
    pos_a = 0
    ticks_a = None
    cost_a = 0

    # Approach B: skip Bot 1 asks (vol > 15), only Bot 2
    pos_b = 0
    ticks_b = None
    cost_b = 0

    # Approach C: skip expensive asks, only buy below FV+5
    pos_c = 0
    ticks_c = None
    cost_c = 0

    for i, r in enumerate(pepper[:2000]):
        bids, asks = parse_book(r)
        mid = float(r['mid_price']) if r['mid_price'] else None

        # Approach A: take all
        if pos_a < 80 and asks:
            for p in sorted(asks.keys()):
                v = -asks[p]
                q = min(v, 80 - pos_a)
                if q > 0:
                    pos_a += q
                    cost_a += p * q
                if pos_a >= 80:
                    break
            if pos_a >= 80 and ticks_a is None:
                ticks_a = i

        # Approach B: skip Bot 1
        if pos_b < 80 and asks:
            for p in sorted(asks.keys()):
                v = -asks[p]
                if v > 15:
                    continue  # skip Bot 1
                q = min(v, 80 - pos_b)
                if q > 0:
                    pos_b += q
                    cost_b += p * q
                if pos_b >= 80:
                    break
            if pos_b >= 80 and ticks_b is None:
                ticks_b = i

        # Approach C: only cheap asks
        if pos_c < 80 and asks and mid:
            for p in sorted(asks.keys()):
                if p > mid + 6:
                    break
                v = -asks[p]
                q = min(v, 80 - pos_c)
                if q > 0:
                    pos_c += q
                    cost_c += p * q
                if pos_c >= 80:
                    break
            if pos_c >= 80 and ticks_c is None:
                ticks_c = i

    print(f"    A (all asks):    filled {pos_a}/80 in {ticks_a} ticks, avg cost={cost_a/max(pos_a,1):.1f}")
    print(f"    B (skip Bot 1):  filled {pos_b}/80 in {ticks_b} ticks, avg cost={cost_b/max(pos_b,1):.1f}")
    print(f"    C (cheap only):  filled {pos_c}/80 in {ticks_c} ticks, avg cost={cost_c/max(pos_c,1):.1f}")

    # Expected FV at fill time
    for label, ticks, cost, pos in [("A", ticks_a, cost_a, pos_a), ("B", ticks_b, cost_b, pos_b), ("C", ticks_c, cost_c, pos_c)]:
        if ticks is not None and pos >= 80:
            # FV when done filling
            day_idx = [-2, -1, 0].index(day)
            fv_at_fill = 10000 + (day_idx * 10000 + ticks) * 0.1  # using data ticks
            entry_cost = cost - pos * fv_at_fill
            drift_lost = 80 * 0.1 * ticks  # drift PnL lost while building position
            print(f"      {label}: entry_cost_above_fv={entry_cost:.0f}, drift_lost_building={drift_lost:.0f}, total_cost={entry_cost+drift_lost:.0f}")

print("\nDone!")
