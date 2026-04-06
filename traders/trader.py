from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    IMC Prosperity 4 Trading Algorithm v3
    Portal-optimized: penny-jump quoting, correct position limits, no harmful takes.

    Changes from v2:
    - Removed TOMATOES taking (backtester --match-trades none shows EMA-based takes
      are wrong-way trades on a drifting asset: buys falling markets, sells rising)
    - TOMATOES now uses mid-based quote cap instead of EMA (always current, no lag)
    - EMERALDS keeps take-at-fair for spread-tightening events (known fair value)
    """

    PARAMS = {
        "EMERALDS": {
            "strategy": "fixed_mm",
            "fair_value": 10000,
            "limit": 80,
            "soft_limit": 50,
        },
        "TOMATOES": {
            "strategy": "adaptive_mm",
            "limit": 80,
            "soft_limit": 50,
        },
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                trader_data = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            params = self.PARAMS.get(product)
            if not params:
                result[product] = []
                continue

            position = state.position.get(product, 0)

            if params["strategy"] == "fixed_mm":
                orders, trader_data = self._trade_fixed(
                    product, od, position, params, trader_data
                )
            elif params["strategy"] == "adaptive_mm":
                orders, trader_data = self._trade_adaptive(
                    product, od, position, params, trader_data
                )
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(trader_data)

    def _trade_fixed(self, product, od, position, params, td):
        """EMERALDS: penny-jump MM + take at fair value on spread tightening."""
        orders = []
        fair = params["fair_value"]
        limit = params["limit"]
        soft = params["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders, td

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: Take at fair value or better
        # ~59 spread-tightening events per day (ask=10000 or bid=10000)
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fair:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order(product, ask_price, qty))
            buy_ordered += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fair:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order(product, bid_price, -qty))
            sell_ordered += qty

        # Phase 2: Penny-jump passive quotes
        effective_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(effective_pos, soft, limit)
        skew_int = int(round(skew))

        our_bid = min(best_bid + 1, fair - 1) + skew_int
        our_ask = max(best_ask - 1, fair + 1) + skew_int

        if our_bid >= our_ask:
            our_bid = fair - 1
            our_ask = fair + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order(product, our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order(product, our_ask, -passive_sell))

        return orders, td

    def _trade_adaptive(self, product, od, position, params, td):
        """TOMATOES: pure penny-jump MM. No taking (loses money on drifting assets)."""
        orders = []
        limit = params["limit"]
        soft = params["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders, td

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        starting_pos = position

        # Pure passive: penny-jump with mid-based cap (no EMA lag issues)
        skew = self._inventory_skew(starting_pos, soft, limit)
        skew_int = int(round(skew))

        our_bid = min(best_bid + 1, int(mid) - 1) + skew_int
        our_ask = max(best_ask - 1, int(mid) + 1) + skew_int

        if our_bid >= our_ask:
            our_bid = int(mid) - 1
            our_ask = int(mid) + 1

        passive_buy = limit - starting_pos
        passive_sell = limit + starting_pos

        if passive_buy > 0:
            orders.append(Order(product, our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order(product, our_ask, -passive_sell))

        return orders, td

    @staticmethod
    def _inventory_skew(position, soft_limit, hard_limit):
        """Skew quotes to reduce inventory. Max 2 ticks at hard limit."""
        if abs(position) <= soft_limit:
            return 0.0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        magnitude = min((excess / max_excess) * 2.0, 2.0)
        return -magnitude if position > 0 else magnitude
