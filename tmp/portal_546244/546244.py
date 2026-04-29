"""R5 single-product validation trader.

Penny-jumps OXYGEN_SHAKE_GARLIC (V-pulse member, h=7.5).

Predictable expected PnL on 1,000 portal-UI ticks:
- V pulse rate ≈ 0.0244/tick → ~24.4 pulses
- Each fires GARLIC with qty uniform {1..4} (mean 2.5)
- ~50/50 buy/sell direction → inventory churns, both quotes get hit
- Penny-jump edge = h - 1 = 6.5 ticks per fill
- Position limit 10, so ~24 × 2.5 ≈ 60 units volume capped by limit churn
- Expected PnL ≈ ~360 (lower bound) to ~700 (upper bound) per 1k ticks

This trader's job: confirm the sim's per-fill edge calibration matches portal.
"""

from typing import Dict, List

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


SYMBOL = "OXYGEN_SHAKE_GARLIC"


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        if SYMBOL not in state.order_depths:
            return result, 0, ""

        od = state.order_depths[SYMBOL]
        if not od.buy_orders or not od.sell_orders:
            return result, 0, ""

        pos = state.position.get(SYMBOL, 0)
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        if best_ask - best_bid < 2:
            return result, 0, ""

        bid_px = best_bid + 1
        ask_px = best_ask - 1

        bid_size = min(10, max(0, 10 - pos))
        ask_size = min(10, max(0, 10 + pos))

        orders: List[Order] = []
        if bid_size > 0:
            orders.append(Order(SYMBOL, bid_px, bid_size))
        if ask_size > 0:
            orders.append(Order(SYMBOL, ask_px, -ask_size))
        result[SYMBOL] = orders
        return result, 0, ""