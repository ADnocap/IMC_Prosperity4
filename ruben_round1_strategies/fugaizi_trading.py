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
    Round 1 strategy — sweep-optimized.

    ASH_COATED_OSMIUM (stationary random walk, sigma=0.312/tick):
        Pure passive MM. No taking (sweep showed it hurts via adverse selection).
        Volume-based FV from bot walls. Wide quotes at FV +/- 7 (penny-jump
        inner wall). Inventory skew kicks in at soft_limit=60.

    INTARIAN_PEPPER_ROOT (deterministic drift +0.1/tick):
        Pure buy-and-hold to max position. Drift = free PnL.

    Sweep results (200 sessions each, 180 combos):
        Best total PnL: soft=60, take=0, spread=7 -> Total=9,902
        Best Sharpe:     soft=40, take=0, spread=5 -> Sharpe=18.9
        Best P05:        soft=60, take=0, spread=7 -> P05=9,070
    """

    PARAMS = {
        "ASH_COATED_OSMIUM": {
            "limit": 80,
            "soft_limit": 60,
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
    # ASH_COATED_OSMIUM — pure passive MM, no taking
    # ------------------------------------------------------------------
    def _estimate_ash_fv(self, od: OrderDepth, td: dict) -> float:
        """Estimate FV using volume-based bot identification.
        Inner wall (vol 10-15): offset +/-8 from FV.
        Outer wall (vol 20-30): offset ~+/-10.5 from FV.
        """
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())

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
        else:
            fv = td.get("ash_fv", 10000.0)

        td["ash_fv"] = fv
        return fv

    def _trade_ash(self, od: OrderDepth, position: int, td: dict) -> List[Order]:
        orders = []
        p = self.PARAMS["ASH_COATED_OSMIUM"]
        limit = p["limit"]
        soft = p["soft_limit"]

        fv = self._estimate_ash_fv(od, td)
        fv_r = round(fv)

        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        skew = self._inventory_skew(position, soft, limit)

        if bids_sorted and asks_sorted:
            our_bid = min(bids_sorted[0] + 1, fv_r - 7) + skew
            our_ask = max(asks_sorted[0] - 1, fv_r + 7) + skew
        elif bids_sorted:
            our_bid = bids_sorted[0] + 1 + skew
            our_ask = fv_r + 7 + skew
        elif asks_sorted:
            our_bid = fv_r - 7 + skew
            our_ask = asks_sorted[0] - 1 + skew
        else:
            our_bid = fv_r - 7 + skew
            our_ask = fv_r + 7 + skew

        if our_bid >= our_ask:
            our_bid = fv_r - 7
            our_ask = fv_r + 7

        passive_buy = limit - position
        passive_sell = limit + position

        if passive_buy > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, passive_buy))
        if passive_sell > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -passive_sell))

        return orders

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT — buy-and-hold (drift = free PnL)
    # ------------------------------------------------------------------
    def _trade_ipr(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        limit = self.PARAMS["INTARIAN_PEPPER_ROOT"]["limit"]

        remaining = limit - position
        if remaining <= 0:
            return orders

        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []

        # Sweep all ask levels to accumulate fast
        for ask_price in asks_sorted:
            vol = -od.sell_orders[ask_price]
            qty = min(vol, remaining)
            if qty > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", ask_price, qty))
                remaining -= qty
            if remaining <= 0:
                break

        # Passive bid for remaining capacity
        if remaining > 0:
            if bids_sorted:
                our_bid = bids_sorted[0] + 1
            else:
                our_bid = asks_sorted[0] - 1 if asks_sorted else 12000
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
