from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    g3: Fractional FV refinement + wider fallback + aggressive first-tick PEPPER.

    OSMIUM: Uses Bot 1 spread (20 vs 21) to determine if FV is integer or
    non-integer, narrowing the FV estimate by ~0.25 on average. Wider
    empty-book fallback (fv_r-10). Combined with c.py's base approach.

    PEPPER: First tick sweeps ALL asks (including Bot 1) for max speed,
    then switches to selective (never Bot 1) afterward. Rationale: on
    tick 0, 80 units of drift exposure is worth more than 3-tick spread
    savings. After tick 0, we're mostly filled and can be selective for
    the last few units.
    """

    LIMIT = 80

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
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product], td = self._trade_pepper(od, pos, td)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _estimate_fv(self, od, td):
        """Volume-based FV with fractional refinement from Bot 1 spread.

        When both Bot 1 bid and ask visible:
        - spread = 21 → FV is non-integer → narrow to [round(FV), round(FV)+0.5)
          or [round(FV)-0.5, round(FV)) using floor(FV) from Bot 1 bid
        - spread = 20 → FV is integer → FV = round(FV) exactly
        """
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids and not asks:
            return td.get("ash_last_fv")

        if bids and asks:
            raw_mid = (bids[0] + asks[0]) / 2
        elif bids:
            last = td.get("ash_last_fv")
            raw_mid = last if last else bids[0] + 8
        else:
            last = td.get("ash_last_fv")
            raw_mid = last if last else asks[0] - 8

        # Identify bot levels
        bot2_bids = []
        bot1_bids = []
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                bot2_bids.append((p, v))
            elif v >= 20:
                bot1_bids.append((p, v))

        bot2_asks = []
        bot1_asks = []
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                bot2_asks.append((p, v))
            elif v >= 20:
                bot1_asks.append((p, v))

        # Base FV from weighted estimates (same as c.py)
        estimates = []
        for p, v in bot2_bids:
            estimates.append((p + 8, 2.0))
        for p, v in bot1_bids:
            estimates.append((p + 10.5, 1.0))
        for p, v in bot2_asks:
            estimates.append((p - 8, 2.0))
        for p, v in bot1_asks:
            estimates.append((p - 10.5, 1.0))

        if not estimates:
            if bids and asks:
                return raw_mid
            if bids:
                return bids[0] + 10.5
            if asks:
                return asks[0] - 10.5
            return td.get("ash_last_fv")

        tw = sum(w for _, w in estimates)
        base_fv = sum(e * w for e, w in estimates) / tw

        # Fractional refinement using Bot 1 spread
        if bot1_bids and bot1_asks:
            b1_bid = bot1_bids[0][0]  # floor(FV) - 10
            b1_ask = bot1_asks[0][0]  # ceil(FV) + 10
            b1_spread = b1_ask - b1_bid

            rounded = int(round(base_fv))

            if b1_spread == 20:
                # FV is integer → use exactly round(base_fv)
                return float(rounded)
            elif b1_spread == 21:
                # FV is non-integer. floor(FV) = b1_bid + 10
                floor_fv = b1_bid + 10
                if floor_fv == rounded:
                    # FV in (rounded, rounded + 1) → midpoint = rounded + 0.5
                    return rounded + 0.25
                else:
                    # FV in (rounded - 1, rounded) → midpoint
                    return rounded - 0.25

        return base_fv

    def _find_wall_bid(self, bids_sorted, fv_r):
        if len(bids_sorted) >= 3:
            return bids_sorted[1]
        if len(bids_sorted) >= 2:
            if fv_r - bids_sorted[0] >= 5:
                return bids_sorted[0]
            else:
                return bids_sorted[1]
        if bids_sorted:
            return bids_sorted[0]
        return fv_r - 10

    def _find_wall_ask(self, asks_sorted, fv_r):
        if len(asks_sorted) >= 3:
            return asks_sorted[1]
        if len(asks_sorted) >= 2:
            if asks_sorted[0] - fv_r >= 5:
                return asks_sorted[0]
            else:
                return asks_sorted[1]
        if asks_sorted:
            return asks_sorted[0]
        return fv_r + 10

    def _trade_osmium(self, od, position, td):
        orders = []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_fv(od, td)
        if fv is None:
            return orders, td
        td["ash_last_fv"] = fv
        fv_r = int(round(fv))

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        for ap in asks_sorted:
            if ap > fv_r:
                break
            vol = -od.sell_orders[ap]
            can = self.LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order("ASH_COATED_OSMIUM", ap, qty))
            buy_ordered += qty

        for bp in bids_sorted:
            if bp < fv_r:
                break
            vol = od.buy_orders[bp]
            can = self.LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order("ASH_COATED_OSMIUM", bp, -qty))
            sell_ordered += qty

        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        pb = self.LIMIT - starting_pos - buy_ordered
        ps = self.LIMIT + starting_pos - sell_ordered
        if pb > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, pb))
        if ps > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -ps))

        return orders, td

    def _trade_pepper(self, od, position, td):
        """First-tick aggressive, then selective.

        Tick 0: sweep ALL asks (including Bot 1) for max drift exposure.
        After: never buy Bot 1 (same as c.py).
        """
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders, td

        first_tick = td.get("ipr_filled", False) is False

        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                # First tick: sweep everything. After: skip Bot 1
                if not first_tick and vol > 15:
                    continue
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ap, qty))
                    remaining -= qty
                if remaining <= 0:
                    break

        if remaining > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", bb + 1, remaining))

        if remaining < self.LIMIT:
            td["ipr_filled"] = True

        return orders, td
