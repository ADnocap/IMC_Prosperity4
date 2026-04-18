from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Round 1 combined strategy — best of both approaches.

    OSMIUM: Market making on random walk (σ=0.312). Volume-based FV estimation
    with multi-source fallback. Unconditional taking at FV. Penny-jump MM
    with inventory skew.

    PEPPER: Pure buy-and-hold for deterministic drift (+0.1/tick).
    Sweep all asks to reach max position ASAP, hold for drift PnL.
    No selling — every sold unit loses drift exposure.
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
            "soft_limit": 50,
        },
        "INTARIAN_PEPPER_ROOT": {
            "limit": 80,
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

        raw_fv = self._estimate_osmium_fv(od, td)
        if raw_fv is None:
            return orders, td

        # EMA-smoothed FV: reduces noise from single-tick estimation errors
        prev_fv = td.get("ash_last_fv")
        if prev_fv is not None:
            alpha = 0.2  # weight on current tick — heavy smoothing reduces FV noise
            fv = alpha * raw_fv + (1 - alpha) * prev_fv
        else:
            fv = raw_fv
        td["ash_last_fv"] = fv

        fv_r = int(round(fv))
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ── Phase 1: Take mispriced levels ──
        # Take any ask at or below FV (captures Bot 3 crossing quotes)
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

        # Take any bid at or above FV
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
        # Detect Bot 3 (3 levels on a side), use Bot 2 as reference
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
        """Estimate FV using volume-based bot identification with fallbacks.

        Bot 2 (inner wall): vol 10-15, offset ±8 from FV → most precise
        Bot 1 (outer wall): vol 20-30, offset ~±10.5 from FV
        Bot 3 (noise):      vol 2-9, near FV → skip for FV estimation
        """
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
    # INTARIAN_PEPPER_ROOT — pure buy-and-hold for drift
    # ------------------------------------------------------------------
    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        """Buy to max position and hold. Drift does the rest.

        FV increases +0.1/tick. Over 1000 ticks: 80 * 100 = 8,000 drift PnL.
        Every tick not at max = lost drift. Never sell.
        """
        orders = []
        limit = self.PARAMS["INTARIAN_PEPPER_ROOT"]["limit"]
        remaining = limit - position

        if remaining <= 0:
            return orders

        # Sweep all ask levels to get long ASAP
        if od.sell_orders:
            for ask_price in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ask_price]
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                    remaining -= qty
                if remaining <= 0:
                    break

        # Place aggressive passive bid for any unfilled remainder
        if remaining > 0 and od.buy_orders:
            best_bid = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", best_bid + 1, remaining))

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