"""Exhaustive verification of manual challenge auction solution.

We implement the call-auction rules from scratch and brute-force every
(price, quantity) combination to confirm the proposed optimum is best.
"""
from __future__ import annotations


# Order books as (price, volume) lists.
# Bids: existing buyers (descending price).
# Asks: existing sellers (ascending price).
FLAX_BIDS = [(30, 30000), (29, 5000), (28, 12000), (27, 28000)]
FLAX_ASKS = [(28, 40000), (31, 20000), (32, 20000), (33, 30000)]
FLAX_BUYBACK = 30.0
FLAX_FEE = 0.0

MUSH_BIDS = [
    (20, 43000), (19, 17000), (18, 6000), (17, 5000),
    (16, 10000), (15, 5000), (14, 10000), (13, 7000),
]
MUSH_ASKS = [
    (12, 20000), (13, 25000), (14, 35000), (15, 6000),
    (16, 5000), (17, 0), (18, 10000), (19, 12000),
]
MUSH_BUYBACK = 20.0
MUSH_FEE = 0.10


def cum_bid_at(bids, p):
    """Total bid volume with price >= p."""
    return sum(v for pr, v in bids if pr >= p)


def cum_ask_at(asks, p):
    """Total ask volume with price <= p."""
    return sum(v for pr, v in asks if pr <= p)


def clearing_price(bids, asks, price_range):
    """Return clearing price using max-volume rule with higher-price tie-break."""
    best_vol = -1
    best_p = None
    for p in price_range:
        v = min(cum_bid_at(bids, p), cum_ask_at(asks, p))
        # tie-break: higher price wins
        if v > best_vol or (v == best_vol and p > best_p):
            best_vol = v
            best_p = p
    return best_p, best_vol


def our_fill(our_price, our_qty, bids_existing, asks, buyback, fee, price_range):
    """Simulate adding our BUY order (we are last in line at our price level).

    Returns (units_filled, p_star, profit).
    """
    # Build bid list WITH our order; mark ours separately for allocation.
    # For clearing calc, just add quantity at our price.
    bids = list(bids_existing)
    # merge our qty at our price
    merged = {}
    for pr, v in bids:
        merged[pr] = merged.get(pr, 0) + v
    merged[our_price] = merged.get(our_price, 0) + our_qty
    bids_merged = sorted(merged.items(), key=lambda x: -x[0])

    p_star, v_star = clearing_price(bids_merged, asks, price_range)

    # Allocation: price priority (highest bid first), then time priority (existing before us at same price).
    # Total traded = v_star. Allocate from highest bids downward.
    # Sort existing bids descending; within same price, existing first (we are last at our price).
    alloc_list = []  # list of (price, qty, is_ours)
    existing_sorted = sorted(bids_existing, key=lambda x: -x[0])
    for pr, v in existing_sorted:
        alloc_list.append((pr, v, False))
    # Insert our order at the very end of the queue at our price.
    # Merge by price, preserving order: for our price, existing comes first, then ours.
    # Rebuild in descending price order:
    prices_all = sorted(set([pr for pr, _, _ in alloc_list] + [our_price]), reverse=True)
    new_alloc = []
    for pr in prices_all:
        for p2, q2, ours in alloc_list:
            if p2 == pr:
                new_alloc.append((p2, q2, ours))
        if pr == our_price:
            new_alloc.append((pr, our_qty, True))

    remaining = v_star
    our_filled = 0
    for pr, q, ours in new_alloc:
        if remaining <= 0:
            break
        if pr < p_star:
            break  # cannot fill bids below clearing price
        take = min(q, remaining)
        if ours:
            our_filled += take
        remaining -= take

    profit = our_filled * (buyback - p_star - fee)
    return our_filled, p_star, profit


def brute_force(bids, asks, buyback, fee, p_min, p_max, q_max, q_step=1):
    """Search every (price, quantity) combination; return best and full grid."""
    price_range = list(range(p_min, p_max + 1))
    best = (None, None, -1e18, None, None)  # (price, qty, profit, fill, p_star)
    rows = []
    for pr in price_range:
        for q in range(1, q_max + 1, q_step):
            fill, p_star, pnl = our_fill(pr, q, bids, asks, buyback, fee, price_range)
            rows.append((pr, q, fill, p_star, pnl))
            if pnl > best[2]:
                best = (pr, q, pnl, fill, p_star)
    return best, rows


def summarize_per_price(rows):
    """For each price, find the quantity that maximizes profit."""
    by_price = {}
    for pr, q, fill, p_star, pnl in rows:
        cur = by_price.get(pr)
        if cur is None or pnl > cur[2]:
            by_price[pr] = (pr, q, pnl, fill, p_star)
    return sorted(by_price.values(), key=lambda x: x[0])


def main():
    print("=" * 72)
    print("DRYLAND FLAX  (buyback=30, fee=0)")
    print("=" * 72)
    # Price range: anywhere from just below book to above highest ask.
    # Quantity: try 1..60000 to be safe.
    best, rows = brute_force(
        FLAX_BIDS, FLAX_ASKS, FLAX_BUYBACK, FLAX_FEE,
        p_min=25, p_max=35, q_max=60000, q_step=1,
    )
    print(f"Best: bid={best[0]}, qty={best[1]}, profit={best[2]:.2f}, fill={best[3]}, P*={best[4]}")
    print("\nOptimum quantity per bid price:")
    print(f"  {'price':>6} {'qty':>8} {'fill':>8} {'P*':>4} {'profit':>12}")
    for pr, q, pnl, fill, p_star in summarize_per_price(rows):
        print(f"  {pr:>6} {q:>8} {fill:>8} {p_star:>4} {pnl:>12.2f}")

    print()
    print("=" * 72)
    print("EMBER MUSHROOM  (buyback=20, fee=0.10)")
    print("=" * 72)
    best, rows = brute_force(
        MUSH_BIDS, MUSH_ASKS, MUSH_BUYBACK, MUSH_FEE,
        p_min=10, p_max=22, q_max=120000, q_step=1,
    )
    print(f"Best: bid={best[0]}, qty={best[1]}, profit={best[2]:.2f}, fill={best[3]}, P*={best[4]}")
    print("\nOptimum quantity per bid price:")
    print(f"  {'price':>6} {'qty':>8} {'fill':>8} {'P*':>4} {'profit':>12}")
    for pr, q, pnl, fill, p_star in summarize_per_price(rows):
        print(f"  {pr:>6} {q:>8} {fill:>8} {p_star:>4} {pnl:>12.2f}")


if __name__ == "__main__":
    main()
