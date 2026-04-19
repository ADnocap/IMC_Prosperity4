from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math


OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80


# Residual logistic model trained on all 6 days, EXCLUDING center_dist so it
# learns alpha orthogonal to the OU-pull rule that already exploits that signal.
# Target: sign(FV_{t+50} - FV_t). CV mean AUC 0.57, acc 0.55.
ML_BIAS = 0.021432
ML_W_RET1        = -0.196371
ML_W_RET5        = -0.089309
ML_W_RET20       = -0.065724
ML_W_BID_GAP     = +0.001363
ML_W_ASK_GAP     = +0.008386
ML_W_L2_GAP_SIGN = +0.133911
ML_W_SPREAD      = +0.003370
ML_W_OBI         = -0.059562
ML_W_LOG_L1_VOL  = -0.025428


class Trader:
    # Legacy Bot1-asym signal (kept around, but with edge thresholds disabled)
    SIGNAL_MIN_COUNT = 500
    SIGNAL_EDGE_ON = 0.16
    SIGNAL_EDGE_OFF = 0.08

    ACO_SOFT_POS = 30

    # ML residual pulls at moderate center_dist (|dist| < 9) where OU doesn't fire.
    # Tight thresholds — AUC-0.57 residual tolerates few false positives.
    ML_PULL_HI = 0.58   # p_up >= => pull ASK (expect up)
    ML_PULL_LO = 0.42   # p_up <= => pull BID (expect down)

    IPR_ASK_OFFSET_1 = 8
    IPR_ASK_OFFSET_2 = 9
    IPR_ASK_THRESH_1 = 60
    IPR_ASK_THRESH_2 = 75
    IPR_ASK_QTY_1 = 10
    IPR_ASK_QTY_2 = 15

    MAF_BID = 0

    def bid(self):
        return self.MAF_BID

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

    # ACO ============================================================

    def _fv(self, od, bids, asks, td):
        if not bids and not asks:
            return td.get("fv")

        if bids and asks and (asks[0] - bids[0]) == 16:
            bv1 = od.buy_orders[bids[0]]
            av1 = -od.sell_orders[asks[0]]
            if 10 <= bv1 <= 15 and 10 <= av1 <= 15:
                return (bids[0] + asks[0]) / 2

        bot1_bid = None
        bot1_ask = None
        for p in bids:
            if 20 <= od.buy_orders[p] <= 30:
                bot1_bid = p
                break
        for p in asks:
            if 20 <= -od.sell_orders[p] <= 30:
                bot1_ask = p
                break

        if bot1_bid is not None and bot1_ask is not None:
            return (bot1_bid + bot1_ask) / 2

        prev_fv = td.get("fv")
        if bot1_bid is not None and prev_fv is not None:
            return 0.3 * (bot1_bid + 10.5) + 0.7 * prev_fv
        if bot1_ask is not None and prev_fv is not None:
            return 0.3 * (bot1_ask - 10.5) + 0.7 * prev_fv

        if prev_fv is not None:
            return prev_fv

        if bids and asks:
            return (bids[0] + asks[0]) / 2
        if bids:
            return bids[0] + 10.5
        return asks[0] - 10.5

    def _ml_score(self, fv_r, fv_hist, od, bids, asks):
        """Return p_up (logistic) from current book + rounded-FV history."""
        # fv_hist is a deque-like list of recent fv_r ints (oldest first); current not yet appended.
        if len(fv_hist) < 20:
            return 0.5  # not enough history

        fv_1 = fv_hist[-1]
        fv_5 = fv_hist[-5]
        fv_20 = fv_hist[-20]

        ret1 = fv_r - fv_1
        ret5 = fv_r - fv_5
        ret20 = fv_r - fv_20

        bp1 = bids[0] if bids else 0
        bp2 = bids[1] if len(bids) > 1 else 0
        ap1 = asks[0] if asks else 0
        ap2 = asks[1] if len(asks) > 1 else 0
        bv1 = od.buy_orders[bp1] if bp1 else 0
        av1 = -od.sell_orders[ap1] if ap1 else 0

        bid_gap = (bp1 - bp2) if (bp1 and bp2) else 0
        ask_gap = (ap2 - ap1) if (ap1 and ap2) else 0
        if bid_gap == 2 and ask_gap == 3:
            l2_gap_sign = 1
        elif bid_gap == 3 and ask_gap == 2:
            l2_gap_sign = -1
        else:
            l2_gap_sign = 0
        spread = (ap1 - bp1) if (ap1 and bp1) else 16
        total = bv1 + av1
        obi = (bv1 - av1) / total if total > 0 else 0.0
        log_l1 = math.log1p(total)

        z = (ML_BIAS
             + ML_W_RET1 * ret1
             + ML_W_RET5 * ret5
             + ML_W_RET20 * ret20
             + ML_W_BID_GAP * bid_gap
             + ML_W_ASK_GAP * ask_gap
             + ML_W_L2_GAP_SIGN * l2_gap_sign
             + ML_W_SPREAD * spread
             + ML_W_OBI * obi
             + ML_W_LOG_L1_VOL * log_l1)
        # sigmoid
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        else:
            ez = math.exp(z)
            return ez / (1.0 + ez)

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

        # Maintain rolling fv_r history (last 20)
        hist = td.get("fv_hist", [])
        p_up = self._ml_score(fv_r, hist, od, bids, asks)
        hist.append(fv_r)
        if len(hist) > 20:
            hist = hist[-20:]
        td["fv_hist"] = hist

        buy_ordered = 0
        sell_ordered = 0

        # Take
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

        # Clear
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

        # Make
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

        # ML pulls at moderate dist (OU doesn't fire here). Residual signal is weak,
        # so thresholds are tight and we inventory-guard to avoid stacking pulls.
        center_dist = fv_r - 10000
        if abs(center_dist) < 9:
            if p_up >= self.ML_PULL_HI and pos_after < 70:
                sell_cap = 0
            elif p_up <= self.ML_PULL_LO and pos_after > -70:
                buy_cap = 0

        # OU pull at extreme dist (unchanged from v20).
        if center_dist >= 9 and pos_after > -70:
            buy_cap = 0
        elif center_dist <= -9 and pos_after < 70:
            sell_cap = 0

        if pos_after >= 60:
            sell_cap = max(sell_cap, 40)
            buy_cap = min(buy_cap, 20)
        elif pos_after <= -60:
            buy_cap = max(buy_cap, 40)
            sell_cap = min(sell_cap, 20)

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

    # IPR ============================================================

    def _estimate_ipr_fv(self, od: OrderDepth, td: dict) -> float:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 8 <= v <= 12:
                estimates.append((p + 6.5, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p + 9.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 8 <= v <= 12:
                estimates.append((p - 6.5, 2.0))
            elif 15 <= v <= 25:
                estimates.append((p - 9.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids and asks:
            fv = (bids[0] + asks[0]) / 2
        else:
            fv = td.get("ipr_fv", 10000.0)

        td["ipr_fv"] = fv
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
        if position >= self.IPR_ASK_THRESH_1 and sell_room > 0:
            ask_qty_1 = min(self.IPR_ASK_QTY_1, sell_room)
            if ask_qty_1 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_1, -ask_qty_1))
                sell_room -= ask_qty_1

        if position >= self.IPR_ASK_THRESH_2 and sell_room > 0:
            ask_qty_2 = min(self.IPR_ASK_QTY_2, sell_room)
            if ask_qty_2 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_2, -ask_qty_2))

        return orders, td
