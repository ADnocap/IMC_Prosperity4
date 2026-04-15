from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    OSMIUM: Penny-jump MM with minimal mean-reversion overlay.

    Data analysis proves OSMIUM is mean-reverting to ~10000:
    - Variance ratio VR(10) = 0.32 (random walk = 1.0)
    - FV bounded ±18 vs ±90 expected for random walk
    - FV std = 4.5 (random walk would give 31)

    Strategy: keep penny-jump MM unchanged but add TWO small modifications:
    1. RESERVATION PRICE SHIFT: When deviation is large (>5), shift both
       quotes by 1 tick in the reversion direction. This costs 1 edge on the
       new "tight" side but biases fills towards building the right position.
    2. MR TAKING: When deviation > 5, expand the taking threshold by 1 tick
       in the reversion direction to opportunistically build position.

    These changes are conservative - they activate <20% of the time and
    cost only 1 tick of edge when they do.

    PEPPER: Buy-and-hold (same as always).
    """

    LONG_TERM_MEAN = 10000
    MR_ACTIVATION = 5  # deviation threshold to activate MR overlay

    PARAMS = {
        "ASH_COATED_OSMIUM": {"limit": 80},
        "INTARIAN_PEPPER_ROOT": {"limit": 80},
    }

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
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == "ASH_COATED_OSMIUM":
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        limit = 80

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_osmium_fv(od, td)
        if fv is None:
            return orders, td

        td["ash_last_fv"] = fv
        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Mean reversion signal
        deviation = fv - self.LONG_TERM_MEAN
        abs_dev = abs(deviation)

        # ── Phase 1: Taking with MR bias ──
        # Base: take at fv_r (same as a.py)
        # MR enhancement: when deviation large, widen by 1 in reversion direction
        buy_thresh = fv_r
        sell_thresh = fv_r

        if abs_dev >= self.MR_ACTIVATION:
            if deviation < 0:
                # FV below mean → want to buy → widen buy threshold
                buy_thresh = fv_r + 1
            else:
                # FV above mean → want to sell → widen sell threshold
                sell_thresh = fv_r - 1

        for ask_price in asks_sorted:
            if ask_price > buy_thresh:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        for bid_price in bids_sorted:
            if bid_price < sell_thresh:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # ── Phase 2: Passive penny-jump with reservation shift ──
        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)

        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        # MR overlay: shift reservation price by 1 when deviation is large
        # This makes one side tighter (1 less edge) and the other wider (1 more edge)
        # Net effect: biases fills toward building position in reversion direction
        if abs_dev >= self.MR_ACTIVATION:
            if deviation > 0:
                # FV above mean → want to sell → tighten ask by 1
                our_ask = max(our_ask - 1, fv_r + 1)
            else:
                # FV below mean → want to buy → tighten bid by 1
                our_bid = min(our_bid + 1, fv_r - 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders, td

    def _estimate_osmium_fv(self, od: OrderDepth, td: dict):
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
            if 10 <= vol <= 15:
                if raw_mid - price >= 5:
                    estimates.append((price + 8, 2.0))
            elif vol >= 20:
                estimates.append((price + 10.5, 1.0))
        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                if price - raw_mid >= 5:
                    estimates.append((price - 8, 2.0))
            elif vol >= 20:
                estimates.append((price - 10.5, 1.0))

        if estimates:
            total_weight = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / total_weight

        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        if asks:
            return asks[0] - 10.5
        return td.get("ash_last_fv")

    @staticmethod
    def _find_wall_bid(bids_sorted, fv_r):
        if len(bids_sorted) >= 3:
            return bids_sorted[1]
        if len(bids_sorted) >= 2:
            if fv_r - bids_sorted[0] >= 5:
                return bids_sorted[0]
            else:
                return bids_sorted[1]
        if bids_sorted:
            return bids_sorted[0]
        return fv_r - 8

    @staticmethod
    def _find_wall_ask(asks_sorted, fv_r):
        if len(asks_sorted) >= 3:
            return asks_sorted[1]
        if len(asks_sorted) >= 2:
            if asks_sorted[0] - fv_r >= 5:
                return asks_sorted[0]
            else:
                return asks_sorted[1]
        if asks_sorted:
            return asks_sorted[0]
        return fv_r + 8

    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        orders = []
        limit = 80
        remaining = limit - position
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
