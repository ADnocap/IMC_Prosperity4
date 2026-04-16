"""Stable FV: only update FV from spread-16 ticks (most precise).
On non-16 ticks, keep the last known FV. This should give more
accurate taking decisions and quote placement.

Also takes at edge >= 1 (more aggressive) since FV is now more reliable."""
import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80

DISREGARD = 1
JOIN_EDGE = 2
DEFAULT_EDGE = 7
TAKE_EDGE = 1  # More aggressive taking with reliable FV


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

        if not bids and not asks:
            return orders, td

        # ═══ STABLE FV ESTIMATION ═══
        # Only update FV on spread=16 ticks (symmetric book, most precise)
        # On other ticks, use last known FV
        spread = None
        if bids and asks:
            spread = asks[0] - bids[0]

        fv = td.get("fv")

        if spread is not None and abs(spread - 16) < 0.5:
            # Spread = 16: book is symmetric, update FV
            fv = (bids[0] + asks[0]) / 2.0
            td["fv"] = fv
        elif fv is None:
            # Fallback: use volume-weighted estimate
            fv = self._fallback_fv(od, bids, asks, td)
            if fv is not None:
                td["fv"] = fv
            else:
                return orders, td

        fv_r = int(round(fv))

        buy_ordered = 0
        sell_ordered = 0

        # ═══ TAKE at edge >= 1 (reliable FV allows aggressive taking) ═══
        for ap in asks:
            if ap > fv_r - TAKE_EDGE:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + TAKE_EDGE:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # ═══ CLEAR at FV ═══
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

        # ═══ MAKE: penny-jump at FV±7 ═══
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

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

    def _fallback_fv(self, od, bids, asks, td):
        """Fallback FV when no spread-16 anchor available."""
        bot1_estimates = []
        for p in bids:
            if od.buy_orders[p] >= 20:
                bot1_estimates.append(p + 10.5)
        for p in asks:
            if -od.sell_orders[p] >= 20:
                bot1_estimates.append(p - 10.5)
        if bot1_estimates:
            return sum(bot1_estimates) / len(bot1_estimates)

        ref_fv = td.get("fv")
        if ref_fv is None:
            if bids and asks:
                return (bids[0] + asks[0]) / 2
            elif bids:
                return bids[0] + 8
            else:
                return asks[0] - 8
        return ref_fv

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
