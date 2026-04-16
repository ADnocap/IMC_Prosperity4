"""Probe trader: dumps all TradingState data to sandboxLog for analysis.
Still trades normally (d.py logic) but prints everything we might be missing."""
import json
from datamodel import Order, OrderDepth, TradingState

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
LIMIT = 80

class Trader:
    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result: dict[str, list[Order]] = {}
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        # PROBE: dump state fields on first 5 ticks and every 100th tick
        ts = state.timestamp
        if ts <= 400 or ts % 10000 == 0:
            print(f"=== TICK {ts} ===")
            print(f"listings: {list(state.listings.keys()) if state.listings else 'None'}")
            if state.listings:
                for sym, lst in state.listings.items():
                    print(f"  {sym}: product={lst.product}, denom={lst.denomination}")
            print(f"observations: {state.observations}")
            if state.observations:
                print(f"  plain: {state.observations.plainValueObservations}")
                print(f"  conversion: {state.observations.conversionObservations}")
            print(f"position: {state.position}")
            print(f"own_trades: {state.own_trades}")
            print(f"market_trades: {state.market_trades}")
            for prod in state.order_depths:
                od = state.order_depths[prod]
                print(f"  {prod} book: bids={dict(sorted(od.buy_orders.items(), reverse=True))}, asks={dict(sorted(od.sell_orders.items()))}")

        # Normal trading logic (copy from d.py / 176475)
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == OSMIUM:
                result[product], td = self._trade_osmium(od, pos, td)
            elif product == PEPPER:
                result[product], td = self._trade_pepper(od, pos, td)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    def _trade_osmium(self, od, position, td):
        orders = []
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        fv = self._fv(od, bids, asks, td)
        if fv is None:
            return orders, td
        fv_r = int(round(fv))
        td["fv"] = fv
        buy_ordered = sell_ordered = 0

        # Take (edge >= 2)
        for ap in asks:
            if ap > fv_r - 2: break
            vol = -od.sell_orders[ap]
            can = LIMIT - position - buy_ordered
            if can <= 0: break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty
        for bp in bids:
            if bp < fv_r + 2: break
            vol = od.buy_orders[bp]
            can = LIMIT + position - sell_ordered
            if can <= 0: break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # Clear
        pos_after = position + buy_ordered - sell_ordered
        if pos_after > 0:
            for bp in bids:
                if bp < fv_r: break
                vol = od.buy_orders[bp]
                c = min(vol, pos_after, LIMIT + position - sell_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, bp, -c))
                    sell_ordered += c; pos_after -= c
        elif pos_after < 0:
            for ap in asks:
                if ap > fv_r: break
                vol = -od.sell_orders[ap]
                c = min(vol, -pos_after, LIMIT - position - buy_ordered)
                if c > 0:
                    orders.append(Order(OSMIUM, ap, c))
                    buy_ordered += c; pos_after += c

        # Make (penny-jump)
        buy_room = LIMIT - position - buy_ordered
        sell_room = LIMIT + position - sell_ordered
        our_bid = fv_r - 7
        for bp in bids:
            if bp <= fv_r - 1:
                if fv_r - bp <= 2: our_bid = bp
                else: our_bid = bp + 1
                break
        our_ask = fv_r + 7
        for ap in asks:
            if ap >= fv_r + 1:
                if ap - fv_r <= 2: our_ask = ap
                else: our_ask = ap - 1
                break
        our_bid = min(our_bid, fv_r - 1)
        our_ask = max(our_ask, fv_r + 1)
        if our_bid >= our_ask:
            our_bid = fv_r - 1; our_ask = fv_r + 1
        if buy_room > 0:
            orders.append(Order(OSMIUM, our_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(OSMIUM, our_ask, -sell_room))
        return orders, td

    def _fv(self, od, bids, asks, td):
        if not bids and not asks: return td.get("fv")
        bot1 = []
        for p in bids:
            if od.buy_orders[p] >= 20: bot1.append(p + 10.5)
        for p in asks:
            if -od.sell_orders[p] >= 20: bot1.append(p - 10.5)
        b1fv = sum(bot1)/len(bot1) if bot1 else None
        ref = b1fv or td.get("fv")
        if ref is None:
            if bids and asks: ref = (bids[0]+asks[0])/2
            elif bids: ref = bids[0]+8
            else: ref = asks[0]-8
        est = []
        for p in bids:
            v = od.buy_orders[p]
            if 10<=v<=15 and abs(p-(ref-8))<=3: est.append((p+8,2.0))
            elif v>=20: est.append((p+10.5,1.0))
        for p in asks:
            v = -od.sell_orders[p]
            if 10<=v<=15 and abs(p-(ref+8))<=3: est.append((p-8,2.0))
            elif v>=20: est.append((p-10.5,1.0))
        if est:
            tw = sum(w for _,w in est)
            return sum(e*w for e,w in est)/tw
        if bids and asks: return (bids[0]+asks[0])/2
        if bids: return bids[0]+10.5
        if asks: return asks[0]-10.5
        return td.get("fv")

    def _trade_pepper(self, od, position, td):
        orders = []
        rem = LIMIT - position
        if rem <= 0: return orders, td
        if od.sell_orders:
            for ap in sorted(od.sell_orders.keys()):
                vol = -od.sell_orders[ap]
                if rem > 20 and vol > 15: continue
                qty = min(vol, rem)
                if qty > 0:
                    orders.append(Order(PEPPER, ap, qty))
                    rem -= qty
                if rem <= 0: break
        if rem > 0 and od.buy_orders:
            bb = max(od.buy_orders.keys())
            orders.append(Order(PEPPER, bb + 1, rem))
        return orders, td
