from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Mix: Frankfurt OSMIUM + c.py PEPPER.

    OSMIUM: Wall-mid FV (robust, no Bot 3 confusion possible).
    Frankfurt overbid quoting (penny best level below FV, handles
    competing players on portal). No skew.

    PEPPER: Never buy Bot 1 (from c.py).
    """

    LIMIT = 80

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

    def _trade_osmium(self, od: OrderDepth, position: int):
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders

        # ── FV: Wall-mid (Frankfurt Hedgehogs, 2nd P3) ──
        bid_wall = min(od.buy_orders.keys())
        ask_wall = max(od.sell_orders.keys())
        wall_mid = (bid_wall + ask_wall) / 2
        wm = int(round(wall_mid))

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── TAKE: buy below wall_mid-1, sell above wall_mid+1 ──
        for ap in sorted(od.sell_orders.keys()):
            if ap > wall_mid - 1:
                break
            vol = -od.sell_orders[ap]
            can = self.LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order("ASH_COATED_OSMIUM", ap, qty))
            buy_ordered += qty

        for bp in sorted(od.buy_orders.keys(), reverse=True):
            if bp < wall_mid + 1:
                break
            vol = od.buy_orders[bp]
            can = self.LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order("ASH_COATED_OSMIUM", bp, -qty))
            sell_ordered += qty

        # ── CLEAR: flatten at wall_mid (0 edge) ──
        eff = starting_pos + buy_ordered - sell_ordered
        if eff < 0:
            for ap in sorted(od.sell_orders.keys()):
                if ap > wall_mid:
                    break
                vol = -od.sell_orders[ap]
                can = self.LIMIT - starting_pos - buy_ordered
                cq = min(vol, abs(eff), can)
                if cq > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", ap, cq))
                    buy_ordered += cq
                    eff += cq
        elif eff > 0:
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if bp < wall_mid:
                    break
                vol = od.buy_orders[bp]
                can = self.LIMIT + starting_pos - sell_ordered
                cq = min(vol, eff, can)
                if cq > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", bp, -cq))
                    sell_ordered += cq
                    eff -= cq

        # ── MAKE: Frankfurt overbid — penny best visible level ──
        our_bid = bid_wall + 1
        for bp in sorted(od.buy_orders.keys(), reverse=True):
            if bp >= wall_mid:
                continue
            bv = od.buy_orders[bp]
            if bv > 1 and bp + 1 < wall_mid:
                our_bid = max(our_bid, bp + 1)
            else:
                our_bid = max(our_bid, bp)
            break

        our_ask = ask_wall - 1
        for ap in sorted(od.sell_orders.keys()):
            if ap <= wall_mid:
                continue
            av = -od.sell_orders[ap]
            if av > 1 and ap - 1 > wall_mid:
                our_ask = min(our_ask, ap - 1)
            else:
                our_ask = min(our_ask, ap)
            break

        our_bid = min(our_bid, wm - 1)
        our_ask = max(our_ask, wm + 1)
        if our_bid >= our_ask:
            our_bid = wm - 1
            our_ask = wm + 1

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
