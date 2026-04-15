from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Round 1 strategy — MM + Bot2 volume imbalance signal.

    OSMIUM hidden pattern: When Bot2 bid vol != ask vol, a ~5-tick
    FV jump is imminent in the direction of the heavier side.
    Verified across all 3 data days with near 100% accuracy.

    Strategy:
    - Normal ticks: standard penny-jump MM (take at FV, quote at FV±7)
    - Signal ticks (Bot2 vol imbalance): aggressively take in the
      predicted direction to build position BEFORE the jump. Then
      profit from the ~5-tick FV move.

    PEPPER: Buy-and-hold for drift.
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

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM
    # ------------------------------------------------------------------
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

        # ── Detect Bot2 volume imbalance signal ──
        # Bot2 normally posts SAME volume on both sides.
        # When bid_vol != ask_vol, a ~5 tick FV jump is coming.
        # Direction: heavier side = direction of jump.
        signal = 0  # +1 = jump up expected, -1 = jump down
        bot2_bid_vol = 0
        bot2_ask_vol = 0

        for price in bids_sorted:
            vol = od.buy_orders[price]
            if 10 <= vol <= 15:
                ref = td.get("ash_last_fv", fv)
                if abs(price - (ref - 8)) <= 3:
                    bot2_bid_vol = vol
                    break

        for price in asks_sorted:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                ref = td.get("ash_last_fv", fv)
                if abs(price - (ref + 8)) <= 3:
                    bot2_ask_vol = vol
                    break

        if bot2_bid_vol > 0 and bot2_ask_vol > 0:
            if bot2_bid_vol > bot2_ask_vol + 1:
                signal = +1  # FV about to jump UP ~5
            elif bot2_ask_vol > bot2_bid_vol + 1:
                signal = -1  # FV about to jump DOWN ~5

        # ── Phase 1: Taking ──
        if signal != 0:
            # SIGNAL ACTIVE: aggressively take in predicted direction
            # FV is about to move ~5 ticks, so taking at up to FV±3
            # still has positive expected value after the jump
            if signal > 0:
                # Jump UP expected → BUY aggressively
                aggressive_buy_thresh = fv_r + 3
                for ask_price in asks_sorted:
                    if ask_price > aggressive_buy_thresh:
                        break
                    vol = -od.sell_orders[ask_price]
                    can_buy = limit - starting_pos - buy_ordered
                    if can_buy <= 0:
                        break
                    qty = min(vol, can_buy)
                    orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
                    buy_ordered += qty
            else:
                # Jump DOWN expected → SELL aggressively
                aggressive_sell_thresh = fv_r - 3
                for bid_price in bids_sorted:
                    if bid_price < aggressive_sell_thresh:
                        break
                    vol = od.buy_orders[bid_price]
                    can_sell = limit + starting_pos - sell_ordered
                    if can_sell <= 0:
                        break
                    qty = min(vol, can_sell)
                    orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
                    sell_ordered += qty
        else:
            # NO SIGNAL: standard taking at FV with 1+ edge
            for ask_price in asks_sorted:
                if ask_price > fv_r - 1:
                    break
                vol = -od.sell_orders[ask_price]
                can_buy = limit - starting_pos - buy_ordered
                if can_buy <= 0:
                    break
                qty = min(vol, can_buy)
                orders.append(Order("ASH_COATED_OSMIUM", ask_price, qty))
                buy_ordered += qty

            for bid_price in bids_sorted:
                if bid_price < fv_r + 1:
                    break
                vol = od.buy_orders[bid_price]
                can_sell = limit + starting_pos - sell_ordered
                if can_sell <= 0:
                    break
                qty = min(vol, can_sell)
                orders.append(Order("ASH_COATED_OSMIUM", bid_price, -qty))
                sell_ordered += qty

        # ── Phase 2: Passive quoting ──
        # When signal active: skew quotes toward predicted direction
        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)

        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if signal > 0:
            # Expect UP: only place bid (no ask) to force long position
            # Any elastic fill = buy → profits from +5 jump next tick
            if passive_buy > 0:
                orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
            # Also place a bid closer to FV to catch market trade matching
            extra_buy = limit - starting_pos - buy_ordered - passive_buy
            if extra_buy > 0 and passive_buy > 0:
                pass  # already used full capacity
        elif signal < 0:
            # Expect DOWN: only place ask (no bid) to force short position
            if passive_sell > 0:
                orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))
        else:
            # Normal: place both sides
            if passive_buy > 0:
                orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
            if passive_sell > 0:
                orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders, td

    # ------------------------------------------------------------------
    def _estimate_osmium_fv(self, od: OrderDepth, td: dict):
        """Bot1-anchored FV estimation to avoid Bot3 contamination."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if not bids and not asks:
            return td.get("ash_last_fv")

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

        ref_fv = bot1_fv or td.get("ash_last_fv")
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
                if abs(price - (ref_fv - 8)) <= 3:
                    estimates.append((price + 8, 2.0))
            elif vol >= 20:
                estimates.append((price + 10.5, 1.0))

        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                if abs(price - (ref_fv + 8)) <= 3:
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
        return td.get("ash_last_fv")

    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
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
