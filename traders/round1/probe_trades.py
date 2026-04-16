"""Probe: dump market_trades on every tick they're non-empty.
Uses signal_mm OSMIUM logic + standard PEPPER for actual trading."""
import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80
MEAN = 10000

DISREGARD = 1
JOIN_EDGE = 2
DEFAULT_EDGE = 7
DISTANCE_COEFF = 3.0
STEP_COEFF = 8.0
MAX_TARGET = 50
MIN_COUNTER_SIZE = 15
OBI_COEFF = 2.0


class Trader:

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result: dict[str, list[Order]] = {}
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        # ── PROBE: market_trades + own_trades ──
        ts = state.timestamp
        has_mt = any(len(v) > 0 for v in state.market_trades.values()) if state.market_trades else False
        if has_mt:
            print(f"MT@{ts}: {state.market_trades}")
        # Also print own_trades when they contain non-empty data (fills from last tick)
        has_ot = any(len(v) > 0 for v in state.own_trades.values()) if state.own_trades else False
        if has_ot and ts <= 5000:
            for sym, trades in state.own_trades.items():
                if sym == OSMIUM and trades:
                    for t in trades:
                        print(f"OT@{ts}: {sym} {t.buyer}<<{t.seller} {t.quantity}@{t.price} ts={t.timestamp}")

        # First tick: dump observations and listings
        if ts == 0:
            print(f"OBS: {state.observations}")
            if state.observations:
                print(f"PLAIN: {state.observations.plainValueObservations}")
                print(f"CONV: {state.observations.conversionObservations}")

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

    def _compute_signal(self, fv, td):
        signal = 0.0
        distance = fv - MEAN
        signal -= distance * DISTANCE_COEFF
        last_fv = td.get("last_fv")
        if last_fv is not None:
            step = fv - last_fv
            if abs(step) > 0.05:
                signal -= step * STEP_COEFF
        run_dir = td.get("run_dir", 0)
        run_len = td.get("run_len", 0)
        if last_fv is not None:
            step = fv - last_fv
            if abs(step) > 0.05:
                new_dir = 1 if step > 0 else -1
                if new_dir == run_dir:
                    run_len += 1
                else:
                    run_dir = new_dir
                    run_len = 1
        td["run_dir"] = run_dir
        td["run_len"] = run_len
        if run_len >= 3:
            signal -= run_dir * 15.0
        elif run_len >= 2:
            signal -= run_dir * 5.0
        target = int(round(signal))
        return max(-MAX_TARGET, min(MAX_TARGET, target))

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        starting_pos = position
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        obi = (total_bid - total_ask) / total if total > 0 else 0
        fv = fv + OBI_COEFF * obi
        fv_r = int(round(fv))
        target_pos = self._compute_signal(fv, td)
        td["last_fv"] = fv
        td["fv"] = fv
        buy_ordered = sell_ordered = 0

        # TAKE
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

        # CLEAR toward target
        pos_after = starting_pos + buy_ordered - sell_ordered
        if pos_after > max(0, target_pos):
            for bp in bids:
                if bp < fv_r:
                    break
                vol = od.buy_orders[bp]
                excess = pos_after - max(0, target_pos)
                c = min(vol, excess, LIMIT + starting_pos - sell_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, bp, -c))
                    sell_ordered += c
                    pos_after -= c
        elif pos_after < min(0, target_pos):
            for ap in asks:
                if ap > fv_r:
                    break
                vol = -od.sell_orders[ap]
                excess = min(0, target_pos) - pos_after
                c = min(vol, excess, LIMIT - starting_pos - buy_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, ap, c))
                    buy_ordered += c
                    pos_after += c

        # MAKE with signal sizing
        max_buy = LIMIT - starting_pos - buy_ordered
        max_sell = LIMIT + starting_pos - sell_ordered
        pos_gap = target_pos - pos_after
        if pos_gap > 10:
            buy_room = max_buy
            sell_room = max(min(max_sell, MIN_COUNTER_SIZE), 0)
        elif pos_gap < -10:
            buy_room = max(min(max_buy, MIN_COUNTER_SIZE), 0)
            sell_room = max_sell
        else:
            buy_room = max_buy
            sell_room = max_sell

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
            if 10 <= v <= 15 and abs(p - (ref_fv - 8)) <= 3:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and abs(p - (ref_fv + 8)) <= 3:
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
