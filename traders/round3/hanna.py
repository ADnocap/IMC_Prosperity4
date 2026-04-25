# Hanna — Mark Hanna's "first rule of Wall Street: nobody knows if a stock is
# going up, down, sideways or in fucking circles." Hypothesis test:
# is the only thing wrong with a.py the quote size?
#
# Identical logic to traders/round3/a.py, single change: R3_QUOTE_SIZE 5 -> 30.
# Top P3 teams sized to the full position limit. This bumps us 6x without
# adding any new logic, to isolate the size-scaling component of the gap.

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
VEV_4000 = "VEV_4000"
VEV_4500 = "VEV_4500"
VEV_5000 = "VEV_5000"
VEV_5100 = "VEV_5100"
VEV_5200 = "VEV_5200"
VEV_5300 = "VEV_5300"
VEV_5400 = "VEV_5400"
VEV_5500 = "VEV_5500"
VEV_6000 = "VEV_6000"
VEV_6500 = "VEV_6500"

LIMITS = {
    HYDROGEL: 200,
    VELVET: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}


class Trader:
    R3_QUOTE_SIZE = 30
    R3_TIGHT_SPREAD_THRESHOLD = 2
    R3_SOFT_POS_FRAC = 0.6

    R3_ACTIVE_ASSETS = (HYDROGEL, VELVET, VEV_4000, VEV_4500,
                        VEV_5000, VEV_5100, VEV_5200, VEV_5300,
                        VEV_5400, VEV_5500)

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td: dict = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in self.R3_ACTIVE_ASSETS:
                result[product] = self._trade_r3_generic(product, od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _trade_r3_generic(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []

        best_bid = bids[0]
        best_ask = asks[0]
        spread = best_ask - best_bid
        if spread < self.R3_TIGHT_SPREAD_THRESHOLD:
            return []

        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        limit = LIMITS.get(product, 200)
        soft_thresh = int(self.R3_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(self.R3_QUOTE_SIZE, max(0, buy_room))
        sell_qty = min(self.R3_QUOTE_SIZE, max(0, sell_room))

        if pos >= soft_thresh:
            buy_qty = 0
        elif pos <= -soft_thresh:
            sell_qty = 0

        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(product, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(product, our_ask, -sell_qty))
        return orders
