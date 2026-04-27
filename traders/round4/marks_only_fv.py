"""MARK-ONLY VARIANT 3 - Mark-driven fair value + MM.

Standalone trader. Use a rolling EMA of Mark 14 + Mark 01 trade prices
(both have agg_pct == 0.0 == informed passive MMs) as the fair-value
signal. Quote tightly around that FV.

Universe of products with non-trivial Mark 14/01 informed flow (from
signals.json):
  - HYDROGEL_PACK         (Mark 14)
  - VEV_4000              (Mark 14)
  - VELVETFRUIT_EXTRACT   (Mark 14, Mark 01)
  - VEV_5300              (Mark 01)
  - VEV_5400              (Mark 01)
  - VEV_5500              (Mark 01)

For each: maintain EMA of recent informed-Mark trade prices. When
EMA available + book has >= MIN_SPREAD spread, quote at
(round(fv) - 1, round(fv) + 1) capped to be inside top-of-book.
Modest size, soft inventory cap.
"""

try:
    from datamodel import Order, OrderDepth, TradingState, Trade
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState, Trade

from typing import Dict, List, Optional, Tuple
import json


HYDROGEL = "HYDROGEL_PACK"
VELVETFRUIT = "VELVETFRUIT_EXTRACT"
VEV_4000 = "VEV_4000"
VEV_5300 = "VEV_5300"
VEV_5400 = "VEV_5400"
VEV_5500 = "VEV_5500"

LIMITS: Dict[str, int] = {
    HYDROGEL: 200, VELVETFRUIT: 200,
    VEV_4000: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
}

# product -> set of Mark IDs to include in FV (informed passive only)
INFORMED_MARKS: Dict[str, set] = {
    HYDROGEL:    {"Mark 14"},
    VEV_4000:    {"Mark 14"},
    VELVETFRUIT: {"Mark 14", "Mark 01"},
    VEV_5300:    {"Mark 01"},
    VEV_5400:    {"Mark 01"},
    VEV_5500:    {"Mark 01"},
}

FV_PRODUCTS = tuple(INFORMED_MARKS.keys())

EMA_ALPHA = 0.05            # half-life ~14 ticks (fast — these are noisy)
MIN_OBS_BEFORE_QUOTE = 5    # need this many informed-Mark prints first
QUOTE_SIZE = 10
SOFT_POS_FRAC = 0.5
MIN_SPREAD = 2              # don't quote when book spread < 2


class Trader:
    MAF_BID = 0

    def bid(self) -> int:
        return int(self.MAF_BID)

    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        # Update EMA from each new informed-Mark trade
        self._update_fv(state, td)

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            if product not in FV_PRODUCTS:
                result[product] = []
                continue
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            result[product] = self._mm_around_fv(product, od, pos, td)
        return result, 0, json.dumps(td)

    def _update_fv(self, state: TradingState, td: dict) -> None:
        for sym, trades in (state.market_trades or {}).items():
            if sym not in INFORMED_MARKS:
                continue
            allowed = INFORMED_MARKS[sym]
            for t in trades:
                buyer = t.buyer or ""
                seller = t.seller or ""
                # If either counterparty is one of our informed Marks,
                # the print is a "signal price". (Both sides considered
                # equal weight — agg_pct == 0 means they were on the book.)
                if buyer in allowed or seller in allowed:
                    px = float(t.price)
                    ema_key = f"fv_{sym}"
                    n_key = f"fvn_{sym}"
                    prev = td.get(ema_key)
                    if prev is None:
                        td[ema_key] = px
                    else:
                        td[ema_key] = (1.0 - EMA_ALPHA) * prev + EMA_ALPHA * px
                    td[n_key] = td.get(n_key, 0) + 1

    def _mm_around_fv(self, product: str, od: OrderDepth, pos: int,
                       td: dict) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < MIN_SPREAD:
            return []

        fv = td.get(f"fv_{product}")
        n = td.get(f"fvn_{product}", 0)
        if fv is None or n < MIN_OBS_BEFORE_QUOTE:
            return []

        # Target quote: (floor(fv) - 0, ceil(fv) + 0) but at minimum
        # 1 tick inside the book.
        # We quote +/-1 around fv if that fits inside the book.
        fv_int = int(round(fv))
        our_bid = fv_int - 1
        our_ask = fv_int + 1

        # Stay strictly inside the book (penny-jump)
        if our_bid < best_bid + 1:
            our_bid = best_bid + 1
        if our_ask > best_ask - 1:
            our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        limit = LIMITS[product]
        soft = int(SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos

        bsize = QUOTE_SIZE
        asize = QUOTE_SIZE

        # Inventory skew: shrink the side that grows our position
        if pos > 0:
            bsize = max(2, bsize // 2)
        elif pos < 0:
            asize = max(2, asize // 2)
        if pos >= soft:
            bsize = 0
        elif pos <= -soft:
            asize = 0

        bqty = min(bsize, max(0, buy_room))
        aqty = min(asize, max(0, sell_room))
        orders: List[Order] = []
        if bqty > 0:
            orders.append(Order(product, our_bid, bqty))
        if aqty > 0:
            orders.append(Order(product, our_ask, -aqty))
        return orders

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
