from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    IMC Prosperity 4 Trading Algorithm v4
    Bot3-aware market making with smart inventory management.

    Key innovations over v3:
    - Bot3 detection: 3 price levels on one side = bot3 present. Use bot2
      (2nd level) for mid/penny-jump to prevent distorted pricing when bot3
      temporarily narrows the spread.
    - Smart bot3 taking (TOMATOES): Take favorable bot3 orders when they
      reduce inventory OR position is small. Earns alpha while managing risk.
    - Bot2-aware quoting (both products): Penny-jump references bot2 levels
      even when bot3 is the best bid/ask.

    EMERALDS: Take at fair (10000), penny-jump MM, bot2-aware quoting.
    TOMATOES: Bot3 detection/taking, penny-jump off bot2 levels,
              threshold inventory skew.
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
            "take_free_zone": 20,
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
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                orders = self._trade_emeralds(od, position)
            elif product == "TOMATOES":
                orders = self._trade_tomatoes(od, position)
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(trader_data)

    # ------------------------------------------------------------------
    # EMERALDS: take at fair + bot2-aware penny-jump
    # ------------------------------------------------------------------
    def _trade_emeralds(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        p = self.PARAMS["EMERALDS"]
        fair = p["fair_value"]
        limit = p["limit"]
        soft = p["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True)
        asks_sorted = sorted(od.sell_orders.keys())

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: Take at fair value or better (captures bot3 at 10000)
        for ask_price in asks_sorted:
            if ask_price > fair:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("EMERALDS", ask_price, qty))
            buy_ordered += qty

        for bid_price in bids_sorted:
            if bid_price < fair:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("EMERALDS", bid_price, -qty))
            sell_ordered += qty

        # Phase 2: Passive penny-jump using bot2 reference levels
        # Skip bot3 (1st level when 3 levels present) for accurate pricing
        ref_bid = bids_sorted[1] if len(bids_sorted) >= 3 else bids_sorted[0]
        ref_ask = asks_sorted[1] if len(asks_sorted) >= 3 else asks_sorted[0]

        effective_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(effective_pos, soft, limit)

        our_bid = min(ref_bid + 1, fair - 1) + skew
        our_ask = max(ref_ask - 1, fair + 1) + skew

        if our_bid >= our_ask:
            our_bid = fair - 1
            our_ask = fair + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("EMERALDS", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("EMERALDS", our_ask, -passive_sell))

        return orders

    # ------------------------------------------------------------------
    # TOMATOES: bot3-aware MM with smart taking
    # ------------------------------------------------------------------
    def _trade_tomatoes(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        p = self.PARAMS["TOMATOES"]
        limit = p["limit"]
        soft = p["soft_limit"]
        free_zone = p["take_free_zone"]

        if not od.buy_orders or not od.sell_orders:
            return orders

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True)
        asks_sorted = sorted(od.sell_orders.keys())

        # Detect bot3 from level count (normal book = 2 levels per side)
        bot3_on_bid = len(bids_sorted) >= 3
        bot3_on_ask = len(asks_sorted) >= 3

        # Reference levels: bot2 (skip bot3 if present) for accurate FV
        ref_bid = bids_sorted[1] if bot3_on_bid else bids_sorted[0]
        ref_ask = asks_sorted[1] if bot3_on_ask else asks_sorted[0]
        mid = (ref_bid + ref_ask) / 2

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: Smart bot3 taking
        # Take when: (a) reduces inventory, OR (b) position is small
        if bot3_on_ask:
            bot3_ask = asks_sorted[0]
            bot3_vol = -od.sell_orders[bot3_ask]
            if bot3_ask <= int(mid):  # positive edge: below fair value
                if position < 0:
                    # Short → buying reduces inventory (take up to flat)
                    can = min(bot3_vol, limit - starting_pos - buy_ordered,
                              -position)
                elif abs(position) < free_zone:
                    # Near flat → safe to take (cap at free zone)
                    can = min(bot3_vol, limit - starting_pos - buy_ordered,
                              free_zone - position)
                else:
                    can = 0
                if can > 0:
                    orders.append(Order("TOMATOES", bot3_ask, can))
                    buy_ordered += can

        if bot3_on_bid:
            bot3_bid = bids_sorted[0]
            bot3_vol = od.buy_orders[bot3_bid]
            if bot3_bid >= int(mid) + 1:  # positive edge: above fair value
                if position > 0:
                    # Long → selling reduces inventory (take up to flat)
                    can = min(bot3_vol, limit + starting_pos - sell_ordered,
                              position)
                elif abs(position) < free_zone:
                    # Near flat → safe to take (cap at free zone)
                    can = min(bot3_vol, limit + starting_pos - sell_ordered,
                              free_zone + position)
                else:
                    can = 0
                if can > 0:
                    orders.append(Order("TOMATOES", bot3_bid, -can))
                    sell_ordered += can

        # Phase 2: Passive penny-jump using bot2 reference levels
        effective_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(effective_pos, soft, limit)

        our_bid = min(ref_bid + 1, int(mid) - 1) + skew
        our_ask = max(ref_ask - 1, int(mid) + 1) + skew

        if our_bid >= our_ask:
            our_bid = int(mid) - 1
            our_ask = int(mid) + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("TOMATOES", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("TOMATOES", our_ask, -passive_sell))

        return orders

    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_skew(position: int, soft_limit: int, hard_limit: int) -> int:
        """Skew quotes to reduce inventory. Max 2 ticks at hard limit."""
        if abs(position) <= soft_limit:
            return 0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        magnitude = min(round((excess / max_excess) * 2), 2)
        return -magnitude if position > 0 else magnitude
