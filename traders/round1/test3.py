from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Test 3: Add PEPPER MM cycling when at max position.

    Key insight: Once at 80 PEPPER, we have NO resting PEPPER orders.
    This means we miss 3.5% elastic taker demand per tick on PEPPER.
    By placing passive sells at penny-jump level, we:
    - Earn spread on each fill
    - Then aggressively rebuy to restore drift exposure
    - Net: spread_captured - drift_lost_while_underweight

    OSMIUM: same as a.py
    PEPPER: buy to 80, then cycle sell/rebuy
    """

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
                result[product], td = self._trade_pepper(od, pos, td)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    # ------ OSMIUM: same as a.py ------
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

        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
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

    # ------ PEPPER: buy-and-hold + MM cycling ------
    def _trade_pepper(self, od: OrderDepth, position: int, td: dict):
        """
        Phase 1 (pos < 80): Buy to max ASAP (same as a.py, skip Bot1 when far from full)
        Phase 2 (pos == 80): Place passive sell at penny-jump level to earn spread
        Phase 3 (pos < 80 after sells): Aggressively rebuy to restore drift exposure
        """
        orders = []
        limit = 80
        starting_pos = position

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # Estimate PEPPER FV from bot quotes
        pep_fv = self._estimate_pepper_fv(od, td)
        td["pep_last_fv"] = pep_fv

        if position < 80:
            # REBUY PHASE: Get back to 80 quickly
            remaining = limit - position
            buy_ordered = 0

            # Take all available asks (including Bot 1 - speed is critical)
            if od.sell_orders:
                for ask_price in asks_sorted:
                    vol = -od.sell_orders[ask_price]
                    qty = min(vol, remaining - buy_ordered)
                    if qty > 0:
                        orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                        buy_ordered += qty
                    if buy_ordered >= remaining:
                        break

            # Place aggressive passive bid for remainder
            if buy_ordered < remaining and bids_sorted:
                best_bid = bids_sorted[0]
                orders.append(Order("INTARIAN_PEPPER_ROOT", best_bid + 1, remaining - buy_ordered))
                buy_ordered = remaining

        if position >= 80:
            # MM CYCLING: Sell a chunk passively at premium
            # Use Bot2 inner wall as reference for sell price
            sell_size = 10  # small chunk to minimize drift loss

            if asks_sorted and pep_fv:
                # Find Bot2 ask (vol 8-12)
                bot2_ask = None
                for p in asks_sorted:
                    v = -od.sell_orders[p]
                    if 8 <= v <= 12:
                        bot2_ask = p
                        break

                if bot2_ask:
                    # Penny-jump Bot2 ask: sell at bot2_ask - 1
                    our_sell = bot2_ask - 1
                else:
                    # Fallback: sell at FV + reasonable offset
                    our_sell = int(round(pep_fv)) + 5

                can_sell = limit + starting_pos
                qty = min(sell_size, can_sell)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", our_sell, -qty))

            # Also place a wide bid to catch potential sell takers
            # This earns additional spread when a taker sells into our bid
            if bids_sorted and pep_fv:
                bot2_bid = None
                for p in bids_sorted:
                    v = od.buy_orders[p]
                    if 8 <= v <= 12:
                        bot2_bid = p
                        break

                if bot2_bid:
                    our_buy = bot2_bid + 1
                else:
                    our_buy = int(round(pep_fv)) - 5

                # Can buy: this would go above 80 temporarily...
                # Wait, position limit check: if sum of all buys could push past 80, ALL orders cancelled
                # Position is 80. Any buy order would potentially push to 81+.
                # So we can place buy of 0... which is nothing.
                # We CAN'T place buy orders when at position 80!
                pass

        return orders, td

    def _estimate_pepper_fv(self, od, td):
        """Simple PEPPER FV from bot quotes."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if not bids and not asks:
            return td.get("pep_last_fv")

        # Use inner levels (Bot2: vol 8-12)
        bot2_bids = [p for p in bids if 8 <= od.buy_orders[p] <= 12]
        bot2_asks = [p for p in asks if 8 <= -od.sell_orders[p] <= 12]

        if bot2_bids and bot2_asks:
            return (bot2_bids[0] + bot2_asks[0]) / 2
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 6
        if asks:
            return asks[0] - 6
        return td.get("pep_last_fv")
