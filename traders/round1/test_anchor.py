from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    OSMIUM: Mean-Anchored Market Making (Ahuja et al. 2016 insight)

    Instead of penny-jumping around CURRENT FV (which tracks the price),
    anchor quotes to the LONG-TERM MEAN (10000). The mean reversion
    guarantees fills come to us as price oscillates through our quotes.

    When FV > 10000: our ask is closer to FV → more sell fills → builds
    short position → profits from reversion back to 10000.
    When FV < 10000: our bid is closer → more buy fills → builds long
    → profits from reversion up.

    The edge per fill varies (7 when FV=mean, lower when FV deviates)
    but the position drift is systematically profitable via MR.

    Key: still use penny-jump LOGIC but reference the MEAN not current FV
    for the quote center. Take phase still tracks current FV for mispricings.

    PEPPER: Buy-and-hold (unchanged).
    """

    MEAN = 10000
    QUOTE_EDGE = 7  # distance from MEAN to our quotes

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

        fv = self._estimate_fv(od, td)
        if fv is None:
            fv = td.get("fv")
            if fv is None:
                return orders, td
        td["fv"] = fv
        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Take mispriced orders (track current FV) ──
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

        # ── Phase 2: Mean-anchored passive quoting ──
        # Quote at MEAN ± EDGE, but ensure we're still the best price
        # (ahead of Bot2 which is at FV ± 8)
        our_bid = self.MEAN - self.QUOTE_EDGE
        our_ask = self.MEAN + self.QUOTE_EDGE

        # Safety: don't quote ABOVE current FV for bid or BELOW for ask
        # (that would be crossing the true spread)
        our_bid = min(our_bid, fv_r - 1)
        our_ask = max(our_ask, fv_r + 1)

        # Also ensure we're ahead of Bot2 (penny-jump if needed)
        # When mean-anchored price would be BEHIND Bot2, fall back to penny-jump
        bot2_bid = self._find_bot2_bid(bids_sorted)
        bot2_ask = self._find_bot2_ask(asks_sorted)

        if bot2_bid is not None and our_bid <= bot2_bid:
            our_bid = bot2_bid + 1  # penny-jump instead
        if bot2_ask is not None and our_ask >= bot2_ask:
            our_ask = bot2_ask - 1  # penny-jump instead

        our_bid = min(our_bid, fv_r - 1)
        our_ask = max(our_ask, fv_r + 1)

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

    def _find_bot2_bid(self, bids_sorted):
        """Find Bot2 bid (vol 10-15, should be at FV-8)."""
        for p in bids_sorted:
            # Can't access od here, approximate from sorted list
            # Bot2 is typically the highest bid with vol 10-15
            return p  # best bid is either Bot2 or Bot3
        return None

    def _find_bot2_ask(self, asks_sorted):
        """Find Bot2 ask."""
        for p in asks_sorted:
            return p
        return None

    def _estimate_fv(self, od, td):
        """Same Bot1-anchored FV estimation as fixed a.py."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids and not asks:
            return td.get("fv")

        bot1_estimates = []
        for price in bids:
            vol = od.buy_orders[price]
            if vol >= 20:
                bot1_estimates.append(price + 10.5)
        for price in asks:
            vol = -od.sell_orders[price]
            if vol >= 20:
                bot1_estimates.append(price - 10.5)
        bot1_fv = sum(bot1_estimates) / len(bot1_estimates) if bot1_estimates else None

        ref_fv = bot1_fv or td.get("fv")
        if ref_fv is None:
            if bids and asks:
                ref_fv = (bids[0] + asks[0]) / 2
            elif bids:
                ref_fv = bids[0] + 8
            else:
                ref_fv = asks[0] - 8

        estimates = []
        for price in bids:
            vol = od.buy_orders[price]
            if 10 <= vol <= 15:
                expected = ref_fv - 8
                if abs(price - expected) <= 3:
                    estimates.append((price + 8, 2.0))
            elif vol >= 20:
                estimates.append((price + 10.5, 1.0))
        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                expected = ref_fv + 8
                if abs(price - expected) <= 3:
                    estimates.append((price - 8, 2.0))
            elif vol >= 20:
                estimates.append((price - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / tw
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        if asks:
            return asks[0] - 10.5
        return td.get("fv")

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
