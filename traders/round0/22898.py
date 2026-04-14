from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Penny-jump market-making with order-book imbalance signal.

    EMERALDS: Take at fair (10000) during spread-tightening,
              single-level penny-jump passive MM.
    TOMATOES: Single-level penny-jump MM. When order book is imbalanced
              (~250 times/day), shift quotes toward the predicted mean-
              reversion direction. Ask-heavy book -> price about to rise
              -> shift bid up to buy before the bounce. Bid-heavy -> opposite.
    """

    PARAMS = {
        "EMERALDS": {
            "fair_value": 10000,
            "limit": 80,
            "soft_limit": 50,
        },
        "TOMATOES": {
            "limit": 80,
            "soft_limit": 50,
        },
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except json.JSONDecodeError:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                orders = self._trade_emeralds(od, position)
            elif product == "TOMATOES":
                orders, td = self._trade_tomatoes(od, position, td)
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(td)

    # ------------------------------------------------------------------
    # EMERALDS
    # ------------------------------------------------------------------
    def _trade_emeralds(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        p = self.PARAMS["EMERALDS"]
        fair = p["fair_value"]
        limit = p["limit"]
        soft = p["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: take at fair value or better (spread-tightening events)
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fair:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - position - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("EMERALDS", ask_price, qty))
            buy_ordered += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fair:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + position - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("EMERALDS", bid_price, -qty))
            sell_ordered += qty

        # Phase 2: single-level penny-jump passive quotes
        eff_pos = position + buy_ordered - sell_ordered
        skew = self._inventory_skew(eff_pos, soft, limit)

        our_bid = min(best_bid + 1, fair - 1) + skew
        our_ask = max(best_ask - 1, fair + 1) + skew

        our_bid = int(our_bid)
        our_ask = int(our_ask)

        if our_bid >= our_ask:
            our_bid = fair - 1
            our_ask = fair + 1

        remaining_buy = limit - position - buy_ordered
        remaining_sell = limit + position - sell_ordered

        if remaining_buy > 0:
            orders.append(Order("EMERALDS", our_bid, remaining_buy))
        if remaining_sell > 0:
            orders.append(Order("EMERALDS", our_ask, -remaining_sell))

        return orders

    # ------------------------------------------------------------------
    # TOMATOES
    # ------------------------------------------------------------------
    def _trade_tomatoes(self, od: OrderDepth, position: int, td: dict):
        orders = []
        p = self.PARAMS["TOMATOES"]
        limit = p["limit"]
        soft = p["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders, td

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        # Compute order book imbalance
        bid_vol = sum(od.buy_orders.values())
        ask_vol = sum(-v for v in od.sell_orders.values())
        total_vol = bid_vol + ask_vol
        imbalance = bid_vol / total_vol if total_vol > 0 else 0.5

        # Directional skew from imbalance signal
        # imbalance < 0.45 (ask-heavy) -> price about to rise -> shift UP to buy
        # imbalance > 0.55 (bid-heavy) -> price about to drop -> shift DOWN to sell
        if imbalance < 0.45:
            dir_skew = 1   # shift quotes up: bid more aggressive, ask higher
        elif imbalance > 0.55:
            dir_skew = -1  # shift quotes down: ask more aggressive, bid lower
        else:
            dir_skew = 0   # balanced: no directional view

        # Inventory skew
        inv_skew = self._inventory_skew(position, soft, limit)

        # Combine skews — inventory safety takes priority
        total_skew = inv_skew + dir_skew

        # Single-level penny-jump passive quotes
        our_bid = min(best_bid + 1, int(mid) - 1) + total_skew
        our_ask = max(best_ask - 1, int(mid) + 1) + total_skew

        our_bid = int(our_bid)
        our_ask = int(our_ask)

        if our_bid >= our_ask:
            our_bid = int(mid) - 1
            our_ask = int(mid) + 1

        passive_buy = limit - position
        passive_sell = limit + position

        if passive_buy > 0:
            orders.append(Order("TOMATOES", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("TOMATOES", our_ask, -passive_sell))

        return orders, td

    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_skew(position: int, soft_limit: int, hard_limit: int) -> int:
        if abs(position) <= soft_limit:
            return 0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        if max_excess == 0:
            return 0
        magnitude = min(round((excess / max_excess) * 2), 2)
        return -magnitude if position > 0 else magnitude