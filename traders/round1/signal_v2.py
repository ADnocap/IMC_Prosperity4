import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80
MEAN = 10000

# ─── v2: Reversal-aware MM with asymmetric spread ─────────────────
#
# Instead of size asymmetry (which loses MM income), use SPREAD
# asymmetry: quote TIGHTER on the side where we expect a fill to
# move us toward the signal-indicated direction. The tighter quote
# gets order priority (penny-jumps harder) without losing edge.
#
# Key: when signal says "go short", our ASK should be more
# competitive (closer to FV) to attract sells, while our BID
# stays at the standard level.
# ──────────────────────────────────────────────────────────────────


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

        # OBI adjustment
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        obi = (total_bid - total_ask) / total if total > 0 else 0
        fv = fv + 2.0 * obi

        fv_r = int(round(fv))

        # Compute reversal signal
        last_fv = td.get("last_fv")
        signal = 0  # positive = expect up, negative = expect down
        if last_fv is not None:
            step = fv - last_fv
            if abs(step) > 0.05:
                # 65% reversal probability → expected direction is opposite
                signal = -1 if step > 0 else 1

        # Run-length tracking
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

        # Strengthen signal for long runs
        if run_len >= 3 and signal != 0:
            signal *= 2  # Double confidence

        # Distance from mean adds to signal
        dist = fv - MEAN
        if abs(dist) > 5:
            signal -= 1 if dist > 0 else -1

        td["last_fv"] = fv
        td["fv"] = fv

        buy_ordered = 0
        sell_ordered = 0

        # ═══ Phase 1: TAKE ═══
        # Relax take threshold when aligned with signal
        for ap in asks:
            thresh = 1 if signal > 0 else 2  # signal>0 = expect up = want to buy
            if ap > fv_r - thresh:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            thresh = 1 if signal < 0 else 2  # signal<0 = expect down = want to sell
            if bp < fv_r + thresh:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # ═══ Phase 2: CLEAR ═══
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

        # ═══ Phase 3: MAKE — signal-aware penny-jump ═══
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        # Standard penny-jump logic
        our_bid = fv_r - 7
        for bp in bids:
            if bp <= fv_r - 1:
                if fv_r - bp <= 2:
                    our_bid = bp
                else:
                    our_bid = bp + 1
                break

        our_ask = fv_r + 7
        for ap in asks:
            if ap >= fv_r + 1:
                if ap - fv_r <= 2:
                    our_ask = ap
                else:
                    our_ask = ap - 1
                break

        # Signal-based spread adjustment:
        # When signal is strong, tighten the favorable side by 1 tick
        if signal > 0 and our_bid < fv_r - 2:
            our_bid = min(our_bid + 1, fv_r - 1)  # Tighter bid (want to buy)
        elif signal < 0 and our_ask > fv_r + 2:
            our_ask = max(our_ask - 1, fv_r + 1)  # Tighter ask (want to sell)

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
