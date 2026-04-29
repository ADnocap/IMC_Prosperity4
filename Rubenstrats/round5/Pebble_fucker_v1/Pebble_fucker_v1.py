"""Pebble_fucker_v1 — basket-residual MM on the 5 PEBBLES products.

Empirical constraint (verified on 30k ticks of R5 historical data):

    PEBBLES_XS + PEBBLES_S + PEBBLES_M + PEBBLES_L + PEBBLES_XL = 50,000
    (std 2.8 — exact in expectation, ~2% of ticks deviate by ±14-18)

Strategy: per tick we compute the basket residual

    r = sum_all_5_mids - 50,000

A nonzero r means SOMETHING in the basket is mispriced. The math doesn't
isolate which leg is the offender (every leg's mid_i - implied_fv_i is r
itself), so we trade symmetric: when r > 0 we want to short the basket
(post asks across all 5), when r < 0 we want long (post bids across all 5).
Whichever leg actually reverts pays out, the others wash.

Layers:
  - r > +threshold  → suppress bids on all 5, only post asks
  - r < -threshold  → suppress asks on all 5, only post bids
  - |r| <= threshold → penny-jump MM on both sides (noise floor)

Plus inventory-aware sizing so we never breach pos limit = 10.

This v1 is a passive make layer only. A take layer for huge residuals
(|r| > 5 * h_avg ≈ 30) can be bolted on once we see how the make layer
performs.
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

# 0.5-tick noise floor: parity artifact, not signal.
RESIDUAL_THRESHOLD = 1.0

# Max single-quote size. We cap at the position limit so worst-case
# (one side fully fills) just hits the cap rather than breaching it.
MAX_QUOTE_SIZE = POSITION_LIMIT


class Trader:

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # 1. Pull mids for all 5 pebbles. If any leg has an empty book, bail —
        #    the basket constraint is unreliable when we can't see one mid.
        mids: Dict[str, float] = {}
        for p in PEBBLES:
            od = state.order_depths.get(p)
            if od is None or not od.buy_orders or not od.sell_orders:
                return result, 0, ""
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mids[p] = (best_bid + best_ask) / 2.0

        # 2. Basket residual. Single scalar shared across all 5 legs.
        sum_all = sum(mids.values())
        residual = sum_all - BASKET_SUM

        # 3. Direction gating from residual.
        if residual > RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = False, True
        elif residual < -RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = True, False
        else:
            allow_bid_global, allow_ask_global = True, True

        # 4. Quote each pebble.
        for p in PEBBLES:
            od = state.order_depths[p]
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            position = state.position.get(p, 0)

            # Penny-jump prices (stay strictly inside the bot quote).
            bid_px = best_bid + 1
            ask_px = best_ask - 1
            # Don't cross our own quotes.
            if bid_px >= ask_px:
                continue

            allow_bid = allow_bid_global
            allow_ask = allow_ask_global

            # Inventory-aware sizing: never let worst-case fill breach the limit.
            max_buy = max(0, POSITION_LIMIT - position)
            max_sell = max(0, POSITION_LIMIT + position)
            bid_qty = min(MAX_QUOTE_SIZE, max_buy)
            ask_qty = min(MAX_QUOTE_SIZE, max_sell)

            orders: List[Order] = []
            if allow_bid and bid_qty > 0:
                orders.append(Order(p, bid_px, bid_qty))
            if allow_ask and ask_qty > 0:
                orders.append(Order(p, ask_px, -ask_qty))

            result[p] = orders

        return result, 0, ""
