"""MARK-ONLY VARIANT 1 - Aggressive takes only.

Standalone trader (no IV-scalp, no stratton MM). For each product with a
high-confidence Mark signal, watch state.market_trades for a recent Mark
trade matching one of the signal patterns. When found, place an aggressive
take (lift the ask if action=BUY, hit the bid if action=SELL) at top of
book. NO other orders ever.

Signal universe (calibration/marks/signals.json, confidence == "high"
AND |drift_H200_mean| >= 1.0):
  - HYDROGEL_PACK, VEV_4000: Mark 14 (follow), Mark 38 (fade)
  - VELVETFRUIT_EXTRACT: Mark 01 (follow), Mark 55 (fade)
  - VEV_5300/5400/5500: Mark 22 (fade) and Mark 01 (follow)

Tunables:
  MARK_LOOKBACK_TICKS = 20    # consider trades from the last 20 ticks
  MARK_TAKE_COOLDOWN  = 25    # min ticks between takes per product
  MARK_TAKE_SIZE      = 5     # lots per take, capped by book depth + room
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
VEV_4500 = "VEV_4500"
VEV_5000 = "VEV_5000"
VEV_5100 = "VEV_5100"
VEV_5200 = "VEV_5200"
VEV_5300 = "VEV_5300"
VEV_5400 = "VEV_5400"
VEV_5500 = "VEV_5500"
VEV_6000 = "VEV_6000"
VEV_6500 = "VEV_6500"

LIMITS: Dict[str, int] = {
    HYDROGEL: 200, VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

# === Inlined Mark signals (high-confidence, |drift_H200| >= 1.0) =========
# (mark, product, mark_side, action_for_us, drift_abs)
MARK_SIGNALS: List[Tuple[str, str, str, str, float]] = [
    # HYDROGEL — strong (drift ~7-9 ticks)
    ("Mark 14", HYDROGEL,    "buyer",  "BUY",  8.938),
    ("Mark 38", HYDROGEL,    "seller", "BUY",  8.554),
    ("Mark 14", HYDROGEL,    "seller", "SELL", 7.415),
    ("Mark 38", HYDROGEL,    "buyer",  "SELL", 7.321),
    # VEV_4000 — strong (drift ~10-11 ticks)
    ("Mark 14", VEV_4000,    "seller", "SELL", 11.263),
    ("Mark 38", VEV_4000,    "buyer",  "SELL", 11.081),
    ("Mark 38", VEV_4000,    "seller", "BUY",  9.938),
    ("Mark 14", VEV_4000,    "buyer",  "BUY",  9.892),
    # VELVETFRUIT — moderate (drift ~1-3 ticks)
    ("Mark 01", VELVETFRUIT, "seller", "SELL", 2.730),
    ("Mark 55", VELVETFRUIT, "buyer",  "SELL", 1.622),
    ("Mark 55", VELVETFRUIT, "seller", "BUY",  1.363),
    ("Mark 01", VELVETFRUIT, "buyer",  "BUY",  2.054),
    # VEV_5300/5400/5500 — weak (drift ~0.5-1.3)
    ("Mark 22", VEV_5300,    "seller", "BUY",  1.270),
    ("Mark 01", VEV_5300,    "buyer",  "BUY",  1.205),
]

MARK_LOOKUP: Dict[Tuple[str, str, str], str] = {
    (p, m, s): a for (m, p, s, a, _d) in MARK_SIGNALS
}
MARK_PRODUCTS = set(s[1] for s in MARK_SIGNALS)

MARK_LOOKBACK_TICKS = 20
MARK_TAKE_COOLDOWN = 25
MARK_TAKE_SIZE = 5
MARK_WINDOW_LOG_TICKS = 50  # bigger buffer to keep enough history


class Trader:
    MAF_BID = 0  # zero — this is an experiment, no auction commitment

    def bid(self) -> int:
        return int(self.MAF_BID)

    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        self._update_mark_log(state, td)
        cur_ts = state.timestamp

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            if product not in MARK_PRODUCTS:
                result[product] = []
                continue
            od = state.order_depths[product]
            pos = state.position.get(product, 0)

            action = self._mark_take_for(product, td, cur_ts)
            if action is None:
                result[product] = []
                continue
            orders = self._emit_take(product, action, od, pos)
            if orders:
                # Record cooldown
                last_map = td.get("last_take_ts", {})
                last_map[product] = cur_ts
                td["last_take_ts"] = last_map
            result[product] = orders

        return result, 0, json.dumps(td)

    # === Mark trade log ====================================================
    def _update_mark_log(self, state: TradingState, td: dict) -> None:
        log: List[Dict] = td.get("mark_trades", [])
        cur_ts = state.timestamp
        cutoff = cur_ts - MARK_WINDOW_LOG_TICKS * 100
        log = [e for e in log if e["ts"] >= cutoff]
        seen = {(e["sym"], e["ts"], e["price"], e["qty"], e["buyer"], e["seller"])
                for e in log}
        for sym, trades in (state.market_trades or {}).items():
            if sym not in MARK_PRODUCTS:
                continue
            for t in trades:
                buyer = t.buyer or ""
                seller = t.seller or ""
                if not buyer and not seller:
                    continue
                # Only keep entries that match a known signal (saves storage)
                if (sym, buyer, "buyer") not in MARK_LOOKUP and \
                   (sym, seller, "seller") not in MARK_LOOKUP:
                    continue
                key = (sym, t.timestamp, t.price, t.quantity, buyer, seller)
                if key in seen:
                    continue
                log.append({
                    "sym": sym, "ts": int(t.timestamp), "price": int(t.price),
                    "qty": int(t.quantity), "buyer": buyer, "seller": seller,
                })
                seen.add(key)
        td["mark_trades"] = log

    def _mark_take_for(self, product: str, td: dict, cur_ts: int
                        ) -> Optional[str]:
        last_map: Dict[str, int] = td.get("last_take_ts", {})
        last = last_map.get(product, -10**9)
        if cur_ts - last < MARK_TAKE_COOLDOWN * 100:
            return None
        log: List[Dict] = td.get("mark_trades", [])
        cutoff = cur_ts - MARK_LOOKBACK_TICKS * 100
        best_action: Optional[str] = None
        best_ts = -1
        for e in log:
            if e["sym"] != product or e["ts"] < cutoff:
                continue
            buyer, seller = e["buyer"], e["seller"]
            act = MARK_LOOKUP.get((product, buyer, "buyer"))
            if act is not None and e["ts"] > best_ts:
                best_action = act
                best_ts = e["ts"]
            act2 = MARK_LOOKUP.get((product, seller, "seller"))
            if act2 is not None and e["ts"] > best_ts:
                best_action = act2
                best_ts = e["ts"]
        return best_action

    def _emit_take(self, product: str, action: str, od: OrderDepth,
                    pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        limit = LIMITS[product]
        buy_room = limit - pos
        sell_room = limit + pos
        if action == "BUY":
            ask_vol = -od.sell_orders[best_ask]
            qty = min(MARK_TAKE_SIZE, buy_room, ask_vol)
            if qty <= 0:
                return []
            return [Order(product, best_ask, qty)]
        else:  # SELL
            bid_vol = od.buy_orders[best_bid]
            qty = min(MARK_TAKE_SIZE, sell_room, bid_vol)
            if qty <= 0:
                return []
            return [Order(product, best_bid, -qty)]

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
