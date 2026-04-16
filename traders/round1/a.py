import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMITS = {OSMIUM: 80, PEPPER: 80}


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
                result[product] = self._trade_pepper(od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    # ==================================================================
    #  OSMIUM: FV±3 tight MM
    #
    #  Hypothesis: real server has price-sensitive taker bots.
    #  Top teams trade at avg fill 2.32 and make 8,924 on OSMIUM.
    #  Tighter spreads get more fills, compensating for lower spread.
    #
    #  Also uses run-length signal for PRICE SKEW (not sizing):
    #  - Both sides always have full capacity (no lost counter-fills)
    #  - Signal shifts quotes 1 tick toward expected reversal
    # ==================================================================
    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        limit = LIMITS[OSMIUM]
        starting_pos = position

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._extract_fv(od, bids_sorted, asks_sorted, td)
        if fv is None:
            return orders, td

        fv_r = int(round(fv))

        # --- Run-length tracking ---
        prev_fv_r = td.get("osm_fv_r")
        run_dir = td.get("osm_run_dir", 0)
        run_len = td.get("osm_run_len", 0)

        if prev_fv_r is not None and fv_r != prev_fv_r:
            step = 1 if fv_r > prev_fv_r else -1
            if step == run_dir:
                run_len += 1
            else:
                run_dir = step
                run_len = 1

        td["osm_fv_r"] = fv_r
        td["osm_fv"] = fv
        td["osm_run_dir"] = run_dir
        td["osm_run_len"] = run_len

        exp_dir = -run_dir if run_dir != 0 else 0

        buy_ordered = 0
        sell_ordered = 0

        # --- Phase 1: Take mispriced orders ---
        for ask_price in asks_sorted:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - starting_pos - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order(OSMIUM, ask_price, qty))
            buy_ordered += qty

        for bid_price in bids_sorted:
            if bid_price < fv_r:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + starting_pos - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order(OSMIUM, bid_price, -qty))
            sell_ordered += qty

        # --- Phase 2: Passive quoting at FV±3 ---
        buy_room = limit - starting_pos - buy_ordered
        sell_room = limit + starting_pos - sell_ordered

        inv_ratio = starting_pos / limit

        # Price skew: shift toward expected reversal (1 tick when signal exists)
        signal_skew = 0
        if exp_dir > 0 and run_len >= 2:
            signal_skew = 1   # shift up: tighter bid, wider ask
        elif exp_dir < 0 and run_len >= 2:
            signal_skew = -1  # shift down: wider bid, tighter ask

        # Inventory skew
        inv_skew = round(-inv_ratio * 2)

        total_skew = signal_skew + inv_skew

        our_bid = fv_r - 3 + total_skew
        our_ask = fv_r + 3 + total_skew

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        # Full capacity both sides (no asymmetric sizing)
        pb = min(buy_room, buy_room)  # max available
        ps = min(sell_room, sell_room)

        if pb > 0:
            orders.append(Order(OSMIUM, our_bid, pb))
        if ps > 0:
            orders.append(Order(OSMIUM, our_ask, -ps))

        return orders, td

    def _extract_fv(self, od, bids, asks, td):
        if not bids and not asks:
            return td.get("osm_fv")

        if bids and asks:
            spread = asks[0] - bids[0]
            mid = (bids[0] + asks[0]) / 2.0

            if spread == 16:
                return int(mid)

            if 17 <= spread <= 19:
                bv1 = od.buy_orders.get(bids[0], 0)
                av1 = abs(od.sell_orders.get(asks[0], 0))
                if av1 > bv1 and bv1 > 0:
                    return bids[0] + 8
                elif bv1 > av1 and av1 > 0:
                    return asks[0] - 8
                prev = td.get("osm_fv")
                return prev if prev is not None else round(mid)

            prev = td.get("osm_fv")
            return prev if prev is not None else round(mid)

        if bids:
            for p in bids:
                vol = od.buy_orders[p]
                if 10 <= vol <= 15:
                    return p + 8
                elif vol >= 20:
                    return p + 10.5
            return td.get("osm_fv", bids[0] + 8)

        if asks:
            for p in asks:
                vol = abs(od.sell_orders[p])
                if 10 <= vol <= 15:
                    return p - 8
                elif vol >= 20:
                    return p - 10.5
            return td.get("osm_fv", asks[0] - 8)

        return td.get("osm_fv")

    # ==================================================================
    #  PEPPER: Buy-and-hold for deterministic drift (+0.1/tick)
    # ==================================================================
    def _trade_pepper(self, od: OrderDepth, position: int) -> list:
        orders = []
        limit = LIMITS[PEPPER]
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
                    orders.append(Order(PEPPER, ask_price, qty))
                    remaining -= qty
                if remaining <= 0:
                    break

        if remaining > 0 and od.buy_orders:
            best_bid = max(od.buy_orders.keys())
            orders.append(Order(PEPPER, best_bid + 1, remaining))

        return orders
