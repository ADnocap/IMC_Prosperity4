"""Round 5 factor_v5 — v1_noproj + correctly-sized snackpack pair signal.

v1_noproj ships 147K mean. Adding the K=CHOC+VAN pair MR signal — the ONLY basket
trade that survived residual sanity checks (pebbles drift far from 10000 across
days, triplet-projection logic was algebraically off). Pair: K(t) is a slow OU
around K_day with std(K - EMA_HL3000(K)) ≈ 35 ticks historically.

When K is above its slow trend → both legs are mispriced UP → short both.
When K is below → long both. Sized via z-score on K-resid with its own KAPPA.

Same execution as v1: directional close-the-gap orders only (no MM tail).
Dollar-neutral projection kept (sharpe-positive in v1_noproj test).
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
N_ASSETS = 50
ASSET_IDX = {s: i for i, s in enumerate(ASSETS)}

SIGMA: Tuple[float, ...] = (
    10.2457, 11.4797, 10.8791, 10.5392, 11.0946, 11.4217, 10.7125, 11.8908,
    9.6210, 11.6766, 9.2342, 12.4780, 20.7075, 13.1303, 14.5040, 15.0524,
    15.0203, 15.1336, 15.0255, 30.3142, 9.2356, 11.1458, 17.7795, 9.8223,
    10.4437, 11.0062, 8.0050, 10.4606, 11.0305, 11.2025, 9.4238, 9.4489,
    9.8573, 10.1300, 10.8332, 9.0543, 9.5962, 9.4831, 11.2892, 9.9571,
    10.1008, 10.9833, 9.8836, 10.8903, 12.0146, 6.5756, 6.5131, 5.2378,
    8.1330, 8.0918,
)

POS_LIMIT = 10
HL_TICKS = 1500
EMA_ALPHA = 1.0 - 2.0 ** (-1.0 / HL_TICKS)
KAPPA = 4.0
ALPHA_CAP = 3.0

# --- Snackpack pair (CHOC + VANILLA = K_day, slow OU pair sum) ----------
SP_CHOC = 'SNACKPACK_CHOCOLATE'
SP_VAN = 'SNACKPACK_VANILLA'
HL_K = 3000                    # slower EMA for K (K_day moves on a longer time scale)
EMA_ALPHA_K = 1.0 - 2.0 ** (-1.0 / HL_K)
PAIR_SIGMA_K = 35.0            # historical std(K - EMA_K) ≈ 31-39 across days
PAIR_KAPPA = 6.0               # max-out target at z_K ≈ 1.67
PAIR_ALPHA_CAP = 3.0


class Trader:
    def run(self, state: TradingState):
        try:
            td: Dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            td = {}

        # ---- 1. EMAs and mids ----
        mids: Dict[str, float] = {}
        for sym in ASSETS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = 0.5 * (best_bid + best_ask)
            mids[sym] = mid
            key = f"fv_{sym}"
            prev = td.get(key)
            td[key] = mid if prev is None else (1.0 - EMA_ALPHA) * prev + EMA_ALPHA * mid

        # ---- 2. Per-asset target from FV mean reversion ----
        target: List[float] = [0.0] * N_ASSETS
        for i, sym in enumerate(ASSETS):
            mid = mids.get(sym)
            if mid is None:
                continue
            fv = td[f"fv_{sym}"]
            sigma = SIGMA[i]
            if sigma <= 0:
                continue
            z = (fv - mid) / sigma
            if z > ALPHA_CAP:
                z = ALPHA_CAP
            elif z < -ALPHA_CAP:
                z = -ALPHA_CAP
            t = KAPPA * z
            target[i] = t

        # ---- 3. Snackpack pair K = CHOC + VAN signal ----
        if SP_CHOC in mids and SP_VAN in mids:
            K = mids[SP_CHOC] + mids[SP_VAN]
            ema_K = td.get('ema_K')
            td['ema_K'] = K if ema_K is None else (1.0 - EMA_ALPHA_K) * ema_K + EMA_ALPHA_K * K
            K_resid = K - td['ema_K']
            z_K = K_resid / PAIR_SIGMA_K
            if z_K > PAIR_ALPHA_CAP:
                z_K = PAIR_ALPHA_CAP
            elif z_K < -PAIR_ALPHA_CAP:
                z_K = -PAIR_ALPHA_CAP
            # K above trend → short both legs; K below trend → long both
            pair_target = -PAIR_KAPPA * z_K
            target[ASSET_IDX[SP_CHOC]] += pair_target
            target[ASSET_IDX[SP_VAN]] += pair_target

        # ---- 4. Clip target to ±10 ----
        target_int = [0] * N_ASSETS
        for i in range(N_ASSETS):
            t = target[i]
            if t > POS_LIMIT:
                t = POS_LIMIT
            elif t < -POS_LIMIT:
                t = -POS_LIMIT
            target_int[i] = int(round(t))

        # ---- 5. Generate orders ----
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        for i, sym in enumerate(ASSETS):
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            if best_ask - best_bid < 2:
                continue
            pos = state.position.get(sym, 0)
            tgt = target_int[i]
            diff = tgt - pos
            orders: List[Order] = []
            if diff > 0:
                qty = min(diff, POS_LIMIT - pos)
                if qty > 0:
                    orders.append(Order(sym, best_bid + 1, qty))
            elif diff < 0:
                qty = min(-diff, POS_LIMIT + pos)
                if qty > 0:
                    orders.append(Order(sym, best_ask - 1, -qty))
            if orders:
                result[sym] = orders

        return result, 0, json.dumps(td, separators=(",", ":"))
