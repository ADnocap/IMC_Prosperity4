"""Test: Take with 1+ edge (only buy at FV_r-1 or below, sell at FV_r+1 or above)"""
from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json

class Trader:
    PARAMS = {"ASH_COATED_OSMIUM": {"limit": 80}, "INTARIAN_PEPPER_ROOT": {"limit": 80}}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        td = {}
        if state.traderData:
            try: td = json.loads(state.traderData)
            except: td = {}

        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == "ASH_COATED_OSMIUM":
                result[product], td = self._osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._pepper(od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    def _osmium(self, od, pos, td):
        orders = []
        limit = 80
        bids_s = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_s = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._fv(od, td)
        if fv is None:
            fv = td.get("fv")
            if fv is None: return orders, td
        td["fv"] = fv
        fv_r = int(round(fv))
        starting_pos = pos
        buy_ordered = 0
        sell_ordered = 0

        # TAKE with 1+ edge: buy at fv_r-1 or below, sell at fv_r+1 or above
        for p in asks_s:
            if p > fv_r - 1:
                break
            v = -od.sell_orders[p]
            can = limit - starting_pos - buy_ordered
            if can <= 0: break
            q = min(v, can)
            orders.append(Order("ASH_COATED_OSMIUM", p, q))
            buy_ordered += q

        for p in bids_s:
            if p < fv_r + 1:
                break
            v = od.buy_orders[p]
            can = limit + starting_pos - sell_ordered
            if can <= 0: break
            q = min(v, can)
            orders.append(Order("ASH_COATED_OSMIUM", p, -q))
            sell_ordered += q

        # Passive: same penny-jump
        ref_bid = self._wall_bid(bids_s, fv_r)
        ref_ask = self._wall_ask(asks_s, fv_r)
        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        pb = limit - starting_pos - buy_ordered
        ps = limit + starting_pos - sell_ordered
        if pb > 0: orders.append(Order("ASH_COATED_OSMIUM", our_bid, pb))
        if ps > 0: orders.append(Order("ASH_COATED_OSMIUM", our_ask, -ps))
        return orders, td

    def _fv(self, od, td):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids and not asks: return td.get("fv")
        if bids and asks: raw_mid = (bids[0] + asks[0]) / 2
        elif bids: raw_mid = td.get("fv", bids[0] + 8)
        else: raw_mid = td.get("fv", asks[0] - 8)
        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and raw_mid - p >= 5: estimates.append((p + 8, 2.0))
            elif v >= 20: estimates.append((p + 10.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - raw_mid >= 5: estimates.append((p - 8, 2.0))
            elif v >= 20: estimates.append((p - 10.5, 1.0))
        if estimates:
            tw = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / tw
        if bids and asks: return (bids[0] + asks[0]) / 2
        if bids: return bids[0] + 10.5
        if asks: return asks[0] - 10.5
        return td.get("fv")

    @staticmethod
    def _wall_bid(bids_s, fv_r):
        if len(bids_s) >= 3: return bids_s[1]
        if len(bids_s) >= 2: return bids_s[0] if fv_r - bids_s[0] >= 5 else bids_s[1]
        return bids_s[0] if bids_s else fv_r - 8

    @staticmethod
    def _wall_ask(asks_s, fv_r):
        if len(asks_s) >= 3: return asks_s[1]
        if len(asks_s) >= 2: return asks_s[0] if asks_s[0] - fv_r >= 5 else asks_s[1]
        return asks_s[0] if asks_s else fv_r + 8

    def _pepper(self, od, pos):
        orders = []
        remaining = 80 - pos
        if remaining <= 0: return orders
        if od.sell_orders:
            for p in sorted(od.sell_orders.keys()):
                v = -od.sell_orders[p]
                if remaining > 20 and v > 15: continue
                q = min(v, remaining)
                if q > 0: orders.append(Order("INTARIAN_PEPPER_ROOT", p, q))
                remaining -= q
                if remaining <= 0: break
        if remaining > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", bb + 1, remaining))
        return orders
