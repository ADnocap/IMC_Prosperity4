from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


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

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80


class Trader:
    """
    Round 1 — TaiLUNG v4.1.

    Base:
      - TaiLUNG v2 Take/Clear/Make for ACO.
      - TaiLUNG v2 IPR accumulation and passive bid.

    New:
      - Lower-threshold adaptive Bot1 signal activation.
      - Tiny size-only signal skew with strict safety caps.
      - Two-tier IPR passive ask ladder.
    """

    # Adaptive signal controls
    SIGNAL_MIN_COUNT = 120
    SIGNAL_EDGE_ON = 0.18
    SIGNAL_EDGE_OFF = 0.10

    # ACO safety cap
    ACO_SOFT_POS = 30

    # IPR exits
    IPR_ASK_OFFSET_1 = 8
    IPR_ASK_OFFSET_2 = 9
    IPR_ASK_THRESH_1 = 60
    IPR_ASK_THRESH_2 = 75
    IPR_ASK_QTY_1 = 10
    IPR_ASK_QTY_2 = 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == OSMIUM:
                orders, td = self._trade_osmium(od, pos, td)
            elif product == PEPPER:
                orders, td = self._trade_ipr(od, pos, td)
            else:
                orders = []

            result[product] = orders

        trader_data_str = json.dumps(td)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ==================================================================
    # ASH_COATED_OSMIUM
    # ==================================================================
    def _fv(self, od, bids, asks, td):
        """Bot1-anchored FV estimation (alex)."""
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

    def _detect_bot1_asym(self, od, bids, asks, fv_r):
        """Raw Bot1 signal: +1 bullish, -1 bearish, 0 unavailable."""
        bid_off = None
        ask_off = None

        for p in bids:
            v = od.buy_orders[p]
            if 20 <= v <= 30:
                bid_off = fv_r - p
                break

        for p in asks:
            v = -od.sell_orders[p]
            if 20 <= v <= 30:
                ask_off = p - fv_r
                break

        if bid_off in (10, 11) and ask_off in (10, 11) and bid_off != ask_off:
            return ask_off - bid_off
        return 0

    def _signal_mode(self, td: dict, fv_r: int) -> int:
        """
        Adaptive signal mode:
          +1 -> use raw signal
          -1 -> invert raw signal
           0 -> disabled
        """
        prev_fv = td.get("sig_prev_fv")
        prev_raw = td.get("sig_prev_raw", 0)
        mode = td.get("sig_mode", 0)

        if prev_fv is not None and prev_raw != 0:
            move = fv_r - prev_fv
            if move != 0:
                count = td.get("sig_count", 0) + 1
                score = td.get("sig_score", 0)
                if (prev_raw > 0 and move > 0) or (prev_raw < 0 and move < 0):
                    score += 1
                else:
                    score -= 1
                td["sig_count"] = count
                td["sig_score"] = score

        td["sig_prev_fv"] = fv_r

        count = td.get("sig_count", 0)
        if count < self.SIGNAL_MIN_COUNT:
            td["sig_mode"] = 0
            return 0

        edge = td.get("sig_score", 0) / count

        # Hysteresis to avoid flip-flopping on noise.
        if mode == 0:
            if edge >= self.SIGNAL_EDGE_ON:
                mode = 1
            elif edge <= -self.SIGNAL_EDGE_ON:
                mode = -1
        elif mode == 1:
            if edge < self.SIGNAL_EDGE_OFF:
                mode = 0
        elif mode == -1:
            if edge > -self.SIGNAL_EDGE_OFF:
                mode = 0

        td["sig_mode"] = mode
        return mode

    def _find_wall_bid(self, bids, fv_r):
        """V4/V5 wall detection: skip L1 noise, find real wall."""
        if len(bids) >= 3:
            return bids[1]
        if len(bids) >= 2:
            if fv_r - bids[0] >= 5:
                return bids[0]
            else:
                return bids[1]
        if bids:
            return bids[0]
        return fv_r - 10

    def _find_wall_ask(self, asks, fv_r):
        """V4/V5 wall detection: skip L1 noise, find real wall."""
        if len(asks) >= 3:
            return asks[1]
        if len(asks) >= 2:
            if asks[0] - fv_r >= 5:
                return asks[0]
            else:
                return asks[1]
        if asks:
            return asks[0]
        return fv_r + 10

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

        mode = self._signal_mode(td, fv_r)
        raw_signal = self._detect_bot1_asym(od, bids, asks, fv_r)
        td["sig_prev_raw"] = raw_signal
        signal = raw_signal * mode

        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: TAKE — edge >= 2 (v2 baseline)
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

        # Phase 2: CLEAR — flatten at FV (v2 baseline)
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

        # Phase 3: MAKE — baseline quotes + tiny size-only signal skew
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        ref_bid = self._find_wall_bid(bids, fv_r)
        ref_ask = self._find_wall_ask(asks, fv_r)
        base_bid = min(ref_bid + 1, fv_r - 1)
        base_ask = max(ref_ask - 1, fv_r + 1)

        our_bid = base_bid
        our_ask = base_ask
        buy_cap = 40
        sell_cap = 40

        if signal > 0 and abs(pos_after) < self.ACO_SOFT_POS:
            buy_cap, sell_cap = 41, 39
        elif signal < 0 and abs(pos_after) < self.ACO_SOFT_POS:
            buy_cap, sell_cap = 39, 41

        # Strict safety cap only when adaptive signal mode is active.
        if mode != 0:
            if pos_after >= self.ACO_SOFT_POS:
                buy_cap = min(buy_cap, 30)
                sell_cap = max(sell_cap, 45)
            elif pos_after <= -self.ACO_SOFT_POS:
                buy_cap = max(buy_cap, 45)
                sell_cap = min(sell_cap, 30)

        buy_room = min(buy_room, buy_cap)
        sell_room = min(sell_room, sell_cap)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))

        return orders, td

    # ==================================================================
    # INTARIAN_PEPPER_ROOT
    # ==================================================================
    def _estimate_ipr_fv(self, od: OrderDepth, td: dict) -> float:
        """Estimate IPR fair value from bot walls."""
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

    def _trade_ipr(self, od: OrderDepth, position: int, td: dict):
        orders = []
        remaining = LIMIT - position

        fv = self._estimate_ipr_fv(od, td)
        fv_r = int(round(fv))

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        # Accumulate: sweep asks vol <= 15 (Bot 2 + Bot 3, skip Bot 1)
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

        # Passive bid: penny-jump best bid
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = fv_r - 6
            orders.append(Order(PEPPER, our_bid, remaining))

        # Two-tier passive exit ladder.
        sell_room = LIMIT + position
        if position >= self.IPR_ASK_THRESH_1 and sell_room > 0:
            ask_qty_1 = min(self.IPR_ASK_QTY_1, sell_room)
            if ask_qty_1 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_1, -ask_qty_1))
                sell_room -= ask_qty_1

        if position >= self.IPR_ASK_THRESH_2 and sell_room > 0:
            ask_qty_2 = min(self.IPR_ASK_QTY_2, sell_room)
            if ask_qty_2 > 0:
                orders.append(Order(PEPPER, fv_r + self.IPR_ASK_OFFSET_2, -ask_qty_2))

        return orders, td
