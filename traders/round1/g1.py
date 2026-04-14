from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    g1: Micro-price (weighted mid) FV for OSMIUM.

    Uses wmid = (bid * ask_vol + ask * bid_vol) / (bid_vol + ask_vol)
    on the INNER wall (Bot 2) levels only. Reported by EchoRover to
    outperform raw mid by 5-9% (Sharpe ~42). The micro-price naturally
    adjusts for volume imbalance — when one side has more volume, the
    FV shifts toward the lighter side.

    Rest of strategy identical to c.py (no skew, penny Bot 2, never Bot 1
    PEPPER).
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
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _estimate_fv(self, od, td):
        """Micro-price FV using volume-weighted mid of identified bot levels.

        Standard micro-price: wmid = (bid*ask_vol + ask*bid_vol) / (bid_vol + ask_vol)
        Applied to Bot 2 (inner wall) when identifiable, falling back to
        all-level micro-price.
        """
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if not bids and not asks:
            return td.get("ash_last_fv")

        # Identify Bot 2 levels (vol 10-15, far from mid)
        if bids and asks:
            raw_mid = (bids[0] + asks[0]) / 2
        else:
            last = td.get("ash_last_fv")
            raw_mid = last if last else (bids[0] + 8 if bids else asks[0] - 8)

        bot2_bid = bot2_bid_vol = None
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                bot2_bid, bot2_bid_vol = p, v
                break
            elif v >= 20:
                bot2_bid, bot2_bid_vol = p, v
                break

        bot2_ask = bot2_ask_vol = None
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                bot2_ask, bot2_ask_vol = p, v
                break
            elif v >= 20:
                bot2_ask, bot2_ask_vol = p, v
                break

        # Micro-price on identified levels
        if bot2_bid is not None and bot2_ask is not None:
            wmid = (bot2_bid * bot2_ask_vol + bot2_ask * bot2_bid_vol) / (bot2_bid_vol + bot2_ask_vol)
            return wmid

        # Single-side fallback with known offsets
        if bot2_bid is not None:
            offset = 8 if bot2_bid_vol <= 15 else 10.5
            return bot2_bid + offset
        if bot2_ask is not None:
            offset = 8 if bot2_ask_vol <= 15 else 10.5
            return bot2_ask - offset

        # Raw micro-price on whatever's visible
        if bids and asks:
            b, bv = bids[0], od.buy_orders[bids[0]]
            a, av = asks[0], -od.sell_orders[asks[0]]
            return (b * av + a * bv) / (bv + av)

        return td.get("ash_last_fv")

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
