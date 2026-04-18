"""sensei: Step-reversal informed MM on OSMIUM, building on tigress.

Portal-validated: step reversal is 84.5% accurate.
Bot1 asymmetry is noise (50.8%) — don't use it.

ACO changes from tigress:
1. OBI adjustment (0.3 coeff) on FV
2. Asymmetric passive caps when signal present (50 on signal side, 30 opposite)

IPR: Sweep small asks + passive bid + passive ask at high position.
"""

import json
from datamodel import Order, OrderDepth, TradingState


OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80
OBI_COEFF = 0.3


class Logger:
    """Compressed logger for the Prosperity visualizer."""

    def __init__(self):
        self.logs = ""

    def print(self, *objects, sep=" ", end="\n"):
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        listings = [[l.symbol, l.product, l.denomination] for l in state.listings.values()] if hasattr(state, 'listings') and state.listings else []
        order_depths = {sym: [od.buy_orders, od.sell_orders] for sym, od in state.order_depths.items()}
        own_trades = []
        if hasattr(state, 'own_trades'):
            for sym, trades in state.own_trades.items():
                for t in trades:
                    own_trades.append([sym, t.price, t.quantity, getattr(t, 'buyer', ''), getattr(t, 'seller', ''), t.timestamp])
        market_trades = []
        if hasattr(state, 'market_trades'):
            for sym, trades in state.market_trades.items():
                for t in trades:
                    market_trades.append([sym, t.price, t.quantity, getattr(t, 'buyer', ''), getattr(t, 'seller', ''), t.timestamp])
        position = state.position if state.position else {}
        observations = [{}, {}]
        if hasattr(state, 'observations') and state.observations:
            obs = state.observations
            if hasattr(obs, 'plainValueObservations') and obs.plainValueObservations:
                observations[0] = obs.plainValueObservations
            if hasattr(obs, 'conversionObservations') and obs.conversionObservations:
                for prod, co in obs.conversionObservations.items():
                    observations[1][prod] = [co.bidPrice, co.askPrice, co.transportFees, co.exportTariff, co.importTariff, co.sugarPrice, co.sunlightIndex]

        compressed = [
            [state.timestamp, state.traderData, listings, order_depths, own_trades, market_trades, position, observations],
            [[sym, o.price, o.quantity] for sym, ol in orders.items() for o in ol],
            conversions, trader_data, self.logs
        ]
        print(json.dumps(compressed, separators=(",", ":")))
        self.logs = ""


logger = Logger()


class Trader:

    LIMIT = 80

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

        trader_data_str = json.dumps(td)
        logger.flush(state, result, 0, trader_data_str)
        return result, 0, trader_data_str

    # ------------------------------------------------------------------
    # OSMIUM FV — Bot1-anchored + OBI
    # ------------------------------------------------------------------
    def _fv(self, od, bids, asks, td):
        if not bids and not asks:
            return td.get("fv")

        # Bot1 anchor (vol >= 20, always reliable)
        bot1_estimates = []
        for p in bids:
            if od.buy_orders[p] >= 20:
                bot1_estimates.append(p + 10.5)
        for p in asks:
            if -od.sell_orders[p] >= 20:
                bot1_estimates.append(p - 10.5)
        bot1_fv = sum(bot1_estimates) / len(bot1_estimates) if bot1_estimates else None

        # Reference FV for Bot3 filtering
        ref_fv = bot1_fv or td.get("fv")
        if ref_fv is None:
            if bids and asks:
                ref_fv = (bids[0] + asks[0]) / 2
            elif bids:
                ref_fv = bids[0] + 8
            else:
                ref_fv = asks[0] - 8

        # Weighted: Bot2 (vol 10-15, weight 2) + Bot1 (vol 20+, weight 1)
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
            fv = sum(e * w for e, w in estimates) / tw
        elif bids and asks:
            fv = (bids[0] + asks[0]) / 2
        elif bids:
            fv = bids[0] + 10.5
        elif asks:
            fv = asks[0] - 10.5
        else:
            return td.get("fv")

        # OBI adjustment
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        if total > 0:
            obi = (total_bid - total_ask) / total
            fv += OBI_COEFF * obi

        return fv

    # ------------------------------------------------------------------
    # OSMIUM: 3-phase with step reversal (tigress architecture)
    # ------------------------------------------------------------------
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

        # --- Step reversal signal ---
        prev_fv = td.get("prev_fv_r")
        if prev_fv is not None and fv_r != prev_fv:
            td["last_step"] = 1 if fv_r > prev_fv else -1
        td["prev_fv_r"] = fv_r

        signal = td.get("last_step", 0)
        bullish = signal < 0   # last step down -> expect up
        bearish = signal > 0   # last step up -> expect down

        buy_ordered = 0
        sell_ordered = 0

        # === Phase 1: TAKE — edge >= 1 on reversal side, >= 2 otherwise ===
        buy_edge = 1 if bullish else 2
        sell_edge = 1 if bearish else 2

        for ap in asks:
            if ap > fv_r - buy_edge:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + sell_edge:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # === Phase 2: CLEAR — reduce position at FV ===
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

        # === Phase 3: PASSIVE — penny-jump with asymmetric caps ===
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        if bullish:
            buy_room = min(buy_room, 50)
            sell_room = min(sell_room, 30)
        elif bearish:
            buy_room = min(buy_room, 30)
            sell_room = min(sell_room, 50)
        else:
            buy_room = min(buy_room, 40)
            sell_room = min(sell_room, 40)

        # Penny-jump logic (from tigress)
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

    # ------------------------------------------------------------------
    # PEPPER — accumulate + passive ask at high position
    # ------------------------------------------------------------------
    IPR_ASK_OFFSET = 5

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

    def _trade_pepper(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position

        fv = self._estimate_ipr_fv(od, td)
        fv_r = int(round(fv))

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        buy_ordered = 0

        # Phase 1: Sweep small asks (vol <= 15)
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
                buy_ordered += qty

        # Phase 2: Passive bid
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = fv_r - 6
            orders.append(Order(PEPPER, our_bid, remaining))

        # Phase 3: Passive ask when position is high
        if position >= 70:
            sell_room = LIMIT + position
            our_ask = fv_r + self.IPR_ASK_OFFSET
            ask_qty = min(10, sell_room)
            if ask_qty > 0:
                orders.append(Order(PEPPER, our_ask, -ask_qty))

        return orders, td
