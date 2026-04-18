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
    Round 1 — shifu_trader v2 (research-optimized).

    ASH_COATED_OSMIUM: Raw wall FV (no EMA) + take at FV + penny-jump MM.
    INTARIAN_PEPPER_ROOT: Sweep ALL asks for fastest accumulation + passive bid.
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
            "soft_limit": 70,
        },
        "INTARIAN_PEPPER_ROOT": {
            "limit": 80,
        },
    }

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
                orders = self._trade_ash(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_ipr(od, pos)
            else:
                orders = []

            result[product] = orders

        trader_data_str = json.dumps(td)
        logger.flush(state, result, conversions, trader_data_str)
        return result, conversions, trader_data_str

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM — raw wall FV + taking + penny-jump MM
    # ------------------------------------------------------------------
    def _estimate_ash_fv(self, od: OrderDepth, td: dict) -> float:
        """FV from bot wall levels with multi-source fallback.
        Inner wall (vol 10-15): +/-8 from FV.
        Outer wall (vol 20-30): +/-10.5 from FV.
        """
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        bid_fv = None
        for price in bids:
            vol = od.buy_orders[price]
            if 10 <= vol <= 15:
                bid_fv = price + 8
                break
            elif vol >= 20:
                bid_fv = price + 10.5
                break

        ask_fv = None
        for price in asks:
            vol = -od.sell_orders[price]
            if 10 <= vol <= 15:
                ask_fv = price - 8
                break
            elif vol >= 20:
                ask_fv = price - 10.5
                break

        if bid_fv is not None and ask_fv is not None:
            fv = (bid_fv + ask_fv) / 2
        elif bid_fv is not None:
            fv = bid_fv
        elif ask_fv is not None:
            fv = ask_fv
        elif bids and asks:
            fv = (bids[0] + asks[0]) / 2
        elif bids:
            fv = bids[0] + 10.5
        elif asks:
            fv = asks[0] - 10.5
        else:
            fv = td.get("ash_fv", 10000.0)

        td["ash_fv"] = fv
        return fv

    def _trade_ash(self, od: OrderDepth, position: int, td: dict) -> List[Order]:
        orders = []
        p = self.PARAMS["ASH_COATED_OSMIUM"]
        limit = p["limit"]
        soft = p["soft_limit"]

        raw_fv = self._estimate_ash_fv(od, td)
        if raw_fv is None:
            return orders

        # EMA-smooth FV
        prev_fv = td.get("ash_ema_fv")
        if prev_fv is not None:
            fv = 0.2 * raw_fv + 0.8 * prev_fv
        else:
            fv = raw_fv
        td["ash_ema_fv"] = fv

        fv_r = int(round(fv))

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: Take mispriced levels (asks <= FV, bids >= FV)
        for ask_price in asks_sorted:
            if ask_price > fv_r:
                break
            vol = -od.sell_orders[ask_price]
            can = min(vol, limit - starting_pos - buy_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", ask_price, can))
            buy_ordered += can

        for bid_price in bids_sorted:
            if bid_price < fv_r:
                break
            vol = od.buy_orders[bid_price]
            can = min(vol, limit + starting_pos - sell_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", bid_price, -can))
            sell_ordered += can

        # Phase 2: Penny-jump with Bot3 detection
        bot3_on_bid = len(bids_sorted) >= 3
        bot3_on_ask = len(asks_sorted) >= 3
        ref_bid = bids_sorted[1] if bot3_on_bid else (bids_sorted[0] if bids_sorted else fv_r - 8)
        ref_ask = asks_sorted[1] if bot3_on_ask else (asks_sorted[0] if asks_sorted else fv_r + 8)

        eff_pos = starting_pos + buy_ordered - sell_ordered
        skew = self._inventory_skew(eff_pos, soft, limit)

        our_bid = min(ref_bid + 1, fv_r - 1) + skew
        our_ask = max(ref_ask - 1, fv_r + 1) + skew

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        passive_buy = limit - starting_pos - buy_ordered
        passive_sell = limit + starting_pos - sell_ordered

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — sweep ALL asks + passive bid (fastest accumulation)
    # ------------------------------------------------------------------
    def _trade_ipr(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        limit = self.PARAMS["INTARIAN_PEPPER_ROOT"]["limit"]

        remaining = limit - position
        if remaining <= 0:
            return orders

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        # Only sweep the cheapest ask level (inner bot) to get some position fast
        # Passive bid for the rest to save spread cost
        if asks_sorted:
            best_ask = asks_sorted[0]
            vol = -od.sell_orders[best_ask]
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", best_ask, qty))
                remaining -= qty

        # Passive bid for remaining — penny-jump inside best bid
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            elif asks_sorted:
                our_bid = asks_sorted[0] - 1
            else:
                our_bid = 12000
            orders.append(Order("INTARIAN_PEPPER_ROOT", our_bid, remaining))

        return orders

    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_skew(position: int, soft_limit: int, hard_limit: int) -> int:
        """Skew quotes to reduce inventory. Max 2 ticks at hard limit."""
        if abs(position) <= soft_limit:
            return 0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        magnitude = min(round((excess / max_excess) * 2), 2)
        return -magnitude if position > 0 else magnitude
