from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Ultra-simple fixed-spread approach (inspired by JackRao123, 19th P3).

    OSMIUM: Volume-based FV. Fixed spread at FV ± K. Position-adjusted
    sizing (natural skew). No taking phase — pure passive quoting.
    Simple = fewer edge cases = more robust.

    PEPPER: Same selective buy-and-hold.
    """

    LIMIT = 80
    K = 7  # half-spread

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
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _estimate_fv(self, od, td):
        """Volume-based FV with Bot 3 filtering (same as a.py)."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids and not asks:
            return td.get("ash_last_fv")

        if bids and asks:
            raw_mid = (bids[0] + asks[0]) / 2
        elif bids:
            last = td.get("ash_last_fv")
            raw_mid = last if last is not None else bids[0] + 8
        else:
            last = td.get("ash_last_fv")
            raw_mid = last if last is not None else asks[0] - 8

        estimates = []
        for price in bids:
            vol = od.buy_orders[price]
            if 10 <= vol <= 15 and raw_mid - price >= 5:
                estimates.append((price + 8, 2.0))
            elif vol >= 20:
                estimates.append((price + 10.5, 1.0))
        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15 and price - raw_mid >= 5:
                estimates.append((price - 8, 2.0))
            elif vol >= 20:
                estimates.append((price - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / tw
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        return td.get("ash_last_fv")

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        fv = self._estimate_fv(od, td)
        if fv is None:
            return orders, td
        td["ash_last_fv"] = fv
        fv_r = int(round(fv))

        # Phase 1: Take crossing quotes (same as a.py — proven optimal)
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        for ask_price in sorted(od.sell_orders.keys()) if od.sell_orders else []:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = self.LIMIT - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []:
            if bid_price < fv_r:
                break
            vol = od.buy_orders[bid_price]
            can_sell = self.LIMIT + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # Phase 2: Fixed spread quoting — FV ± K
        bid_price = fv_r - self.K
        ask_price = fv_r + self.K

        passive_buy = self.LIMIT - starting_pos - buy_ordered
        passive_sell = self.LIMIT + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, -passive_sell))

        return orders, td

    def _trade_pepper(self, od: OrderDepth, position: int):
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders
        if od.sell_orders:
            for ask_price in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ask_price]
                if remaining > 20 and vol > 15:
                    continue
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                    remaining -= qty
                if remaining <= 0:
                    break
        if remaining > 0 and od.buy_orders:
            best_bid = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", best_bid + 1, remaining))
        return orders
