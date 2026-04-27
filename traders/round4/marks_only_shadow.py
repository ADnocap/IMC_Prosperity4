"""MARK-ONLY VARIANT 2 - Shadow Mark 14 (the smart passive MM).

Standalone trader. Mark 14 has agg_pct == 0.0 on HYDROGEL_PACK / VEV_4000 —
they sit on the book and let others lift them. So when Mark 14 is recorded
as the BUYER at price X, X is approximately their resting BID. When they
are the SELLER at X, X is approximately their resting ASK.

Strategy: maintain rolling estimates of Mark 14's recent bid and ask for
HYDROGEL and VEV_4000. Quote 1 tick INSIDE Mark 14's level (= 1 tick
better) to get filled before them — but only if our quote stays inside
top-of-book (never cross our own existing book).

Sizes: modest (15 lots / side) to keep risk low. No takes, no other logic.
"""

try:
    from datamodel import Order, OrderDepth, TradingState, Trade
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState, Trade

from typing import Dict, List, Optional, Tuple
import json


HYDROGEL = "HYDROGEL_PACK"
VEV_4000 = "VEV_4000"

LIMITS: Dict[str, int] = {HYDROGEL: 200, VEV_4000: 300}

# Products to shadow-trade Mark 14 on
SHADOW_PRODUCTS = (HYDROGEL, VEV_4000)
SHADOW_MARK = "Mark 14"

# Window for tracking Mark 14's recent bid/ask levels
SHADOW_LOOKBACK_TICKS = 50
SHADOW_QUOTE_SIZE = 15
SOFT_POS_FRAC = 0.5


class Trader:
    MAF_BID = 0

    def bid(self) -> int:
        return int(self.MAF_BID)

    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        self._update_mark14_log(state, td)
        cur_ts = state.timestamp

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            if product not in SHADOW_PRODUCTS:
                result[product] = []
                continue
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            result[product] = self._shadow_quotes(product, od, pos, td, cur_ts)

        return result, 0, json.dumps(td)

    def _update_mark14_log(self, state: TradingState, td: dict) -> None:
        log: List[Dict] = td.get("m14_trades", [])
        cur_ts = state.timestamp
        cutoff = cur_ts - SHADOW_LOOKBACK_TICKS * 100
        log = [e for e in log if e["ts"] >= cutoff]
        seen = {(e["sym"], e["ts"], e["price"], e["qty"], e["side"]) for e in log}
        for sym, trades in (state.market_trades or {}).items():
            if sym not in SHADOW_PRODUCTS:
                continue
            for t in trades:
                buyer = t.buyer or ""
                seller = t.seller or ""
                # Mark 14 as buyer => their bid was approximately t.price
                if buyer == SHADOW_MARK:
                    key = (sym, int(t.timestamp), int(t.price), int(t.quantity), "bid")
                    if key not in seen:
                        log.append({
                            "sym": sym, "ts": int(t.timestamp),
                            "price": int(t.price), "qty": int(t.quantity),
                            "side": "bid",
                        })
                        seen.add(key)
                # Mark 14 as seller => their ask was approximately t.price
                if seller == SHADOW_MARK:
                    key = (sym, int(t.timestamp), int(t.price), int(t.quantity), "ask")
                    if key not in seen:
                        log.append({
                            "sym": sym, "ts": int(t.timestamp),
                            "price": int(t.price), "qty": int(t.quantity),
                            "side": "ask",
                        })
                        seen.add(key)
        td["m14_trades"] = log

    def _recent_m14_levels(self, product: str, td: dict, cur_ts: int
                            ) -> Tuple[Optional[int], Optional[int]]:
        """Return (median bid, median ask) of Mark 14 trades in lookback window
        for `product`. None if no observations on that side."""
        log: List[Dict] = td.get("m14_trades", [])
        cutoff = cur_ts - SHADOW_LOOKBACK_TICKS * 100
        bids = []
        asks = []
        for e in log:
            if e["sym"] != product or e["ts"] < cutoff:
                continue
            if e["side"] == "bid":
                bids.append(e["price"])
            else:
                asks.append(e["price"])
        med_bid = self._median(bids) if bids else None
        med_ask = self._median(asks) if asks else None
        return med_bid, med_ask

    def _median(self, lst: List[int]) -> int:
        s = sorted(lst)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) // 2

    def _shadow_quotes(self, product: str, od: OrderDepth, pos: int,
                        td: dict, cur_ts: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]

        m14_bid, m14_ask = self._recent_m14_levels(product, td, cur_ts)

        orders: List[Order] = []
        limit = LIMITS[product]
        soft = int(SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos

        # Quote one tick BETTER than Mark 14 — but never cross top-of-book.
        # Our bid: max(m14_bid + 1, best_bid + 1) capped under best_ask
        if m14_bid is not None:
            our_bid = m14_bid + 1
            # Cap: must be <= best_bid + 1 (don't outrun the book; also don't
            # post below best_bid since that's pointless)
            if our_bid > best_ask - 1:
                our_bid = best_ask - 1
            # If our inferred Mark 14 bid is already worse than best_bid,
            # post at best_bid + 1 (penny-jump the book)
            if our_bid < best_bid:
                our_bid = best_bid + 1 if (best_bid + 1) < best_ask else best_bid
        else:
            our_bid = None

        if m14_ask is not None:
            our_ask = m14_ask - 1
            if our_ask < best_bid + 1:
                our_ask = best_bid + 1
            if our_ask > best_ask:
                our_ask = best_ask - 1 if (best_ask - 1) > best_bid else best_ask
        else:
            our_ask = None

        # Final guard: bid must be < ask
        if our_bid is not None and our_ask is not None and our_bid >= our_ask:
            return []

        bsize = SHADOW_QUOTE_SIZE
        asize = SHADOW_QUOTE_SIZE
        # Soft inventory cap
        if pos >= soft:
            bsize = 0
        elif pos <= -soft:
            asize = 0

        bqty = min(bsize, max(0, buy_room))
        aqty = min(asize, max(0, sell_room))

        if our_bid is not None and bqty > 0:
            orders.append(Order(product, int(our_bid), bqty))
        if our_ask is not None and aqty > 0:
            orders.append(Order(product, int(our_ask), -aqty))
        return orders

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
