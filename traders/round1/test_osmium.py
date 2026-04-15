from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    OSMIUM improvements over current a.py:

    1. PRECISE FV: Use Bot1+Bot2 combined for sub-integer FV precision.
       Bot2 gives floor(FV-0.5), Bot1 gives floor(FV) and ceil(FV).
       Combined: narrows FV from ±0.5 to ±0.25.

    2. ALWAYS QUOTE: Even when book is one-sided, use last known FV
       to keep passive quotes up. Elastic demand (4.2%/tick) only fires
       when we have resting orders → never miss a tick.

    3. SMARTER TAKING: Only take when we have >0.5 edge (using precise FV).
       Current code takes at ≤FV_rounded which is 0-edge on average.

    4. MULTI-LEVEL QUOTING: Place orders at multiple offsets to capture
       both Bot3 trades (tight) and elastic taker trades (wide).

    5. POSITION-AWARE SIZING: Reduce position extremes to cut variance.
       Don't aggressively skew quotes, but reduce size on overweight side.

    PEPPER: Same buy-and-hold (already optimal at 7.5k).
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
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        limit = 80

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_fv_precise(od, td)
        if fv is None:
            # ALWAYS QUOTE: use last known FV
            fv = td.get("ash_last_fv")
            if fv is None:
                return orders, td

        td["ash_last_fv"] = fv
        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Take clearly mispriced levels ──
        # Only take with >0.5 edge to avoid adverse selection
        for ask_price in asks_sorted:
            edge = fv - ask_price
            if edge < 0.5:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        for bid_price in bids_sorted:
            edge = bid_price - fv
            if edge < 0.5:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # ── Phase 2: Multi-level passive quoting ──
        # Level 1: Penny-jump Bot2 (FV±7) - main edge
        # Level 2: Tight quote (FV±2) - catches Bot3 + some elastic

        ref_bid = self._find_wall_bid(bids_sorted, od, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, od, fv_r)

        # Primary quote: penny-jump the inner wall
        our_bid_1 = min(ref_bid + 1, fv_r - 1)
        our_ask_1 = max(ref_ask - 1, fv_r + 1)

        if our_bid_1 >= our_ask_1:
            our_bid_1 = fv_r - 1
            our_ask_1 = fv_r + 1

        # Position-aware sizing: when heavily long, reduce buy size
        # When heavily short, reduce sell size
        # Use soft limit at 50 to start reducing
        pos_ratio = position / limit  # -1 to +1
        buy_scale = max(0.2, 1.0 - max(0, pos_ratio) * 0.8)
        sell_scale = max(0.2, 1.0 + min(0, pos_ratio) * 0.8)

        total_buy = limit - starting_pos - buy_ordered
        total_sell = limit + starting_pos - sell_ordered

        if total_buy > 0:
            buy_qty = max(1, int(total_buy * buy_scale))
            buy_qty = min(buy_qty, total_buy)
            orders.append(Order("ASH_COATED_OSMIUM", our_bid_1, buy_qty))
            buy_ordered += buy_qty

        if total_sell > 0:
            sell_qty = max(1, int(total_sell * sell_scale))
            sell_qty = min(sell_qty, total_sell)
            orders.append(Order("ASH_COATED_OSMIUM", our_ask_1, -sell_qty))
            sell_ordered += sell_qty

        # Remaining capacity at secondary level (tighter, catches Bot3)
        remaining_buy = limit - starting_pos - buy_ordered
        remaining_sell = limit + starting_pos - sell_ordered

        if remaining_buy > 0:
            tight_bid = fv_r - 2
            if tight_bid < our_bid_1:
                tight_bid = our_bid_1
            if tight_bid >= our_ask_1:
                tight_bid = our_bid_1  # fallback to primary
            if tight_bid != our_bid_1:
                orders.append(Order("ASH_COATED_OSMIUM", tight_bid, remaining_buy))

        if remaining_sell > 0:
            tight_ask = fv_r + 2
            if tight_ask > our_ask_1:
                tight_ask = our_ask_1
            if tight_ask <= our_bid_1:
                tight_ask = our_ask_1
            if tight_ask != our_ask_1:
                orders.append(Order("ASH_COATED_OSMIUM", tight_ask, -remaining_sell))

        return orders, td

    def _estimate_fv_precise(self, od: OrderDepth, td: dict):
        """Precise FV using Bot1+Bot2 combined estimates."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if not bids and not asks:
            return None

        # Classify levels
        bot2_bids = []
        bot2_asks = []
        bot1_bids = []
        bot1_asks = []

        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15:
                bot2_bids.append(p)
            elif v >= 20:
                bot1_bids.append(p)

        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15:
                bot2_asks.append(p)
            elif v >= 20:
                bot1_asks.append(p)

        # Bot2: FV = bid + 8 = ask - 8 (when spread = 16)
        bot2_estimates = []
        if bot2_bids:
            bot2_estimates.append(bot2_bids[0] + 8)
        if bot2_asks:
            bot2_estimates.append(bot2_asks[0] - 8)

        if len(bot2_estimates) == 2:
            # Both sides: average gives good FV
            fv = sum(bot2_estimates) / 2
        elif len(bot2_estimates) == 1:
            fv = bot2_estimates[0]
        else:
            # No Bot2: use Bot1
            bot1_estimates = []
            if bot1_bids:
                bot1_estimates.append(bot1_bids[0] + 10.5)
            if bot1_asks:
                bot1_estimates.append(bot1_asks[0] - 10.5)
            if bot1_estimates:
                fv = sum(bot1_estimates) / len(bot1_estimates)
            elif bids and asks:
                fv = (bids[0] + asks[0]) / 2
            else:
                return None

        # Refine with Bot1 if available
        # Bot1 bid = floor(FV) - 10, so floor(FV) = bot1_bid + 10
        # Bot1 ask = ceil(FV) + 10, so ceil(FV) = bot1_ask - 10
        if bot1_bids and bot1_asks:
            floor_fv = bot1_bids[0] + 10
            ceil_fv = bot1_asks[0] - 10
            if ceil_fv == floor_fv:
                # FV is exactly an integer
                fv = float(floor_fv)
            elif ceil_fv == floor_fv + 1:
                # FV is between floor and ceil
                # Use Bot2 estimate as center, but clamp to [floor, ceil]
                fv = max(floor_fv + 0.01, min(fv, ceil_fv - 0.01))

        return fv

    @staticmethod
    def _find_wall_bid(bids_sorted, od, fv_r):
        """Find Bot2 inner wall bid for penny-jumping."""
        for p in bids_sorted:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and fv_r - p >= 5:
                return p
        # Fallback: use furthest bot level
        for p in bids_sorted:
            v = od.buy_orders[p]
            if v >= 20:
                return p
        if bids_sorted:
            return bids_sorted[0]
        return fv_r - 8

    @staticmethod
    def _find_wall_ask(asks_sorted, od, fv_r):
        """Find Bot2 inner wall ask for penny-jumping."""
        for p in asks_sorted:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - fv_r >= 5:
                return p
        for p in asks_sorted:
            v = -od.sell_orders[p]
            if v >= 20:
                return p
        if asks_sorted:
            return asks_sorted[0]
        return fv_r + 8

    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        """Buy to max position ASAP. Take ALL asks (including Bot 1).
        Every tick at <80 costs 80*0.1 = 8 in lost drift.
        Bot1 spread penalty (~3/unit) is worth paying for speed."""
        orders = []
        limit = 80
        remaining = limit - position

        if remaining <= 0:
            return orders

        if od.sell_orders:
            for ask_price in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ask_price]
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
