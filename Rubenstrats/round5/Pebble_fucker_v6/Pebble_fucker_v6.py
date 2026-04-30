"""Pebble_fucker_v6 — v4 + POS_CAP[XL] = 6.

Lever attribution from v4 → v5_portal → v5_clean portal subs:

    v4:        single-leg take, XL cap=10, XL skew=0.1   →  XL = -1,642
    v5_portal: multi-leg  take, XL cap= 6, XL skew=0.0   →  XL = +126,  M = -2,822
    v5_clean:  single-leg take, XL cap=10, XL skew=0.0   →  XL = -1,630, M = +117

Pinning the variables:
  * Multi-leg take BREAKS M (-2,939 swing) by recreating v2-style basket
    inventory accumulation across legs.
  * XL cap=6 FIXES XL (+1,768 swing) by limiting the per-tick drift
    exposure on a σ=30/tick asset — full 10-lot capacity gives drift more
    room to compound MTM losses than passive MM can unwind.
  * XL skew on/off is a no-op (-1,642 → -1,630, noise).

So v6 = v4 (single-leg take, all skew on) + the ONLY real lever that helped:
XL position capped at ±6. The skew on XL stays at 0.1 since v5_clean proved
zeroing it doesn't matter.

Predicted portal: ~+6,300 (XS+S+M+L unchanged at +6,213, XL flips from
-1,642 to ~+126).
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

# Per-leg position cap. XL tightened to 6 — this was the actual lever that
# stopped the XL bleed in v5_portal (the LAMBDA_PX[XL]=0 change was a no-op).
POS_CAP: Dict[str, int] = {
    "PEBBLES_XS": 10,
    "PEBBLES_S": 10,
    "PEBBLES_M": 10,
    "PEBBLES_L": 10,
    "PEBBLES_XL": 6,
}

# Per-leg lean-into-inventory price-skew gain (ticks/lot of |position|).
# Same on every leg — v5_clean proved zeroing on XL doesn't matter.
LAMBDA_PX = 0.1

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

        # 3. Single-leg take target — smallest-h leg that qualifies.
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

            # Lean-into-inventory price-skew on the unwind side only.
            inv_shift = int(round(LAMBDA_PX * abs(position)))
            if position > 0:
                passive_bid_px = best_bid + 1
                passive_ask_px = best_ask - 1 - inv_shift
            elif position < 0:
                passive_bid_px = best_bid + 1 + inv_shift
                passive_ask_px = best_ask - 1
            else:
                passive_bid_px = best_bid + 1
                passive_ask_px = best_ask - 1

            # Don't cross own quotes / cross the bot.
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
            if p == take_target and take_side == "sell" and max_sell > 0:
                take_qty = min(best_bid_qty[p], max_sell)
                if take_qty > 0:
                    orders.append(Order(p, best_bid, -take_qty))
                    max_sell -= take_qty
                    took_sell = True
            elif p == take_target and take_side == "buy" and max_buy > 0:
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
