"""Pebble_winner — locked R5 pebble trader (was Pebble_fucker_v5_clean).

Selected after a 5-version sweep (v1..v6, portal subs 557974, 558352, 558769,
559847, 559976, 560220, 560506). Final portal day-4 1K-tick: +4,583.
Sister versions and analysis live under ../Pebble_fucker_v{1..6}/.

Lever attribution from the sweep:
  * Concentrated single-leg take on the smallest-h leg (XS first) is the
    main edge — XS alone delivers ~+4,000 of the +4,500 portal total.
  * Multi-leg take recreates v2-style basket-stacking and bleeds M and XL.
  * Per-leg position cap below 10 hurts (less MM capacity, more bleed).
  * Lean-into-inventory price-skew is mildly positive on XS/S/L, neutral
    on M, neutral-or-mildly-negative on XL.
  * Setting LAMBDA_PX[XL]=0 (the v4→v5 change) was a no-op (-1,642 vs
    -1,630, noise). Kept here as a defensible default but the win is
    elsewhere.
  * v5_portal's apparent XL fix (+126 vs v4's -1,642) came from the
    multi-leg take giving XL the cross-spread edge directly, not from
    skew or cap changes. Multi-leg take's M/L bleed exceeds the XL gain,
    so we don't ship it.

Original docstring follows.

---

Pebble_fucker_v5 — v4 with XL price-skew disabled (the bleeder).

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

v5 change (one surgical edit vs v4):

  PRICE-SKEW DISABLED ON XL. XL trades pure penny-jump (LAMBDA_PX=0).
  The skew remains on lower-σ legs (XS, S, M, L) where the one-tick
  ask-shift earns more than σ-driven adverse selection costs.

Multi-leg takes were tried and rejected — they recreated v2's basket
inventory accumulation (MC std blew from 1.3k to 8.7k). Single-leg take
in TAKE_ORDER (smallest-h first) is the right concentration.

Position cap stays uniform at 10. The XL bleed in v4 was a price-skew
artifact, not a position-range artifact, so tightening cap there only
sacrifices upside without fixing root cause.
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

# Per-leg position cap (uniform — XL bleed in v4 came from the price-skew,
# not from the position range, so leaving capacity at 10 across the board).
POS_CAP: Dict[str, int] = {p: POSITION_LIMIT for p in PEBBLES}

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

        # 3. Pre-compute take target — single leg, smallest-h first.
        #    Multi-leg takes were tested in an earlier v5 draft and blew up
        #    variance (std 8.7k vs v4's 1.3k) by recreating v2's basket
        #    inventory accumulation. Single-leg take is the right concentration.
        take_target = None
        take_side = None
        if residual > 0:
            for q in TAKE_ORDER:
                if residual > HALF_SPREAD[q] + TAKE_CUSHION:
                    take_target, take_side = q, "sell"
                    break
        elif residual < 0:
            for q in TAKE_ORDER:
                if -residual > HALF_SPREAD[q] + TAKE_CUSHION:
                    take_target, take_side = q, "buy"
                    break

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

            # --- Take layer (single leg, smallest-h first). ---
            side = take_side if p == take_target else None
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
