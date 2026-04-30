"""Pebble_fucker_v4 — v1 + lean-into-inventory price-skew + smallest-h take.

Diagnosis recap (see diagnose_v4.py + earlier v4 attempts):

  * Basket constraint enforced fast: |r|<=1 in 96.9% of ticks. Most of the
    PnL comes from harvesting penny-jump spread in noise zone, not from
    residual takes (which fire ~3% of ticks).
  * Per-leg 5-tick |Δmid| ≈ 27 (σ=15√5). Stale-leg-via-velocity is hopeless
    at this scale — there are no quiet legs.
  * Earlier v4 attempts hurt mean PnL by being too clever in the noise zone.
    Continuous size-skew driven by `-r/5` introduces tilt where there's no
    real signal (since |r| is just rounding); two-sided price-skew cripples
    competitiveness when inventory is large.

v4 keeps v1's structure intact and adds two surgical upgrades:

  #1  CONCENTRATED TAKES on the smallest-h leg only. Edge per cross is
      |r| - h_p, biggest on XS (h=4.5). Taking only the lowest-h leg cuts
      basket inventory variance versus v2/v3 (which took on every qualifying
      leg simultaneously and ended up at -50 basket).

  #3  LEAN-INTO-INVENTORY PRICE-SKEW (one-sided). When long, the ASK
      quote is shifted IN by `floor(LAMBDA_PX * pos)` ticks (more aggressive
      sell, faster unwind). The BID stays at penny-jump — we don't punish
      our own MM-fill rate just because we're long. Mirror when short.

In noise zone (|r| ≤ RESIDUAL_THRESHOLD): symmetric penny-jump on both sides
with one-sided inventory price-skew. In signal zone: v1-style binary side
gating with one-sided inventory price-skew. In take zone: cross the
smallest-h qualifying leg, then post the same-side passive for residual capacity.
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

# 0.5-tick parity floor; below this the residual is rounding noise.
RESIDUAL_THRESHOLD = 1.0

# Take order: smallest h first → biggest edge per cross.
TAKE_ORDER = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")
TAKE_CUSHION = 1.0

# Inventory price-skew: ticks of one-sided shift per lot of position.
# At pos=±10 this shifts the unwind side IN by 1 tick (LAMBDA_PX=0.1).
LAMBDA_PX = 0.1


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

        # 2. Direction gating (v1-style for non-take sizing).
        if residual > RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = False, True
        elif residual < -RESIDUAL_THRESHOLD:
            allow_bid_global, allow_ask_global = True, False
        else:
            allow_bid_global, allow_ask_global = True, True

        # 3. Find the single take target leg (smallest h that qualifies).
        take_target = None
        take_side = None
        if residual > 0:
            for p in TAKE_ORDER:
                if residual > HALF_SPREAD[p] + TAKE_CUSHION:
                    take_target = p
                    take_side = "sell"
                    break
        elif residual < 0:
            for p in TAKE_ORDER:
                if -residual > HALF_SPREAD[p] + TAKE_CUSHION:
                    take_target = p
                    take_side = "buy"
                    break

        # 4. Per-leg orders.
        for p in PEBBLES:
            position = state.position.get(p, 0)
            best_bid = best_bids[p]
            best_ask = best_asks[p]

            max_buy = max(0, POSITION_LIMIT - position)
            max_sell = max(0, POSITION_LIMIT + position)

            # Lean-into-inventory price-skew: only the unwind side gets shifted.
            # Long pos>0 → ask comes IN by |LAMBDA_PX*pos|, bid stays at penny.
            # Short pos<0 → bid goes UP by |LAMBDA_PX*pos|, ask stays at penny.
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

            # --- Take layer (concentrated on smallest-h leg). ---
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
