"""Penny-jump market maker on every R3 asset. If books look sane, this
trader should fill some trades and accumulate position/cash on each asset.
A flat-zero PnL across 100 sessions would mean the simulator's books are
empty or pathological for that asset."""
try:
    from datamodel import Order, TradingState
except ImportError:
    from prosperity3bt.datamodel import Order, TradingState

# Each NAME = "..." line activates the asset in the Rust simulator.
NAME_HYDROGEL = "HYDROGEL_PACK"
NAME_VELVETFRUIT = "VELVETFRUIT_EXTRACT"
NAME_VEV_4000 = "VEV_4000"
NAME_VEV_4500 = "VEV_4500"
NAME_VEV_5000 = "VEV_5000"
NAME_VEV_5100 = "VEV_5100"
NAME_VEV_5200 = "VEV_5200"
NAME_VEV_5300 = "VEV_5300"
NAME_VEV_5400 = "VEV_5400"
NAME_VEV_5500 = "VEV_5500"
NAME_VEV_6000 = "VEV_6000"
NAME_VEV_6500 = "VEV_6500"

POS_LIMIT = 80


class Trader:
    def run(self, state: TradingState):
        result = {}
        for sym, depth in state.order_depths.items():
            pos = state.position.get(sym, 0)
            buys = sorted(depth.buy_orders.keys(), reverse=True)
            sells = sorted(depth.sell_orders.keys())
            if not buys or not sells:
                result[sym] = []
                continue
            best_bid = buys[0]
            best_ask = sells[0]
            spread = best_ask - best_bid
            if spread < 2:
                # No room to penny-jump
                result[sym] = []
                continue
            orders = []
            # Penny-jump: bid at best_bid+1, ask at best_ask-1
            buy_room = POS_LIMIT - pos
            sell_room = POS_LIMIT + pos
            if buy_room > 0:
                orders.append(Order(sym, best_bid + 1, min(5, buy_room)))
            if sell_room > 0:
                orders.append(Order(sym, best_ask - 1, -min(5, sell_room)))
            result[sym] = orders
        return result, 0, ""
