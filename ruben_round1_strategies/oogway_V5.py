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


class Trader:
    """
    Round 1 — oogway_V5: Pure directional ACO.

    No symmetric MM. Only trade ACO when we have a signal.
    Signals:
    1. Market trades: bot trades predict direction (qty=2 → +1.49 signed ret)
    2. FV change: fade the last move (AC=-0.34, 32% reversal)
    3. Spread deviation: abnormal spread predicts direction

    Place small orders (qty 2-3) on the predicted side only.
    Accept directional risk. Target avg fill ~2-3.

    IPR: Sweep small asks + passive bid (unchanged).
    """

    LIMIT = 80
    DIR_QTY = 3  # Small directional size like top scorers

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
                orders, td = self._trade_ash(od, pos, td, state)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_ipr(od, pos)
            else:
                orders = []

            result[product] = orders

        trader_data_str = json.dumps(td)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM — pure directional
    # ------------------------------------------------------------------
    def _estimate_fv(self, od: OrderDepth, td: dict) -> float:
        """Weighted wall FV."""
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

    def _compute_signal(self, od: OrderDepth, td: dict, state: TradingState, fv: float) -> float:
        """Combine all signals into a single directional score.
        Positive = bullish (expect up), negative = bearish (expect down).
        """
        signal = 0.0
        fv_r = int(round(fv))

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # --- Signal 1: Market trades (strongest) ---
        # Bot trades predict direction. qty=2 is most informative.
        if hasattr(state, 'market_trades') and state.market_trades:
            aco_trades = state.market_trades.get("ASH_COATED_OSMIUM", [])
            for t in aco_trades:
                weight = 3.0 if t.quantity <= 2 else 1.5
                if t.price > fv:
                    signal += weight  # Buy trade → bullish
                elif t.price < fv:
                    signal -= weight  # Sell trade → bearish

        # --- Signal 2: FV change mean-reversion ---
        # After FV moves up, expect down (AC=-0.34)
        prev_fv_r = td.get("ash_prev_fv_r")
        if prev_fv_r is not None:
            fv_change = fv_r - prev_fv_r
            if fv_change > 0:
                signal -= 1.0  # Fade the up move
            elif fv_change < 0:
                signal += 1.0  # Fade the down move
            # Consecutive moves → stronger signal
            prev_change = td.get("ash_prev_change", 0)
            if fv_change > 0 and prev_change > 0:
                signal -= 2.0  # Two ups → strong fade
            elif fv_change < 0 and prev_change < 0:
                signal += 2.0  # Two downs → strong fade
            td["ash_prev_change"] = fv_change
        td["ash_prev_fv_r"] = fv_r

        # --- Signal 3: Spread deviation ---
        # Abnormal spread predicts direction
        if bids and asks:
            spread = asks[0] - bids[0]
            if spread < 14:
                # Tight spread: check which side moved
                # If bid is closer to FV than usual → bid moved up → bullish
                bid_dist = fv_r - bids[0]
                ask_dist = asks[0] - fv_r
                if bid_dist < ask_dist:
                    signal += 1.5  # Bid closer → bullish
                elif ask_dist < bid_dist:
                    signal -= 1.5  # Ask closer → bearish

        # --- Signal 4: Book imbalance ---
        # Heavy bids → bullish (93.5% accuracy on raw mid)
        total_bid = sum(od.buy_orders.values()) if od.buy_orders else 0
        total_ask = sum(-v for v in od.sell_orders.values()) if od.sell_orders else 0
        total = total_bid + total_ask
        if total > 0:
            obi = (total_bid - total_ask) / total
            signal += obi * 2.0  # Strong OBI → strong signal

        return signal

    def _trade_ash(self, od: OrderDepth, position: int, td: dict, state: TradingState):
        orders = []
        limit = self.LIMIT

        fv = self._estimate_fv(od, td)
        if fv is None:
            return orders, td

        fv_r = int(round(fv))

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        signal = self._compute_signal(od, td, state, fv)

        # --- Always take clear mispricings (below FV-1 or above FV+1) ---
        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        for ask_price in asks_sorted:
            if ask_price >= fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can = min(vol, limit - starting_pos - buy_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, can))
            buy_ordered += can

        for bid_price in bids_sorted:
            if bid_price <= fv_r:
                break
            vol = od.buy_orders[bid_price]
            can = min(vol, limit + starting_pos - sell_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -can))
            sell_ordered += can

        # --- Directional orders based on signal ---
        # Only place orders on the predicted side
        # Use small qty to match top scorer profile
        if signal > 0.5:
            # Bullish: place buy order at FV-1 (passive, wait for Bot3 to sell to us)
            qty = min(self.DIR_QTY, limit - starting_pos - buy_ordered)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv_r - 1, qty))
                buy_ordered += qty

        elif signal < -0.5:
            # Bearish: place sell order at FV+1 (passive, wait for Bot3 to buy from us)
            qty = min(self.DIR_QTY, limit + starting_pos - sell_ordered)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv_r + 1, -qty))
                sell_ordered += qty

        # --- Position unwinding ---
        # When position gets large, actively unwind toward flat
        if position > 20:
            # Long: place sell to reduce
            unwind_qty = min(self.DIR_QTY, limit + starting_pos - sell_ordered, position)
            if unwind_qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv_r + 1, -unwind_qty))
                sell_ordered += unwind_qty
        elif position < -20:
            # Short: place buy to reduce
            unwind_qty = min(self.DIR_QTY, limit - starting_pos - buy_ordered, -position)
            if unwind_qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", fv_r - 1, unwind_qty))
                buy_ordered += unwind_qty

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

        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = 12000
            orders.append(Order("INTARIAN_PEPPER_ROOT", our_bid, remaining))

        return orders
