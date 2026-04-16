"""P3-informed strategy: incorporates specific techniques from top P3 teams.

Changes from best.py:
1. DISREGARD=2 (skip Bot3 orders within 2 of FV - avoids joining at bad priority)
2. Conditional take: edge >= 1 when spread=16 (precise FV), edge >= 2 otherwise
3. Brezina both-sides skew: shift BOTH quotes by position/40 (not tested before)
"""
import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80

DISREGARD = 2   # CHANGED from 1: skip Bot3 near FV (bad priority)
JOIN_EDGE = 2
DEFAULT_EDGE = 7
SKEW_DIVISOR = 40  # Shift both quotes by position / SKEW_DIVISOR


class Trader:

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result: dict[str, list[Order]] = {}
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == OSMIUM:
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == PEPPER:
                result[product], td = self._trade_pepper(od, pos, td)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

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

        # Check spread to determine FV confidence
        spread = None
        if bids and asks:
            spread = asks[0] - bids[0]
        precise_fv = spread is not None and abs(spread - 16) < 0.5

        buy_ordered = 0
        sell_ordered = 0

        # ═══ TAKE: conditional threshold ═══
        # Spread=16 → FV is precise → take at edge >= 1
        # Otherwise → take at edge >= 2 (safe)
        take_thresh = 1 if precise_fv else 2

        for ap in asks:
            if ap > fv_r - take_thresh:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + take_thresh:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # ═══ CLEAR at FV ═══
        pos_after_take = starting_pos + buy_ordered - sell_ordered

        if pos_after_take > 0:
            for bp in bids:
                if bp < fv_r:
                    break
                vol = od.buy_orders[bp]
                can_clear = min(vol, pos_after_take, LIMIT + starting_pos - sell_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, bp, -can_clear))
                    sell_ordered += can_clear
                    pos_after_take -= can_clear

        elif pos_after_take < 0:
            for ap in asks:
                if ap > fv_r:
                    break
                vol = -od.sell_orders[ap]
                can_clear = min(vol, -pos_after_take, LIMIT - starting_pos - buy_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, ap, can_clear))
                    buy_ordered += can_clear
                    pos_after_take += can_clear

        # ═══ MAKE: penny-jump with both-sides skew ═══
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        # Brezina both-sides skew: shift BOTH quotes to reduce inventory
        # Positive position → shift both quotes DOWN → easier sell, harder buy
        skew = int(round(position / SKEW_DIVISOR))

        our_bid = fv_r - DEFAULT_EDGE
        for bp in bids:
            if bp <= fv_r - DISREGARD:
                if fv_r - bp <= JOIN_EDGE:
                    our_bid = bp
                else:
                    our_bid = bp + 1
                break

        our_ask = fv_r + DEFAULT_EDGE
        for ap in asks:
            if ap >= fv_r + DISREGARD:
                if ap - fv_r <= JOIN_EDGE:
                    our_ask = ap
                else:
                    our_ask = ap - 1
                break

        # Apply both-sides skew
        our_bid -= skew
        our_ask -= skew

        # Safety
        our_bid = min(our_bid, fv_r - 1)
        our_ask = max(our_ask, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))

        return orders, td

    def _fv(self, od, bids, asks, td):
        """Bot1-anchored FV with volume-weighted estimation."""
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

    # ── PEPPER: Buy-and-hold, skip Bot 1 ──
    def _trade_pepper(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position
        if remaining <= 0:
            return orders, td
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if vol > 15:
                    continue
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order(PEPPER, ap, qty))
                    remaining -= qty
                if remaining <= 0:
                    break
        if remaining > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order(PEPPER, bb + 1, remaining))
        return orders, td
