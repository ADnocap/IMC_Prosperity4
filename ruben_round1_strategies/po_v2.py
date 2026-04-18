from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math


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
    """
    Round 1 — Signal-Enhanced MM (optimized for real exchange).

    ACO: Proven penny-jump MM base (unchanged from original) +
         3 directional signals (Bot1 asymmetry 92-95% acc, step reversal
         65% acc, distance-from-mean) that enhance TAKING decisions.
         Quoting is unchanged — signals only affect what we take.
    IPR: Sweep small asks + passive bid (original, proven in MC).

    Design: Signals are designed for the REAL exchange where Bot1
    asymmetry is observable. The MC sim doesn't model Bot1, so signal
    improvements won't show there, but the base strategy is preserved.
    """

    LIMIT = 80
    OBI_COEFF = 0.5
    LONG_RUN_MEAN = 10000

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except json.JSONDecodeError:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == "ASH_COATED_OSMIUM":
                orders, td = self._trade_ash(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_ipr(od, pos)
            else:
                orders = []

            result[product] = orders

        trader_data_str = json.dumps(td)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ------------------------------------------------------------------
    # ACO — FV Estimation (proven weighted wall approach)
    # ------------------------------------------------------------------
    def _estimate_ash_fv(self, od: OrderDepth, td: dict) -> float:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        if not bids and not asks:
            return td.get("ash_fv")

        if bids and asks:
            raw_mid = (bids[0] + asks[0]) / 2
        elif bids:
            last = td.get("ash_fv")
            raw_mid = last if last else bids[0] + 8
        else:
            last = td.get("ash_fv")
            raw_mid = last if last else asks[0] - 8

        estimates = []
        for p in bids:
            v = od.buy_orders[p]
            if 10 <= v <= 15 and raw_mid - p >= 5:
                estimates.append((p + 8, 2.0))
            elif v >= 20:
                estimates.append((p + 10.5, 1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 10 <= v <= 15 and p - raw_mid >= 5:
                estimates.append((p - 8, 2.0))
            elif v >= 20:
                estimates.append((p - 10.5, 1.0))

        if estimates:
            tw = sum(w for _, w in estimates)
            fv = sum(e * w for e, w in estimates) / tw
        elif bids and asks:
            fv = raw_mid
        elif bids:
            fv = bids[0] + 10.5
        elif asks:
            fv = asks[0] - 10.5
        else:
            fv = td.get("ash_fv", 10000.0)

        td["ash_fv"] = fv
        return fv

    def _compute_obi(self, od: OrderDepth) -> float:
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    # ------------------------------------------------------------------
    # ACO — Signal Detection (for real exchange exploitation)
    # ------------------------------------------------------------------
    def _detect_bot1_asym(self, od: OrderDepth, bids: list, asks: list, fv: int) -> int:
        """Detect Bot1 outer wall asymmetry — 92-95% directional accuracy.

        Bot1 (vol 20-30) posts at FV ± {10, 11}. When offsets differ:
          asym = ask_offset - bid_offset
          +1 = bid at FV-11, ask at FV+10 (bid wider) → FV GOES UP
          -1 = bid at FV-10, ask at FV+11 (ask wider) → FV GOES DOWN
        """
        bid_offset = None
        ask_offset = None
        for p in bids:
            if od.buy_orders[p] >= 20:
                bid_offset = fv - p
                break
        for p in asks:
            if -od.sell_orders[p] >= 20:
                ask_offset = p - fv
                break
        if bid_offset is not None and ask_offset is not None:
            if bid_offset in (10, 11) and ask_offset in (10, 11) and bid_offset != ask_offset:
                return ask_offset - bid_offset
        return 0

    def _get_signal(self, fv_r: int, td: dict) -> float:
        """Combined directional signal in [-1, +1].
        Positive = expect FV to rise. Used only for taking decisions.

        Components:
          Bot1 asymmetry (wt 3.0): 92-95% accuracy, strongest signal
          Step reversal  (wt 1.0): 65% accuracy, fade last FV move
          Distance mean  (wt 0.5): fade distance from ~10000
        """
        bot1 = td.get("_bot1", 0)

        # Step reversal: fade last FV step (65% reversal probability)
        step = 0
        prev_fv = td.get("ash_prev_fv")
        if prev_fv is not None and fv_r != prev_fv:
            step_dir = 1 if fv_r > prev_fv else -1
            td["ash_last_step"] = step_dir
            step = -step_dir
        elif "ash_last_step" in td:
            step = -td["ash_last_step"]
        td["ash_prev_fv"] = fv_r

        # Distance from long-run mean
        dist = fv_r - self.LONG_RUN_MEAN
        dist_sig = 0.0
        if abs(dist) >= 3:
            dist_sig = -max(-1.0, min(1.0, dist / 10.0))

        raw = 3.0 * bot1 + 1.0 * step + 0.5 * dist_sig
        return max(-1.0, min(1.0, raw / 3.5))

    # ------------------------------------------------------------------
    # ACO — Wall Detection (proven)
    # ------------------------------------------------------------------
    def _find_wall_bid(self, bids_sorted, fv_r):
        if len(bids_sorted) >= 3:
            return bids_sorted[1]
        if len(bids_sorted) >= 2:
            if fv_r - bids_sorted[0] >= 5:
                return bids_sorted[0]
            else:
                return bids_sorted[1]
        if bids_sorted:
            return bids_sorted[0]
        return fv_r - 10

    def _find_wall_ask(self, asks_sorted, fv_r):
        if len(asks_sorted) >= 3:
            return asks_sorted[1]
        if len(asks_sorted) >= 2:
            if asks_sorted[0] - fv_r >= 5:
                return asks_sorted[0]
            else:
                return asks_sorted[1]
        if asks_sorted:
            return asks_sorted[0]
        return fv_r + 10

    # ------------------------------------------------------------------
    # ACO — Main Trading Logic
    # ------------------------------------------------------------------
    def _trade_ash(self, od: OrderDepth, position: int, td: dict):
        orders = []
        limit = self.LIMIT

        fv = self._estimate_ash_fv(od, td)
        if fv is None:
            return orders, td

        obi = self._compute_obi(od)
        fv = fv + self.OBI_COEFF * obi
        td["ash_fv"] = fv

        fv_r = int(round(fv))
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # Compute directional signal (for taking decisions)
        td["_bot1"] = self._detect_bot1_asym(od, bids_sorted, asks_sorted, fv_r)
        signal = self._get_signal(fv_r, td)

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # ==============================================================
        # Phase 1: Signal-enhanced taking
        #
        # Below FV: always take (same as original).
        # AT FV: enhanced — take if:
        #   (a) shedding inventory (position < 0 for buys), OR
        #   (b) signal confirms direction (>0.3 threshold)
        # This exploits Bot1 asymmetry on the real exchange.
        # In MC sim, Bot1 signal is always 0, so this degrades to
        # step+distance only, requiring both to agree (threshold 0.3).
        # ==============================================================
        for ask_price in asks_sorted:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can = min(vol, limit - starting_pos - buy_ordered)
            if can <= 0:
                break
            if ask_price == fv_r:
                # Take at FV only if:
                # - We're short (inventory reduction) → always good
                # - Signal is bullish → Bot1/step/distance say price will rise
                if position >= 0 and signal <= 0.3:
                    continue
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, can))
            buy_ordered += can

        for bid_price in bids_sorted:
            if bid_price < fv_r:
                break
            vol = od.buy_orders[bid_price]
            can = min(vol, limit + starting_pos - sell_ordered)
            if can <= 0:
                break
            if bid_price == fv_r:
                if position <= 0 and signal >= -0.3:
                    continue
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -can))
            sell_ordered += can

        # ==============================================================
        # Phase 2: Penny-jump quoting (unchanged from original)
        # No signal-based skew — proven to hurt fill rate in MC.
        # ==============================================================
        ref_bid = self._find_wall_bid(bids_sorted, fv_r)
        ref_ask = self._find_wall_ask(asks_sorted, fv_r)

        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders, td

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — sweep small asks + passive bid
    # ------------------------------------------------------------------
    def _trade_ipr(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        # Sweep ask levels but skip vol > 15 (outer wall — overpaying)
        for ask_price in asks_sorted:
            vol = -od.sell_orders[ask_price]
            if vol > 15:
                continue
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                remaining -= qty
            if remaining <= 0:
                break

        # Passive bid: penny-jump best bid
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = 12000
            orders.append(Order("INTARIAN_PEPPER_ROOT", our_bid, remaining))

        return orders
