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

# ACO making constants
DISREGARD = 1
JOIN_EDGE = 2
DEFAULT_EDGE = 7


class Trader:
    """
    Round 1 — TaiLUNG.

    ACO: P3-inspired three-phase (Take/Clear/Make) with Bot1-anchored FV,
         penny/join passive quoting.
    IPR: Fast accumulation (sweep vol <= 15) + passive bid + FV-aware
         passive ask at FV+8 to capture trade bot buys when Bot 2 absent.
    """

    # ACO microstructure signal controls.
    ACO_OBI_TRIGGER = 0.40
    ACO_MID_ALPHA = 0.08
    ACO_MID_DEV_TRIGGER = 1.60
    ACO_RET_WINDOW = 16
    ACO_RECENT_RET = 4
    ACO_VOL_WIDEN = 1.20
    ACO_VOL_WIDEN_STRONG = 1.60

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
    # ASH_COATED_OSMIUM — P3-inspired Take/Clear/Make
    # ==================================================================
    def _fv(self, od, bids, asks, td):
        """Bot1-anchored FV estimation."""
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

        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: TAKE — grab mispriced orders (edge >= 2)
        take_thresh = 2
        for ap in asks:
            if ap > fv_r - take_thresh:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + take_thresh:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # Phase 2: CLEAR — flatten inventory at FV (0-edge)
        pos_after_take = starting_pos + buy_ordered - sell_ordered

        if pos_after_take > 0:
            for bp in bids:
                if bp < fv_r:
                    break
                vol = od.buy_orders[bp]
                can_clear = min(vol, pos_after_take, LIMIT + starting_pos - sell_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, bp, -can_clear))
                    sell_ordered += can_clear
                    pos_after_take -= can_clear

        elif pos_after_take < 0:
            for ap in asks:
                if ap > fv_r:
                    break
                vol = -od.sell_orders[ap]
                can_clear = min(vol, -pos_after_take, LIMIT - starting_pos - buy_ordered)
                if can_clear > 0:
                    orders.append(Order(OSMIUM, ap, can_clear))
                    buy_ordered += can_clear
                    pos_after_take += can_clear

        # Phase 3: MAKE — penny/join passive quoting
        directional_skew, make_edge = self._aco_make_signal(od, bids, asks, td)
        center = fv_r + directional_skew

        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered

        our_bid = center - make_edge
        for bp in bids:
            if bp <= center - DISREGARD:
                if center - bp <= JOIN_EDGE:
                    our_bid = bp
                else:
                    our_bid = bp + 1
                break

        our_ask = center + make_edge
        for ap in asks:
            if ap >= center + DISREGARD:
                if ap - center <= JOIN_EDGE:
                    our_ask = ap
                else:
                    our_ask = ap - 1
                break

        our_bid = min(our_bid, center - 1)
        our_ask = max(our_ask, center + 1)
        if our_bid >= our_ask:
            our_bid = center - 1
            our_ask = center + 1

        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))

        return orders, td

    def _aco_make_signal(self, od: OrderDepth, bids: List[int], asks: List[int], td: dict):
        """Return (directional center skew in ticks, adaptive make edge)."""
        if not bids or not asks:
            return 0, DEFAULT_EDGE

        best_bid = bids[0]
        best_ask = asks[0]
        mid = (best_bid + best_ask) / 2

        # L1 imbalance: robust directional cue for next-tick return.
        bid_vol = od.buy_orders.get(best_bid, 0)
        ask_vol = -od.sell_orders.get(best_ask, 0)
        total = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / total if total > 0 else 0.0
        if abs(obi) >= self.ACO_OBI_TRIGGER:
            obi_skew = 1 if obi > 0 else -1
        else:
            obi_skew = 0

        # Mid deviation from EMA mean: weak mean-reversion fallback cue.
        ema = td.get("aco_mid_ema", mid)
        ema = self.ACO_MID_ALPHA * mid + (1 - self.ACO_MID_ALPHA) * ema
        td["aco_mid_ema"] = ema

        mid_dev = mid - ema
        if mid_dev >= self.ACO_MID_DEV_TRIGGER:
            dev_skew = -1
        elif mid_dev <= -self.ACO_MID_DEV_TRIGGER:
            dev_skew = 1
        else:
            dev_skew = 0

        directional_skew = obi_skew if obi_skew != 0 else dev_skew

        # Volatility clustering: widen edge after elevated |mid returns|.
        abs_rets = td.get("aco_abs_rets", [])
        prev_mid = td.get("aco_prev_mid")
        if prev_mid is not None:
            abs_rets.append(abs(mid - prev_mid))
            if len(abs_rets) > self.ACO_RET_WINDOW:
                abs_rets = abs_rets[-self.ACO_RET_WINDOW:]
        td["aco_prev_mid"] = mid
        td["aco_abs_rets"] = abs_rets

        make_edge = DEFAULT_EDGE
        if len(abs_rets) >= self.ACO_RECENT_RET + 2:
            recent = sum(abs_rets[-self.ACO_RECENT_RET:]) / self.ACO_RECENT_RET
            long = sum(abs_rets) / len(abs_rets)
            if long > 0:
                ratio = recent / long
                if ratio >= self.ACO_VOL_WIDEN_STRONG:
                    make_edge += 2
                elif ratio >= self.ACO_VOL_WIDEN:
                    make_edge += 1

        td["aco_obi"] = obi
        td["aco_mid_dev"] = mid_dev
        td["aco_dir_skew"] = directional_skew
        td["aco_make_edge"] = make_edge
        return directional_skew, make_edge

    # ==================================================================
    # INTARIAN_PEPPER_ROOT — accumulate + FV-aware passive ask
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

    IPR_ASK_OFFSET = 8

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

        # Passive ask at FV+8: fills when Bot 2 absent (~20%), sells above rebuy cost
        sell_room = LIMIT + position
        if position >= 60:
            our_ask = fv_r + self.IPR_ASK_OFFSET
            ask_qty = min(25, sell_room)
            if ask_qty > 0:
                orders.append(Order(PEPPER, our_ask, -ask_qty))

        return orders, td