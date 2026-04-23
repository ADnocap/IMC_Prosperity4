"""Tunable wrapper of traders/round2/submission.py.

Identical trading logic to the shipped R2 submission. The only change: all
tunable constants live in a `PARAMS` dict and are read via `self.p["..."]`
so the optimizer can sweep them via the `PROSPERITY_PARAMS` env var.

The shipped `traders/round2/submission.py` is NOT touched — this file exists
so we can tune R2 without mutating a submission result that already shipped.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import os


OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80


def _load_param_overrides():
    raw = os.environ.get("PROSPERITY_PARAMS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class Trader:
    PARAMS = {
        "SIGNAL_MIN_COUNT":  500,
        "SIGNAL_EDGE_ON":    0.16,
        "SIGNAL_EDGE_OFF":   0.08,
        "ACO_SOFT_POS":      30,
        "IPR_ASK_OFFSET_1":  8,
        "IPR_ASK_OFFSET_2":  9,
        "IPR_ASK_THRESH_1":  60,
        "IPR_ASK_THRESH_2":  75,
        "IPR_ASK_QTY_1":     10,
        "IPR_ASK_QTY_2":     15,
        "MAF_BID":           400,
    }

    def __init__(self):
        self.p = {**self.PARAMS, **_load_param_overrides()}

    def bid(self):
        return int(self.p["MAF_BID"])

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == OSMIUM:
                orders, td = self._trade_osmium(od, pos, td)
            elif product == PEPPER:
                orders, td = self._trade_ipr(od, pos, td)
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(td)

    def _fv(self, od, bids, asks, td):
        if not bids and not asks:
            return td.get("fv")

        bot1_estimates = []
        for p in bids:
            if od.buy_orders[p] >= 20:
                bot1_estimates.append(p + 10.5)
        for p in asks:
            if -od.sell_orders[p] >= 20:
                bot1_estimates.append(p - 10.5)
        bot1_fv = sum(bot1_estimates) / len(bot1_estimates) if bot1_estimates else None

        ref_fv = bot1_fv or td.get("fv")
        if ref_fv is None:
            if bids and asks:
                ref_fv = (bids[0] + asks[0]) / 2
            elif bids:
                ref_fv = bids[0] + 8
            else:
                ref_fv = asks[0] - 8

        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15:
                if abs(p - (ref_fv - 8)) <= 3:
                    estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))

        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15:
                if abs(p - (ref_fv + 8)) <= 3:
                    estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            return sum(e * w for e, w in estimates) / tw
        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        if asks:
            return asks[0] - 10.5
        return td.get("fv")

    def _detect_bot1_asym(self, od, bids, asks, fv_r):
        bid_off = None
        ask_off = None

        for p in bids:
            v = od.buy_orders[p]
            if 20 <= v <= 30:
                bid_off = fv_r - p
                break

        for p in asks:
            v = -od.sell_orders[p]
            if 20 <= v <= 30:
                ask_off = p - fv_r
                break

        if bid_off in (10, 11) and ask_off in (10, 11) and bid_off != ask_off:
            return ask_off - bid_off
        return 0

    def _signal_mode(self, td: dict, fv_r: int) -> int:
        prev_fv = td.get("sig_prev_fv")
        prev_raw = td.get("sig_prev_raw", 0)
        mode = td.get("sig_mode", 0)

        if prev_fv is not None and prev_raw != 0:
            move = fv_r - prev_fv
            if move != 0:
                count = td.get("sig_count", 0) + 1
                score = td.get("sig_score", 0)
                if (prev_raw > 0 and move > 0) or (prev_raw < 0 and move < 0):
                    score += 1
                else:
                    score -= 1
                td["sig_count"] = count
                td["sig_score"] = score

        td["sig_prev_fv"] = fv_r

        count = td.get("sig_count", 0)
        if count < int(self.p["SIGNAL_MIN_COUNT"]):
            td["sig_mode"] = 0
            return 0

        edge = td.get("sig_score", 0) / count

        edge_on = float(self.p["SIGNAL_EDGE_ON"])
        edge_off = float(self.p["SIGNAL_EDGE_OFF"])
        if mode == 0:
            if edge >= edge_on:
                mode = 1
            elif edge <= -edge_on:
                mode = -1
        elif mode == 1:
            if edge < edge_off:
                mode = 0
        elif mode == -1:
            if edge > -edge_off:
                mode = 0

        td["sig_mode"] = mode
        return mode

    def _find_wall_bid(self, bids, fv_r):
        if len(bids) >= 3:
            return bids[1]
        if len(bids) >= 2:
            return bids[0] if fv_r - bids[0] >= 5 else bids[1]
        if bids:
            return bids[0]
        return fv_r - 10

    def _find_wall_ask(self, asks, fv_r):
        if len(asks) >= 3:
            return asks[1]
        if len(asks) >= 2:
            return asks[0] if asks[0] - fv_r >= 5 else asks[1]
        if asks:
            return asks[0]
        return fv_r + 10

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        starting_pos = position

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td

        fv_r = int(round(fv))
        td["fv"] = fv

        mode = self._signal_mode(td, fv_r)
        raw_signal = self._detect_bot1_asym(od, bids, asks, fv_r)
        td["sig_prev_raw"] = raw_signal
        signal = raw_signal * mode

        soft_pos = int(self.p["ACO_SOFT_POS"])

        buy_ordered = 0
        sell_ordered = 0

        for ap in asks:
            if ap > fv_r - 2:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + 2:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        pos_after = starting_pos + buy_ordered - sell_ordered

        if pos_after > 0:
            for bp in bids:
                if bp < fv_r:
                    break
                vol = od.buy_orders[bp]
                c = min(vol, pos_after, LIMIT + starting_pos - sell_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, bp, -c))
                    sell_ordered += c
                    pos_after -= c
        elif pos_after < 0:
            for ap in asks:
                if ap > fv_r:
                    break
                vol = -od.sell_orders[ap]
                c = min(vol, -pos_after, LIMIT - starting_pos - buy_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, ap, c))
                    buy_ordered += c
                    pos_after += c

        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        bv1 = od.buy_orders[bids[0]] if bids else 0
        av1 = -od.sell_orders[asks[0]] if asks else 0
        total_l1 = bv1 + av1
        obi = (bv1 - av1) / total_l1 if total_l1 > 0 else 0.0
        obi_shift = 1 if obi > 0.7 else (-1 if obi < -0.7 else 0)

        ref_bid = self._find_wall_bid(bids, fv_r)
        ref_ask = self._find_wall_ask(asks, fv_r)
        our_bid = min(ref_bid + 1 + obi_shift, fv_r - 1)
        our_ask = max(ref_ask - 1 + obi_shift, fv_r + 1)
        buy_cap = 40
        sell_cap = 40

        if signal > 0 and abs(pos_after) < soft_pos:
            buy_cap, sell_cap = 41, 39
        elif signal < 0 and abs(pos_after) < soft_pos:
            buy_cap, sell_cap = 39, 41

        if mode != 0:
            if pos_after >= soft_pos:
                our_bid = min(our_bid, fv_r - 2)
                our_ask = max(fv_r + 1, our_ask - 1)
                buy_cap = min(buy_cap, 32)
                sell_cap = max(sell_cap, 46)
            elif pos_after <= -soft_pos:
                our_bid = min(fv_r - 1, our_bid + 1)
                our_ask = max(our_ask, fv_r + 2)
                buy_cap = max(buy_cap, 46)
                sell_cap = min(sell_cap, 32)

        buy_room = min(buy_room, buy_cap)
        sell_room = min(sell_room, sell_cap)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))

        return orders, td

    def _estimate_ipr_fv(self, od: OrderDepth, td: dict) -> float:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if bids and asks:
            rough_fv = (bids[0] + asks[0]) / 2
        else:
            rough_fv = td.get("ipr_fv") or td.get("ipr_fv_init") or 10000.0

        bot1_off = rough_fv * 0.00075
        bot2_off = rough_fv * 0.0005

        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 8 <= v <= 12:
                estimates.append((p + bot2_off, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p + bot1_off, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 8 <= v <= 12:
                estimates.append((p - bot2_off, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p - bot1_off, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        else:
            fv = rough_fv

        td["ipr_fv"] = fv
        if "ipr_fv_init" not in td:
            td["ipr_fv_init"] = fv
        return fv

    def _trade_ipr(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position

        fv = self._estimate_ipr_fv(od, td)
        fv_r = int(round(fv))

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        for ask_price in asks_sorted:
            if remaining <= 0:
                break
            vol = -od.sell_orders[ask_price]
            if vol > 15:
                continue
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order(PEPPER, ask_price, qty))
                remaining -= qty

        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = fv_r - 6
            orders.append(Order(PEPPER, our_bid, remaining))

        sell_room = LIMIT + position
        thresh_1 = int(self.p["IPR_ASK_THRESH_1"])
        thresh_2 = int(self.p["IPR_ASK_THRESH_2"])
        if position >= thresh_1 and sell_room > 0:
            ask_qty_1 = min(int(self.p["IPR_ASK_QTY_1"]), sell_room)
            if ask_qty_1 > 0:
                orders.append(Order(PEPPER, fv_r + int(self.p["IPR_ASK_OFFSET_1"]), -ask_qty_1))
                sell_room -= ask_qty_1

        if position >= thresh_2 and sell_room > 0:
            ask_qty_2 = min(int(self.p["IPR_ASK_QTY_2"]), sell_room)
            if ask_qty_2 > 0:
                orders.append(Order(PEPPER, fv_r + int(self.p["IPR_ASK_OFFSET_2"]), -ask_qty_2))

        return orders, td
