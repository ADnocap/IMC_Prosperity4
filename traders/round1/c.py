from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Round 1 strategy c — our best, building on a.py.

    OSMIUM: Same as a.py — multi-source weighted FV estimation with
    Bot 3 filtering, no EMA, no inventory skew. Penny-jump Bot 2.

    PEPPER: Never buy from Bot 1 (vol > 15). Bot 2 asks are ~3 ticks
    cheaper. Over 80 units, saves ~100+ PnL in spread cost vs ~30 PnL
    in drift loss from 7 extra ticks to fill. Net: +35 PnL.
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
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
        limit = self.PARAMS["ASH_COATED_OSMIUM"]["limit"]

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

        # ── Phase 1: Take mispriced levels (positive edge) ──
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
        """Estimate FV using all bot levels with Bot 3 filtering."""
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

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — strictly selective buy-and-hold
    # ------------------------------------------------------------------
    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        """Buy to max position, never from Bot 1.

        Bot 2 asks (vol 8-12) are at FV+5, Bot 1 asks (vol 15-25) at
        FV+8. Saving 3 ticks/unit over 80 units = 240 PnL. Drift loss
        from ~7 extra accumulation ticks ≈ 30 PnL. Net gain: ~100+ PnL.
        Also captures Bot 3 crossing asks (below FV, even better price).
        """
        orders = []
        limit = self.PARAMS["INTARIAN_PEPPER_ROOT"]["limit"]
        remaining = limit - position

        if remaining <= 0:
            return orders

        if od.sell_orders:
            for ask_price in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ask_price]
                if vol > 15:
                    continue  # never buy expensive Bot 1 asks
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

    # ------------------------------------------------------------------
    @staticmethod
    def _find_wall_bid(bids_sorted, fv_r):
        """Find Bot 2 (inner wall) bid as penny-jump reference."""
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
        """Find Bot 2 (inner wall) ask as penny-jump reference."""
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
