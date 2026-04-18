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
    Round 1 — shifu_V5: Mean-reversion signal exploitation.

    ACO: Weighted wall FV + mean-reversion directional skew.
    When FV moves up, fade it (tighter ask, wider bid). Vice versa.
    The hidden pattern: bots use integer rounding on continuous FV,
    creating predictable overshoots (AC=-0.34, 32% reversal rate).

    IPR: Sweep small asks (vol <= 15) + passive bid for drift.
    """

    LIMIT = 80

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
    # ASH_COATED_OSMIUM — mean-reversion signal + market making
    # ------------------------------------------------------------------
    def _estimate_ash_fv(self, od: OrderDepth, td: dict) -> float:
        """Weighted wall FV with sanity checks.
        Inner wall (vol 10-15): +/-8, weight 2.0 — must be 5+ ticks from raw mid.
        Outer wall (vol 20+): +/-10.5, weight 1.0.
        """
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

    def _trade_ash(self, od: OrderDepth, position: int, td: dict):
        orders = []
        limit = self.LIMIT

        fv = self._estimate_ash_fv(od, td)
        if fv is None:
            return orders, td

        fv_r = int(round(fv))

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        # --- Mean-reversion signal ---
        # After FV moves up, expect reversal (AC=-0.34, 32% reversal, 5% continuation)
        # After FV moves down, expect reversal up
        prev_fv_r = td.get("ash_prev_fv_r")
        fv_went_up = False
        fv_went_down = False
        if prev_fv_r is not None:
            if fv_r > prev_fv_r:
                fv_went_up = True
            elif fv_r < prev_fv_r:
                fv_went_down = True
        td["ash_prev_fv_r"] = fv_r

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: Directional taking using mean-reversion signal
        # Below FV: always take (clear edge)
        # At exactly FV: only take in the FADE direction
        #   - FV went up → sell at FV (expect price to come back down)
        #   - FV went down → buy at FV (expect price to come back up)
        #   - No change → take at FV to reduce inventory (conservative)
        for ask_price in asks_sorted:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can = min(vol, limit - starting_pos - buy_ordered)
            if can <= 0:
                break
            if ask_price == fv_r:
                # At FV: buy only if fading a down move OR reducing short position
                if not (fv_went_down or position < 0):
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
                # At FV: sell only if fading an up move OR reducing long position
                if not (fv_went_up or position > 0):
                    continue
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -can))
            sell_ordered += can

        # Phase 2: Penny-jump (no skew — keep quotes symmetric)
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

        # Sweep ask levels but skip vol > 15 (outer wall — too expensive)
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

        # Passive bid for remaining
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = 12000
            orders.append(Order("INTARIAN_PEPPER_ROOT", our_bid, remaining))

        return orders
