"""Round 5 factor_v4 — best-of-both: v3's signal generator + v1's directional-only execution.

Why
---
v1 (one-sided close-the-gap) made 147K mean. v2/v3 (added 2-sided MM tail)
dropped to 114-116K. Diagnosis: in our MC sim, **drift capture dominates spread
harvest**. The MM tail trades drift PnL for tiny spread PnL — net negative.
ROBOT_DISHES alone went from +18K (v1) to +127 (v3) because the small ask tail
kept selling against the strong upward drift.

v4 keeps v3's three alpha sources (FV-EMA z-score, OBI, basket residuals) but
executes one-sided close-the-gap orders only, like v1.

Signal stack (per asset, additive)
----------------------------------
  z_self     = (mid - fv) / sigma_i        (pure mean-reversion to slow EMA)
  obi        = top-of-book imbalance
  basket_z   = pebble residual + CHOC/VAN K-residual + triplet residual
  signal     = -MR_K * z_self + OBI_K * obi + basket_z
  target     = round(clip(signal, ±TARGET_FRAC) * POS_LIMIT)

Execution
---------
  diff = target - pos
  if diff > 0: bid `diff` units at best_bid + 1 (cap by buy_room)
  if diff < 0: ask `-diff` units at best_ask - 1 (cap by sell_room)
  if diff == 0: do nothing (no MM tail)

Same skip rule as v1: skip if spread < 2 (penny-jump impossible).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


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

PEBBLES = ('PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL')
PEBBLE_REF = 10000.0
PEBBLE_SIGMA_RES = 12.0

SNACKPACK_PAIR = ('SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA')
PAIR_SIGMA_K = 60.0

TRIPLET = ('SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY')
TRIPLET_LOADINGS = (-0.395, -0.657, +0.643)
TRIPLET_SIGMA_K = 6.5

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
TARGET_FRAC = 1.0          # use the whole limit when signal is strong
TIGHT_SPREAD_MIN = 2


class Trader:
    def run(self, state: TradingState):
        td = self._parse_td(state.traderData)

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
            b1 = od.buy_orders[best_bid]
            a1 = -od.sell_orders[best_ask]
            tot = b1 + a1
            obi_map[sym] = 0.0 if tot == 0 else (b1 - a1) / tot
            key = f"fv_{sym}"
            prev = td.get(key)
            td[key] = mid if prev is None else (1.0 - EMA_ALPHA_FV) * prev + EMA_ALPHA_FV * mid

        basket_z: Dict[str, float] = {s: 0.0 for s in ASSETS}
        for sym in PEBBLES:
            if sym in mids:
                resid = mids[sym] - PEBBLE_REF
                basket_z[sym] += -MR_K_BASKET * (resid / PEBBLE_SIGMA_RES)

        if all(s in mids for s in SNACKPACK_PAIR):
            K = mids[SNACKPACK_PAIR[0]] + mids[SNACKPACK_PAIR[1]]
            ema_K = td.get('ema_K')
            td['ema_K'] = K if ema_K is None else (1 - EMA_ALPHA_BASKET) * ema_K + EMA_ALPHA_BASKET * K
            K_resid = K - td['ema_K']
            sig = -MR_K_PAIR * (K_resid / PAIR_SIGMA_K)
            basket_z[SNACKPACK_PAIR[0]] += sig
            basket_z[SNACKPACK_PAIR[1]] += sig

        if all(s in mids for s in TRIPLET):
            f = sum(L * mids[s] for L, s in zip(TRIPLET_LOADINGS, TRIPLET))
            for L, sym in zip(TRIPLET_LOADINGS, TRIPLET):
                resid = mids[sym] - L * f
                basket_z[sym] += -MR_K_TRIPLET * (resid / TRIPLET_SIGMA_K) * (1.0 if L > 0 else -1.0)

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

            z_self = (mid - fv) / max(sigma, 1e-6)
            signal = -MR_K * z_self + OBI_K * obi + basket_z[sym]
            target_frac = max(-TARGET_FRAC, min(TARGET_FRAC, signal))
            target = int(round(target_frac * POS_LIMIT))

            buy_room = POS_LIMIT - pos
            sell_room = POS_LIMIT + pos
            diff = target - pos

            orders: List[Order] = []
            if diff > 0:
                qty = min(diff, buy_room)
                if qty > 0:
                    orders.append(Order(sym, best_bid + 1, qty))
            elif diff < 0:
                qty = min(-diff, sell_room)
                if qty > 0:
                    orders.append(Order(sym, best_ask - 1, -qty))
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
