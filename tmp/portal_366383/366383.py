# R3 trader. Round 3 only exposes the new R3 products on the portal — OSMIUM
# and PEPPER are NOT tradeable in R3, so their handlers are intentionally
# absent. Position limits are R3-specific (200 for the spot products, 300
# for each VEV voucher); see calibration/<asset>/calibration.md.

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


HYDROGEL = "HYDROGEL_PACK"           # spot, position limit 200
VELVET = "VELVETFRUIT_EXTRACT"        # spot, position limit 200
# VEV_<strike> = VELVETFRUIT_EXTRACT_VOUCHER (call options on VELVETFRUIT) at
# the listed strike. Each voucher has its own position limit of 300.
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

# Per-product position limits (R3 — confirmed against the portal product page).
LIMITS = {
    HYDROGEL: 200,
    VELVET: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}


class Trader:
    # Penny-jump MM: tighten one tick inside best bid/ask. Skip ticks where the
    # spread is too narrow to extract edge after the tighten.
    R3_QUOTE_SIZE = 5
    R3_TIGHT_SPREAD_THRESHOLD = 2  # require best_ask - best_bid >= 2 to MM
    R3_SOFT_POS_FRAC = 0.6          # tighten one side past this position fraction

    R3_ACTIVE_ASSETS = (HYDROGEL, VELVET, VEV_4000, VEV_4500,
                        VEV_5000, VEV_5100, VEV_5200, VEV_5300,
                        VEV_5400, VEV_5500)
    # VEV_6000 / VEV_6500 are dead options (FV ~ 0, spread = 1) — penny-jump
    # has no room. Listed but excluded from active MM.

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
        """One-size-fits-all penny-jump MM for R3 products.

        Reads the current best bid/ask, posts a tighter bid + tighter ask if the
        spread leaves >= 2 ticks of room. Quote size is fixed at R3_QUOTE_SIZE
        (5) and we tighten one side once we cross R3_SOFT_POS_FRAC * limit to
        bleed inventory back. No state needed — this is a stateless edge grab.
        """
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
        # Don't cross our own quotes if the penny-jump would tie.
        if our_bid >= our_ask:
            return []

        limit = LIMITS.get(product, 200)
        soft_thresh = int(self.R3_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        # Cap quote size by what we can still queue without breaching the limit.
        # Exchange cancels ALL orders on a side if total queued > limit headroom.
        buy_qty = min(self.R3_QUOTE_SIZE, max(0, buy_room))
        sell_qty = min(self.R3_QUOTE_SIZE, max(0, sell_room))

        # Inventory tilt: when long past soft threshold, drop the bid side
        # (don't add to a long); when short past it, drop the ask side.
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