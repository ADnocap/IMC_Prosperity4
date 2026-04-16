import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80
MEAN = 10000  # OU mean for OSMIUM

# ─── Signal-Based Market Making ───────────────────────────────────
#
# Combines best.py's proven take/clear/make framework with
# SIGNAL-DRIVEN size asymmetry. Unlike inventory skew (which
# reduces alpha by unwinding correct-direction positions), this
# targets a DESIRED position based on the mean-reversion signal.
#
# Key insight: When FV > 10000, we WANT to be short (expecting
# reversion down). When FV < 10000, we WANT to be long. Size
# our quotes asymmetrically to drift toward the target.
#
# Phase 1: TAKE — grab mispriced orders (edge >= 2, relaxed to 1
#           when aligned with strong signal)
# Phase 2: CLEAR — flatten toward TARGET (not zero!) at FV
# Phase 3: MAKE — penny-jump with asymmetric sizing
# ──────────────────────────────────────────────────────────────────

DISREGARD = 1
JOIN_EDGE = 2
DEFAULT_EDGE = 7

# Signal parameters
DISTANCE_COEFF = 3.0   # target_pos units per tick of distance from mean
STEP_COEFF = 8.0       # target_pos adjustment per step direction
MAX_TARGET = 50        # max absolute target position
MIN_COUNTER_SIZE = 15  # minimum quote size on counter-signal side
OBI_COEFF = 2.0        # FV adjustment per unit of OBI (from g2.py)


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

    def _compute_signal(self, fv, td):
        """Compute mean-reversion signal → target position.

        Positive signal = want long. Negative = want short.
        """
        signal = 0.0

        # 1. Distance from mean: fade deviations
        distance = fv - MEAN
        signal -= distance * DISTANCE_COEFF

        # 2. Step reversal: 65% probability of reversal
        last_fv = td.get("last_fv")
        if last_fv is not None:
            step = fv - last_fv
            if abs(step) > 0.05:
                signal -= step * STEP_COEFF

        # 3. Run-length escalation: longer runs → stronger reversal
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
            # Don't update if FV unchanged
        td["run_dir"] = run_dir
        td["run_len"] = run_len

        # Escalate signal for long runs (super-geometric reversal)
        if run_len >= 3:
            signal -= run_dir * 15.0  # Strong reversal bet
        elif run_len >= 2:
            signal -= run_dir * 5.0

        target = int(round(signal))
        target = max(-MAX_TARGET, min(MAX_TARGET, target))
        return target

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict):
        orders = []
        starting_pos = position

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td

        # Apply OBI adjustment (from g2.py)
        obi = self._compute_obi(od)
        fv = fv + OBI_COEFF * obi

        fv_r = int(round(fv))

        # Compute signal and target position
        target_pos = self._compute_signal(fv, td)
        td["last_fv"] = fv
        td["fv"] = fv
        td["target"] = target_pos

        buy_ordered = 0
        sell_ordered = 0

        # ══════════════════════════════════════════════════════
        # Phase 1: TAKE — grab mispriced orders
        # Standard threshold = 2, relaxed to 1 when aligned with signal
        # ══════════════════════════════════════════════════════
        buy_take_thresh = 2
        sell_take_thresh = 2

        # Relax threshold when signal is strong and aligned
        if target_pos > 20:
            buy_take_thresh = 1   # More aggressive buying
        elif target_pos < -20:
            sell_take_thresh = 1  # More aggressive selling

        for ap in asks:
            if ap > fv_r - buy_take_thresh:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + sell_take_thresh:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # ══════════════════════════════════════════════════════
        # Phase 2: CLEAR — flatten toward TARGET (not zero!)
        # If pos is farther from target than from zero, clear
        # more aggressively to get closer to target.
        # ══════════════════════════════════════════════════════
        pos_after_take = starting_pos + buy_ordered - sell_ordered

        if pos_after_take > max(0, target_pos):
            # Too long relative to target → sell to bids at FV+
            for bp in bids:
                if bp < fv_r:
                    break
                vol = od.buy_orders[bp]
                excess = pos_after_take - max(0, target_pos)
                can_clear = min(vol, excess, LIMIT + starting_pos - sell_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, bp, -can_clear))
                    sell_ordered += can_clear
                    pos_after_take -= can_clear

        elif pos_after_take < min(0, target_pos):
            # Too short relative to target → buy asks at FV-
            for ap in asks:
                if ap > fv_r:
                    break
                vol = -od.sell_orders[ap]
                excess = min(0, target_pos) - pos_after_take
                can_clear = min(vol, excess, LIMIT - starting_pos - buy_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, ap, can_clear))
                    buy_ordered += can_clear
                    pos_after_take += can_clear

        # ══════════════════════════════════════════════════════
        # Phase 3: MAKE — penny/jump with SIGNAL-BASED sizing
        # Full size on signal side, reduced on counter side.
        # ══════════════════════════════════════════════════════
        max_buy = LIMIT - starting_pos - buy_ordered
        max_sell = LIMIT + starting_pos - sell_ordered

        # Compute desired sizes based on signal
        pos_gap = target_pos - pos_after_take

        if pos_gap > 10:
            # Want more long → full buy, reduced sell
            buy_room = max_buy
            sell_room = max(min(max_sell, MIN_COUNTER_SIZE), 0)
        elif pos_gap < -10:
            # Want more short → reduced buy, full sell
            buy_room = max(min(max_buy, MIN_COUNTER_SIZE), 0)
            sell_room = max_sell
        else:
            # Near target → symmetric
            buy_room = max_buy
            sell_room = max_sell

        # Find best levels to penny/join
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

    def _compute_obi(self, od):
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    # ── PEPPER: Buy-and-hold, skip Bot 1 ──
    def _trade_pepper(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position
        if remaining <= 0:
            return orders, td
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if vol > 15:  # Skip Bot 1 (vol 15-25)
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
