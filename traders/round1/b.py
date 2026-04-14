from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Round 1 strategy — optimized for non-linear scaling on long sessions.

    OSMIUM: Market making on random walk (σ=0.312). Volume-based FV estimation,
    unconditional taking at FV, penny-jump MM with inventory skew.

    PEPPER: Drift exploitation (+0.1/tick) PLUS active market making at max
    position. Capture spread by selling small chunks and rebuying, while
    maintaining near-max drift exposure. On 1,000-tick test: drift dominates
    (~8K). On 10,000-tick eval: drift (80K) + MM cycling (~15K) = ~95K+.
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
            "soft_limit": 50,
        },
        "INTARIAN_PEPPER_ROOT": {
            "limit": 80,
            "sell_chunk": 10,  # units to offer for sale when at max position
        },
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

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM — random walk market making
    # ------------------------------------------------------------------
    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        p = self.PARAMS["ASH_COATED_OSMIUM"]
        limit = p["limit"]
        soft = p["soft_limit"]

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_osmium_fv(od, td)
        td["ash_last_fv"] = fv
        if fv is None:
            return orders, td

        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Take mispriced levels ──
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

        # ── Phase 2: Passive penny-jump quoting ──
        bot3_on_bid = len(bids_sorted) >= 3
        bot3_on_ask = len(asks_sorted) >= 3
        ref_bid = bids_sorted[1] if bot3_on_bid else (bids_sorted[0] if bids_sorted else fv_r - 8)
        ref_ask = asks_sorted[1] if bot3_on_ask else (asks_sorted[0] if asks_sorted else fv_r + 8)

        effective_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(effective_pos, soft, limit)

        our_bid = min(ref_bid + 1, fv_r - 1) + skew
        our_ask = max(ref_ask - 1, fv_r + 1) + skew

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
        """Volume-based FV estimation with multi-source fallback."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        bid_fv = None
        for price in bids:
            vol = od.buy_orders[price]
            if 10 <= vol <= 15:
                bid_fv = price + 8
                break
            elif vol >= 20:
                bid_fv = price + 10.5
                break

        ask_fv = None
        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                ask_fv = price - 8
                break
            elif vol >= 20:
                ask_fv = price - 10.5
                break

        if bid_fv is not None and ask_fv is not None:
            return (bid_fv + ask_fv) / 2
        if bid_fv is not None:
            return bid_fv
        if ask_fv is not None:
            return ask_fv
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        if asks:
            return asks[0] - 10.5
        return td.get("ash_last_fv")

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — drift + active market making
    # ------------------------------------------------------------------
    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        """Exploit drift AND capture spread by cycling at max position.

        Phase 1 (pos < limit): Buy aggressively to reach 80 ASAP.
        Phase 2 (pos = limit): Sell small chunk passively. Can't bid this tick.
        Phase 3 (pos < limit, after sell filled): Rebuy + sell again.

        On 1,000 ticks: mostly drift (~8K) + small MM (~1.5K) = ~9.5K
        On 10,000 ticks: drift (80K) + MM cycling (~15K) = ~95K
        """
        orders = []
        limit = self.PARAMS["INTARIAN_PEPPER_ROOT"]["limit"]
        sell_chunk = self.PARAMS["INTARIAN_PEPPER_ROOT"]["sell_chunk"]

        starting_pos = position
        buy_capacity = limit - starting_pos  # max we can buy (position limit check)
        sell_capacity = limit + starting_pos  # max we can sell

        buy_ordered = 0

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        # ── Always try to reach max position: sweep all asks ──
        for ask_price in asks_sorted:
            remaining = buy_capacity - buy_ordered
            if remaining <= 0:
                break
            vol = -od.sell_orders[ask_price]
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                buy_ordered += qty

        # ── Place passive bid for any remaining buy capacity ──
        remaining_buy = buy_capacity - buy_ordered
        if remaining_buy > 0 and bids_sorted:
            best_bid = bids_sorted[0]
            orders.append(Order("INTARIAN_PEPPER_ROOT", best_bid + 1, remaining_buy))

        # ── Sell small chunk passively for spread capture ──
        # Only sell if we're near max (drift exposure is high).
        # The sell order will get filled by elastic takers ~3.5% of ticks.
        # Next tick we rebuy via the buy logic above.
        if starting_pos >= limit - sell_chunk and asks_sorted:
            # Ask inside Bot 2's ask: penny-jump the best ask
            best_ask = asks_sorted[0]
            our_ask = best_ask - 1
            # Size: sell up to sell_chunk, respecting position limit
            sell_qty = min(sell_chunk, sell_capacity)
            if sell_qty > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", our_ask, -sell_qty))

        return orders

    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_skew(position: int, soft_limit: int, hard_limit: int) -> int:
        """Skew quotes to reduce inventory. Max 2 ticks at hard limit."""
        if abs(position) <= soft_limit:
            return 0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        magnitude = min(round((excess / max_excess) * 2), 2)
        return -magnitude if position > 0 else magnitude
