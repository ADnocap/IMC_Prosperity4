"""Pebble_fucker_v3 — v2 with inventory-aware quote sizing (close-side uncapped).

The diagnostic on v2 (portal sub 558352) was: ended day at -8 across all 5
pebbles for a -40 basket short, ~+18% worse than v1 mainly because the
unrealised loss on the stuck short ate the take alpha.

Why v2 got stuck: in noise-zone (|r| ≤ 1, ~89-97% of ticks), v2 quoted

    bid_qty = min(MAX_QUOTE_SIZE, max_buy)
    ask_qty = min(MAX_QUOTE_SIZE, max_sell)

with MAX_QUOTE_SIZE = 10. At pos = -8, max_buy = 18 (room for 10 long +
8 short-close). v2 only used 10 of those 18 — leaving 8 lots of bid
capacity ON THE TABLE exactly when we needed to close the short.

The position-limit math caps each side at max_buy / max_sell already; the
MAX_QUOTE_SIZE cap was redundant defence. In v3 we remove it. The bid
quote is always sized at max_buy and the ask at max_sell (both naturally
0..2*POSITION_LIMIT and capped by the limit rule).

At pos=0:   bid 10, ask 10  (same as v2)
At pos=+5:  bid 5,  ask 15  (v2 had ask 10 — v3 leans harder into shedding longs)
At pos=-8:  bid 18, ask 2   (v2 had bid 10 — v3 closes the short faster)

Take-layer logic is identical to v2 (per-leg threshold = HALF_SPREAD + 1).
Self-cross is avoided because we never post a closing quote on the side
that the take is using — when residual > take_thresh we sell at L1 (and
no bid), and when residual < -take_thresh we buy at L1 (and no ask).
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List


PEBBLES = (
    "PEBBLES_XS",
    "PEBBLES_S",
    "PEBBLES_M",
    "PEBBLES_L",
    "PEBBLES_XL",
)
BASKET_SUM = 50_000

POSITION_LIMIT = 10

# Half-tick parity threshold; below this the residual is just rounding noise.
RESIDUAL_THRESHOLD = 1.0

# Per-leg half-spread (median observed in analysis/round5/eda_per_product.csv).
HALF_SPREAD: Dict[str, float] = {
    "PEBBLES_XS": 4.5,
    "PEBBLES_S": 6.0,
    "PEBBLES_M": 6.5,
    "PEBBLES_L": 6.5,
    "PEBBLES_XL": 8.5,
}

# Cushion above per-leg half-spread before crossing the spread is +EV.
TAKE_CUSHION = 1.0


def take_threshold(symbol: str) -> float:
    return HALF_SPREAD[symbol] + TAKE_CUSHION


class Trader:

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # 1. Collect mids; bail if any pebble book is empty (constraint unreliable).
        mids: Dict[str, float] = {}
        for p in PEBBLES:
            od = state.order_depths.get(p)
            if od is None or not od.buy_orders or not od.sell_orders:
                return result, 0, ""
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mids[p] = (best_bid + best_ask) / 2.0

        # 2. Basket residual — single signal shared across all 5 legs.
        sum_all = sum(mids.values())
        residual = sum_all - BASKET_SUM

        # 3. Quote each leg.
        for p in PEBBLES:
            od = state.order_depths[p]
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            best_bid_qty = od.buy_orders[best_bid]
            best_ask_qty = abs(od.sell_orders[best_ask])
            position = state.position.get(p, 0)

            passive_bid_px = best_bid + 1
            passive_ask_px = best_ask - 1
            if passive_bid_px >= passive_ask_px:
                continue

            # Inventory-aware capacity. Worst-case-fill check on each side
            # individually: total buys ≤ max_buy, total sells ≤ max_sell.
            max_buy = max(0, POSITION_LIMIT - position)
            max_sell = max(0, POSITION_LIMIT + position)

            t_thresh = take_threshold(p)
            orders: List[Order] = []

            if residual > t_thresh:
                # Basket overpriced AND this leg's cross is +EV.
                # Take at L1 bid, then passive ask for any remaining sell room.
                # No bid side (would self-cross at best_bid+1 vs take at best_bid).
                take_qty = min(best_bid_qty, max_sell)
                if take_qty > 0:
                    orders.append(Order(p, best_bid, -take_qty))
                passive_qty = max_sell - take_qty
                if passive_qty > 0:
                    orders.append(Order(p, passive_ask_px, -passive_qty))

            elif residual < -t_thresh:
                # Mirror: basket underpriced, take at L1 ask + passive bid.
                take_qty = min(best_ask_qty, max_buy)
                if take_qty > 0:
                    orders.append(Order(p, best_ask, take_qty))
                passive_qty = max_buy - take_qty
                if passive_qty > 0:
                    orders.append(Order(p, passive_bid_px, passive_qty))

            elif residual > RESIDUAL_THRESHOLD:
                # Mild positive — passive ask only, no opening bid.
                if max_sell > 0:
                    orders.append(Order(p, passive_ask_px, -max_sell))

            elif residual < -RESIDUAL_THRESHOLD:
                # Mild negative — passive bid only.
                if max_buy > 0:
                    orders.append(Order(p, passive_bid_px, max_buy))

            else:
                # Noise floor — penny-jump both sides at FULL inventory-aware
                # capacity. This is the v2→v3 fix: max_buy includes closing
                # capacity (e.g. up to 18 lots when position=-8), so the
                # short can actually unwind during the long stretches of
                # zero-residual ticks.
                if max_buy > 0:
                    orders.append(Order(p, passive_bid_px, max_buy))
                if max_sell > 0:
                    orders.append(Order(p, passive_ask_px, -max_sell))

            result[p] = orders

        return result, 0, ""
