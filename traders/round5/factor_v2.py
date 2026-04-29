"""Round 5 factor_v2 — 2-sided MM with drift signal + basket-residual MR.

Compared to factor_v1 the big change is **always quote both sides** (penny-jump
bid AND ask sized to remaining position-limit budget). v1 only sent one-sided
close-the-gap orders, leaving 6-8 ticks of edge per fill on the table for
every adversely-selected pulse.

Per-asset layer (all 50)
------------------------
  fv_i  = EMA of mid (HL_TICKS, slow)
  z_i   = (mid_i - fv_i) / sigma_i              # mean-reversion signal
  obi   = (bid1_vol - ask1_vol) / (bid1_vol + ask1_vol)
  target_i = clip(-MR_K * z_i + OBI_K * obi, -TARGET_FRAC, +TARGET_FRAC) * POS_LIMIT
  diff   = target_i - pos
  ┌─ big-side / small-side sizes
  │   if diff > 0: bid_qty=BIG, ask_qty=SMALL  (skew toward buying)
  │   if diff < 0: bid_qty=SMALL, ask_qty=BIG  (skew toward selling)
  │   else:        bid_qty=BAL, ask_qty=BAL    (balanced 2-sided MM)
  └─ cap by worst-case room: bid ≤ POS_LIMIT - pos, ask ≤ POS_LIMIT + pos
  Place at penny-jump (best_bid+1, best_ask-1) when spread ≥ 2.

Basket-residual MR layer (5 pebbles + 2 snackpack pair + 3 snackpack triplet)
-----------------------------------------------------------------------------
- Pebbles: sum is exactly 50,000 → residual_i = pebble_i - 10000.
  Σ residual = 0. Each residual is OU around 0 with calibrated half-life.
  Add MR_K_BASKET * residual / σ_basket to z_i.
- Snackpack CHOC/VAN pair: K = CHOC + VAN, slow OU around K_day.
  K_residual = K(t) - EMA_K(t). Add ±MR_K_PAIR * K_resid/sigma_K to both legs
  (long when K below trend, short when above).
- Snackpack triplet: residual_i = mid_i - factor_proj_i where
  factor_proj_i = ℓ_i × Σ_j ℓ_j × mid_j  (loadings from PCA fit).
  Boost MR signal by MR_K_TRIPLET on each.

State persistence: traderData = JSON dict (EMAs, EMA_K).

Parameters (v2 defaults — to tune):
  HL_TICKS    = 3000   # fair value EMA, ~2x median OU half-life
  HL_BASKET   = 1500   # faster EMA for basket residuals (their HL is shorter)
  MR_K        = 0.6    # alpha-to-target scale per asset
  MR_K_BASKET = 1.0    # basket residual boost
  MR_K_PAIR   = 1.2
  MR_K_TRIPLET= 1.0
  OBI_K       = 0.3    # OBI tilt magnitude
  TARGET_FRAC = 0.6    # cap target at 60% of limit (room for whipsaws)
  BIG_QTY     = 7
  SMALL_QTY   = 3
  BAL_QTY     = 4      # balanced (no skew) bid+ask
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


# ---------------------------------------------------------------------------
# Universe + per-asset σ (raw mid-diff std, days 2/3/4 historical)
# ---------------------------------------------------------------------------
ASSETS: Tuple[str, ...] = (
    'GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES',
    'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS',
    'GALAXY_SOUNDS_SOLAR_FLAMES', 'SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON',
    'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
    'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE', 'PEBBLES_XS', 'PEBBLES_S',
    'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL', 'ROBOT_VACUUMING',
    'ROBOT_MOPPING', 'ROBOT_DISHES', 'ROBOT_LAUNDRY', 'ROBOT_IRONING',
    'UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE', 'UV_VISOR_RED',
    'UV_VISOR_MAGENTA', 'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK',
    'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST',
    'TRANSLATOR_VOID_BLUE', 'PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4',
    'PANEL_2X4', 'PANEL_4X4', 'OXYGEN_SHAKE_MORNING_BREATH',
    'OXYGEN_SHAKE_EVENING_BREATH', 'OXYGEN_SHAKE_MINT',
    'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC', 'SNACKPACK_CHOCOLATE',
    'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY',
    'SNACKPACK_RASPBERRY',
)

SIGMA: Dict[str, float] = {
    'GALAXY_SOUNDS_DARK_MATTER': 10.25, 'GALAXY_SOUNDS_BLACK_HOLES': 11.48,
    'GALAXY_SOUNDS_PLANETARY_RINGS': 10.88, 'GALAXY_SOUNDS_SOLAR_WINDS': 10.54,
    'GALAXY_SOUNDS_SOLAR_FLAMES': 11.09, 'SLEEP_POD_SUEDE': 11.42,
    'SLEEP_POD_LAMB_WOOL': 10.71, 'SLEEP_POD_POLYESTER': 11.89,
    'SLEEP_POD_NYLON': 9.62, 'SLEEP_POD_COTTON': 11.68,
    'MICROCHIP_CIRCLE': 9.23, 'MICROCHIP_OVAL': 12.48,
    'MICROCHIP_SQUARE': 20.71, 'MICROCHIP_RECTANGLE': 13.13,
    'MICROCHIP_TRIANGLE': 14.50, 'PEBBLES_XS': 15.05, 'PEBBLES_S': 15.02,
    'PEBBLES_M': 15.13, 'PEBBLES_L': 15.03, 'PEBBLES_XL': 30.31,
    'ROBOT_VACUUMING': 9.24, 'ROBOT_MOPPING': 11.15, 'ROBOT_DISHES': 17.78,
    'ROBOT_LAUNDRY': 9.82, 'ROBOT_IRONING': 10.44,
    'UV_VISOR_YELLOW': 11.01, 'UV_VISOR_AMBER': 8.00,
    'UV_VISOR_ORANGE': 10.46, 'UV_VISOR_RED': 11.03, 'UV_VISOR_MAGENTA': 11.20,
    'TRANSLATOR_SPACE_GRAY': 9.42, 'TRANSLATOR_ASTRO_BLACK': 9.45,
    'TRANSLATOR_ECLIPSE_CHARCOAL': 9.86, 'TRANSLATOR_GRAPHITE_MIST': 10.13,
    'TRANSLATOR_VOID_BLUE': 10.83, 'PANEL_1X2': 9.05, 'PANEL_2X2': 9.60,
    'PANEL_1X4': 9.48, 'PANEL_2X4': 11.29, 'PANEL_4X4': 9.96,
    'OXYGEN_SHAKE_MORNING_BREATH': 10.10, 'OXYGEN_SHAKE_EVENING_BREATH': 10.98,
    'OXYGEN_SHAKE_MINT': 9.88, 'OXYGEN_SHAKE_CHOCOLATE': 10.89,
    'OXYGEN_SHAKE_GARLIC': 12.01, 'SNACKPACK_CHOCOLATE': 6.58,
    'SNACKPACK_VANILLA': 6.51, 'SNACKPACK_PISTACHIO': 5.24,
    'SNACKPACK_STRAWBERRY': 8.13, 'SNACKPACK_RASPBERRY': 8.09,
}

# Basket structure (from calibration + factor analysis)
PEBBLES = ('PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL')
PEBBLE_REF = 10000.0  # equal-weight equilibrium (sum=50000)
PEBBLE_SIGMA_RES = 12.0  # std of (pebble - 10000); from calibration

SNACKPACK_PAIR = ('SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA')
PAIR_SIGMA_K = 60.0  # std of K_day pair sum residual (from calibration)

TRIPLET = ('SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY')
TRIPLET_LOADINGS = (-0.395, -0.657, +0.643)  # PCA top eigenvector
TRIPLET_SIGMA_K = 6.5  # std of factor projection

# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------
POS_LIMIT = 10
HL_TICKS = 3000
HL_BASKET = 1500
EMA_ALPHA_FV = 1.0 - 2.0 ** (-1.0 / HL_TICKS)
EMA_ALPHA_BASKET = 1.0 - 2.0 ** (-1.0 / HL_BASKET)

MR_K = 0.6
MR_K_BASKET = 1.0
MR_K_PAIR = 1.2
MR_K_TRIPLET = 1.0
OBI_K = 0.3
TARGET_FRAC = 0.6
BIG_QTY = 7
SMALL_QTY = 3
BAL_QTY = 4
TIGHT_SPREAD_MIN = 2  # skip MM if spread < 2


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        td = self._parse_td(state.traderData)

        # ---- 1. Gather mids and update EMAs ----
        mids: Dict[str, float] = {}
        obi_map: Dict[str, float] = {}
        for sym in ASSETS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = 0.5 * (best_bid + best_ask)
            mids[sym] = mid
            # OBI on top-of-book L1
            b1 = od.buy_orders[best_bid]
            a1 = -od.sell_orders[best_ask]
            tot = b1 + a1
            obi_map[sym] = 0.0 if tot == 0 else (b1 - a1) / tot
            # Update FV EMA
            key = f"fv_{sym}"
            prev = td.get(key)
            td[key] = mid if prev is None else (1.0 - EMA_ALPHA_FV) * prev + EMA_ALPHA_FV * mid

        # ---- 2. Basket-residual signals ----
        basket_z: Dict[str, float] = {s: 0.0 for s in ASSETS}

        # 2a. Pebbles: each pebble's deviation from 10000 is its own residual
        for sym in PEBBLES:
            if sym in mids:
                resid = mids[sym] - PEBBLE_REF
                # Long if resid<0 (pebble cheap), short if resid>0
                basket_z[sym] += -MR_K_BASKET * (resid / PEBBLE_SIGMA_RES)

        # 2b. SNACKPACK CHOC/VAN pair: K = sum, slow EMA → residual mean-reverts
        if all(s in mids for s in SNACKPACK_PAIR):
            K = mids[SNACKPACK_PAIR[0]] + mids[SNACKPACK_PAIR[1]]
            ema_K = td.get('ema_K')
            td['ema_K'] = K if ema_K is None else (1 - EMA_ALPHA_BASKET) * ema_K + EMA_ALPHA_BASKET * K
            K_resid = K - td['ema_K']
            # Long both legs when K below trend (K_resid < 0); short both when above.
            sig = -MR_K_PAIR * (K_resid / PAIR_SIGMA_K)
            basket_z[SNACKPACK_PAIR[0]] += sig
            basket_z[SNACKPACK_PAIR[1]] += sig

        # 2c. Triplet: factor projection f = sum_j L_j * mid_j; residual_i = mid_i - L_i*f
        if all(s in mids for s in TRIPLET):
            f = sum(L * mids[s] for L, s in zip(TRIPLET_LOADINGS, TRIPLET))
            for L, sym in zip(TRIPLET_LOADINGS, TRIPLET):
                resid = mids[sym] - L * f
                basket_z[sym] += -MR_K_TRIPLET * (resid / TRIPLET_SIGMA_K) * (1.0 if L > 0 else -1.0)

        # ---- 3. Per-asset target position + 2-sided MM ----
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        for sym in ASSETS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            if best_ask - best_bid < TIGHT_SPREAD_MIN:
                continue
            mid = mids[sym]
            sigma = SIGMA[sym]
            fv = td.get(f"fv_{sym}", mid)
            obi = obi_map[sym]
            pos = state.position.get(sym, 0)

            # Per-asset z-score (mean reversion to FV)
            z_self = (mid - fv) / max(sigma, 1e-6)
            # Combined raw target signal
            signal = -MR_K * z_self + OBI_K * obi + basket_z[sym]
            # Target position (capped)
            target_frac = max(-TARGET_FRAC, min(TARGET_FRAC, signal))
            target = int(round(target_frac * POS_LIMIT))

            # Asymmetric quote sizes based on target-pos diff
            diff = target - pos
            if diff > 0:
                bid_q, ask_q = BIG_QTY, SMALL_QTY
            elif diff < 0:
                bid_q, ask_q = SMALL_QTY, BIG_QTY
            else:
                bid_q = ask_q = BAL_QTY

            # Worst-case position-limit caps (bids and asks checked independently)
            buy_room = POS_LIMIT - pos
            sell_room = POS_LIMIT + pos
            bid_q = max(0, min(bid_q, buy_room))
            ask_q = max(0, min(ask_q, sell_room))

            our_bid = best_bid + 1
            our_ask = best_ask - 1
            if our_bid >= our_ask:
                continue

            orders: List[Order] = []
            if bid_q > 0:
                orders.append(Order(sym, our_bid, bid_q))
            if ask_q > 0:
                orders.append(Order(sym, our_ask, -ask_q))
            if orders:
                result[sym] = orders

        return result, 0, json.dumps(td, separators=(",", ":"))

    @staticmethod
    def _parse_td(s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
