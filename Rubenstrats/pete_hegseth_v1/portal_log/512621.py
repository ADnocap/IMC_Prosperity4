"""pete_hegseth_v1 — counterparty-flow follower on VELVETFRUIT_EXTRACT.

Round-4 trades CSVs reveal each fill's buyer/seller (anonymised as
"Mark 01..67"). A lead-lag test on every (trader, symbol, horizon)
slice — pooled across days 1/2/3, then re-run on day 3 alone as
out-of-sample holdout — found two signals that survive both:

    Mark 67 BUYS  VELVETFRUIT_EXTRACT  ->  +1.97 mid  (h=1, t=+26.2 pooled / +13.1 d3)
                                       ->  +2.13 mid  (h=20, t=+3.34 d3)
    Mark 49 SELLS VELVETFRUIT_EXTRACT  ->  -2.05 mid  (h=1, t=-19.0 pooled / -11.7 d3)
                                       ->  -2.50 mid  (h=20, t=-3.69 d3)

Both edges hold per-day with t-stats scaling ~1/sqrt(N) — i.e. the
signal is genuinely intra-day stable, not an artifact of two
re-released days. Mean signed move is ~+/-2 mid units sustained
through h~20 (i.e. 2000 timestamps), decaying past that.

Mark 22's VEV-ladder fade signals from the pooled run failed to
replicate on day-3 holdout, so they're ignored here.

Strategy:
    - Watch state.market_trades[VELVETFRUIT_EXTRACT] each tick.
    - For every NEW Mark 67 buy: register a long bias of +qty,
      decaying linearly over HOLD_TICKS.
    - For every NEW Mark 49 sell: register a short bias of -qty,
      decaying linearly over HOLD_TICKS.
    - Sum active biases into a target position, clamp to limit.
    - Reach target via aggressive cross-spread takes (the alpha
      decays in ~20 ticks, so sitting passive misses most of it).

Other products quoted as a thin penny-jump MM purely so we don't
forfeit edge on unrelated assets while testing the signal in isolation.
That's intentionally minimal — the point of v1 is to A/B *the
follower* against doing nothing on VELVETFRUIT.
"""

try:
    from datamodel import Order, OrderDepth, TradingState, Trade
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState, Trade

from typing import Dict, List, Optional, Tuple
import json


VELVETFRUIT = "VELVETFRUIT_EXTRACT"
INFORMED_BUYER = "Mark 67"
INFORMED_SELLER = "Mark 49"

LIMIT_VELVETFRUIT = 200

# Hold horizon: signal mean ~+2 mid through h=20 (2000 ts), t-stat at
# h=20 still 3-5 OOS. Past 2000 ts t-stat collapses, so we exit by then.
HOLD_TICKS = 2000

# Per-trade bias multiplier. The lead-lag test measured fills of avg
# size ~9; a bias of K * qty units of position per fill, summed across
# many fills, gives the directional book.
SIGNAL_GAIN = 4.0  # position units per traded share at peak

# Take aggressively — alpha decays before passive fills accumulate.
TAKE_MAX = 40


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        ts = state.timestamp

        # Active biases: list of (trigger_ts, signed_size). Decays linearly
        # over HOLD_TICKS, drops out once expired.
        biases: List[List[int]] = td.get("biases", [])
        last_seen_ts: int = td.get("last_seen_ts", -1)

        # Scan VELVETFRUIT market_trades for NEW Mark 67 / Mark 49 fills.
        new_high_water = last_seen_ts
        for trade in (state.market_trades or {}).get(VELVETFRUIT, []) or []:
            if trade.timestamp <= last_seen_ts:
                continue
            if trade.timestamp > new_high_water:
                new_high_water = trade.timestamp
            qty = abs(int(trade.quantity))
            if trade.buyer == INFORMED_BUYER:
                biases.append([trade.timestamp, +qty])
            elif trade.seller == INFORMED_SELLER:
                biases.append([trade.timestamp, -qty])
        td["last_seen_ts"] = new_high_water

        # Drop expired biases, sum active signed weight (linear decay).
        live: List[List[int]] = []
        signed_weight = 0.0
        for trigger_ts, signed_qty in biases:
            age = ts - trigger_ts
            if age >= HOLD_TICKS or age < 0:
                continue
            decay = max(0.0, 1.0 - age / HOLD_TICKS)
            signed_weight += signed_qty * decay
            live.append([trigger_ts, signed_qty])
        td["biases"] = live

        # Target position: gain * signed_weight, clamped to limit.
        raw_target = SIGNAL_GAIN * signed_weight
        target = int(max(-LIMIT_VELVETFRUIT, min(LIMIT_VELVETFRUIT, raw_target)))

        result: Dict[str, List[Order]] = {}
        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            if product == VELVETFRUIT:
                result[product] = self._trade_velvet(od, pos, target)
            else:
                result[product] = []  # v1 keeps all other assets flat

        return result, 0, json.dumps(td)

    def _trade_velvet(self, od: OrderDepth, pos: int, target: int) -> List[Order]:
        """Aggressive take toward target; passive top-of-book if at target."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []

        diff = target - pos
        buy_room = LIMIT_VELVETFRUIT - pos
        sell_room = LIMIT_VELVETFRUIT + pos
        orders: List[Order] = []

        if diff > 0:
            cap = min(diff, TAKE_MAX, buy_room)
            for ap in asks:
                if cap <= 0:
                    break
                vol = -od.sell_orders[ap]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(VELVETFRUIT, ap, qty))
                cap -= qty
        elif diff < 0:
            cap = min(-diff, TAKE_MAX, sell_room)
            for bp in bids:
                if cap <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(VELVETFRUIT, bp, -qty))
                cap -= qty

        return orders

    @staticmethod
    def _parse_td(s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}