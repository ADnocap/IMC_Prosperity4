"""Pebble_fucker_v5 — v4 with XL price-skew disabled (the bleeder).

v4 portal sub 559847 broke down per-leg as:

    XS  +4,096   (90% of total)
    S   +1,265
    L     +735
    M     +117
    XL  -1,642
    --------------
    TOTAL +4,571   peak +5,045   trough -1,304   max_DD 1,808

XS dominates because:
  * smallest h (4.5) → biggest take edge per cross
  * lowest σ (15/tick) → inventory accumulated by skew unwinds before mid drifts

XL bleeds because:
  * h=8.5 → take threshold |r|>9.5 rarely clears, almost no take
  * σ=30/tick → 2× the volatility of others; positions accumulate faster than
    the lean-into-inventory ask-shift can shed them, so MTM losses pile up
    while we sit long XL into a falling tape (or short into rising)
  * the LAMBDA_PX=0.1 inventory shift is overwhelmed by the per-tick drift

v5 changes:

  #1  PRICE-SKEW DISABLED ON XL. XL trades pure penny-jump, no inventory
      shift. The skew works on lower-σ legs (XS, S, M, L) where the shift's
      one-tick benefit isn't drowned by per-tick noise.

  #2  EXTEND TAKE TO SECOND LEG (S) when XS uses up max_sell/max_buy. With
      a residual large enough to clear S's threshold (h_S+1=7.0), and XS at
      its position limit, we'd otherwise leave the residual on the table.
      v4's smallest-h-only rule misses this.

  #3  BACKSTOP on XL inventory: tighter MAX_POS_XL = 6 (instead of 10).
      Caps the risk on the bleeding leg without removing it from the
      basket-residual computation (still need all 5 mids for residual).

Same v1-style residual gating + penny-jump otherwise.
"""

from typing import Dict, List

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


PEBBLES = (
    "PEBBLES_XS",
    "PEBBLES_S",
    "PEBBLES_M",
    "PEBBLES_L",
    "PEBBLES_XL",
)
BASKET_SUM = 50_000
POSITION_LIMIT = 10

# Per-leg half-spread (median, analysis/round5/eda_per_product.csv).
HALF_SPREAD: Dict[str, float] = {
    "PEBBLES_XS": 4.5,
    "PEBBLES_S": 6.0,
    "PEBBLES_M": 6.5,
    "PEBBLES_L": 6.5,
    "PEBBLES_XL": 8.5,
}

# Per-leg position cap. XL tightened to 6 to bound the bleed.
POS_CAP: Dict[str, int] = {
    "PEBBLES_XS": 10,
    "PEBBLES_S": 10,
    "PEBBLES_M": 10,
    "PEBBLES_L": 10,
    "PEBBLES_XL": 6,
}

# Per-leg price-skew gain (ticks/lot). Zero on XL — its σ=30/tick washes out
# any skew benefit, and the resulting adverse-selection drag was -1,642 in v4.
LAMBDA_PX: Dict[str, float] = {
    "PEBBLES_XS": 0.1,
    "PEBBLES_S": 0.1,
    "PEBBLES_M": 0.1,
    "PEBBLES_L": 0.1,
    "PEBBLES_XL": 0.0,
}

# Half-tick parity floor; below this the residual is rounding noise.
RESIDUAL_THRESHOLD = 1.0

# Take ordering: smallest h first → biggest edge per cross.
TAKE_ORDER = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")
TAKE_CUSHION = 1.0


class Trader:

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # 1. Pull L1; bail if any pebble book is empty.
        mids: Dict[str, float] = {}
        best_bids: Dict[str, int] = {}
        best_asks: Dict[str, int] = {}
        best_bid_qty: Dict[str, int] = {}
        best_ask_qty: Dict[str, int] = {}
        for p in PEBBLES:
            od = state.order_depths.get(p)
            if od is None or not od.buy_orders or not od.sell_orders:
                return result, 0, ""
            best_bids[p] = max(od.buy_orders.keys())
            best_asks[p] = min(od.sell_orders.keys())
            best_bid_qty[p] = od.buy_orders[best_bids[p]]
            best_ask_qty[p] = abs(od.sell_orders[best_asks[p]])
            mids[p] = (best_bids[p] + best_asks[p]) / 2.0

        residual = sum(mids.values()) - BASKET_SUM

        # 2. v1-style direction gating for passive sizes.
        if residual > RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = False, True
        elif residual < -RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = True, False
        else:
            allow_bid_global, allow_ask_global = True, True

        # 3. Pre-compute take eligibility per leg in TAKE_ORDER. We extend
        #    beyond first-qualifying because positions on the smallest-h
        #    leg (XS) can be exhausted before the residual is reverted.
        take_targets: Dict[str, str] = {}  # symbol -> "buy" or "sell"
        if residual > 0:
            for q in TAKE_ORDER:
                if residual > HALF_SPREAD[q] + TAKE_CUSHION:
                    take_targets[q] = "sell"
        elif residual < 0:
            for q in TAKE_ORDER:
                if -residual > HALF_SPREAD[q] + TAKE_CUSHION:
                    take_targets[q] = "buy"

        # 4. Per-leg orders.
        for p in PEBBLES:
            position = state.position.get(p, 0)
            best_bid = best_bids[p]
            best_ask = best_asks[p]

            cap = POS_CAP[p]
            max_buy = max(0, cap - position)
            max_sell = max(0, cap + position)

            # Per-leg lean-into-inventory price-skew (zero on XL).
            inv_shift = int(round(LAMBDA_PX[p] * abs(position)))
            if position > 0:
                passive_bid_px = best_bid + 1
                passive_ask_px = best_ask - 1 - inv_shift
            elif position < 0:
                passive_bid_px = best_bid + 1 + inv_shift
                passive_ask_px = best_ask - 1
            else:
                passive_bid_px = best_bid + 1
                passive_ask_px = best_ask - 1

            # Guards: don't cross the bot or self-cross.
            if passive_ask_px <= best_bid:
                passive_ask_px = best_bid + 1
            if passive_bid_px >= best_ask:
                passive_bid_px = best_ask - 1
            if passive_bid_px >= passive_ask_px:
                continue

            orders: List[Order] = []
            took_sell = False
            took_buy = False

            # --- Take layer (multi-leg, smallest-h first by TAKE_ORDER). ---
            side = take_targets.get(p)
            if side == "sell" and max_sell > 0:
                take_qty = min(best_bid_qty[p], max_sell)
                if take_qty > 0:
                    orders.append(Order(p, best_bid, -take_qty))
                    max_sell -= take_qty
                    took_sell = True
            elif side == "buy" and max_buy > 0:
                take_qty = min(best_ask_qty[p], max_buy)
                if take_qty > 0:
                    orders.append(Order(p, best_ask, take_qty))
                    max_buy -= take_qty
                    took_buy = True

            # --- v1-style passive sizing with global gating. ---
            allow_bid = allow_bid_global and not took_sell
            allow_ask = allow_ask_global and not took_buy

            bid_qty = max_buy if allow_bid else 0
            ask_qty = max_sell if allow_ask else 0

            if bid_qty > 0:
                orders.append(Order(p, passive_bid_px, bid_qty))
            if ask_qty > 0:
                orders.append(Order(p, passive_ask_px, -ask_qty))

            result[p] = orders

        return result, 0, ""