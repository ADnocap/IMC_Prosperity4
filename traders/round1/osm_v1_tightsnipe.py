"""
OSMIUM Strategy V1: Tight Sniper
- Ultra-tight directional quotes (FV +/- 2-4) on the EXPECTED reversal side
- Wide exit quotes on the other side to unwind inventory
- Exploits wide-book states by stepping into gaps before MM re-quotes
- Higher fill rate per signal, trades volume over edge-per-trade
"""
import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMITS = {OSMIUM: 80, PEPPER: 80}
LONG_RUN_MEAN = 10000


class Trader:

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result: dict[str, list[Order]] = {}
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        if OSMIUM in state.order_depths:
            result[OSMIUM] = self.trade_osmium(state, td)
        if PEPPER in state.order_depths:
            result[PEPPER] = self.trade_pepper(state, td)

        return result, 0, json.dumps(td)

    def trade_osmium(self, state: TradingState, td: dict) -> list[Order]:
        orders: list[Order] = []
        od = state.order_depths[OSMIUM]
        pos = state.position.get(OSMIUM, 0)
        limit = LIMITS[OSMIUM]

        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None
        prev_fv = td.get("osm_fv")
        prev_step = td.get("osm_step", 0)

        fv = prev_fv

        book_state = "unknown"
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0
            if spread == 16:
                fv = int(mid)
                book_state = "symmetric"
            elif spread in (18, 19) and prev_fv is not None:
                book_state = "wide"
            elif spread < 16 and prev_fv is not None:
                book_state = "tight"
            else:
                fv = round(mid)
        elif best_bid is not None and best_ask is None:
            book_state = "bid_only"
        elif best_ask is not None and best_bid is None:
            book_state = "ask_only"

        if fv is None:
            td["osm_fv"] = None
            return orders

        # Detect FV step
        step = 0
        if prev_fv is not None and fv != prev_fv:
            step = 1 if fv > prev_fv else -1
            td["osm_step"] = step
        elif prev_step != 0:
            step = prev_step

        td["osm_fv"] = fv

        # Signals
        reversal = -step if step != 0 else 0  # expected next direction
        dist = fv - LONG_RUN_MEAN
        dist_signal = 0
        if dist > 3:
            dist_signal = -1
        elif dist < -3:
            dist_signal = 1
        combined = reversal + dist_signal  # -2 to +2

        # Inventory pressure: how urgently do we need to unwind?
        inv_ratio = pos / limit  # -1 to +1

        buy_qty = 0
        sell_qty = 0

        # === PHASE 1: Aggressive take mispriced orders ===
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                if ap <= fv - 2:  # anything 2+ below FV is free money
                    vol = abs(od.sell_orders[ap])
                    can = limit - pos - buy_qty
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, ap, t))
                        buy_qty += t
        if od.buy_orders:
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if bp >= fv + 2:
                    vol = od.buy_orders[bp]
                    can = limit + pos - sell_qty
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, bp, -t))
                        sell_qty += t

        # === PHASE 2: Wide book exploitation ===
        # When book is wide (18-19), one side was just hit. Step in front.
        if book_state == "wide":
            if best_ask - fv > fv - best_bid:
                # Ask side is further → ask was hit → place ask closer to FV
                gap_ask = fv + 7  # just inside where MM will re-quote at FV+8
                can = limit + pos - sell_qty
                sz = min(10, can)
                if sz > 0:
                    orders.append(Order(OSMIUM, gap_ask, -sz))
                    sell_qty += sz
            else:
                gap_bid = fv - 7
                can = limit - pos - buy_qty
                sz = min(10, can)
                if sz > 0:
                    orders.append(Order(OSMIUM, gap_bid, sz))
                    buy_qty += sz

        # === PHASE 3: Directional tight quotes ===
        # Signal side: tight quote (FV +/- 3)
        # Counter side: wider quote (FV +/- 6) for inventory unwinding

        signal_spread = 3  # tight on the signal side
        exit_spread = 6    # wider on the exit side
        base_size = 15

        # Adjust for inventory: want to unwind faster when heavily loaded
        inv_urgency = max(0, abs(inv_ratio) - 0.3) / 0.7  # 0 below 30%, ramps to 1

        if combined > 0:
            # Expect price UP → want to BUY (signal side) and SELL wide (exit)
            bid_p = fv - signal_spread
            ask_p = fv + exit_spread
            # Boost buy size when signal is strong, reduce sell size
            buy_size = min(base_size + combined * 3, limit - pos - buy_qty)
            sell_size = min(base_size - 5 + int(inv_urgency * 10), limit + pos - sell_qty)
        elif combined < 0:
            # Expect price DOWN → want to SELL (signal side) and BUY wide (exit)
            bid_p = fv - exit_spread
            ask_p = fv + signal_spread
            sell_size = min(base_size + abs(combined) * 3, limit + pos - sell_qty)
            buy_size = min(base_size - 5 + int(inv_urgency * 10), limit - pos - buy_qty)
        else:
            # No signal → symmetric wider quotes
            bid_p = fv - 5
            ask_p = fv + 5
            buy_size = min(base_size - 5, limit - pos - buy_qty)
            sell_size = min(base_size - 5, limit + pos - sell_qty)

        # Inventory override: if we're heavily loaded, force exit
        if inv_ratio > 0.5:
            # Long → aggressive sell
            ask_p = min(ask_p, fv + 2)
            sell_size = max(sell_size, min(20, limit + pos - sell_qty))
        elif inv_ratio < -0.5:
            bid_p = max(bid_p, fv - 2)
            buy_size = max(buy_size, min(20, limit - pos - buy_qty))

        if bid_p >= ask_p:
            bid_p = fv - 1
            ask_p = fv + 1

        buy_size = int(max(0, buy_size))
        sell_size = int(max(0, sell_size))

        if buy_size > 0:
            orders.append(Order(OSMIUM, bid_p, buy_size))
        if sell_size > 0:
            orders.append(Order(OSMIUM, ask_p, -sell_size))

        return orders

    def trade_pepper(self, state: TradingState, td: dict) -> list[Order]:
        # Identical PEPPER logic from c.py
        orders = []
        od = state.order_depths[PEPPER]
        pos = state.position.get(PEPPER, 0)
        limit = LIMITS[PEPPER]
        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None
        if best_bid is None or best_ask is None:
            return orders
        mid = (best_bid + best_ask) / 2.0
        prev_ema = td.get("pep_ema")
        ema = mid if prev_ema is None else 0.3 * mid + 0.7 * prev_ema
        td["pep_ema"] = ema
        prev_slow = td.get("pep_slow_ema")
        slow_ema = mid if prev_slow is None else 0.05 * mid + 0.95 * prev_slow
        td["pep_slow_ema"] = slow_ema
        trend = 0
        diff = ema - slow_ema
        if diff > 1.0: trend = 1
        elif diff < -1.0: trend = -1
        fv = round(ema)
        inv_skew = pos / limit
        net_skew = trend * 1.5 - inv_skew * 3.0
        bid_p = round(fv - 5 + net_skew)
        ask_p = round(fv + 5 + net_skew)
        if bid_p >= ask_p:
            bid_p, ask_p = fv - 1, fv + 1
        inv_pen = abs(pos) / limit
        sz = max(1, round(10 * (1 - inv_pen * 0.5)))
        br = limit - pos
        if min(sz, br) > 0:
            orders.append(Order(PEPPER, bid_p, min(sz, br)))
        sr = limit + pos
        if min(sz, sr) > 0:
            orders.append(Order(PEPPER, ask_p, -min(sz, sr)))
        return orders
