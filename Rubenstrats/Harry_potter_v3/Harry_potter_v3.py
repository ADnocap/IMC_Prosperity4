"""Harry_potter_v3 — OBI-tilted penny-jump MM.

v2 (pure penny-jump) got +1,469 on portal. Signal analysis on the 3-day
R3 CSVs found L1 OBI is the dominant predictor of next-tick mid returns:
  VEV_4000    corr = +0.48
  VEV_4500    corr = +0.40
  VELVETFRUIT corr = +0.33
  HYDROGEL    corr = +0.32
  VEV_5000..5500: corr +0.20 to +0.30

v3 keeps v2's penny-jump base and adds asymmetric quote sizing based on
OBI_L1 = (bid1_vol - ask1_vol) / (bid1_vol + ask1_vol). When OBI tilts
one way, we expect mid to drift that way, so we accumulate more on the
winning side and less on the losing side. Prices stay at best_bid+1 /
best_ask-1 (same as v2) — only sizes change.

Take logic (cross the spread on extreme OBI) was considered and rejected:
expected 1-tick mid move at OBI=+0.95 is ~1 unit on VEV_4000 vs half-
spread of ~10, so take is -9 EV per contract. MM tilt is the clean edge.

Size regimes per |OBI|:
  < 0.2 : base on both sides (15 / 15)
  0.2-0.6 : mild tilt (20 / 10)
  0.6-0.9 : strong tilt (25 / 5)
  >= 0.9 : extreme tilt (30 / 0)

Mean-reversion overlay on OTM VEVs (5400, 5500, ret_lag_1 corr -0.23)
is deferred — would need prev-mid state. Add in v4 if v3 is promising.
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


class Trader:
    # Base penny-jump parameters (same as v2).
    BASE_SIZE = 15
    TIGHT_SPREAD_MIN = 2
    SOFT_POS_FRAC = 0.6

    # OBI tilt thresholds (absolute value). Tuned on CSV replay — lower
    # onset threshold (0.1) captures the typical OBI distribution, which
    # rarely reaches extreme values in the historical data.
    OBI_SKEW_1 = 0.1   # start tilting sizes above this
    OBI_SKEW_2 = 0.4   # stronger tilt
    OBI_SKEW_3 = 0.7   # extreme tilt

    # Size pair at each regime: (big, small).
    # big = side aligned with signal, small = opposite.
    # Extreme keeps a small (3) opposite-side quote rather than skipping
    # entirely — occasional mispriced taker on the wrong side still gives
    # us free edge.
    SIZES_MILD = (22, 8)
    SIZES_STRONG = (30, 2)
    SIZES_EXTREME = (40, 3)

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

        # Compute L1 OBI from top-of-book volumes.
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total

        buy_size, sell_size = self._obi_sizes(obi)

        limit = LIMITS[product]
        soft_thresh = int(self.SOFT_POS_FRAC * limit)

        # Worst-case-all-fill: per-side order sum must fit in (limit ± pos).
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(buy_size, max(0, buy_room))
        sell_qty = min(sell_size, max(0, sell_room))

        # Hard inventory cutoff overrides OBI signal. Risk > signal at extremes.
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

    def _obi_sizes(self, obi: float) -> Tuple[int, int]:
        abs_obi = abs(obi)
        if abs_obi < self.OBI_SKEW_1:
            return (self.BASE_SIZE, self.BASE_SIZE)
        if abs_obi < self.OBI_SKEW_2:
            big, small = self.SIZES_MILD
        elif abs_obi < self.OBI_SKEW_3:
            big, small = self.SIZES_STRONG
        else:
            big, small = self.SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)
