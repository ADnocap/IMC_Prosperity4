"""Pebble_fucker_v2 — v1 + per-leg take layer for extreme basket residuals.

Same core as v1 (basket-residual MM on the 5 PEBBLES products around the
exact constraint sum = 50,000), with one upgrade: when the residual `r` is
big enough that crossing a specific leg's spread is profitable on its own,
we take aggressively at that leg's L1 instead of waiting passively.

Per-leg take threshold is `h_p + TAKE_CUSHION`, since cross-spread sell at
best_bid earns `r - h_p` per lot vs implied fair, so the cross is positive
EV only when `r > h_p`. Cushion adds a small safety margin against the
~1-tick passive close cost.

Half-spreads from analysis/round5/eda_per_product.csv:
  XS=4.5, S=6.0, M=6.5, L=6.5, XL=8.5

So with TAKE_CUSHION=1.0, only XS triggers when |r| ≥ 5.5; the full basket
takes at |r| ≥ 9.5 (when XL clears its threshold). That matches FINDINGS:
~2.3% of ticks see |r| > 5 (XS-only takes), ~2% see |r| > 10 (everyone).

In normal residual range (|r| ≤ 1), behavior is identical to v1: penny-jump
both sides on every leg.
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
MAX_QUOTE_SIZE = POSITION_LIMIT

# 0.5-tick noise floor: parity artifact, no signal.
RESIDUAL_THRESHOLD = 1.0

# Per-leg half-spread, calibrated from analysis/round5/eda_per_product.csv.
HALF_SPREAD: Dict[str, float] = {
    "PEBBLES_XS": 4.5,
    "PEBBLES_S": 6.0,
    "PEBBLES_M": 6.5,
    "PEBBLES_L": 6.5,
    "PEBBLES_XL": 8.5,
}

# Required edge over half-spread before taking. 1 tick covers the typical
# passive-close cost when residual reverts to noise.
TAKE_CUSHION = 1.0


def take_threshold(symbol: str) -> float:
    return HALF_SPREAD[symbol] + TAKE_CUSHION


class Trader:

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # 1. Pull mids; bail if any pebble's book is empty.
        mids: Dict[str, float] = {}
        for p in PEBBLES:
            od = state.order_depths.get(p)
            if od is None or not od.buy_orders or not od.sell_orders:
                return result, 0, ""
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mids[p] = (best_bid + best_ask) / 2.0

        # 2. Basket residual (single scalar, same edge for every leg).
        sum_all = sum(mids.values())
        residual = sum_all - BASKET_SUM

        # 3. Per-leg orders.
        for p in PEBBLES:
            od = state.order_depths[p]
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            best_bid_qty = od.buy_orders[best_bid]          # positive
            best_ask_qty = abs(od.sell_orders[best_ask])    # negate sell side
            position = state.position.get(p, 0)

            passive_bid_px = best_bid + 1
            passive_ask_px = best_ask - 1
            if passive_bid_px >= passive_ask_px:
                # Spread too tight for a penny-jump; skip this leg this tick.
                continue

            # Position-limit envelope (worst-case all-fills).
            max_buy = max(0, POSITION_LIMIT - position)
            max_sell = max(0, POSITION_LIMIT + position)

            orders: List[Order] = []
            t_thresh = take_threshold(p)

            if residual > t_thresh:
                # Basket overpriced AND this leg's cross is profitable.
                # Take at best_bid up to L1 size + position room; remaining
                # sell capacity goes to a penny-jump passive ask.
                take_qty = min(best_bid_qty, max_sell, MAX_QUOTE_SIZE)
                if take_qty > 0:
                    orders.append(Order(p, best_bid, -take_qty))
                remaining_sell = min(max_sell - take_qty, MAX_QUOTE_SIZE)
                if remaining_sell > 0:
                    orders.append(Order(p, passive_ask_px, -remaining_sell))
                # No bid side — don't add long basket exposure.

            elif residual < -t_thresh:
                # Mirror: basket underpriced, take at best_ask, no asks.
                take_qty = min(best_ask_qty, max_buy, MAX_QUOTE_SIZE)
                if take_qty > 0:
                    orders.append(Order(p, best_ask, take_qty))
                remaining_buy = min(max_buy - take_qty, MAX_QUOTE_SIZE)
                if remaining_buy > 0:
                    orders.append(Order(p, passive_bid_px, remaining_buy))

            elif residual > RESIDUAL_THRESHOLD:
                # Mild signal: passive ask only, no bid.
                ask_qty = min(MAX_QUOTE_SIZE, max_sell)
                if ask_qty > 0:
                    orders.append(Order(p, passive_ask_px, -ask_qty))

            elif residual < -RESIDUAL_THRESHOLD:
                # Mild signal: passive bid only, no ask.
                bid_qty = min(MAX_QUOTE_SIZE, max_buy)
                if bid_qty > 0:
                    orders.append(Order(p, passive_bid_px, bid_qty))

            else:
                # Noise floor: penny-jump both sides.
                bid_qty = min(MAX_QUOTE_SIZE, max_buy)
                ask_qty = min(MAX_QUOTE_SIZE, max_sell)
                if bid_qty > 0:
                    orders.append(Order(p, passive_bid_px, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(p, passive_ask_px, -ask_qty))

            result[p] = orders

        return result, 0, ""
