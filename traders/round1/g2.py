from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    g2: Volume imbalance signal for OSMIUM FV.

    Uses c.py's volume-based FV as base, then adjusts by the order book
    imbalance (OBI). EchoRover analysis reports r=0.59 correlation between
    OBI and 1-tick-ahead returns. OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol).
    When bids are heavier, price tends up → shift FV up.

    Also: wider empty-book fallback (fv_r-10 vs fv_r-8).
    """

    LIMIT = 80
    OBI_COEFF = 2.0  # ticks of FV adjustment per unit of OBI

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
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _base_fv(self, od, td):
        """Volume-based FV (same as c.py) — returns base estimate."""
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

        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / tw
        if bids and asks:
            return raw_mid
        if bids:
            return bids[0] + 10.5
        if asks:
            return asks[0] - 10.5
        return td.get("ash_last_fv")

    def _compute_obi(self, od):
        """Order book imbalance: (total_bid_vol - total_ask_vol) / total."""
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

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
        return fv_r - 10  # wider fallback

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
        return fv_r + 10  # wider fallback

    def _trade_osmium(self, od, position, td):
        orders = []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._base_fv(od, td)
        if fv is None:
            return orders, td

        # Apply OBI adjustment
        obi = self._compute_obi(od)
        fv = fv + self.OBI_COEFF * obi

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

    def _trade_pepper(self, od, position):
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if vol > 15:
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
        return orders
