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

# ACO micro skew controls (strict + time gated).
ACO_OBI_TRIGGER = 0.60
ACO_OBI_INV_GATE = 12
ACO_OBI_MIN_TOTAL = 24
ACO_OBI_LAST_TS = 70000
# OBI-gated taking controls (very small size).
ACO_OBI_TAKE_TRIGGER = 0.55
ACO_OBI_TAKE_MAX = 10
ACO_OBI_TAKE_INV_GATE = 20


class Trader:
    """
    spongebob_v2 — MrPing_v6 tuned for Round 2 MAF +25% quote regime.

    Delta vs MrPing_v6:
      - IPR_ASK_OFFSET: 8 -> 9  (wider passive ask; denser book supports it)
      - OSMIUM take:    always edge-1, ungated  (was OBI-gated only)

    Dominates MrPing_v6 in both qf=0.8 and qf=1.25 MC scenarios.
    """

    # R2 Market Access Fee. Top 50% of bids (strictly above median) pay bid once
    # and get +25% quote volume during final sim. Cap: V ~ 1,400-1,500. Don't exceed.
    MAF_BID = 500

    def bid(self):
        return self.MAF_BID

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
                orders, td = self._trade_osmium(od, pos, td, state.timestamp)
            elif product == PEPPER:
                orders, td = self._trade_ipr(od, pos, td)
            else:
                orders = []

            result[product] = orders

        trader_data_str = json.dumps(td)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ==================================================================
    # ASH_COATED_OSMIUM — Alex base + V4/V5 L2 wall detection
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

    def _obi_skew(self, od: OrderDepth, bids: List[int], asks: List[int], pos_after: int, timestamp: int) -> int:
        """Return a tiny directional skew from L1 imbalance, with strict guards."""
        if not bids or not asks:
            return 0
        if timestamp >= ACO_OBI_LAST_TS:
            return 0
        if abs(pos_after) > ACO_OBI_INV_GATE:
            return 0

        best_bid = bids[0]
        best_ask = asks[0]
        bid_vol = od.buy_orders.get(best_bid, 0)
        ask_vol = -od.sell_orders.get(best_ask, 0)
        total = bid_vol + ask_vol
        if total < ACO_OBI_MIN_TOTAL:
            return 0

        obi = (bid_vol - ask_vol) / total
        if obi >= ACO_OBI_TRIGGER:
            return 1
        if obi <= -ACO_OBI_TRIGGER:
            return -1
        return 0

    def _trade_osmium(self, od: OrderDepth, position: int, td: dict, timestamp: int):
        orders = []
        starting_pos = position

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td

        fv_r = int(round(fv))
        td["fv"] = fv

        # Small OBI-gated edge-1 taking allowances.
        buy_take_edge = 1
        sell_take_edge = 1
        extra_buy_room = LIMIT
        extra_sell_room = LIMIT

        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: TAKE — edge >= 2 (alex)
        for ap in asks:
            if ap > fv_r - buy_take_edge:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - starting_pos - buy_ordered
            if buy_take_edge == 1 and ap == fv_r - 1:
                can = min(can, extra_buy_room)
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty
            if buy_take_edge == 1 and ap == fv_r - 1:
                extra_buy_room -= qty

        for bp in bids:
            if bp < fv_r + sell_take_edge:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + starting_pos - sell_ordered
            if sell_take_edge == 1 and bp == fv_r + 1:
                can = min(can, extra_sell_room)
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty
            if sell_take_edge == 1 and bp == fv_r + 1:
                extra_sell_room -= qty

        # Phase 2: CLEAR — flatten at FV (alex)
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

        # Phase 3: MAKE — V4/V5 L2 wall detection + penny-jump, capped at 40
        buy_room = LIMIT - starting_pos - buy_ordered
        sell_room = LIMIT + starting_pos - sell_ordered
        buy_room = min(buy_room, 40)
        sell_room = min(sell_room, 40)

        ref_bid = self._find_wall_bid(bids, fv_r)
        ref_ask = self._find_wall_ask(asks, fv_r)

        center = fv_r + self._obi_skew(od, bids, asks, pos_after, timestamp)
        our_bid = min(ref_bid + 1, center - 1)
        our_ask = max(ref_ask - 1, center + 1)

        if our_bid >= our_ask:
            our_bid = center - 1
            our_ask = center + 1

        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))

        return orders, td

    # ==================================================================
    # INTARIAN_PEPPER_ROOT — TaiLUNG v1 IPR (unchanged)
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

    IPR_ASK_OFFSET = 9

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
        if position >= 70:
            our_ask = fv_r + self.IPR_ASK_OFFSET
            ask_qty = min(15, sell_room)
            if ask_qty > 0:
                orders.append(Order(PEPPER, our_ask, -ask_qty))

        return orders, td
