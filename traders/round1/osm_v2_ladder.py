"""
OSMIUM Strategy V2: Multi-Level Ladder
- Place orders at MULTIPLE price levels (FV+/-3, FV+/-5, FV+/-7)
- Asymmetric sizing: heavier on the signal side
- Captures depth at different fill probabilities
- More resilient to book disruptions
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
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0
            if spread == 16:
                fv = int(mid)
            elif spread <= 19 and prev_fv is not None:
                pass
            else:
                fv = round(mid)

        if fv is None:
            td["osm_fv"] = None
            return orders

        step = 0
        if prev_fv is not None and fv != prev_fv:
            step = 1 if fv > prev_fv else -1
            td["osm_step"] = step
        elif prev_step != 0:
            step = prev_step
        td["osm_fv"] = fv

        # Signals
        reversal = -step if step != 0 else 0
        dist = fv - LONG_RUN_MEAN
        dist_signal = -1 if dist > 3 else (1 if dist < -3 else 0)
        combined = reversal + dist_signal  # -2 to +2
        inv_ratio = pos / limit

        buy_used, sell_used = 0, 0

        # === Take mispriced ===
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                if ap <= fv - 1:
                    vol = abs(od.sell_orders[ap])
                    can = limit - pos - buy_used
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, ap, t))
                        buy_used += t
        if od.buy_orders:
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if bp >= fv + 1:
                    vol = od.buy_orders[bp]
                    can = limit + pos - sell_used
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, bp, -t))
                        sell_used += t

        # === Multi-level ladder ===
        # Define price levels and base sizes
        # Levels closer to FV get smaller size (higher fill prob, higher risk)
        # Levels further get larger size (lower fill prob, safer)
        levels = [
            (3, 5),   # offset=3, base_size=5  (tight, risky)
            (5, 8),   # offset=5, base_size=8  (medium)
            (7, 10),  # offset=7, base_size=10 (wide, safe)
        ]

        # Skew factor: positive = favor buying
        skew = combined * 0.4 - inv_ratio * 1.5

        total_buy_room = limit - pos - buy_used
        total_sell_room = limit + pos - sell_used

        for offset, base_sz in levels:
            # Apply skew: multiply signal-side size, reduce counter-side
            if skew > 0:  # favor buying
                buy_mult = 1.0 + skew * 0.5
                sell_mult = max(0.3, 1.0 - skew * 0.3)
            elif skew < 0:
                buy_mult = max(0.3, 1.0 + skew * 0.3)  # skew is negative
                sell_mult = 1.0 - skew * 0.5
            else:
                buy_mult = sell_mult = 1.0

            buy_sz = int(round(base_sz * buy_mult))
            sell_sz = int(round(base_sz * sell_mult))

            # Apply inventory penalty to the overloaded side
            if inv_ratio > 0.4:
                buy_sz = max(1, int(buy_sz * (1 - inv_ratio)))
            elif inv_ratio < -0.4:
                sell_sz = max(1, int(sell_sz * (1 + inv_ratio)))

            # Place orders within remaining room
            actual_buy = min(buy_sz, total_buy_room)
            if actual_buy > 0:
                orders.append(Order(OSMIUM, fv - offset, actual_buy))
                total_buy_room -= actual_buy

            actual_sell = min(sell_sz, total_sell_room)
            if actual_sell > 0:
                orders.append(Order(OSMIUM, fv + offset, -actual_sell))
                total_sell_room -= actual_sell

        return orders

    def trade_pepper(self, state: TradingState, td: dict) -> list[Order]:
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
