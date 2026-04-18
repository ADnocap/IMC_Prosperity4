from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json


class Trader:
    """
    Data-gathering bot — logs market_trades with buyer/seller names
    to find the informed trader (P4's "Olivia" equivalent).

    Also trades normally (V4 strategy) so we don't waste a submission.
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

        # === DATA GATHERING: Log all market trades with bot names ===
        if hasattr(state, 'market_trades') and state.market_trades:
            for sym, trades in state.market_trades.items():
                for t in trades:
                    buyer = getattr(t, 'buyer', '')
                    seller = getattr(t, 'seller', '')
                    print(f"MT|{state.timestamp}|{sym}|{buyer}|{seller}|{t.price}|{t.quantity}")

        # === Log order book state for cross-referencing ===
        for sym, od in state.order_depths.items():
            if sym == "ASH_COATED_OSMIUM":
                bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
                asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
                bid_str = ";".join(f"{p}:{od.buy_orders[p]}" for p in bids[:3])
                ask_str = ";".join(f"{p}:{-od.sell_orders[p]}" for p in asks[:3])
                print(f"OB|{state.timestamp}|{sym}|{bid_str}|{ask_str}")

        # === Trade normally (V4 strategy for baseline PnL) ===
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)

            if product == "ASH_COATED_OSMIUM":
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._trade_ipr(od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _estimate_fv(self, od, td):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids and not asks:
            return td.get("ash_fv")
        if bids and asks:
            raw_mid = (bids[0] + asks[0]) / 2
        elif bids:
            raw_mid = td.get("ash_fv", bids[0] + 8)
        else:
            raw_mid = td.get("ash_fv", asks[0] - 8)

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

    def _trade_osmium(self, od, position, td):
        orders = []
        limit = self.LIMIT
        fv = self._estimate_fv(od, td)
        if fv is None:
            return orders, td
        fv_r = int(round(fv))
        bids_sorted = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks_sorted = sorted(od.sell_orders.keys()) if od.sell_orders else []

        starting_pos = position
        buy_ordered = 0
        sell_ordered = 0

        for ap in asks_sorted:
            if ap > fv_r:
                break
            vol = -od.sell_orders[ap]
            can = min(vol, limit - starting_pos - buy_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", ap, can))
            buy_ordered += can

        for bp in bids_sorted:
            if bp < fv_r:
                break
            vol = od.buy_orders[bp]
            can = min(vol, limit + starting_pos - sell_ordered)
            if can <= 0:
                break
            orders.append(Order("ASH_COATED_OSMIUM", bp, -can))
            sell_ordered += can

        # Penny-jump
        if len(bids_sorted) >= 3:
            ref_bid = bids_sorted[1]
        elif len(bids_sorted) >= 2:
            ref_bid = bids_sorted[0] if fv_r - bids_sorted[0] >= 5 else bids_sorted[1]
        elif bids_sorted:
            ref_bid = bids_sorted[0]
        else:
            ref_bid = fv_r - 10

        if len(asks_sorted) >= 3:
            ref_ask = asks_sorted[1]
        elif len(asks_sorted) >= 2:
            ref_ask = asks_sorted[0] if asks_sorted[0] - fv_r >= 5 else asks_sorted[1]
        elif asks_sorted:
            ref_ask = asks_sorted[0]
        else:
            ref_ask = fv_r + 10

        our_bid = min(ref_bid + 1, fv_r - 1)
        our_ask = max(ref_ask - 1, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        pb = limit - starting_pos - buy_ordered
        ps = limit + starting_pos - sell_ordered
        if pb > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_bid, pb))
        if ps > 0:
            orders.append(Order("ASH_COATED_OSMIUM", our_ask, -ps))
        return orders, td

    def _trade_ipr(self, od, position):
        orders = []
        remaining = self.LIMIT - position
        if remaining <= 0:
            return orders
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if vol > 15:
                    continue
                qty = min(vol, remaining)
                if qty > 0:
                    orders.append(Order("INTARIAN_PEPPER_ROOT", ap, qty))
                    remaining -= qty
                if remaining <= 0:
                    break
        if remaining > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order("INTARIAN_PEPPER_ROOT", bb + 1, remaining))
        return orders
