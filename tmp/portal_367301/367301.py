# R3 test trader B — same penny-jump as a.py, but doubles the quote size
# (5 -> 10) to stress-test the elastic-rate calibration. If the calibration is
# right, predicted PnL changes per asset are:
#   * VEV_4000: ~2x (mean trade qty 2; capacity was the bottleneck)
#   * VELVETFRUIT: ~1.4x (mean trade qty 6; partial saturation)
#   * HYDROGEL:    ~1.2x (mean trade qty 4; small capacity gain)
#   * Mid VEVs:    ~1.5x (low fill volume, capacity helps a bit)
#
# Logs (printed to portal sandbox stream) once every 100 ticks:
#   "B: t=<ts> <ASSET>=<pos>;<fills_total>;<spread> ..."
# We can diff cumulative fills across log lines to back out per-asset elastic
# rate, and compare against R3_ELASTIC_OVERRIDES in the generator.

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

LOG_EVERY = 100  # tick stride between log lines (10 lines per portal-UI day)


class Trader:
    R3_QUOTE_SIZE = 10  # doubled from a.py's 5
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

        # Cumulative own-trade counts by asset (persists in traderData).
        fills = td.setdefault("fills", {})
        for sym, trades in (state.own_trades or {}).items():
            # own_trades reflects trades since the LAST run() — tally them.
            n = sum(abs(t.quantity) for t in trades if t.timestamp == state.timestamp - 100)
            if n:
                fills[sym] = fills.get(sym, 0) + n

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in self.R3_ACTIVE_ASSETS:
                result[product] = self._trade(product, od, pos)
            else:
                result[product] = []

        # Periodic compact log line — one print/100 ticks keeps log volume
        # tractable (~10 lines/day @ 1k ticks, 100 lines/day @ 10k ticks).
        if state.timestamp % LOG_EVERY == 0:
            parts = []
            for sym in self.R3_ACTIVE_ASSETS:
                pos = state.position.get(sym, 0)
                fc = fills.get(sym, 0)
                od = state.order_depths.get(sym)
                if od and od.buy_orders and od.sell_orders:
                    bb = max(od.buy_orders.keys())
                    ba = min(od.sell_orders.keys())
                    sp = ba - bb
                else:
                    sp = -1
                parts.append(f"{sym[:6]}={pos};{fc};{sp}")
            print(f"B t={state.timestamp} " + " ".join(parts))

        return result, conversions, json.dumps(td)

    def _trade(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
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