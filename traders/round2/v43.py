"""v43 — pure directional mean-reversion on OSMIUM.

Drops MM entirely. When FV is far from 10000 we aggressively build a position
betting on reversion; when FV returns to the band we flatten. PEPPER logic is
unchanged from v20 (at its ceiling already).

Entry/exit thresholds and target position are parameterized for grid search.

Design tradeoffs:
  * Aggressive takes cross Bot2's spread (≈8/unit), so gross reversion must
    exceed 8 per unit for a winning round trip. OSMIUM half-life ≈ 90, σ ≈ 2.5
    stationary. Expect this to break even at best; it is a *directional* bet
    that disproves (or confirms) the claim that MM is the only viable shape.
"""
from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80


class Trader:
    # Pure-directional OSMIUM params
    ACO_ENTRY = 4        # center_dist threshold to start building toward target
    ACO_MAX_DIST = 10    # at this dist, target full LIMIT
    ACO_EXIT_BAND = 1    # when |center_dist| <= this, flatten

    # PEPPER (unchanged from v20)
    IPR_ASK_OFFSET_1 = 8
    IPR_ASK_OFFSET_2 = 9
    IPR_ASK_THRESH_1 = 60
    IPR_ASK_THRESH_2 = 75
    IPR_ASK_QTY_1 = 10
    IPR_ASK_QTY_2 = 15

    MAF_BID = 0

    def bid(self):
        return self.MAF_BID

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == OSMIUM:
                orders, td = self._trade_osmium(od, pos, td)
            elif product == PEPPER:
                orders, td = self._trade_ipr(od, pos, td)
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(td)

    # ACO ============================================================

    def _fv(self, od, bids, asks, td):
        if not bids and not asks:
            return td.get("fv")
        if bids and asks and (asks[0] - bids[0]) == 16:
            bv1 = od.buy_orders[bids[0]]
            av1 = -od.sell_orders[asks[0]]
            if 10 <= bv1 <= 15 and 10 <= av1 <= 15:
                return (bids[0] + asks[0]) / 2
        bot1_bid = next((p for p in bids if 20 <= od.buy_orders[p] <= 30), None)
        bot1_ask = next((p for p in asks if 20 <= -od.sell_orders[p] <= 30), None)
        if bot1_bid is not None and bot1_ask is not None:
            return (bot1_bid + bot1_ask) / 2
        prev_fv = td.get("fv")
        if bot1_bid is not None and prev_fv is not None:
            return 0.3 * (bot1_bid + 10.5) + 0.7 * prev_fv
        if bot1_ask is not None and prev_fv is not None:
            return 0.3 * (bot1_ask - 10.5) + 0.7 * prev_fv
        if prev_fv is not None:
            return prev_fv
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        return asks[0] - 10.5

    def _target_position(self, center_dist):
        """Linear interpolation: dist=ENTRY -> partial target; dist=MAX -> full."""
        if abs(center_dist) <= self.ACO_EXIT_BAND:
            return 0
        if abs(center_dist) < self.ACO_ENTRY:
            return None  # no change, hold current
        sign = -1 if center_dist > 0 else 1  # long when FV low
        frac = min(1.0, (abs(center_dist) - self.ACO_ENTRY + 1) /
                         (self.ACO_MAX_DIST - self.ACO_ENTRY + 1))
        return int(sign * LIMIT * frac)

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td
        fv_r = int(round(fv))
        td["fv"] = fv

        center_dist = fv_r - 10000
        target = self._target_position(center_dist)
        if target is None:
            target = position  # hold

        delta = target - position

        if delta > 0:
            # Need to buy: take asks from best outward, up to delta
            need = delta
            cap_buy = LIMIT - position
            need = min(need, cap_buy)
            for ap in asks:
                if need <= 0:
                    break
                vol = -od.sell_orders[ap]
                qty = min(vol, need)
                if qty > 0:
                    orders.append(Order(OSMIUM, ap, qty))
                    need -= qty
        elif delta < 0:
            # Need to sell: hit bids from best outward, up to -delta
            need = -delta
            cap_sell = LIMIT + position
            need = min(need, cap_sell)
            for bp in bids:
                if need <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, need)
                if qty > 0:
                    orders.append(Order(OSMIUM, bp, -qty))
                    need -= qty

        return orders, td

    # IPR ============================================================

    def _estimate_ipr_fv(self, od: OrderDepth, td: dict) -> float:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 8 <= v <= 12:
                estimates.append((p + 6.5, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p + 9.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 8 <= v <= 12:
                estimates.append((p - 6.5, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p - 9.5, 1.0))
        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids and asks:
            fv = (bids[0] + asks[0]) / 2
        else:
            fv = td.get("ipr_fv", 10000.0)
        td["ipr_fv"] = fv
        return fv

    def _trade_ipr(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position
        fv = self._estimate_ipr_fv(od, td)
        fv_r = int(round(fv))
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        for ask_price in asks_sorted:
            if remaining <= 0:
                break
            vol = -od.sell_orders[ask_price]
            if vol > 15:
                continue
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order(PEPPER, ask_price, qty))
                remaining -= qty
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = fv_r - 6
            orders.append(Order(PEPPER, our_bid, remaining))
        sell_room = LIMIT + position
        if position >= self.IPR_ASK_THRESH_1 and sell_room > 0:
            ask_qty_1 = min(self.IPR_ASK_QTY_1, sell_room)
            if ask_qty_1 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_1, -ask_qty_1))
                sell_room -= ask_qty_1
        if position >= self.IPR_ASK_THRESH_2 and sell_room > 0:
            ask_qty_2 = min(self.IPR_ASK_QTY_2, sell_room)
            if ask_qty_2 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_2, -ask_qty_2))
        return orders, td
