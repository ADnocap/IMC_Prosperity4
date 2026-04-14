from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math


class Trader:
    """
    Round 1 strategy for ASH_COATED_OSMIUM and INTARIAN_PEPPER_ROOT.

    OSMIUM: Stationary random walk (σ=0.312). Market making around FV estimated
    from Bot 2 mid. Penny-jump inside bot spread, inventory skew toward zero.

    PEPPER: Deterministic drift +0.1/tick. FV is perfectly predictable.
    Exploit by accumulating max long position (drift = free PnL), then
    market make asymmetrically to capture additional spread.
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
            "soft_limit": 50,
        },
        "INTARIAN_PEPPER_ROOT": {
            "limit": 80,
            "soft_limit": 60,
            "drift_per_ts": 0.001,       # FV increases by 0.001 per timestamp unit (0.1 per tick)
            "buy_aggression": 8,          # take asks up to FV + this
            "sell_spread": 4,             # place asks at floor(FV) + this
            "sell_chunk": 15,             # max units to sell per tick when cycling
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
                result[product], td = self._trade_pepper(od, pos, state.timestamp, td)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM — stationary random walk market making
    # ------------------------------------------------------------------
    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        p = self.PARAMS["ASH_COATED_OSMIUM"]
        limit = p["limit"]
        soft = p["soft_limit"]

        # ── Estimate FV from Bot 2 levels ──
        # Bot 2: round(FV) - 8 / round(FV) + 8, spread = 16
        # Bot 3 detection: 3 levels on one side
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_osmium_fv(bids_sorted, asks_sorted, od, td)
        td["ash_last_fv"] = fv

        if fv is None:
            return orders, td

        mid_int = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Bot 3 detection: 3 levels on one side
        bot3_on_bid = len(bids_sorted) >= 3
        bot3_on_ask = len(asks_sorted) >= 3

        # ── Phase 1: Take mispriced levels (unconditional — no position restriction) ──
        # Take any ask at or below FV
        for ask_price in asks_sorted:
            if ask_price > mid_int:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
            buy_ordered += qty

        # Take any bid at or above FV
        for bid_price in bids_sorted:
            if bid_price < mid_int:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
            sell_ordered += qty

        # ── Phase 2: Passive penny-jump quoting ──
        # Reference levels: skip Bot 3 (1st of 3), use Bot 2 or Bot 1
        ref_bid = bids_sorted[1] if bot3_on_bid and len(bids_sorted) >= 2 else (bids_sorted[0] if bids_sorted else mid_int - 8)
        ref_ask = asks_sorted[1] if bot3_on_ask and len(asks_sorted) >= 2 else (asks_sorted[0] if asks_sorted else mid_int + 8)

        effective_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(effective_pos, soft, limit)

        # Penny-jump: +1 inside the reference level (Bot 2 or Bot 1)
        our_bid = min(ref_bid + 1, mid_int - 1) + skew
        our_ask = max(ref_ask - 1, mid_int + 1) + skew

        if our_bid >= our_ask:
            our_bid = mid_int - 1
            our_ask = mid_int + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders, td

    def _estimate_osmium_fv(self, bids_sorted, asks_sorted, od, td):
        """Estimate OSMIUM fair value from Bot 2 levels.
        Bot 2: round(FV)-8 / round(FV)+8. Use mid of inner levels.
        When 3 levels: skip Bot 3 (innermost = Bot 3, 2nd = Bot 2).
        When 1 level: invert the formula.
        When 0 levels: use last known FV."""
        ref_bid = None
        ref_ask = None

        if bids_sorted:
            # If 3 levels: Bot3 is innermost, Bot2 is 2nd, Bot1 is 3rd
            if len(bids_sorted) >= 3:
                ref_bid = bids_sorted[1]
            elif len(bids_sorted) >= 2:
                ref_bid = bids_sorted[0]  # Bot 2 is best
            else:
                # Single level — could be Bot 1 or Bot 2. Check volume.
                price = bids_sorted[0]
                vol = od.buy_orders[price]
                if 10 <= vol <= 15:
                    ref_bid = price  # Bot 2
                # else Bot 1, less precise

        if asks_sorted:
            if len(asks_sorted) >= 3:
                ref_ask = asks_sorted[1]
            elif len(asks_sorted) >= 2:
                ref_ask = asks_sorted[0]
            else:
                price = asks_sorted[0]
                vol = -od.sell_orders[price]
                if 10 <= vol <= 15:
                    ref_ask = price

        if ref_bid is not None and ref_ask is not None:
            return (ref_bid + ref_ask) / 2
        elif ref_bid is not None:
            return ref_bid + 8  # round(FV)-8 → FV ≈ bid + 8
        elif ref_ask is not None:
            return ref_ask - 8  # round(FV)+8 → FV ≈ ask - 8
        elif bids_sorted and asks_sorted:
            # No Bot 2 identified, use raw mid
            return (bids_sorted[0] + asks_sorted[0]) / 2
        elif bids_sorted:
            return bids_sorted[0] + 10.5  # Bot 1 bid ≈ FV - 10.5
        elif asks_sorted:
            return asks_sorted[0] - 10.5
        else:
            return td.get("ash_last_fv")

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — deterministic drift exploitation
    # ------------------------------------------------------------------
    def _trade_pepper(self, od: OrderDepth, position: int, timestamp: int, td: dict):
        orders = []
        p = self.PARAMS["INTARIAN_PEPPER_ROOT"]
        limit = p["limit"]
        soft = p["soft_limit"]
        drift = p["drift_per_ts"]
        buy_aggr = p["buy_aggression"]
        sell_spread = p["sell_spread"]
        sell_chunk = p["sell_chunk"]

        # ── Compute FV from drift model ──
        if "ipr_fv_start" not in td:
            fv_start = self._estimate_pepper_fv_start(od)
            td["ipr_fv_start"] = fv_start

        fv = td["ipr_fv_start"] + drift * timestamp

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Aggressive buying ──
        # Take ALL asks up to FV + buy_aggression. Drift makes all buys profitable.
        # Even buying at Bot 1 ask (FV+10) recoups in ~100 ticks from drift.
        for ask_price in asks_sorted:
            if ask_price > fv + buy_aggr:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
            buy_ordered += qty

        # ── Phase 2: Sell to capture spread (only when near max position) ──
        # Sell small chunk at favorable prices, rebuy next tick via passive bid.
        # Only sell above FV to guarantee positive edge.
        if starting_pos >= soft:
            sold_this_tick = 0
            for bid_price in bids_sorted:
                if bid_price < fv + 1:
                    break
                if sold_this_tick >= sell_chunk:
                    break
                vol = od.buy_orders[bid_price]
                can_sell = limit + starting_pos - sell_ordered
                qty = min(vol, can_sell, sell_chunk - sold_this_tick)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", bid_price, -qty))
                    sell_ordered += qty
                    sold_this_tick += qty

        # ── Phase 3: Passive quoting ──
        # Tight bid (want fills — more long exposure from drift)
        # Wide ask (reluctant to sell — would lose drift exposure)
        passive_buy = limit - starting_pos - buy_ordered
        fv_int = int(math.ceil(fv))

        if passive_buy > 0:
            our_bid = fv_int - 2  # tight bid, close to FV
            orders.append(Order("INTARIAN_PEPPER_ROOT", our_bid, passive_buy))

        # Only place passive asks if significantly long
        if starting_pos > soft // 2:
            passive_sell_qty = min(sell_chunk, limit + starting_pos - sell_ordered)
            if passive_sell_qty > 0:
                our_ask = int(math.floor(fv)) + sell_spread
                orders.append(Order("INTARIAN_PEPPER_ROOT", our_ask, -passive_sell_qty))

        return orders, td

    def _estimate_pepper_fv_start(self, od: OrderDepth) -> float:
        """Estimate PEPPER starting FV from tick 0 order book.
        Uses Bot 2 levels (vol 8-12) or falls back to mid-price."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # Try to identify Bot 2 by volume (8-12)
        bot2_bid = None
        for price in bids:
            vol = od.buy_orders[price]
            if 8 <= vol <= 12:
                bot2_bid = price
                break

        bot2_ask = None
        for price in asks:
            vol = -od.sell_orders[price]
            if 8 <= vol <= 12:
                bot2_ask = price
                break

        # Infer FV from Bot 2 formulas: bid = ceil(FV)-7, ask = floor(FV)+7
        if bot2_bid is not None and bot2_ask is not None:
            fv_from_bid = bot2_bid + 7 - 0.5  # ceil(FV)-7 = bid → FV ≈ bid+7 - 0.5
            fv_from_ask = bot2_ask - 7 + 0.5  # floor(FV)+7 = ask → FV ≈ ask-7 + 0.5
            return (fv_from_bid + fv_from_ask) / 2
        elif bot2_bid is not None:
            return bot2_bid + 7 - 0.5
        elif bot2_ask is not None:
            return bot2_ask - 7 + 0.5

        # Fallback: use raw mid
        if bids and asks:
            return (bids[0] + asks[0]) / 2

        # Last resort
        return 12000.0

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
