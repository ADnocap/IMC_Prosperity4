"""
OSMIUM Strategy V3: Position Accumulation + Mean Reversion
- Not a market maker. A directional mean-reversion trader.
- Accumulates positions when FV is far from 10000
- Builds inventory patiently, exits when FV reverts to mean
- Passive orders at FV+/-1 to get best fills when signal is strong
- Falls back to wider MM when signal is weak
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

        dist = fv - LONG_RUN_MEAN
        reversal = -step if step != 0 else 0
        abs_dist = abs(dist)

        buy_used, sell_used = 0, 0

        # === Always take free money ===
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                if ap <= fv - 2:
                    vol = abs(od.sell_orders[ap])
                    can = limit - pos - buy_used
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, ap, t))
                        buy_used += t
        if od.buy_orders:
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if bp >= fv + 2:
                    vol = od.buy_orders[bp]
                    can = limit + pos - sell_used
                    t = min(vol, can)
                    if t > 0:
                        orders.append(Order(OSMIUM, bp, -t))
                        sell_used += t

        # === Core logic: Position accumulation based on distance from mean ===
        # Three regimes based on how far FV is from 10000:

        if abs_dist >= 5:
            # REGIME 1: Strong mean reversion signal
            # Aggressively accumulate position toward the mean
            # Place tight orders (FV+/-1) on the signal side
            # Wide orders (FV+/-6) on the exit side for unwinding

            if dist > 0:
                # FV above mean → want to be SHORT
                # Aggressive sell at tight price
                sell_p = fv + 1
                sell_sz = min(20, limit + pos - sell_used)
                if sell_sz > 0:
                    orders.append(Order(OSMIUM, sell_p, -sell_sz))
                    sell_used += sell_sz
                # Patient buy far below (in case of overshoot, and MM passive)
                buy_p = fv - 7
                buy_sz = min(5, limit - pos - buy_used)
                if buy_sz > 0:
                    orders.append(Order(OSMIUM, buy_p, buy_sz))
                    buy_used += buy_sz
            else:
                # FV below mean → want to be LONG
                buy_p = fv - 1
                buy_sz = min(20, limit - pos - buy_used)
                if buy_sz > 0:
                    orders.append(Order(OSMIUM, buy_p, buy_sz))
                    buy_used += buy_sz
                sell_p = fv + 7
                sell_sz = min(5, limit + pos - sell_used)
                if sell_sz > 0:
                    orders.append(Order(OSMIUM, sell_p, -sell_sz))
                    sell_used += sell_sz

        elif abs_dist >= 2:
            # REGIME 2: Moderate signal - directional MM
            # Skew toward mean with moderate spread
            if dist > 0:
                # Above mean → skew sell side tighter
                sell_p = fv + 3
                buy_p = fv - 6
            else:
                buy_p = fv - 3
                sell_p = fv + 6

            # Size scaled by distance: more when further
            sig_sz = min(12 + abs_dist, 20)
            exit_sz = 8

            sell_sz = min(sig_sz if dist > 0 else exit_sz, limit + pos - sell_used)
            buy_sz = min(sig_sz if dist <= 0 else exit_sz, limit - pos - buy_used)

            # Extra inventory pressure
            if pos > 20:
                sell_p = min(sell_p, fv + 2)
                sell_sz = min(sell_sz + 5, limit + pos - sell_used)
            elif pos < -20:
                buy_p = max(buy_p, fv - 2)
                buy_sz = min(buy_sz + 5, limit - pos - buy_used)

            if buy_p >= sell_p:
                buy_p, sell_p = fv - 1, fv + 1

            if buy_sz > 0:
                orders.append(Order(OSMIUM, buy_p, buy_sz))
                buy_used += buy_sz
            if sell_sz > 0:
                orders.append(Order(OSMIUM, sell_p, -sell_sz))
                sell_used += sell_sz

        else:
            # REGIME 3: Near mean - pure reversal MM
            # Symmetric-ish quotes with step reversal skew
            half_spread = 5
            skew = reversal * 1.0 - (pos / limit) * 3.0

            bid_p = round(fv - half_spread + skew)
            ask_p = round(fv + half_spread + skew)
            if bid_p >= ask_p:
                bid_p, ask_p = fv - 1, fv + 1

            sz = 12
            buy_sz = min(sz, limit - pos - buy_used)
            sell_sz = min(sz, limit + pos - sell_used)

            if buy_sz > 0:
                orders.append(Order(OSMIUM, bid_p, buy_sz))
            if sell_sz > 0:
                orders.append(Order(OSMIUM, ask_p, -sell_sz))

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
