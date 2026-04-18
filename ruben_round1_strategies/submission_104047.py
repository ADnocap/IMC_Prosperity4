"""
SUBMISSION: Position Limit Finder
PURPOSE: Discover the max position allowed for ACO and IPR.
HOW: Try to buy increasing amounts. The server cancels ALL orders
     if worst-case would breach the limit. By trying big then small,
     we find the exact limit.
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
    """
    Strategy: On different ticks, try to buy different amounts.
    Check own_trades to see what actually filled.
    The portal tells us position limits in the results.

    Tick 0: Try to buy 50 of each (generous price to ensure fill if allowed)
    Tick 1: If position is 0 (orders got cancelled), try 30
    Tick 2: If still 0, try 20
    Tick 3: Try 10
    ... etc

    Also: once we have a position, HOLD it to extract FV from PnL.
    """

    SKIP = {"EMERALDS", "TOMATOES"}
    # Try these sizes in order
    TRY_SIZES = [50, 40, 30, 25, 20, 15, 10, 5]

    def run(self, state: TradingState):
        orders = {}
        for product in state.order_depths:
            orders[product] = []

        # Load state
        td = {}
        if state.traderData:
            td = json.loads(state.traderData)

        tick = state.timestamp // 100

        for product in state.order_depths:
            if product in self.SKIP:
                continue

            pos = state.position.get(product, 0)
            found_limit = td.get(f"{product}_limit", None)
            attempt_idx = td.get(f"{product}_attempt", 0)

            # Log position every tick
            logger.print(f"t={state.timestamp} {product} pos={pos} limit_found={found_limit} attempt={attempt_idx}")

            if found_limit is not None:
                # Already found the limit, just hold
                continue

            if pos > 0:
                # We successfully bought! The limit is at least this much.
                td[f"{product}_limit"] = pos
                logger.print(f"FOUND: {product} limit >= {pos} (bought {pos} successfully)")
                continue

            # pos == 0, try the next size
            if attempt_idx < len(self.TRY_SIZES):
                size = self.TRY_SIZES[attempt_idx]
                ob = state.order_depths.get(product)
                if ob and ob.sell_orders:
                    # Buy at a generous price (best ask + 5) to ensure fill
                    best_ask = min(ob.sell_orders.keys())
                    price = best_ask + 5
                    orders[product] = [Order(product, price, size)]
                    logger.print(f"TRYING: {product} buy {size} @ {price}")
                    td[f"{product}_attempt"] = attempt_idx + 1
                else:
                    logger.print(f"NO ASKS for {product}")

        trader_data = json.dumps(td)
        logger.flush(state, orders, 0, trader_data)
        return orders, 0, trader_data