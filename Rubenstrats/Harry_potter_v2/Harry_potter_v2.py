"""Harry_potter_v2 — R3 "Gloves Off" penny-jump MM.

v1 shipped a BS vol-arb on VEVs and lost -998 on vouchers (portal 367534).
The vouchers MTM at the bot's BS price, so "buy cheap vol" doesn't turn into
PnL. v2 drops all BS/take-on-cheap-vol logic and does pure penny-jump MM.

MC at 10k ticks, 100 sessions (calibrated sim):
  v1 (BS + vol-arb) : mean 8.6k, 5% -3.0k
  a.py size=5       : mean 11.7k
  b.py size=10      : mean 13.2k
  v2 size=15        : mean 13.3k  <-- shipping

Full write-up in README.md.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Tuple
import json


HYDROGEL = "HYDROGEL_PACK"
VELVETFRUIT = "VELVETFRUIT_EXTRACT"
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

LIMITS: Dict[str, int] = {
    HYDROGEL: 200,
    VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

ACTIVE = (HYDROGEL, VELVETFRUIT,
          VEV_4000, VEV_4500, VEV_5000, VEV_5100,
          VEV_5200, VEV_5300, VEV_5400, VEV_5500)
# VEV_6000 / VEV_6500 are dead (FV ~ 0, spread = 1) -- skipped.


class Trader:
    # Class attrs so tweaks don't require forking the whole file.
    QUOTE_SIZE = 15
    TIGHT_SPREAD_MIN = 2
    SOFT_POS_FRAC = 0.6

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in ACTIVE:
                result[product] = self._trade(product, od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    def _trade(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []

        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.TIGHT_SPREAD_MIN:
            return []

        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        limit = LIMITS[product]
        soft_thresh = int(self.SOFT_POS_FRAC * limit)

        # Worst-case-all-fill limit check uses STARTING position. The exchange
        # cancels ALL orders on a side if sum of outstanding orders on that
        # side > limit - starting_position.
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(self.QUOTE_SIZE, max(0, buy_room))
        sell_qty = min(self.QUOTE_SIZE, max(0, sell_room))

        # Hard inventory cutoff outperforms "soft skew" in MC because the
        # penny-jump's edge comes from being priority-one-tick-inside the bot.
        # Stepping back to the best price drops priority and kills fills.
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
