from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Mix: Linear Utility OSMIUM + c.py PEPPER.

    OSMIUM: Filtered-mid FV (vol >= 10 = market maker levels). Three-
    phase Take/Clear/Make. Penny/join with disregard/join zones. Soft
    position limit at 40. Adverse volume filter on taking.

    PEPPER: Never buy Bot 1 (from c.py).
    """

    LIMIT = 80
    TAKE_WIDTH = 1
    ADVERSE_VOL = 9
    DISREGARD_EDGE = 1
    JOIN_EDGE = 4
    DEFAULT_EDGE = 7
    SOFT_POS = 40

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
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                result[product] = self._trade_osmium(od, pos)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _filtered_mid(self, od):
        """FV from market-maker levels only (vol >= 10)."""
        fb = [p for p in od.buy_orders if od.buy_orders[p] >= 10]
        fa = [p for p in od.sell_orders if -od.sell_orders[p] >= 10]
        mb = max(fb) if fb else (max(od.buy_orders) if od.buy_orders else None)
        ma = min(fa) if fa else (min(od.sell_orders) if od.sell_orders else None)
        if mb is not None and ma is not None:
            return (mb + ma) / 2
        if mb is not None:
            return mb + 8
        if ma is not None:
            return ma - 8
        return None

    def _trade_osmium(self, od: OrderDepth, position: int):
        orders = []
        fv = self._filtered_mid(od)
        if fv is None:
            return orders
        fv_r = int(round(fv))

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: TAKE with adverse volume filter ──
        for ap in sorted(od.sell_orders.keys()):
            if ap > fv_r - self.TAKE_WIDTH:
                break
            av = -od.sell_orders[ap]
            if av > self.ADVERSE_VOL:
                continue
            can = self.LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(av, can)
            orders.append(Order("ASH_COATED_OSMIUM", ap, qty))
            buy_ordered += qty

        for bp in sorted(od.buy_orders.keys(), reverse=True):
            if bp < fv_r + self.TAKE_WIDTH:
                break
            bv = od.buy_orders[bp]
            if bv > self.ADVERSE_VOL:
                continue
            can = self.LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(bv, can)
            orders.append(Order("ASH_COATED_OSMIUM", bp, -qty))
            sell_ordered += qty

        # ── Phase 2: CLEAR at FV ──
        eff = starting_pos + buy_ordered - sell_ordered
        if eff > 0:
            bv = od.buy_orders.get(fv_r, 0)
            if bv > 0:
                can = self.LIMIT + starting_pos - sell_ordered
                cq = min(bv, eff, can)
                if cq > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", fv_r, -cq))
                    sell_ordered += cq
        elif eff < 0:
            av = -od.sell_orders.get(fv_r, 0)
            if av > 0:
                can = self.LIMIT - starting_pos - buy_ordered
                cq = min(av, abs(eff), can)
                if cq > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", fv_r, cq))
                    buy_ordered += cq

        # ── Phase 3: MAKE with penny/join zones ──
        bids_s = sorted(od.buy_orders.keys(), reverse=True)
        asks_s = sorted(od.sell_orders.keys())

        asks_above = [p for p in asks_s if p > fv_r + self.DISREGARD_EDGE]
        if asks_above:
            ba = asks_above[0]
            our_ask = ba if abs(ba - fv_r) <= self.JOIN_EDGE else ba - 1
        else:
            our_ask = fv_r + self.DEFAULT_EDGE

        bids_below = [p for p in bids_s if p < fv_r - self.DISREGARD_EDGE]
        if bids_below:
            bb = bids_below[0]
            our_bid = bb if abs(fv_r - bb) <= self.JOIN_EDGE else bb + 1
        else:
            our_bid = fv_r - self.DEFAULT_EDGE

        # Soft position limit skew
        eff = starting_pos + buy_ordered - sell_ordered
        if eff > self.SOFT_POS:
            our_ask -= 1
        elif eff < -self.SOFT_POS:
            our_bid += 1

        our_ask = max(our_ask, fv_r + 1)
        our_bid = min(our_bid, fv_r - 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        pb = self.LIMIT - starting_pos - buy_ordered
        ps = self.LIMIT + starting_pos - sell_ordered
        if pb > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, pb))
        if ps > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -ps))

        return orders

    def _trade_pepper(self, od: OrderDepth, position: int):
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if vol > 15:
                    continue
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ap, qty))
                    remaining -= qty
                if remaining <= 0:
                    break
        if remaining > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", bb + 1, remaining))
        return orders
