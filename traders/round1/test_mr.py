from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    OSMIUM: Mean-Reversion + Market Making combined strategy.

    Key finding from data: OSMIUM FV is mean-reverting to ~10000
    with half-life ~50 ticks (O-U process, theta ≈ 0.015).
    FV std ≈ 4-5, range ≈ ±18.

    Strategy:
    1. Estimate FV from Bot2/Bot1 quotes
    2. Compute deviation from 10000 (the long-term mean)
    3. Set target position proportional to -deviation
    4. Skew MM quotes to build towards target position
    5. Take aggressively when deviation is large (high-confidence reversion)

    PEPPER: Buy-and-hold (same as before).
    """

    LONG_TERM_MEAN = 10000
    MR_THRESHOLD = 8       # max deviation for full position
    MR_AGGRESSION = 2      # take edge threshold when signal is strong

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
            fv = td.get("ash_last_fv")
            if fv is None:
                return orders, td

        td["ash_last_fv"] = fv
        fv_r = int(round(fv))
        starting_pos = position

        # ── Mean reversion signal ──
        deviation = fv - self.LONG_TERM_MEAN
        # Target position: go opposite to deviation
        # When FV > mean: want to be short (negative position)
        # When FV < mean: want to be long (positive position)
        target_pos = int(-limit * max(-1, min(1, deviation / self.MR_THRESHOLD)))

        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Aggressive taking when deviation is large ──
        # When deviation is large, we're more confident about reversion
        # Take with reduced edge threshold
        abs_dev = abs(deviation)

        if abs_dev > 3:
            # Strong signal: take aggressively in reversion direction
            if deviation > 3 and position > target_pos:
                # FV above mean: want to sell → take bids aggressively
                for bid_price in bids_sorted:
                    if bid_price < fv_r - 1:  # need at least 1 edge
                        break
                    vol = od.buy_orders[bid_price]
                    can_sell = limit + starting_pos - sell_ordered
                    if can_sell <= 0:
                        break
                    # Limit sell to not overshoot target
                    max_sell = max(0, starting_pos - target_pos - sell_ordered + buy_ordered)
                    qty = min(vol, can_sell, max_sell)
                    if qty > 0:
                        orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
                        sell_ordered += qty

            elif deviation < -3 and position < target_pos:
                # FV below mean: want to buy → take asks aggressively
                for ask_price in asks_sorted:
                    if ask_price > fv_r + 1:
                        break
                    vol = -od.sell_orders[ask_price]
                    can_buy = limit - starting_pos - buy_ordered
                    if can_buy <= 0:
                        break
                    max_buy = max(0, target_pos - starting_pos - buy_ordered + sell_ordered)
                    qty = min(vol, can_buy, max_buy)
                    if qty > 0:
                        orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
                        buy_ordered += qty

        # ── Also take standard mispriced orders (same as baseline) ──
        for ask_price in asks_sorted:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        for bid_price in bids_sorted:
            if bid_price < fv_r:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # ── Phase 2: Skewed passive quoting ──
        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)

        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        # Skew based on mean reversion signal:
        # When FV > mean (want short): tighten ask, widen bid
        # When FV < mean (want long): tighten bid, widen ask
        skew = 0
        if abs_dev > 2:
            skew = 1 if deviation > 0 else -1  # +1 means tighten ask
        if abs_dev > 5:
            skew = 2 if deviation > 0 else -2

        our_ask_skewed = max(our_ask - max(0, skew), fv_r + 1)
        our_bid_skewed = min(our_bid + max(0, -skew), fv_r - 1)

        if our_bid_skewed >= our_ask_skewed:
            our_bid_skewed = fv_r - 1
            our_ask_skewed = fv_r + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid_skewed, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask_skewed, -passive_sell))

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
