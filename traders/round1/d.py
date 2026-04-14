from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Linear Utility approach (2nd place P2).

    OSMIUM: Filtered-mid FV (only orders with vol >= 10). Three-phase
    Take/Clear/Make. Adverse volume filter on taking (only take small
    orders). Penny/join with disregard/join zones. Soft position limit
    inventory management.

    PEPPER: Same selective buy-and-hold.
    """

    LIMIT = 80
    # Linear Utility params adapted for our bot structure
    TAKE_WIDTH = 1       # take at FV ± 1 (positive edge)
    ADVERSE_VOL = 9      # only take orders with vol <= 9 (skip Bot 2)
    DISREGARD_EDGE = 1   # ignore levels within 1 of FV
    JOIN_EDGE = 4        # join levels within 4 of FV
    DEFAULT_EDGE = 7     # default spread if no levels to penny
    SOFT_POS = 40        # start managing position at 40

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
                result[product] = self._trade_osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _filtered_mid(self, od):
        """FV from filtered-mid: only vol >= 10 levels (market maker walls)."""
        filtered_bids = [p for p in od.buy_orders if od.buy_orders[p] >= 10]
        filtered_asks = [p for p in od.sell_orders if -od.sell_orders[p] >= 10]

        mm_bid = max(filtered_bids) if filtered_bids else (max(od.buy_orders) if od.buy_orders else None)
        mm_ask = min(filtered_asks) if filtered_asks else (min(od.sell_orders) if od.sell_orders else None)

        if mm_bid is not None and mm_ask is not None:
            return (mm_bid + mm_ask) / 2
        if mm_bid is not None:
            return mm_bid + 8
        if mm_ask is not None:
            return mm_ask - 8
        return None

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []

        fv = self._filtered_mid(od)
        if fv is None:
            return orders

        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: TAKE with adverse volume filter ──
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fv_r - self.TAKE_WIDTH:
                break
            ask_vol = -od.sell_orders[ask_price]
            if ask_vol > self.ADVERSE_VOL:
                continue  # skip large orders (market maker walls)
            can_buy = self.LIMIT - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(ask_vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fv_r + self.TAKE_WIDTH:
                break
            bid_vol = od.buy_orders[bid_price]
            if bid_vol > self.ADVERSE_VOL:
                continue
            can_sell = self.LIMIT + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(bid_vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # ── Phase 2: CLEAR at FV ──
        effective_pos = starting_pos + buy_ordered - sell_ordered
        if effective_pos > 0:
            fair_for_sell = fv_r
            vol_at_fair = od.buy_orders.get(fair_for_sell, 0)
            if vol_at_fair > 0:
                can_sell = self.LIMIT + starting_pos - sell_ordered
                clear = min(vol_at_fair, effective_pos, can_sell)
                if clear > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", fair_for_sell, -clear))
                    sell_ordered += clear
        elif effective_pos < 0:
            fair_for_buy = fv_r
            vol_at_fair = -od.sell_orders.get(fair_for_buy, 0)
            if vol_at_fair > 0:
                can_buy = self.LIMIT - starting_pos - buy_ordered
                clear = min(vol_at_fair, abs(effective_pos), can_buy)
                if clear > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", fair_for_buy, clear))
                    buy_ordered += clear

        # ── Phase 3: MAKE with penny/join/default zones ──
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # Find best ask above FV outside disregard zone
        asks_above = [p for p in asks_sorted if p > fv_r + self.DISREGARD_EDGE]
        if asks_above:
            best_ask_above = asks_above[0]
            if abs(best_ask_above - fv_r) <= self.JOIN_EDGE:
                our_ask = best_ask_above     # JOIN
            else:
                our_ask = best_ask_above - 1  # PENNY
        else:
            our_ask = fv_r + self.DEFAULT_EDGE

        # Find best bid below FV outside disregard zone
        bids_below = [p for p in bids_sorted if p < fv_r - self.DISREGARD_EDGE]
        if bids_below:
            best_bid_below = bids_below[0]
            if abs(fv_r - best_bid_below) <= self.JOIN_EDGE:
                our_bid = best_bid_below     # JOIN
            else:
                our_bid = best_bid_below + 1  # PENNY
        else:
            our_bid = fv_r - self.DEFAULT_EDGE

        # Soft position limit: tighten the reducing side
        effective_pos = starting_pos + buy_ordered - sell_ordered
        if effective_pos > self.SOFT_POS:
            our_ask -= 1  # make ask more attractive
        elif effective_pos < -self.SOFT_POS:
            our_bid += 1  # make bid more attractive

        our_ask = max(our_ask, fv_r + 1)
        our_bid = min(our_bid, fv_r - 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        passive_buy = self.LIMIT - starting_pos - buy_ordered
        passive_sell = self.LIMIT + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders

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
