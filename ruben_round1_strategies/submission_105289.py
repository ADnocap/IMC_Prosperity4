"""
SUBMISSION 3: Find Real Position Limits
PURPOSE: We know limit >= 50 for IPR, >= 13 for ACO, but what's the ACTUAL cap?
HOW: Buy aggressively across MANY ticks. Each tick, try to add more to position.
     When an order gets cancelled (position stays flat), that tick's attempt
     exceeded the limit. The last successful fill = the limit.

     Strategy:
     - t=0-700: Accumulate as much as possible (buy every tick)
     - After that: hold and extract FV from PnL
"""
try:
    from datamodel import Order, OrderDepth, TradingState, Symbol, Listing, Observation, Trade
except ImportError:
    from prosperity3bt.datamodel import Order, OrderDepth, TradingState, Symbol, Listing, Observation, Trade

import json

class Logger:
    def __init__(self): self.logs = ""
    def print(self, *args, **kwargs):
        self.logs += " ".join(map(str, args)) + "\n"
    def flush(self, state, orders, conversions, trader_data):
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (3750 - base_length) // 3
        print(self.to_json([self.compress_state(state, self.truncate(state.traderData, max_item_length)), self.compress_orders(orders), conversions, self.truncate(trader_data, max_item_length), self.truncate(self.logs, max_item_length)]))
        self.logs = ""
    def compress_state(self, state, trader_data):
        return [state.timestamp, trader_data, self.compress_listings(state.listings), self.compress_order_depths(state.order_depths), self.compress_trades(state.own_trades), self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]
    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]
    def compress_order_depths(self, order_depths):
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}
    def compress_trades(self, trades):
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in trades.values() for t in arr]
    def compress_observations(self, obs):
        co = {}
        for p, o in obs.conversionObservations.items():
            co[p] = [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [obs.plainValueObservations, co]
    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]
    def to_json(self, value):
        return json.dumps(value, separators=(",", ":"))
    def truncate(self, value, max_length):
        return value[:max_length - 3] + "..." if len(value) > max_length else value

logger = Logger()

class Trader:
    SKIP = {"EMERALDS", "TOMATOES"}

    # Phase 1: accumulate. Try buying this many MORE each tick.
    # Start big, shrink as we approach the limit.
    BUY_ATTEMPTS = [50, 50, 50, 30, 20, 10, 5, 1]
    MAX_ACCUMULATE_TICKS = 8  # stop trying after 8 ticks

    def run(self, state: TradingState):
        orders = {}
        for product in state.order_depths:
            orders[product] = []

        td = {}
        if state.traderData:
            td = json.loads(state.traderData)

        tick = state.timestamp // 100

        for product in state.order_depths:
            if product in self.SKIP:
                continue

            pos = state.position.get(product, 0)
            prev_pos = td.get(f"{product}_prev_pos", 0)
            phase = td.get(f"{product}_phase", "accumulate")
            max_pos_seen = td.get(f"{product}_max_pos", 0)

            # Track max position ever achieved
            if pos > max_pos_seen:
                max_pos_seen = pos
                td[f"{product}_max_pos"] = max_pos_seen

            logger.print(f"t={state.timestamp} {product} pos={pos} prev={prev_pos} max={max_pos_seen} phase={phase}")

            if phase == "accumulate" and tick < self.MAX_ACCUMULATE_TICKS:
                # Try to buy more
                ob = state.order_depths.get(product)
                if ob and ob.sell_orders:
                    best_ask = min(ob.sell_orders.keys())
                    # Buy enough to potentially hit the limit
                    # Request: try to get to a target position
                    target = max_pos_seen + (50 if tick < 3 else 20 if tick < 5 else 5)
                    want = target - pos
                    if want > 0:
                        # CRITICAL: order size must not cause worst-case to exceed limit
                        # If we don't know the limit, just try and see if it gets cancelled
                        orders[product] = [Order(product, best_ask + 5, want)]
                        logger.print(f"  BUY {want} @ {best_ask + 5} (target {target})")

                td[f"{product}_prev_pos"] = pos

                # If position didn't increase from last tick (order got cancelled),
                # we might be at the limit
                if tick > 0 and pos == prev_pos and prev_pos > 0:
                    logger.print(f"  LIMIT HIT? pos stuck at {pos}")
                    td[f"{product}_phase"] = "hold"
            else:
                td[f"{product}_phase"] = "hold"

        trader_data = json.dumps(td)
        logger.flush(state, orders, 0, trader_data)
        return orders, 0, trader_data